import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app.companion_memory import CompanionMemory

class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'memory.db';self.memory=CompanionMemory(self.path)
    def tearDown(self):self.tmp.cleanup()

    async def test_recall_survives_restart_without_owner_or_epoch_leak(self):
        self.memory.record('a',0,'我喜欢周末看京剧')
        self.memory.record('b',0,'我的京剧秘密')
        recalled=CompanionMemory(self.path).recall('a',0,'京剧')
        self.assertEqual([r['text'] for r in recalled['episodes']],['我喜欢周末看京剧'])
        self.assertEqual(self.memory.recall('a',2,'京剧')['episodes'],[])

    async def test_network_failure_keeps_episode_and_forgetting_removes_recall(self):
        with patch('httpx.AsyncClient.post',side_effect=httpx.ConnectError('offline')):
            status=await self.memory.learn('a',0,'我喜欢京剧',{'key':'fake','base':'https://example.invalid','model':'x'})
        self.assertEqual(status,'archive_only')
        self.assertTrue(self.memory.recall('a',0,'京剧')['episodes'])
        await self.memory.learn('a',0,'忘记我的爱好',{})
        self.assertEqual(self.memory.recall('a',0,'京剧')['episodes'],[])

    async def test_temporary_request_is_not_archived(self):
        await self.memory.learn('a',0,'今天临时预算二十元，不要长期保存',{})
        self.assertEqual(self.memory.recall('a',0,'预算')['episodes'],[])

    async def test_question_does_not_create_false_evidence(self):
        with patch('httpx.AsyncClient.post') as post:
            await self.memory.learn('a',0,'我喜欢什么？',{'key':'fake'})
        post.assert_not_called()
        self.assertEqual(self.memory.recall('a',0,'喜欢')['preferences'],[])

    async def test_curator_requires_exact_evidence_and_updates_same_topic(self):
        def response(facts):
            import json
            return httpx.Response(200,request=httpx.Request('POST','https://example.invalid'),json={'choices':[{'message':{'content':json.dumps({'facts':facts})}}]})
        cfg={'key':'fake','base':'https://example.invalid','model':'x'}
        with patch('httpx.AsyncClient.post',return_value=response([{'key':'hobby','value':'京剧','evidence':'喜欢京剧'},{'key':'made-up','value':'游泳','evidence':'不存在的原话'}])):
            await self.memory.learn('a',0,'我喜欢京剧',cfg)
        with patch('httpx.AsyncClient.post',return_value=response([{'key':'hobby','value':'越剧','evidence':'改为越剧'}])):
            await self.memory.learn('a',0,'现在改为越剧',cfg)
        facts=self.memory.recall('a',0,'爱好')['preferences']
        self.assertEqual(len(facts),1);self.assertEqual(facts[0]['value'],'越剧')
