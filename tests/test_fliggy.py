import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from app.fliggy import Fliggy, normalize, booking_url


def payload():
    return {'data': {'itemList': [{
        'jumpUrl': 'https://router.feizhu.com/ws/example', 'ticketPrice': '400.00',
        'private': 'hidden', 'journeys': [{'journeyType': '直达', 'segments': [{
            'marketingTransportNo': 'MF8561', 'depStationName': '大兴国际机场',
            'arrStationName': '浦东国际机场', 'depDateTime': '2099-11-13 08:00:00',
            'arrDateTime': '2099-11-13 10:10:00', 'secret': 'hidden'}]}]}]}}


class Flights(unittest.IsolatedAsyncioTestCase):
    def test_public_results_and_links(self):
        result = normalize(payload())
        self.assertFalse(result['order_created'])
        self.assertFalse(result['paid'])
        self.assertEqual(result['flights'][0]['ticket_price_yuan'], '400.00')
        self.assertEqual(result['flights'][0]['journeys'][0]['segments'][0]['marketingTransportNo'], 'MF8561')
        self.assertNotIn('hidden', json.dumps(result))
        for bad in ('javascript:alert(1)', 'https://router.feizhu.com.evil.test/x',
                    'https://user@router.feizhu.com/x', 'http://router.feizhu.com/x'):
            self.assertIsNone(booking_url(bad))

    async def test_validation_before_remote_call(self):
        with patch('app.fliggy.asyncio.create_subprocess_exec') as spawn:
            for args in ({}, {'origin':'北京','destination':'上海','dep_date':'2000-01-01'},
                         {'origin':'北京','destination':'上海','dep_date':'2099-01-02','back_date':'2099-01-01'},
                         {'origin':'北京','destination':'上海','dep_date':'2099-01-02','pay':True}):
                self.assertIn('error', await Fliggy().dispatch(args))
            spawn.assert_not_called()

    async def test_query_uses_fixed_cli_and_environment_key(self):
        process = AsyncMock(returncode=0)
        process.communicate.return_value = (json.dumps(payload()).encode(), b'')
        with patch('app.fliggy.CLI') as cli, patch('app.fliggy.shutil.which', return_value='/node'), \
             patch.dict('os.environ', {'FLYAI_API_KEY':'private-test', 'DEBUG_FLYAI_MCP_URL':'https://evil.test'}), \
             patch('app.fliggy.asyncio.create_subprocess_exec', return_value=process) as spawn:
            cli.is_file.return_value = True
            result = await Fliggy().dispatch({'origin':'北京','destination':'上海','dep_date':'2099-11-13','direct_only':True})
        self.assertEqual(len(result['flights']), 1)
        self.assertIn('search-flight', spawn.call_args.args)
        self.assertNotIn('private-test', str(spawn.call_args.args))
        self.assertNotIn('DEBUG_FLYAI_MCP_URL', spawn.call_args.kwargs['env'])
        self.assertEqual(spawn.call_args.kwargs['env']['FLYAI_API_KEY'], 'private-test')

    async def test_host_dispatch_preserves_public_flight_contract(self):
        from app.agent import AgentService
        from app.plans import PlanStore
        from app.skills import SCHEMAS
        from app import read_only
        self.assertIn('fliggy_search_flights', SCHEMAS)
        self.assertIn('fliggy_search_flights', read_only.QUERY_TOOLS)
        with tempfile.TemporaryDirectory() as directory:
            service = AsyncMock(stores={})
            agent = AgentService(service, PlanStore(Path(directory)/'plans.sqlite3'), data_dir=Path(directory)/'agent')
            expected = normalize(payload())
            with patch.object(agent.life_skills.fliggy, 'dispatch', return_value=expected):
                result = await agent._tool(agent._session('owner'), 'owner', 'fliggy_search_flights', {}, [])
            self.assertEqual(result, expected)
            service.create_order.assert_not_awaited()

    async def test_agent_reply_uses_flights_when_model_mentions_ordering(self):
        from app.agent import AgentService
        from app.plans import PlanStore
        with tempfile.TemporaryDirectory() as directory:
            agent = AgentService(AsyncMock(stores={}), PlanStore(Path(directory)/'plans.sqlite3'), data_dir=Path(directory)/'agent')
            def runtime(settings, path, dispatch, context):
                class Bot:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                    async def stream(self, *args, **kwargs):
                        await dispatch('fliggy_search_flights', {'origin':'北京','destination':'上海','dep_date':'2099-11-13'})
                        yield SimpleNamespace(type='run.completed', name=None,
                            result=SimpleNamespace(error=None, stop_reason='completed', content='我现在可以帮您查麦当劳。'))
                return Bot()
            with patch('app.agent.build_runtime', side_effect=runtime), \
                 patch.object(agent.life_skills.fliggy, 'dispatch', return_value=normalize(payload())):
                events = []
                session = agent._session('owner')
                answer = await agent._run('owner', session, '帮我查机票，先不要下单', events, [])
                answer = agent._answer('owner', session, '帮我查机票，先不要下单', answer, events, [], 'test')['text']
            self.assertIn('MF8561', answer)
            self.assertIn('https://router.feizhu.com/', answer)
            self.assertIn('尚未订票', answer)
            self.assertNotIn('麦当劳', answer)

    def test_empty_and_invalid_responses(self):
        self.assertEqual(normalize({'data':{'itemList':[]}})['flights'], [])
        for data in ({'error':'denied'}, {'success':False}, {'data':{}}, None):
            with self.assertRaises(ValueError):
                normalize(data)
