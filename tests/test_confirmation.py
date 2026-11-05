"""Offline authorization tests. Test doubles never reach the real MCP service."""

import asyncio
import importlib
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.plans import PlanError, PlanStore


class PaymentResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_pay_h5_url_is_returned(self):
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock
        from app.mcd import McdService
        service = McdService()
        call = AsyncMock(return_value={'orderId':'unit-order',
            'payH5Url':'https://m.mcd.cn/mcp/scanToPay?orderId=unit-order'})
        @asynccontextmanager
        async def connection():
            yield call
        with patch.object(service, '_connection', connection):
            result = await service.create_order({'unit':'payload'})
        self.assertEqual(result['payment_url'], 'https://m.mcd.cn/mcp/scanToPay?orderId=unit-order')
        self.assertEqual(result['order_id'], 'unit-order')


def prepared():
    return {
        'request': {'storeCode': 'unit-test-store', 'items': [{'productCode': 'unit-test-product', 'quantity': 1}],
                    'takeWayCode': 'unit-test-pickup'},
        'amount_cents': 3500,
        'summary': {'product_name': '单元测试商品', 'quantity': 1},
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'plans.sqlite3'
        self.store = PlanStore(self.path)
        self.plan = self.store.create('owner-a', prepared())

    def tearDown(self):
        self.temp.cleanup()

    def claim(self, plan=None, owner='owner-a'):
        p = plan or self.plan
        return self.store.claim(p['id'], owner, p['version'], p['confirmation_token'])

    def test_competing_confirmations_have_exactly_one_claim(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.claim()[1], range(16)))
        self.assertEqual(sum(results), 1)

    def test_other_browser_cannot_read_claim_or_cancel(self):
        for operation in [lambda: self.store.get(self.plan['id'], 'owner-b'),
                          lambda: self.claim(owner='owner-b'),
                          lambda: self.store.cancel(self.plan['id'], 'owner-b')]:
            with self.assertRaises(PlanError) as caught:
                operation()
            self.assertEqual(caught.exception.status, 404)

    def test_expired_confirmation_does_not_claim(self):
        self.store.update(self.plan['id'], 'owner-a', expires_at=time.time() - 1)
        with self.assertRaises(PlanError):
            self.claim()
        self.assertNotEqual(self.store.get(self.plan['id'], 'owner-a')['status'], 'rechecking')

    def test_wrong_version_or_token_cannot_claim(self):
        for version, token in [(self.plan['version'] + 1, self.plan['confirmation_token']),
                               (self.plan['version'], 'incorrect-unit-test-token')]:
            with self.assertRaises(PlanError):
                self.store.claim(self.plan['id'], 'owner-a', version, token)
        self.assertEqual(self.store.get(self.plan['id'], 'owner-a')['status'], 'awaiting_confirmation')

    def test_payload_tampering_invalidates_confirmation(self):
        altered = prepared()['request']
        altered['storeCode'] = 'different-unit-test-store'
        self.store.update(self.plan['id'], 'owner-a', request=altered)
        with self.assertRaises(PlanError):
            self.claim()

    def test_cancel_and_replacement_invalidate_old_approval(self):
        self.store.cancel(self.plan['id'], 'owner-a')
        with self.assertRaises(PlanError):
            self.claim()
        second = self.store.create('owner-a', prepared())
        self.store.create('owner-a', prepared())
        with self.assertRaises(PlanError):
            self.claim(second)

    def test_restart_preserves_uncertain_outcome_and_prevents_new_order(self):
        self.claim()
        self.store.update(self.plan['id'], 'owner-a', status='submitting')
        recovered = PlanStore(self.path)
        self.assertEqual(recovered.get(self.plan['id'], 'owner-a')['status'], 'unknown')
        with self.assertRaises(PlanError):
            recovered.create('owner-a', prepared())
        self.assertFalse(self.claim()[1])

    def test_restart_during_requote_requires_new_plan(self):
        self.claim()
        recovered = PlanStore(self.path)
        self.assertEqual(recovered.get(self.plan['id'], 'owner-a')['status'], 'expired')
        with self.assertRaises(PlanError):
            self.claim()


class GatewayDouble:
    """Only used in this test process, never as an application fallback."""
    def __init__(self):
        self.amount = 3500
        self.takeways = ['unit-test-pickup']
        self.creates = 0
        self.failure = None

    async def requote(self, request):
        await asyncio.sleep(0)
        return {'amount_cents': self.amount, 'take_way_codes': self.takeways}

    async def create_order(self, request):
        self.creates += 1
        await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        return {'order_id': 'unit-test-order', 'payment_url': None}


class ConfirmationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlanStore(Path(self.temp.name) / 'plans.sqlite3')
        # Keep import-time configuration and database initialization isolated.
        # No credentials are read and no production database is touched.
        with patch('dotenv.dotenv_values', return_value={}), patch('app.plans.PlanStore', return_value=self.store):
            self.api = importlib.import_module('app.main')
        self.gateway = GatewayDouble()
        self.store.manager._enabled=lambda provider: True
        self.patches = [patch.object(self.api, 'plans', self.store),
                        patch.object(self.api, 'service', self.gateway),
                        patch.object(self.api, 'ORDER_ENABLED', True)]
        for item in self.patches:
            item.start()
        from starlette.requests import Request
        self.request = Request({'type': 'http', 'state': {'owner': 'owner-a'}})
        self.plan = self.store.create('owner-a', prepared())

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def body(self, plan=None, text='确认下单'):
        p = plan or self.plan
        return self.api.Confirmation(version=p['version'], confirmation_token=p['confirmation_token'],
                                     confirmation_text=text)

    async def test_price_change_demands_fresh_confirmation(self):
        self.gateway.amount = 3600
        result = await self.api.confirm(self.plan['id'], self.body(), self.request)
        new = result['plan']
        self.assertEqual(new['status'], 'needs_review')
        self.assertEqual(new['amount_cents'], 3600)
        self.assertEqual(self.gateway.creates, 0)
        with self.assertRaises(PlanError):
            await self.api.confirm(self.plan['id'], self.body(), self.request)
        result = await self.api.confirm(new['id'], self.body(new), self.request)
        self.assertEqual(result['plan']['status'], 'created')
        self.assertEqual(self.gateway.creates, 1)

    async def test_duplicate_requests_do_not_create_twice(self):
        await asyncio.gather(*(self.api.confirm(self.plan['id'], self.body(), self.request) for _ in range(10)))
        self.assertEqual(self.gateway.creates, 1)

    async def test_unknown_creation_result_is_never_retried(self):
        self.gateway.failure = TimeoutError('unit test only')
        result = await self.api.confirm(self.plan['id'], self.body(), self.request)
        self.assertEqual(result['plan']['status'], 'unknown')
        await self.api.confirm(self.plan['id'], self.body(), self.request)
        self.assertEqual(self.gateway.creates, 1)

    async def test_disabled_execution_and_ambiguous_confirmation_do_not_claim(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            await self.api.confirm(self.plan['id'], self.body(text='好的'), self.request)
        with patch.object(self.api, 'ORDER_ENABLED', False):
            with self.assertRaises(HTTPException):
                await self.api.confirm(self.plan['id'], self.body(), self.request)
        self.assertEqual(self.gateway.creates, 0)
        self.assertEqual(self.store.get(self.plan['id'], 'owner-a')['status'], 'awaiting_confirmation')

    async def test_changed_pickup_method_cannot_create_order(self):
        self.gateway.takeways = ['different-unit-test-pickup']
        result = await self.api.confirm(self.plan['id'], self.body(), self.request)
        self.assertEqual(result['plan']['status'], 'expired')
        self.assertEqual(self.gateway.creates, 0)

    async def test_http_boundary_rejects_foreign_origin_and_host(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app),
                                     base_url='http://localhost') as client:
            origin = await client.get('/api/health', headers={'Origin': 'https://other-site.example'})
            host = await client.get('/api/health', headers={'Host': 'other-site.example'})
            self.assertEqual(origin.status_code, 403)
            self.assertEqual(host.status_code, 403)
            self.assertEqual((await client.get('/api/health')).status_code, 200)

    async def test_http_boundary_rejects_non_json_post(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app),
                                     base_url='http://localhost') as client:
            response = await client.post('/api/plans', content='{}',
                                         headers={'Content-Type': 'text/plain'})
            self.assertEqual(response.status_code, 415)
            self.assertEqual(self.gateway.creates, 0)

    async def test_http_boolean_quantity_is_not_an_integer(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app),
                                     base_url='http://localhost') as client:
            response = await client.post('/api/plans', json={
                'store_code': 'unit-test-store', 'product_code': 'unit-test-product',
                'quantity': True, 'rounds': [],
            })
            self.assertEqual(response.status_code, 422)

    async def test_http_boolean_confirmation_version_is_rejected(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app),
                                     base_url='http://localhost') as client:
            response = await client.post('/api/plans/' + self.plan['id'] + '/confirm', json={
                'version': True, 'confirmation_token': self.plan['confirmation_token'],
                'confirmation_text': '确认下单',
            })
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.gateway.creates, 0)


if __name__ == '__main__':
    unittest.main()
