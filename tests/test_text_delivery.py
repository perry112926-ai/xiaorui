import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

from app.agent import AgentService
from app.contact import ContactService
from app.contact_events import contact_reply_mode
from app.plans import PlanStore
from app.text_delivery import quick_answer,acknowledgement,lightweight_chat


class TextDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def test_only_explicit_casual_messages_use_lightweight_context(self):
        self.assertTrue(lightweight_chat('请列出6个轻松的周末活动，每项一句话。'))
        for text in ['周末帮我打车', '讲个故事并记住我喜欢它', '就选这个', '查一下附近可以放松的地方']:
            self.assertFalse(lightweight_chat(text))

    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.agent=AgentService(SimpleNamespace(stores={}),PlanStore(root/'plans.db'),data_dir=root/'agent')
        self.config=patch.object(self.agent,'_config',return_value={'key':'test','model':'test','base':'https://test.invalid'})
        self.config.start()

    async def asyncTearDown(self):
        self.config.stop();self.tmp.cleanup()

    async def test_long_text_returns_before_narrator_and_later_updates_only_its_message(self):
        answer='1. 第一项，测试内容。\n2. 第二项，测试内容。\n'*8
        class Bot:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def stream(self,*args,**kwargs):
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(error=None,stop_reason='completed',content=answer))
        self.agent.speech.compose=AsyncMock(return_value={'text':'这是稍后准备好的自然播报。','source':'model','stage':'conversation'})
        mode=contact_reply_mode.set('text')
        try:
            with patch('app.agent.build_runtime',return_value=Bot()):
                result=await self.agent.chat('a','请列出多个选项')
            self.agent.speech.compose.assert_not_awaited()
            self.assertTrue(result['speech_deferred'])
            self.assertEqual(result['text'],answer.strip())
            event=await self.agent.complete_speech('a',result['task_id'])
            self.assertEqual(event['speech_text'],'这是稍后准备好的自然播报。')
            self.assertEqual(self.agent.history('a')['messages'][-1]['speech_text'],event['speech_text'])
        finally:
            contact_reply_mode.reset(mode)

    async def test_greeting_uses_real_host_answer_without_model_or_narration(self):
        mode=contact_reply_mode.set('text')
        try:
            with patch('app.agent.build_runtime') as runtime:
                result=await self.agent.chat('a','在吗？')
            runtime.assert_not_called()
            self.assertEqual(result['text'],'我在，您说。')
        finally:
            contact_reply_mode.reset(mode)

    async def test_profile_change_prevents_stale_background_speech_delivery(self):
        state=self.agent._session('a')
        state.defer_speech=True
        result=self.agent._answer('a',state,'测试','测试长回复',[],[],'test-task')
        self.agent.speech.compose=AsyncMock(return_value={'text':'旧资料播报','source':'model','stage':'conversation'})
        self.agent.store.save_profile_card(0,{'home.address':'新测试地址'})
        self.assertIsNone(await self.agent.complete_speech('a',result['task_id']))

    def test_receipts_are_not_transaction_success_or_approval(self):
        self.assertEqual(quick_answer('你好，帮我下单'),None)
        for text in ['确认叫车','取消订单','帮我查北京天气']:
            receipt=acknowledgement(text)
            self.assertNotIn('成功',receipt)
            self.assertNotIn('已下单',receipt)
            self.assertNotIn('确认叫车',receipt)


class BackgroundNarrationQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_narration_does_not_hold_next_chat_turn_and_receipt_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate=asyncio.Event();entered=asyncio.Event();calls=[]
            async def chat(owner,text,**kwargs):
                calls.append(text)
                return {'text':text,'events':[],'task_id':text,'speech_deferred':text=='first'}
            async def compose(*args):
                entered.set();await gate.wait()
                return {'type':'speech_ready','task_id':'first','speech_text':'later'}
            agent=SimpleNamespace(chat=chat,complete_speech=compose,discard_speech=Mock(),
                actions=SimpleNamespace(pending=Mock(return_value=None),invalidate_pending=Mock()),
                _session=lambda _:SimpleNamespace(lock=asyncio.Lock()),_plan=lambda *_:None)
            contact=ContactService(agent,Path(tmp)/'contact.db')
            try:
                receipt=contact.enqueue('a','first','text-first')
                self.assertEqual(receipt,contact.enqueue('a','first','text-first'))
                self.assertEqual(receipt['event']['ack_text'],'收到，我看看。')
                await asyncio.wait_for(entered.wait(),2)
                contact.enqueue('a','second','text-second')
                await asyncio.wait_for(contact.workers['a'],2)
                self.assertEqual(calls,['first','second'])
                self.assertFalse(gate.is_set())
                self.assertTrue(any(e['type']=='completed' and e['response']['text']=='second' for e in contact.events('a')))
            finally:
                gate.set();await contact.close()


if __name__=='__main__':
    unittest.main()
