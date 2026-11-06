"""Real McDonald's MCP discovery/read-only probes. Never creates orders.

Credentials and tool results remain local. Public reports contain only tool
schemas and diagnostic metadata, not account data or request arguments.
"""

import argparse
import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcd_payload import business_payloads

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://mcp.mcd.cn'
LOCAL = ROOT / '.research/mcd'
REPORTS = ROOT / '.local-data/probes/mcd-probe'

# Explicit application policy, not server readOnlyHint-based authorization.
# New tools require review; unknown tools are never executable here.
READ_ONLY = frozenset({
    'query-nearby-stores', 'query-meals', 'query-meal-detail',
    'calculate-price', 'query-store-coupons', 'list-nutrition-foods',
    'delivery-query-addresses', 'delivery-query-stores',
    'query-order', 'order-list', 'now-time-info',
})


def save_json(path, value, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if private:
        path.chmod(0o600)


def redact(value, token):
    if isinstance(value, str):
        return value.replace(token, '[REDACTED]')
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, token) for key, item in value.items()}
    return value


async def probe(args):
    logging.getLogger('httpx').setLevel(logging.WARNING)
    token = (dotenv_values(ROOT / '.env').get('MCD_MCP_TOKEN') or '').strip()
    if not token:
        print('尚未配置 MCD_MCP_TOKEN。请在项目 .env 填写后重试。')
        return 2
    arguments = {}
    if args.args_file:
        arguments = json.loads(Path(args.args_file).read_text())
        if not isinstance(arguments, dict):
            raise ValueError('工具参数文件必须是 JSON 对象')
    report = {'endpoint': ENDPOINT, 'live': True, 'mode': 'read-only',
              'requested_tool': args.tool, 'order_creation_enabled': False}
    try:
        async with asyncio.timeout(60):
            async with streamablehttp_client(
                ENDPOINT, headers={'Authorization': 'Bearer ' + token},
                timeout=20, sse_read_timeout=30,
            ) as (read, write, _):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=30),
                ) as session:
                    await session.initialize()
                    tools = {}
                    cursor = None
                    for _ in range(20):
                        page = await session.list_tools(cursor=cursor)
                        tools.update((tool.name, tool) for tool in page.tools)
                        if not page.nextCursor:
                            break
                        if cursor == page.nextCursor:
                            raise RuntimeError('Repeated MCP pagination cursor')
                        cursor = page.nextCursor
                    else:
                        raise RuntimeError('MCP pagination exceeded probe limit')
                    catalog = [redact(tool.model_dump(by_alias=True, exclude_none=True), token)
                               for tool in tools.values()]
                    save_json(REPORTS / 'tool-catalog.json', catalog)
                    report.update(connected=True, tool_count=len(tools),
                                  enabled_read_only_tools=sorted(READ_ONLY & tools.keys()),
                                  excluded_tools=sorted(tools.keys() - READ_ONLY))
                    if args.tool:
                        if args.tool not in READ_ONLY or args.tool not in tools:
                            raise ValueError('Tool is not allowed or not available')
                        # Validate against the actually discovered tool schema.
                        from jsonschema import validate
                        validate(arguments, tools[args.tool].inputSchema)
                        result = await session.call_tool(args.tool, arguments=arguments)
                        payload = redact(result.model_dump(by_alias=True, exclude_none=True), token)
                        path = LOCAL / (args.tool + '-result.json')
                        save_json(path, payload, private=True)
                        report['mcp_tool_error'] = bool(result.isError)
                        report['local_result_file'] = str(path.relative_to(ROOT))
                        business = business_payloads(payload)
                        report['business_payload_found'] = bool(business)
                        report['business_success'] = (
                            all(item['success'] for item in business) if business else None
                        )
                        report['business_codes'] = [item.get('code') for item in business]
                        # Inspect returned data separately to verify the intended task.
                        report['business_result_verified'] = False
                    report['transport_ok'] = True
    except Exception as exc:
        # Avoid persisting server errors containing account or request data.
        report.update(transport_ok=False, error_type=type(exc).__name__)
        causes = getattr(exc, 'exceptions', ())
        if causes:
            report['nested_error_types'] = [type(item).__name__ for item in causes]
    save_json(REPORTS / 'latest-check.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get('business_success') is False:
        return 1
    return 0 if report.get('transport_ok') and not report.get('mcp_tool_error') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=sorted(READ_ONLY))
    parser.add_argument('--args-file', help='Local JSON object matching discovered schema')
    arguments = parser.parse_args()
    if arguments.args_file and not arguments.tool:
        parser.error('--args-file requires --tool')
    raise SystemExit(asyncio.run(probe(arguments)))
