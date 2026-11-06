"""Offline integration probes; no model, fake provider, or external API.

Run write then read in separate processes to verify actual disk persistence.
The sample preference is test input, not a claim about the user's preferences.
"""

import argparse
import asyncio
import importlib.metadata
import inspect
import json
from pathlib import Path

from nanobot import Nanobot
from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / '.research/nanobot/probe-workspace'
SESSION_ROOT = ROOT / '.research/nanobot/probe-sessions'
RESULTS = ROOT / '.local-data/probes/nanobot-probe'
MEMORY = '集成验证资料：长期偏好测试条目。不是用户真实资料。'
MESSAGE = '集成验证历史：测试会话持久化。'


class ReadProbeMemory(Tool):
    """A real read-only local tool used to check the extension interface."""

    @property
    def name(self):
        return 'read_probe_memory'

    @property
    def description(self):
        return 'Read the isolated integration-probe memory file.'

    @property
    def parameters(self):
        return {'type': 'object', 'properties': {}, 'additionalProperties': False}

    @property
    def read_only(self):
        return True

    async def execute(self, **kwargs):
        return MemoryStore(WORKSPACE).read_memory()


async def main(mode):
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(WORKSPACE)
    sessions = SessionManager(WORKSPACE, sessions_root=SESSION_ROOT)
    report = {
        'mode': mode,
        'version': importlib.metadata.version('nanobot-ai'),
        'sdk_import': True,
        'sdk_from_config_signature': str(inspect.signature(Nanobot.from_config)),
        'scope': 'offline storage and tool extension only; no semantic recall test',
    }
    if mode == 'write':
        store.write_memory(MEMORY)
        session = sessions.get_or_create('probe:storage')
        session.clear()
        session.add_message('user', MESSAGE)
        sessions.save(session)
        report['memory_written'] = store.read_memory() == MEMORY
        report['history_written'] = True
        assert report['memory_written']
    else:
        assert store.read_memory() == MEMORY
        session = sessions.get_existing('probe:storage')
        assert session is not None
        assert any(message.get('content') == MESSAGE for message in session.messages)
        report['memory_read_in_new_process'] = True
        report['history_read_in_new_process'] = True

        registry = ToolRegistry()
        registry.register(ReadProbeMemory())
        value = await registry.execute('read_probe_memory', {})
        assert value == MEMORY
        report['custom_tool_reads_real_file'] = True
        rejected = await registry.execute('read_probe_memory', {'unexpected': True})
        assert 'unexpected' in str(rejected).lower()
        report['invalid_tool_arguments_rejected'] = True
        registry.unregister('read_probe_memory')
        assert not registry.has('read_probe_memory')
        report['tool_unregister'] = True

    (RESULTS / (mode + '.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['write', 'read'])
    asyncio.run(main(parser.parse_args().mode))
