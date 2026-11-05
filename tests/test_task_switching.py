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
