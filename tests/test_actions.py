"""Shared authorization gateway tests; no model or external API calls."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.actions import ActionManager, ActionError
from app.agent import AgentService
from app.plans import PlanStore


def quote(amount=1000, trace='fresh'):
    return {'request':{'trace':trace}, 'summary':{'商品':'unit','总价':amount},
            'amount_cents':amount,'comparison':{'item':'unit','amount':amount}}


class ActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'actions.sqlite3'
        self.manager = ActionManager(self.path, enabled=lambda _:True)
        self.adapter = SimpleNamespace(quote=AsyncMock(return_value=quote()),
            execute=AsyncMock(return_value={'order_id':'unit-order'}))
        self.manager.register('didi', self.adapter)
        self.plan = self.manager.prepare('owner','didi','create',{'trace':'old'},quote(trace='old'))

    def tearDown(self):
        self.tmp.cleanup()

    async def confirm(self, owner='owner', **changes):
        args = dict(owner=owner,id=self.plan['id'],version=self.plan['version'],
                    token=self.plan['confirmation_token'],text='确认叫车')
        args.update(changes)
        return await self.manager.confirm(**args)

    async def test_owner_token_phrase_and_bool_version_rejected(self):
        for args in ({'owner':'other'},{'token':'wrong'},{'text':'好的'},{'version':True}):
            with self.assertRaises(ActionError):
                await self.confirm(**args)
        self.adapter.execute.assert_not_awaited()

    async def test_duplicate_confirm_issues_one_remote_request_and_refreshes_trace(self):
        async def execute(action,request):
            await asyncio.sleep(0)
            return {'order_id':'unit-order'}
        self.adapter.execute.side_effect=execute
        await asyncio.gather(self.confirm(),self.confirm())
        self.adapter.execute.assert_awaited_once_with('create',{'trace':'fresh'})
        self.assertEqual(self.manager.get('owner',self.plan['id'])['status'],'created')

    async def test_price_change_needs_new_confirmation_and_old_token_fails(self):
        self.adapter.quote.return_value = quote(1100)
        updated = await self.confirm()
        self.assertEqual(updated['status'],'needs_review')
        self.adapter.execute.assert_not_awaited()
        with self.assertRaises(ActionError):
            await self.confirm()

    async def test_unknown_execution_is_not_retried_or_replaced(self):
        self.adapter.execute.side_effect = TimeoutError()
        self.assertEqual((await self.confirm())['status'],'unknown')
        await self.confirm()
        self.adapter.execute.assert_awaited_once()
        with self.assertRaises(ActionError):
            self.manager.prepare('owner','didi','create',{},quote())
        recovered = ActionManager(self.path,enabled=lambda _:True)
        self.assertEqual(recovered.get('owner',self.plan['id'])['status'],'unknown')

    async def test_new_proposal_supersedes_old_and_local_cancel_never_calls_provider(self):
        newer=self.manager.prepare('owner','didi','create',{},quote())
        self.assertEqual((await self.confirm())['status'],'superseded')
        self.manager.cancel_local('owner',newer['id'])
        self.adapter.execute.assert_not_awaited()

    async def test_disabled_execution_and_external_unknown_block(self):
        self.manager._enabled=lambda _:False
        with self.assertRaises(ActionError):
            await self.confirm()
        self.manager._enabled=lambda _:True
        self.manager.external_blocks=lambda _:True
        with self.assertRaises(ActionError):
            await self.confirm()
        self.adapter.quote.assert_not_awaited()

    async def test_restart_recovery_marks_write_unknown_and_read_expired(self):
        self.manager._update('owner',self.plan['id'],status='submitting')
        self.manager.recover_interrupted()
        self.assertEqual(self.manager.get('owner',self.plan['id'])['status'],'unknown')
        self.adapter.execute.assert_not_awaited()

    async def test_host_confirmation_bypasses_model_and_ambiguous_reply_cannot_execute(self):
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'plans.sqlite3'),
                           data_dir=Path(self.tmp.name)/'agent')
        agent.actions=self.manager
        agent._config=lambda:{'key':'unit','model':'unit','base':'https://unused.invalid'}
        agent._run=AsyncMock(return_value='请先核对方案。')
        reply=await agent.chat('owner','确认叫车')
        self.assertIn('host.confirmation',str(reply['trace']))
        agent._run.assert_not_awaited()
        self.adapter.execute.assert_awaited_once()

    async def test_write_response_stays_private(self):
        self.adapter.execute.return_value={'order_id':'unit','provider_response':{'private':'unit-secret'}}
        result=await self.confirm()
        self.assertNotIn('unit-secret',str(result))
        self.assertEqual(self.manager.get('owner',self.plan['id'])['provider_response']['private'],'unit-secret')

    async def test_expired_mcd_quote_can_renew_without_creating_or_reselecting(self):
        self.manager.register('mcd',self.adapter)
        p=self.manager.prepare('owner','mcd','create',{'trace':'old'},quote(trace='old'))
        self.manager._update('owner',p['id'],expires_at=0)
        renewed=await self.manager.confirm('owner',p['id'],p['version'],p['confirmation_token'],'确认下单')
        self.assertEqual(renewed['status'],'needs_review')
        self.assertEqual(renewed['amount_cents'],1000)
        self.assertGreater(renewed['version'],p['version'])
        self.adapter.execute.assert_not_awaited()
        with self.assertRaises(ActionError):
            await self.manager.confirm('owner',p['id'],p['version'],p['confirmation_token'],'确认下单')
        done=await self.manager.confirm('owner',p['id'],renewed['version'],renewed['confirmation_token'],'确认下单')
        self.assertEqual(done['status'],'created')
        self.adapter.execute.assert_awaited_once()

    async def test_expired_mcd_quote_cannot_revive_after_new_context(self):
        self.manager.register('mcd',self.adapter)
        p=self.manager.prepare('owner','mcd','create',{'trace':'old'},quote(trace='old'))
        self.manager._update('owner',p['id'],status='expired',expires_at=0)
        self.manager.invalidate_pending('owner')
        result=await self.manager.confirm('owner',p['id'],p['version'],p['confirmation_token'],'确认下单')
        self.assertEqual(result['status'],'superseded')
        self.adapter.quote.assert_not_awaited()
        self.adapter.execute.assert_not_awaited()

    async def test_luckin_unknown_blocks_recent_duplicate_but_allows_new_orders(self):
        self.manager.register('luckin', self.adapter)
        request = {'deptId': 'store', 'productList': [{'sku': 'latte'}]}
        quoted = {**quote(), 'request': request}
        self.adapter.quote.return_value = quoted
        self.adapter.execute.side_effect = TimeoutError()
        plan = self.manager.prepare('owner', 'luckin', 'create', request, quoted)
        confirm = lambda: self.manager.confirm('owner', plan['id'], plan['version'],
                                              plan['confirmation_token'], '确认下单')
        self.assertEqual((await confirm())['status'], 'unknown')
        with self.assertRaisesRegex(ActionError, '相同餐品'):
            self.manager.prepare('owner', 'luckin', 'create', {**request, 'couponCodeList': ['new']}, quoted)
        self.manager.prepare('owner', 'luckin', 'create', {**request, 'productList': [{'sku': 'tea'}]}, quoted)
        self.manager._update('owner', plan['id'], submitted_at=0)
        fresh = self.manager.prepare('owner', 'luckin', 'create', request, quoted)
        self.assertEqual(fresh['status'], 'awaiting_confirmation')
        self.assertEqual((await confirm())['status'], 'unknown')
        self.adapter.execute.assert_awaited_once()
