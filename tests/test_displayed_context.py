import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import AgentService
from app.plans import PlanStore


class DisplayedContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_receives_host_only_replies_and_uses_them_in_followup(self):
        class Bot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def stream(self, *args, **kwargs):
                yield SimpleNamespace(type='run.completed', name=None, result=SimpleNamespace(
                    content='刚才说的是瑞幸。', error=None, stop_reason='completed'))

        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            agent = AgentService(SimpleNamespace(stores={}), PlanStore(path/'plans.db'), data_dir=path/'agent')
            agent._config = lambda: {'key': 'test', 'model': 'test', 'base': 'https://unused.invalid'}
            first = await agent.chat('owner', '给我点一杯瑞幸到e世界楼下')
            second = await agent.chat('owner', '外卖可以吗')
            self.assertNotEqual(first['text'], second['text'])
            self.assertIn('刚才那杯瑞幸', second['text'])

            async def build_context():
                with patch('app.agent.build_runtime', return_value=Bot()) as build:
                    answer = await agent.chat('owner', '你刚才说的是哪个品牌？')
                blocks = await build.call_args.args[3](None)
                return answer, next(block.content for block in blocks if block.source == 'recent_displayed_dialogue')

            answer, context = await build_context()
            self.assertIn('给我点一杯瑞幸到e世界楼下', context)
            self.assertIn('外卖可以吗', context)
            self.assertIn(second['text'], context)
            self.assertEqual(answer['text'], '刚才说的是瑞幸。')
