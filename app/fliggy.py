"""Read-only flights through the signed official FlyAI CLI (1.0.16)."""
import asyncio
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / '.local-data/flyai/cli/dist/flyai-bundle.cjs'


class FlightSearch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    origin: str = Field(min_length=1, max_length=80)
    destination: str = Field(min_length=1, max_length=80)
    dep_date: date
    back_date: date | None = None
    direct_only: bool = Field(default=False, strict=True)
    max_price: int | None = Field(default=None, ge=1, le=1000000, strict=True)
    seat_class_name: str | None = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def valid_dates(self):
        if self.dep_date < datetime.now(ZoneInfo('Asia/Shanghai')).date():
            raise ValueError('departure is in the past')
        if self.back_date and self.back_date < self.dep_date:
            raise ValueError('return precedes departure')
        if self.origin == self.destination:
            raise ValueError('identical cities')
        return self


SCHEMAS = {'fliggy_search_flights': (FlightSearch,
    '飞猪官方实时机票查询。先问清出发地、目的地、出发日期，日期按上海时区换算为YYYY-MM-DD；'
    '可按预算、直飞和舱位搜索。只查询，不下单、不扣款、不出票。'
    '只使用返回的航班和booking_url，提供完整预订链接；报价不等于最终含税总价。'
    '请用户在飞猪核对乘机人、行程、税费行李和退改规则并付款，不能声称已订票。')}


def booking_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname == 'router.feizhu.com'
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and not any(c in value for c in '\r\n<>')):
            return value
    except ValueError:
        pass
    return None


def normalize(payload):
    if not isinstance(payload, dict) or payload.get('success') is False or payload.get('error'):
        raise ValueError('provider error')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('itemList'), list):
        raise ValueError('invalid payload')
    flights = []
    segment_fields = ('depCityName', 'arrCityName', 'depStationName', 'arrStationName',
                      'depTerm', 'arrTerm', 'depDateTime', 'arrDateTime',
                      'marketingTransportName', 'marketingTransportNo', 'seatClassName', 'duration')
    for item in data['itemList'][:10]:
        if not isinstance(item, dict):
            continue
        link = booking_url(item.get('jumpUrl'))
        journeys = []
        for journey in (item.get('journeys') or [])[:4]:
            if not isinstance(journey, dict):
                continue
            segments = [{k: s[k] for k in segment_fields if isinstance(s.get(k), (str, int))}
                        for s in (journey.get('segments') or [])[:8] if isinstance(s, dict)]
            if segments:
                journeys.append({'type': str(journey.get('journeyType') or ''), 'segments': segments})
        if link and journeys:
            price = item.get('ticketPrice')
            flights.append({'index': len(flights)+1, 'journeys': journeys,
                            'ticket_price_yuan': price if isinstance(price, (str, int, float)) else None,
                            'booking_url': link})
    return {'flights': flights, 'source': '飞猪 AI 官方实时查询',
            'checked_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
            'order_created': False, 'paid': False,
            'note': '搜索报价，最终含税总价、库存、行李和退改规则以飞猪结算页为准。尚未预订或出票。',
            'next': '选择航班后打开返回的飞猪预订链接，核对乘机人和费用并自行确认付款。' if flights else '本次没有可展示的航班，请调整日期或条件。'}


class Fliggy:
    async def dispatch(self, arguments):
        try:
            args = FlightSearch.model_validate(arguments)
        except ValidationError:
            return {'error': '请提供不同的出发地和目的地、有效的未来出发日期及正确预算；回程不能早于出发。'}
        key = str(os.environ.get('FLYAI_API_KEY', dotenv_values(ROOT / '.env').get('FLYAI_API_KEY') or '')).strip()
        if not key:
            return {'error': '飞猪尚未配置，请由家人在本机设置 FLYAI_API_KEY。'}
        node = shutil.which('node')
        if not node or not CLI.is_file():
            return {'error': '飞猪官方 CLI 尚未准备好，请按 docs/fliggy.md 配置。'}
        command = [node, str(CLI), 'search-flight', '--origin', args.origin,
                   '--destination', args.destination, '--dep-date', args.dep_date.isoformat(), '--sort-type', '3']
        for flag, value in [('--back-date', args.back_date.isoformat() if args.back_date else None),
                            ('--journey-type', 1 if args.direct_only else None),
                            ('--max-price', args.max_price), ('--seat-class-name', args.seat_class_name)]:
            if value is not None:
                command += [flag, str(value)]
        # Do not inherit endpoint overrides, debug logging or unrelated service secrets.
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'SystemRoot') if k in os.environ}
        env.update(FLYAI_API_KEY=key, FLYAI_JSON='1')
        process = None
        try:
            process = await asyncio.create_subprocess_exec(*command, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=50)
            if process.returncode or key.encode() in stdout or len(stdout) > 2_000_000:
                raise ValueError('query failed')
            return normalize(json.loads(stdout))
        except asyncio.CancelledError:
            raise
        except Exception:
            return {'error': '飞猪查询失败，请检查凭据、网络或机票搜索权限后重试。尚未预订、支付或出票。'}
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()


def flight_reply(result):
    """Host-rendered evidence; never let a successful search imply ticketing."""
    if result.get('error'):
        return result['error']
    lines = ['飞猪本次查询结果（搜索报价，最终含税总价以结算页为准）：']
    for flight in result.get('flights', [])[:5]:
        segments = [s for j in flight['journeys'] for s in j['segments']]
        legs = '；'.join(f"{s.get('marketingTransportNo','')} {s.get('depStationName','')} {s.get('depDateTime','')} → {s.get('arrStationName','')} {s.get('arrDateTime','')} {s.get('seatClassName','')}" for s in segments)
        lines.append(f"{flight['index']}. {legs}，票价 ¥{flight['ticket_price_yuan']}\n预订链接：{flight['booking_url']}")
    if not result.get('flights'):
        lines.append('本次没有可展示的航班，请调整日期或条件。')
    lines.append('尚未订票或付款。请在飞猪核对乘机人、费用、行李和退改规则后确认付款。')
    return '\n\n'.join(lines)
