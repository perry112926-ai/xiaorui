"""Behavioral gaps found by the personal-agent capability audit."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
import json
from app.companion_memory import CompanionMemory

class CapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.memory=CompanionMemory(Path(self.tmp.name)/'memory.db')
    def tearDown(self):self.tmp.cleanup()

    async def test_negative_forget_is_not_a_delete_request(self):
        self.memory.record('a',0,'我喜欢听京剧')
        await self.memory.learn('a',0,'请不要忘记我喜欢听京剧',{})
        self.assertTrue(self.memory.recall('a',0,'京剧')['episodes'])

    async def test_discussing_forgetting_does_not_erase_memory(self):
        self.memory.record('a',0,'我喜欢听京剧')
        await self.memory.learn('a',0,'你为什么会忘记事情？',{})
        self.assertTrue(self.memory.recall('a',0,'京剧')['episodes'])

    async def test_topic_forgetting_preserves_unrelated_preference(self):
        self.memory.record('a',0,'我喜欢听京剧')
        self.memory.record('a',0,'我喜欢喝热茶')
        await self.memory.learn('a',0,'请忘记我的京剧爱好',{})
        self.assertFalse(any('京剧' in x['text'] for x in self.memory.recall('a',0,'京剧')['episodes']))
        self.assertTrue(any('热茶' in x['text'] for x in self.memory.recall('a',0,'热茶')['episodes']))

    async def test_durable_change_today_is_not_discarded(self):
        cfg={'key':'fake','base':'https://example.invalid','model':'fake'}
        fact={'key':'drink','value':'以后只喝热茶','evidence':'以后只喝热茶'}
        response=httpx.Response(200,request=httpx.Request('POST',cfg['base']),json={'choices':[{'message':{'content':json.dumps({'facts':[fact]})}}]})
        with patch('httpx.AsyncClient.post',return_value=response):
            await self.memory.learn('a',0,'今天我决定以后只喝热茶',cfg)
        self.assertEqual(self.memory.recall('a',0,'喝什么')['preferences'][0]['value'],'以后只喝热茶')

    async def test_assistant_context_is_retained_with_role_but_not_curated_as_user_fact(self):
        await self.memory.learn('a',0,'你建议什么活动？',{},reply='可以看看附近的戏曲展览。')
        recall=self.memory.recall('a',0,'戏曲展览')
        self.assertIn('assistant:',recall['episodes'][0]['text'])
        self.assertFalse(recall['preferences'])

    async def test_long_message_recall_keeps_relevant_late_fact(self):
        self.memory.record('a',0,'无关内容。'*600+'我的测试乐器是琵琶。')
        recall=self.memory.recall('a',0,'测试乐器')
        self.assertIn('琵琶',recall['episodes'][0]['text'])

    async def test_context_serialization_stays_inside_host_budget(self):
        for i in range(40):self.memory.record('a',0,'京剧'+'x'*1800+str(i))
        with self.memory.db() as db:
            for i in range(24):db.execute('INSERT INTO preferences VALUES (?,?,?,?,?,?,?)',('a',0,str(i),'京剧'*200,'京剧'*100,i,1))
        recall=self.memory.recall('a',0,'京剧')
        from app.companion_memory import encoded_size
        self.assertLess(encoded_size(recall),18000)

    async def test_memory_storage_failure_does_not_fail_completed_reply(self):
        import sqlite3
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.agent import AgentService
        from app.plans import PlanStore
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'plans.db'),data_dir=Path(self.tmp.name)/'agent')
        with patch.object(agent,'_config',return_value={'key':'test','model':'test','base':'https://example.invalid'}),patch.object(agent,'_run',new=AsyncMock(return_value='今天聊聊戏曲吧。')),patch.object(agent.memory,'learn',new=AsyncMock(side_effect=sqlite3.OperationalError('disk busy'))):
            result=await agent.chat('a','聊聊戏曲')
        self.assertEqual(result['text'],'今天聊聊戏曲吧。')
        self.assertIn({'type':'memory.learn','status':'unavailable'},result['trace'])

    async def test_host_forget_rotates_sdk_context_without_losing_other_memories(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.agent import AgentService
        from app.plans import PlanStore
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'p.db'),data_dir=Path(self.tmp.name)/'a')
        owner='a';session=agent._session(owner);before=session.conversation_id
        agent.memory.record(owner,session.forget_epoch,'我喜欢京剧')
        agent.memory.record(owner,session.forget_epoch,'我喜欢热茶')
        with patch.object(agent,'_config',return_value={'key':'test','model':'test','base':'https://example.invalid'}),patch.object(agent,'_run',new=AsyncMock()) as model:
            result=await agent.chat(owner,'请忘记我的京剧爱好')
        model.assert_not_called()
        self.assertNotEqual(before,agent._session(owner).conversation_id)
        recall=agent.memory.recall(owner,agent._session(owner).forget_epoch,'热茶')
        self.assertTrue(any('热茶' in r['text'] for r in recall['episodes']))
        self.assertFalse(any('京剧' in r['text'] for r in recall['episodes']))
        self.assertIn('已删除',result['text'])

    async def test_canonical_delete_preserves_surviving_inferred_memory(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.agent import AgentService
        from app.plans import PlanStore
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'p2.db'),data_dir=Path(self.tmp.name)/'a2')
        owner='a';session=agent._session(owner)
        agent.store.set_fact('preferences.opera','京剧')
        agent.memory.record(owner,session.forget_epoch,'我喜欢京剧')
        agent.memory.record(owner,session.forget_epoch,'我喜欢热茶')
        async def model(owner,session,text,events,trace):
            await agent._tool(session,owner,'personal_profile',{'action':'forget','key':'preferences.opera'},events)
            return '已忘记京剧偏好。'
        with patch.object(agent,'_config',return_value={'key':'test','model':'test','base':'https://example.invalid'}),patch.object(agent,'_run',new=model):
            await agent.chat(owner,'请忘记我的京剧爱好')
        recall=agent.memory.recall(owner,agent._session(owner).forget_epoch,'热茶')
        self.assertTrue(any('热茶' in row['text'] for row in recall['episodes']))
        self.assertFalse(any('京剧' in row['text'] for row in recall['episodes']))

    def test_transaction_commands_are_not_memory_delete_requests(self):
        from app.companion_memory import forget_target
        for text in ['删除订单','delete my order','remove item from cart','请忘记叫车任务']:
            self.assertIsNone(forget_target(text))

    async def test_english_topic_delete_does_not_match_generic_favorite(self):
        with self.memory.db() as db:
            db.execute('INSERT INTO preferences VALUES (?,?,?,?,?,?,?)',('a',0,'favorite opera','Peking','I like opera',1,1))
            db.execute('INSERT INTO preferences VALUES (?,?,?,?,?,?,?)',('a',0,'favorite drink','tea','I like tea',2,2))
        await self.memory.learn('a',0,'forget my favorite opera',{})
        facts=self.memory.recall('a',0,'drink')['preferences']
        self.assertEqual([r['key'] for r in facts],['favorite drink'])

    def test_excerpt_keeps_original_date_and_speaker(self):
        from app.companion_memory import relevant_excerpt
        text='2023/04/01 user: '+'filler '*500+'my instrument is pipa'
        excerpt=relevant_excerpt(text,{'instrument'},{'instrument':2})
        self.assertIn('2023/04/01 user:',excerpt)
        self.assertIn('instrument is pipa',excerpt)
        self.assertLessEqual(len(excerpt),2000)

    async def test_forgotten_fact_cannot_return_via_old_task_body(self):
        from types import SimpleNamespace
        from app.agent import AgentService
        from app.plans import PlanStore
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'barrier-p.db'),data_dir=Path(self.tmp.name)/'barrier-a')
        session=agent._session('a')
        task_id=agent.store.start_task('a',session.conversation_id,'我喜欢京剧')
        agent.store.finish_task(task_id,'completed',result={'text':'您喜欢京剧'})
        agent.memory.record('a',session.forget_epoch,'我喜欢京剧')
        agent.memory.forget('a','我的京剧爱好')
        self.assertNotIn('京剧',json.dumps(agent.tasks('a'),ensure_ascii=False))
        result=await agent._tool(session,'a','task_records',{'action':'get','task_id':task_id},[])
        self.assertIn('task',result)
        self.assertNotIn('京剧',json.dumps(result,ensure_ascii=False))
        self.assertEqual(agent.store.get_task('a',task_id)['status'],'completed')

    async def test_football_does_not_mean_forget_all(self):
        self.memory.record('a',0,'I enjoy football')
        self.memory.record('a',0,'I drink tea')
        await self.memory.learn('a',0,'forget my football preference',{})
        rows=self.memory.recall('a',0,'tea')['episodes']
        self.assertTrue(any('tea' in r['text'] for r in rows))
        self.assertFalse(any('football' in r['text'] for r in rows))

    def test_bracket_heavy_context_is_not_truncated_by_host(self):
        from app.nanobot_runtime import data_context
        for i in range(35):self.memory.record('a',0,'京剧 '+('[]'*1000)+str(i))
        recall=self.memory.recall('a',0,'京剧')
        encoded=json.dumps(recall,ensure_ascii=False).replace('[','\\u005b').replace(']','\\u005d')
        self.assertLess(len(encoded),18000)
        self.assertIn('companion_memory: '+encoded,data_context('companion_memory',recall).content)

    async def test_canonical_forget_removes_old_value_without_topic_word(self):
        from types import SimpleNamespace
        from app.agent import AgentService
        from app.plans import PlanStore
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(self.tmp.name)/'nick-p.db'),data_dir=Path(self.tmp.name)/'nick-a')
        session=agent._session('a');agent.store.set_fact('preferences.nickname','小张')
        agent.memory.record('a',session.forget_epoch,'朋友都叫我小张')
        agent.memory.record('a',session.forget_epoch,'我喜欢热茶')
        async def model(owner,session,text,events,trace):
            await agent._tool(session,owner,'personal_profile',{'action':'forget','key':'preferences.nickname'},events)
            return '已忘记。'
        with patch.object(agent,'_config',return_value={'key':'test','model':'test','base':'https://example.invalid'}),patch.object(agent,'_run',new=model):
            await agent.chat('a','请忘记我的称呼')
        recall=agent.memory.recall('a',agent._session('a').forget_epoch,'小张 热茶')
        self.assertNotIn('小张',json.dumps(recall,ensure_ascii=False))
        self.assertIn('热茶',json.dumps(recall,ensure_ascii=False))

    def test_literal_value_all_does_not_delete_everything(self):
        self.memory.record('a',0,'my nickname is all')
        self.memory.record('a',0,'I like football and tea')
        self.memory.forget('a','all',literal=True)
        rows=self.memory.recall('a',0,'football tea')['episodes']
        self.assertTrue(any('football' in row['text'] for row in rows))
