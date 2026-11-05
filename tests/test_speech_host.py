"""Verify the host persists independent speech and protects critical facts."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace

from app.agent import AgentService
from app.plans import PlanStore


class SpeechHostTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        service=AsyncMock();service.stores={}
        self.agent=AgentService(service,PlanStore(root/'plans.db'),data_dir=root/'agent')

    def tearDown(self):
        self.tmp.cleanup()

    async def test_real_run_path_passes_history_and_keeps_visual_and_spoken_answers_separate(self):
        answer='这是屏幕上的完整介绍，包含很多可以阅读的细节。'*10
        class Bot:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def stream(self,*args,**kw):
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(error=None,stop_reason='completed',content=answer))
        self.agent.speech.compose=AsyncMock(return_value={'text':'咱们先选一件轻松的事，听听喜欢的音乐怎么样？','source':'model','stage':'conversation'})
        session=self.agent._session('a');session.display=[{'role':'user','text':'想休息一下'}]
        with patch('app.agent.build_runtime',return_value=Bot()),patch.object(self.agent,'_config',return_value={'key':'test-only','model':'test-only','base':'https://test.invalid'}):
            response=await self.agent.chat('a','给我一些建议')
        self.assertEqual(response['text'],answer)
        self.assertNotEqual(response['speech_text'],answer)
        self.assertEqual(response['speech_source'],'model')
        self.assertIn('想休息一下',str(self.agent.speech.compose.call_args))
        self.assertEqual(self.agent.history('a')['messages'][-1]['speech_text'],response['speech_text'])

    async def test_stale_narrator_draft_cannot_replace_transaction_confirmation(self):
        session=self.agent._session('a')
        session.speech_turn={'text':'已经帮您叫车了','source':'model','stage':'conversation'}
        plan={'provider':'didi','action':'create','status':'awaiting_confirmation','amount_cents':5200,
              'execution_enabled':True,'confirmation_text':'确认叫车',
              'summary':{'实际上车点':'测试起点','实际下车点':'测试终点','车型':'快车'}}
        result=self.agent._answer('a',session,'选快车','完整方案',[{'type':'action_plan','plan':plan}],[],'test-task')
        self.assertEqual(result['speech_source'],'grounded')
        self.assertIn('52元',result['speech_text'])
        self.assertIn('免密扣款',result['speech_text'])
        self.assertIn('确认叫车',result['speech_text'])
        self.assertNotIn('已经帮您叫车',result['speech_text'])

    async def test_host_passes_current_profile_to_speech_editor_after_preferences_change(self):
        self.agent.store.set_fact('preferences.food','喜欢鱼类')
        self.agent.speech.compose=AsyncMock(return_value={'text':'先核对您选的餐品。','source':'model','stage':'choose_meal'})
        class Bot:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def stream(self,*args,**kw):
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(error=None,stop_reason='completed',content='按您喜欢鱼类的偏好，先看看真实菜单。'))
        with patch('app.agent.build_runtime',return_value=Bot()),patch.object(self.agent,'_config',return_value={'key':'test-only','model':'test-only','base':'https://test.invalid'}):
            await self.agent.chat('a','推荐午餐')
        self.assertEqual(self.agent.speech.compose.call_args.kwargs['profile']['facts']['preferences.food'],'喜欢鱼类')
        self.agent.store.delete_fact('preferences.food')
        with patch('app.agent.build_runtime',return_value=Bot()),patch.object(self.agent,'_config',return_value={'key':'test-only','model':'test-only','base':'https://test.invalid'}):
            await self.agent.chat('a','再看看')
        self.assertNotIn('preferences.food',self.agent.speech.compose.call_args.kwargs['profile']['facts'])
