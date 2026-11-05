"""Progress reflects host work; diagnostics contain no arguments or secrets."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent import AgentService
from app.contact_events import contact_observer
from app.plans import PlanStore
from app.progress import TOOL_ACTIVITY, tool_activity
from app.skills import SCHEMAS


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    def test_all_executable_tools_have_human_readable_activity(self):
        self.assertEqual(set(TOOL_ACTIVITY), set(SCHEMAS))
        self.assertIn('还没有叫车', tool_activity('didi_estimate_ride')['text'])
        self.assertIn('还没有下单', tool_activity('mcd_prepare_order')['text'])
        self.assertIn('还没有取消', tool_activity('didi_prepare_cancel')['text'])
        self.assertNotIn('private-unknown', str(tool_activity('private-unknown')))

    async def test_real_run_emits_tool_stage_and_records_separate_timing_spans(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = AsyncMock()
            service.stores = {}
            agent = AgentService(service, PlanStore(root/'plans.db'), data_dir=root/'agent')
            agent._tool = AsyncMock(return_value={'products': []})
            agent.speech.compose = AsyncMock(return_value={
                'text': '请再告诉我想找哪一种餐品。', 'source': 'brief', 'stage': 'conversation'})

            def runtime(settings, directory, dispatch, context):
                class Bot:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                    async def stream(self, *args, **kwargs):
                        await dispatch('mcd_menu', {'private': 'never show this argument'})
                        yield SimpleNamespace(type='text.delta', delta='请再告诉我', name=None)
                        yield SimpleNamespace(type='run.completed', name=None, result=SimpleNamespace(
                            error=None, stop_reason='completed', content='请再告诉我想找哪一种餐品。'))
                return Bot()

            received = []
            token = contact_observer.set(received.append)
            try:
                with patch('app.agent.build_runtime', side_effect=runtime), patch.object(
                    agent, '_config', return_value={'key': 'secret-test-key', 'model': 'test', 'base': 'https://unused.invalid'}):
                    result = await agent.chat('owner', '看看菜单')
            finally:
                contact_observer.reset(token)
            statuses = [event['text'] for event in received if event['type'] == 'progress']
            self.assertIn('正在查麦当劳菜单', statuses)
            self.assertEqual(statuses[-1], '已核对真实结果，正在显示')
            timing = [event for event in result['trace'] if event['type'] == 'timing']
            self.assertEqual({event['stage'] for event in timing}, {
                'tool', 'first_text', 'runtime_including_tools', 'speech_composition'})
            self.assertTrue(all(event['elapsed_ms'] >= 0 for event in timing))
            self.assertNotIn('never show this argument', str(received) + str(timing))
            self.assertNotIn('secret-test-key', str(received) + str(timing))
