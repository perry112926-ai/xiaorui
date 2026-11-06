import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.agent import AgentService
from app.plans import PlanStore
from app.factual_replies import business_turn,business_reply
from app.task_switching import cancel_mcd_order

class TaskSwitchingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'plans.db'),data_dir=Path(self.tmp.name)/'agent')
        self.agent._config=lambda:{'key':'test','model':'test','base':'https://unused.invalid'}
        self.session=self.agent._session('owner')
        self.session.services={'mcd':{'cart':[{'name':'测试餐'}],'address_draft':{'city':'北京'}}}

    def test_new_topics_are_not_captured_by_any_old_service(self):
        for services in [self.session.services,{'didi':{}},{'luckin':{}}]:
            for text in ['一分钟后提醒我','北京天气怎么样','去医院怎么走','记住我喜欢喝热水','讲个故事','今天星期几']:
                self.assertFalse(business_turn(text,services),(text,services))
        self.assertTrue(business_turn('继续',self.session.services))
        self.assertTrue(business_turn('取消订单',self.session.services))
        self.assertNotIn('门牌',business_reply('帮我打车',self.session.services,[],[]))
        self.assertNotIn('购物车',business_reply('帮我打车',self.session.services,[],[]))

    async def test_reminder_during_checkout_is_truthful_and_does_not_call_model_or_repeat_cart(self):
        self.agent._run=AsyncMock(side_effect=AssertionError('no model needed'))
        result=await self.agent.chat('owner','一分钟后提醒我')
        self.assertIn('不能到时主动提醒',result['text'])
        self.assertNotIn('购物车',result['text'])
        self.agent._run.assert_not_awaited()

    async def test_abandoning_cart_leaves_workflow_and_new_question_is_not_overridden(self):
        result=await self.agent.chat('owner','算了')
        self.assertEqual(self.session.services,{})
        self.assertIn('新的需求',result['text'])
        async def new_answer(*args):
            self.session.model_used=True
            return '可以，给您讲个小故事。'
        with patch.object(self.agent,'_run',side_effect=new_answer):
            result=await self.agent.chat('owner','讲个故事')
        self.assertIn('小故事',result['text'])
        self.assertNotIn('购物车',result['text'])

    async def test_cancel_local_draft_does_not_claim_merchant_cancellation(self):
        result=await self.agent.chat('owner','取消订单')
        self.assertIn('没有可核实的真实',result['text'])
        self.assertEqual(self.session.services,{})

    async def test_already_cancelled_order_is_queried_without_another_cancel(self):
        actions=SimpleNamespace(list=lambda owner:[{'id':'ours','provider':'mcd','action':'create','order':{'order_id':'private'}}],invalidate_pending=lambda *a,**k:None)
        dispatch=AsyncMock(return_value={'order':{'orderStatus':'已取消'}})
        agent=SimpleNamespace(actions=actions,scenarios={'mcd':SimpleNamespace(dispatch=dispatch)})
        reply=await cancel_mcd_order(agent,self.session,'owner',[])
        self.assertIn('已取消',reply);self.assertIn('不需要再取消',reply)
        self.assertEqual(dispatch.await_count,1)
        self.assertEqual(dispatch.call_args.args[2],'mcd_order_status')

    async def test_unpaid_order_prepares_conditions_never_executes_cancel(self):
        dispatch=AsyncMock(side_effect=[{'order':{'orderStatus':'待支付'}},{'error':'官方没有明确返回可取消条件和取消费用，请到麦当劳官方渠道办理。'}])
        agent=SimpleNamespace(actions=SimpleNamespace(list=lambda owner:[{'id':'ours','provider':'mcd','action':'create','order':{'order_id':'private'}}]),scenarios={'mcd':SimpleNamespace(dispatch=dispatch)})
        reply=await cancel_mcd_order(agent,self.session,'owner',[])
        self.assertIn('待支付',reply);self.assertIn('新的需求',reply);self.assertNotIn('已取消',reply)
        self.assertEqual([c.args[2] for c in dispatch.call_args_list],['mcd_order_status','mcd_prepare_cancel'])

    def test_created_checkout_releases_drafts_without_cancelling_real_order(self):
        from app.task_switching import release_completed_drafts
        self.session.services['mcd']['checkout_plan_id']='owned-proposal'
        actions=SimpleNamespace(get=lambda owner,id:{'status':'created'})
        release_completed_drafts(SimpleNamespace(actions=actions),self.session,'owner')
        self.assertNotIn('mcd',self.session.services)

    async def test_luckin_delivery_followup_keeps_user_merchant_and_does_not_query_pickup(self):
        self.agent._run=AsyncMock(side_effect=AssertionError('no model or merchant lookup needed'))
        for text in ('给我点一杯瑞幸到e世界楼下','外卖可以吗','那外送呢'):
            result=await self.agent.chat('owner',text)
            self.assertIn('不能帮您点瑞幸外送',result['text'])
            self.assertNotIn('麦当劳',result['text'])
            self.assertNotIn('附近是什么地标',result['text'])
            self.assertFalse(result['events'])
        self.agent._run.assert_not_awaited()

    def test_delivery_reference_does_not_inherit_across_new_topic_or_merchant(self):
        from app.task_switching import luckin_delivery_boundary
        history=[{'role':'user','text':'点瑞幸'},{'role':'assistant','text':'可以点麦当劳'}]
        self.assertIsNotNone(luckin_delivery_boundary('外卖可以吗',history))
        self.assertIsNone(luckin_delivery_boundary('麦当劳可以外卖吗',history))
        self.assertIsNone(luckin_delivery_boundary('那我自己到店自取',history))
        self.assertIsNone(luckin_delivery_boundary('外卖可以吗',history+[{'role':'user','text':'今天北京天气'}]))

    def test_short_lookup_stays_with_latest_explicit_task(self):
        from app.task_switching import turn_domain
        history = [
            {'role':'user','text':'查询麦当劳订单'},
            {'role':'user','text':'最近的公共厕所在哪里'},
            {'role':'assistant','text':'要查步行路线吗？'},
        ]
        self.assertEqual(turn_domain('查一下',history),'amap')
        self.assertEqual(turn_domain('瑞幸：选择第1个门店',history),'luckin')
        self.assertEqual(turn_domain('我是要瑞幸，不是要麦当劳',history),'luckin')
        self.assertEqual(turn_domain('e世界',[{'role':'assistant','text':'这次想在哪家瑞幸取餐，或附近是什么地标？'}]),'luckin')
        self.assertIsNone(turn_domain('1',history+[{'role':'user','text':'你好'}]))

    async def test_luckin_delivery_landmark_does_not_select_pickup(self):
        self.agent._run=AsyncMock(side_effect=AssertionError('pickup was not accepted'))
        await self.agent.chat('owner','瑞幸能外卖吗')
        result=await self.agent.chat('owner','e世界')
        self.assertIn('愿意改成自取',result['text'])
        self.agent._run.assert_not_awaited()

    def test_old_meal_card_cannot_capture_number_after_new_reply(self):
        from app.mcd_recommendations import resolve_selection
        self.session.display = [
            {'role':'assistant','events':[{'type':'service_choices','choices':[
                {'recommendation_id':'old-meal','label':'旧套餐'}]}]},
            {'role':'user','text':'帮我打车去知春路'},
            {'role':'assistant','text':'请选目的地，1是地铁站。','events':[]},
        ]
        self.assertIsNone(resolve_selection(self.session,'1'))

    async def test_map_continuation_exposes_no_order_tools(self):
        self.session.display = [
            {'role':'user','text':'最近的公共厕所在哪里'},
            {'role':'assistant','text':'要查步行路线吗？'},
        ]
        class Bot:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def stream(self,*args,**kwargs):
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(
                    error=None,stop_reason='completed',content='请核对起点。'))
        self.agent.speech.compose=AsyncMock(return_value={'text':'请核对起点。'})
        with patch('app.agent.build_runtime',return_value=Bot()) as runtime:
            result=await self.agent._run('owner',self.session,'查一下',[],[])
        settings=runtime.call_args.args[0]
        self.assertIn('amap_route',settings['tool_names'])
        self.assertTrue(all(name.startswith('amap_') for name in settings['tool_names']))
        self.assertEqual(result,'请核对起点。')
