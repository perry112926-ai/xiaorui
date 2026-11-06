"""Real Ark + nanobot + real isolated profile storage. No mock endpoints."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import dotenv_values
from loguru import logger
from nanobot import Nanobot
from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool
from nanobot.config.home import set_home_path

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / '.research/nanobot/live-instance'
WORKSPACE = INSTANCE / 'workspace'
RESULTS = ROOT / '.local-data/probes/nanobot-probe'


class PreferenceTool(Tool):
    """Persist/retrieve probe preferences through the real nanobot memory store."""

    @property
    def name(self):
        return 'personal_preference'

    @property
    def description(self):
        return '保存或读取隔离验证用户的长期偏好；返回实际持久化内容。'

    @property
    def parameters(self):
        return {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['save', 'read']},
            'preference': {'type': 'string', 'maxLength': 200},
        }, 'required': ['action'], 'additionalProperties': False}

    async def execute(self, action, preference=''):
        store = MemoryStore(WORKSPACE)
        if action == 'save':
            if not preference.strip():
                return self.error('保存内容不能为空')
            store.write_memory('仅用于集成验证的测试用户偏好：' + preference)
        return json.dumps({'persisted_preference': store.read_memory()}, ensure_ascii=False)


async def main(mode, api):
    logger.remove()  # Avoid upstream debug logs exposing request or credential details.
    settings = dotenv_values(ROOT / '.env')
    key = settings.get('ARK_API_KEY')
    if not key:
        raise SystemExit('Missing ARK_API_KEY')
    os.environ['ARK_API_KEY'] = key
    INSTANCE.mkdir(parents=True, exist_ok=True)
    set_home_path(INSTANCE)
    config = {
        'agents': {'defaults': {
            'workspace': str(WORKSPACE), 'model': settings['ARK_MODEL'],
            'provider': 'ark', 'maxTokens': 1024, 'maxToolIterations': 4,
            'timezone': 'Asia/Shanghai', 'dream': {'enabled': False},
        }},
        'providers': {'ark': {
            'apiKey': '${ARK_API_KEY}', 'apiBase': settings['ARK_BASE_URL'],
            'api': {'supportedApis': [api], 'preferredApi': api},
            'extraBody': ({'extra_body': {'thinking': {'type': 'disabled'}}}
                          if api == 'responses' else {'thinking': {'type': 'disabled'}}),
        }},
    }
    path = INSTANCE / 'config.json'
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    started = time.monotonic()
    report = {'mode': mode, 'api': api, 'live': True,
              'thinking': 'disabled', 'model': settings['ARK_MODEL']}
    try:
        async with Nanobot.from_config(path) as bot:
            # Deliberately isolate tool surface. This uses an internal loop accessor;
            # production composition must avoid depending on this private API.
            registry = bot._loop.tools
            for name in list(registry.tool_names):
                registry.unregister(name)
            registry.register(PreferenceTool())
            assert registry.tool_names == ['personal_preference']
            if mode == 'save':
                message = ('这是隔离测试用户，不是真实用户资料。以后买饮料都不要冰的，'
                           '请调用 personal_preference 工具保存这条长期偏好，再简短告知保存结果。')
            else:
                message = ('这是新对话。请调用 personal_preference 工具读取我已保存的饮料偏好，'
                           '只根据工具实际结果回答，不要猜测。')
            result = await asyncio.wait_for(
                bot.run(message, session_key='live-probe:' + api + ':' + mode), timeout=60,
            )
            persisted = MemoryStore(WORKSPACE).read_memory()
            report.update(
                answer=result.content, tools_used=result.tools_used,
                stop_reason=result.stop_reason, persisted_preference=persisted,
                effective_tools=registry.tool_names,
            )
            report['ok'] = ('personal_preference' in result.tools_used
                            and bool(persisted) and '冰' in persisted
                            and registry.tool_names == ['personal_preference']
                            and result.stop_reason == 'completed'
                            and not result.content.startswith('Error'))
    except Exception as exc:
        report.update(ok=False, error_type=type(exc).__name__,
                      message=str(exc).replace(key, '[REDACTED]'))
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / ('ark-nanobot-' + api + '-' + mode + '.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['save', 'read'])
    parser.add_argument('--api', choices=['responses', 'chat_completions'],
                        default='chat_completions')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.mode, args.api)))
