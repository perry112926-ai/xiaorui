"""Host policy tests use temporary state and no real model or merchant calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.agent import AgentService, AgentError, TOOLS
from app.plans import PlanStore
from app.nanobot_runtime import build_runtime, AgentLoop
from app.skills import SCHEMAS


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_deictic_weather_without_location_asks_city_without_cloud(self):
        with patch('app.agent.build_runtime') as runtime:
            result=await self.agent._run('a',self.agent._session('a'),'我这里现在下雨吗？',[],[])
        runtime.assert_not_called()
        self.assertIn('城市',result)

    async def test_weather_reply_retains_official_report_time(self):
        from types import SimpleNamespace
        self.agent._tool=AsyncMock(return_value={'weather':[{'city':'北京','reporttime':'2026-11-05 10:00:00'}]})
        def runtime(settings,directory,dispatch,context):
            class Bot:
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def stream(self,*args,**kwargs):
                    await dispatch('amap_weather',{'city':'北京'})
                    yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(
                        error=None,stop_reason='completed',content='北京晴。'))
            return Bot()
        with patch('app.agent.build_runtime',side_effect=runtime):
            result=await self.agent._run('a',self.agent._session('a'),'北京天气',[],[])
        self.assertIn('高德报告时间：2026-11-05 10:00:00',result)

    async def test_unverified_accessibility_is_host_boundary_not_model_guess(self):
        with patch('app.agent.build_runtime') as runtime:
            result=await self.agent._run('a',self.agent._session('a'),'保证轮椅全程无台阶怎么走',[],[])
        runtime.assert_not_called()
        self.assertIn('无法核实',result)
        self.assertNotIn('D西南口',result)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plans = PlanStore(Path(self.tmp.name) / 'plans.sqlite3')
        self.service = AsyncMock()
        self.service.stores = {}
        self.agent = AgentService(self.service, self.plans, data_dir=Path(self.tmp.name)/'agent')
        self.cfg = patch.object(self.agent, '_config', return_value={'key':'test-only', 'model':'test-only', 'base':'https://unused.invalid/v1'})
        self.cfg.start()

    def tearDown(self):
        self.cfg.stop()
        self.tmp.cleanup()

    async def test_real_nanobot_composition_has_exact_capability_and_no_commands(self):
        captured = []
        original = AgentLoop.from_config
        def capture(*args, **kwargs):
            loop = original(*args, **kwargs)
            captured.append(loop)
            return loop
        with patch('app.nanobot_runtime.AgentLoop.from_config', side_effect=capture):
            bot = build_runtime(self.agent._config(), Path(self.tmp.name)/'runtime', AsyncMock(), AsyncMock(return_value=[]))
        try:
            self.assertEqual(set(captured[0].tool_names), set(SCHEMAS))
            self.assertEqual({t['function']['name'] for t in TOOLS}, set(SCHEMAS))
            for name in ('/dream','/restart','/exec','/model'):
                self.assertIsNone(captured[0].commands.command_name(name))
            self.assertNotIn('exec', captured[0].tool_names)
        finally:
            await bot.aclose()

    async def test_unknown_write_tool_and_invalid_selection_cannot_execute(self):
        session = self.agent._session('a')
        for name,args in [('create_order',{}),('confirm',{}),('choose_meal',{'index':True}),('choose_meal',{'index':1}),('recommend_meals',{'store_code':'invented','budget_cents':3500})]:
            events=[]
            self.assertIn('error',await self.agent._tool(session,'a',name,args,events))
            self.assertEqual(events,[])
        self.service.prepare_plan.assert_not_awaited()
        self.service.create_order.assert_not_awaited()

    async def test_restart_restores_history_and_candidates_but_owners_stay_isolated(self):
        session=self.agent._session('a')
        session.stores={'unit':{'code':'unit'}}
        self.agent._run=AsyncMock(return_value='请问在哪附近？')
        await self.agent.chat('a','test private context')
        other=AgentService(self.service,self.plans,data_dir=self.agent.data_dir)
        self.assertIn('test private context',str(other.history('a')))
        self.assertNotIn('test private context',str(other.history('b')))
        self.assertIn('unit',other._session('a').stores)
        self.assertEqual(other._session('b').stores,{})

    async def test_failed_search_has_no_success_event(self):
        self.service.search_stores.side_effect=RuntimeError('private failure')
        events=[]
        result=await self.agent._tool(self.agent._session('a'),'a','search_stores',{'city':'unit','keyword':'unit'},events)
        self.assertIn('error',result)
        self.assertNotIn('private failure',str(result))
        self.assertEqual(events,[])

    async def test_plan_uses_trusted_candidate_and_hides_confirmation_token(self):
        session=self.agent._session('a');request={'store_code':'unit','product_code':'unit','quantity':1,'rounds':[]}
        session.meals=[{'request':request}]
        self.service.prepare_plan.return_value={'request':{'trusted':'unit'},'amount_cents':3500,'summary':{'product_name':'unit'}}
        events=[]
        result=await self.agent._tool(session,'a','choose_meal',{'index':1},events)
        self.service.prepare_plan.assert_awaited_once_with(request)
        self.assertNotIn('confirmation_token',str(result))
        self.assertIn('confirmation_token',events[0]['plan'])
        self.service.create_order.assert_not_awaited()

    async def test_same_owner_reentry_is_rejected(self):
        async with self.agent._session('a').lock:
            with self.assertRaises(AgentError) as caught:await self.agent.chat('a','hello')
        self.assertEqual(caught.exception.status,409)

    async def test_queued_confirmation_cannot_approve_a_different_proposal(self):
        quote={'request':{},'summary':{'商品':'test'},'amount_cents':1000,'comparison':{}}
        plan=self.agent.actions.prepare('a','mcd','create',{},quote)
        confirm=AsyncMock()
        with patch.object(self.agent.actions,'confirm',confirm):
            result=await self.agent.chat('a','确认下单',expected_confirmation=['another-plan',plan['version']])
        confirm.assert_not_awaited()
        self.assertIn('没有对应',result['text'])

    async def test_image_caption_cannot_execute_host_confirmation(self):
        from app.contact_events import contact_media
        quote={'request':{},'summary':{'商品':'test'},'amount_cents':1000,'comparison':{}}
        self.agent.actions.prepare('a','mcd','create',{},quote)
        confirm=AsyncMock();self.agent._run=AsyncMock(return_value='收到图片')
        token=contact_media.set(['test-only-image.jpg'])
        try:
            with patch.object(self.agent.actions,'confirm',confirm):
                result=await self.agent.chat('a','确认下单')
        finally:
            contact_media.reset(token)
        confirm.assert_not_awaited()
        self.assertEqual(result['text'],'收到图片')

    async def test_model_quota_error_is_reported_without_account_details(self):
        from types import SimpleNamespace
        class QuotaBot:
            async def __aenter__(self):
                return self
            async def __aexit__(self,*args):
                pass
            async def stream(self,*args,**kwargs):
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(
                    error='SetLimitExceeded: private-account-detail',stop_reason='error'))
        with patch('app.agent.build_runtime',return_value=QuotaBot()):
            with self.assertRaises(AgentError) as caught:
                await self.agent.chat('a','你好')
        self.assertEqual(caught.exception.status,503)
        self.assertIn('用量上限',caught.exception.message)
        self.assertNotIn('private-account-detail',caught.exception.message)

    async def test_model_failure_preserves_real_events_and_failed_task(self):
        async def failure(owner,session,text,events,trace):
            events.append({'type':'stores','stores':[]})
            raise RuntimeError('private failure')
        self.agent._run=failure
        result=await self.agent.chat('a','find store')
        self.assertEqual(result['events'][0]['type'],'stores')
        self.assertIn('尚未下单',result['text'])
        self.assertNotIn('private failure',result['text'])
        self.assertEqual(self.agent.tasks('a')['tasks'][0]['status'],'failed')

    async def test_reset_changes_thread_but_preserves_profile(self):
        before=self.agent._session('a').conversation_id
        self.agent.store.set_fact('preference.drink','不要冰')
        await self.agent.reset('a')
        self.assertNotEqual(before,self.agent._session('a').conversation_id)
        self.assertIn('不要冰',str(self.agent.store.profile()))

    async def test_forget_rotates_thread_and_does_not_restore_old_display(self):
        self.agent.store.set_fact('test.nickname', 'test-person-only')
        self.agent._run = AsyncMock(return_value='已保存。')
        await self.agent.chat('a', 'remember test-person-only')
        before = self.agent._session('a').conversation_id
        async def forget(owner, session, text, events, trace):
            result = await self.agent._tool(session, owner, 'personal_profile',
                                           {'action': 'forget', 'key': 'test.nickname'}, events)
            self.assertTrue(result['forgotten'])
            return '已忘记。'
        self.agent._run = forget
        result = await self.agent.chat('a', 'forget my test nickname')
        self.assertTrue(result['conversation_reset'])
        self.assertNotEqual(before, self.agent._session('a').conversation_id)
        self.assertNotIn('test-person-only', str(self.agent.history('a')))
        self.assertNotIn('test-person-only', str(self.agent.tasks('a')))
        self.assertEqual(self.agent.store.list_facts(), {})

    async def test_elder_says_never_mind_cancels_only_pending_meal_and_clears_cart(self):
        self.agent._run=AsyncMock(side_effect=AssertionError('local cancellation must not need a model'))
        session=self.agent._session('a')
        session.services['mcd']={'cart':[{'product':{'name':'测试餐'}}]}
        quote={'request':{},'summary':{'product':'测试餐'},'amount_cents':1000,'comparison':{}}
        plan=self.agent.actions.prepare('a','mcd','create',{},quote)
        result=await self.agent.chat('a','不点了')
        self.assertEqual(self.agent.actions.get('a',plan['id'])['status'],'cancelled')
        self.assertFalse(session.services['mcd'].get('cart'))
        self.assertIn('没有执行真实交易',result['text'])
        self.service.create_order.assert_not_awaited()

    async def test_restart_restores_fragmented_address_and_cart_without_mixing_owners(self):
        session=self.agent._session('a')
        await self.agent.scenarios['mcd'].dispatch(session,'a','mcd_address_draft',{'city':'北京','address':'测试楼'},[])
        session.services['mcd']['cart']=[{'product':{'code':'P','name':'测试餐'},'quantity':1,'choices':[]}]
        self.agent._run=AsyncMock(return_value='还需要确认具体门牌。')
        await self.agent.chat('a','继续核对')
        restored=AgentService(self.service,self.plans,data_dir=self.agent.data_dir)
        state=restored._session('a').services['mcd']
        self.assertEqual(state['address_draft']['address'],'测试楼')
        self.assertEqual(state['cart'][0]['product']['code'],'P')
        self.assertEqual(restored._session('other').services,{})
        self.service.create_order.assert_not_awaited()

    async def test_no_longer_ordering_clears_cart_before_a_plan_exists(self):
        self.agent._run=AsyncMock(side_effect=AssertionError('local abandonment must not need a model'))
        session=self.agent._session('a')
        session.services['mcd']={'cart':[{'product':{'name':'测试餐'}}],'budget_cents':3500}
        result=await self.agent.chat('a','不点了')
        self.assertFalse(session.services['mcd'].get('cart'))
        self.assertNotIn('budget_cents',session.services['mcd'])
        self.assertIn('真实订单不会因此取消',result['text'])
        self.service.create_order.assert_not_awaited()
