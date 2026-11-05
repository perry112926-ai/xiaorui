import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.agent import AgentService
from app.plans import PlanStore
from app.contact_events import contact_observer
from app.speech import SpeechComposer

class FactualReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unverified_synonyms_never_stream_or_become_business_answer(self):
        draft='单子已经帮您弄好了，师傅在路上了。'
        class Bot:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def stream(self,*args,**kwargs):
                yield SimpleNamespace(type='text.delta',delta=draft,name=None)
                yield SimpleNamespace(type='run.completed',name=None,result=SimpleNamespace(content=draft,error=None,stop_reason='completed'))
        with tempfile.TemporaryDirectory() as temp:
            service=SimpleNamespace(stores={})
            agent=AgentService(service,PlanStore(Path(temp)/'plans.db'),data_dir=Path(temp)/'agent')
            captured=[];token=contact_observer.set(captured.append)
            try:
                with patch.object(agent,'_config',return_value={'key':'test','model':'test','base':'https://unused.invalid'}),patch('app.agent.build_runtime',return_value=Bot()):
                    response=await agent.chat('test-owner','帮我叫车')
            finally:contact_observer.reset(token)
            self.assertNotIn('师傅在路上',str(captured)+str(response))
            self.assertNotIn('弄好了',response['text'])
            self.assertEqual(response['speech_source'],'grounded')
            self.assertFalse(agent.actions.list('test-owner'))

    async def test_business_choices_do_not_call_freeform_narrator(self):
        events=[{'type':'service_choices','choices':[{'label':'快车','detail':'本次预估 52 元'}]}]
        with patch('app.speech.httpx.AsyncClient') as network:
            result=await SpeechComposer().compose({'key':'test','base':'https://unused.invalid','model':'test'},'有哪些车','师傅在路上了',events,[])
        network.assert_not_called();self.assertEqual(result['source'],'grounded');self.assertNotIn('师傅',result['text'])

    def test_closed_store_facts_never_invite_immediate_selection(self):
        from app.factual_replies import business_reply
        from app.agent import choice_cards
        data={'stores':[{'name':'测试门店','index':1,'open':False}]}
        reply=business_reply('查麦当劳',{},[('mcd_search_pickup',data)],[])
        self.assertIn('都未营业',reply)
        self.assertFalse(choice_cards(data)[0]['available'])
