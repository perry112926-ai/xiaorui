"""Local family configuration. Secrets are write-only and stay in .env.

Only existing built-in integrations are configurable. This router does not
register MCP servers, change transaction switches, or execute arbitrary URLs.
The host application's local-origin boundary applies to every route.
"""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key
from fastapi import APIRouter, HTTPException, Request
from app import read_only
from app.fliggy import Fliggy
from app.fliggy_setup import runtime_status, prepare_runtime

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / '.env'
LOCK_PATH = ROOT / '.local-data/settings.lock'
router = APIRouter(prefix='/api/settings', tags=['settings'])
_lock = threading.RLock()
_test_lock = asyncio.Lock()
ARK_BASE = 'https://ark.cn-beijing.volces.com/api/v3'
PROVIDERS = {
    'ark': {'label': '豆包文本模型', 'fields': ['ARK_API_KEY', 'ARK_MODEL', 'ARK_BASE_URL'],
            'required': ['ARK_API_KEY', 'ARK_MODEL'], 'live_check': False},
    'speech': {'label': '豆包语音', 'fields': ['DOUBAO_SPEECH_API_KEY'],
               'required': ['DOUBAO_SPEECH_API_KEY'], 'live_check': False},
    'mcd': {'label': '麦当劳', 'fields': ['MCD_MCP_TOKEN'], 'required': ['MCD_MCP_TOKEN'], 'live_check': True},
    'luckin': {'label': '瑞幸', 'fields': ['LUCKIN_MCP_TOKEN'], 'required': ['LUCKIN_MCP_TOKEN'], 'live_check': True},
    'didi': {'label': '滴滴', 'fields': ['DIDI_MCP_KEY'], 'required': ['DIDI_MCP_KEY'], 'live_check': True},
    'fliggy': {'label': '飞猪 AI 机票', 'fields': ['FLYAI_API_KEY'], 'required': ['FLYAI_API_KEY'], 'live_check': True},
}
ALLOWED_FIELDS = frozenset(field for p in PROVIDERS.values() for field in p['fields'])
NONSECRET_FIELDS = frozenset({'ARK_MODEL', 'ARK_BASE_URL'})


def _read():
    return dotenv_values(ENV_PATH, interpolate=False) if ENV_PATH.exists() else {}


def _value(name, local):
    return str(os.environ.get(name, local.get(name) or (ARK_BASE if name == 'ARK_BASE_URL' else ''))).strip()


def _valid_base(value):
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and parsed.hostname == 'ark.cn-beijing.volces.com'
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path.rstrip('/') == '/api/v3')


def _base_allowed(value):
    try:
        return bool(value) and _valid_base(value)
    except ValueError:
        return False


def configuration():
    local = _read()
    fields = {}
    for name in sorted(ALLOWED_FIELDS):
        value = _value(name, local)
        field = {'configured': bool(value), 'masked': '••••••••' if value else '',
                 'source': 'environment' if name in os.environ else 'local',
                 'editable': name not in os.environ}
        if name in NONSECRET_FIELDS:
            # Never echo an existing endpoint with embedded credentials/query.
            if name == 'ARK_MODEL':
                field['value'] = value if re.fullmatch(r'[A-Za-z0-9_.:/-]{0,160}', value) else ''
            else:
                try:
                    field['value'] = value if _valid_base(value) else ''
                except ValueError:
                    field['value'] = ''
        fields[name] = field
    return {'fields': fields,
            'providers': {provider: {'label': spec['label'],
                 'configured': (all(bool(_value(name, local)) for name in spec['required'])
                                and (provider != 'ark' or _base_allowed(_value('ARK_BASE_URL', local)))),
                 **({'endpoint_allowed': _base_allowed(_value('ARK_BASE_URL', local))} if provider == 'ark' else {}),
                 **(runtime_status() if provider == 'fliggy' else {}),
                 'live_check_available': spec['live_check'], 'verification': 'not_tested'}
                for provider, spec in PROVIDERS.items()},
            'storage': 'local-backend-env', 'transaction_settings_editable': False,
            'read_only': read_only.READ_ONLY,
            'note': '已配置仅表示本机存在凭据，不代表远端权限或查询已验证。'}


@contextmanager
def _configuration_lock():
    # The app is single-process; flock also protects independent local writers
    # using this API when run under multiple workers on Linux/macOS.
    with _lock:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except ImportError:
                pass  # Windows retains the in-process lock; single worker only.
            yield
        finally:
            os.close(descriptor)


def save_values(values):
    if not isinstance(values, dict) or not values or len(values) > len(ALLOWED_FIELDS):
        raise HTTPException(422, '请提供需要更新的配置。')
    if set(values) - ALLOWED_FIELDS:
        raise HTTPException(422, '只允许修改已有服务的指定配置项。')
    clean = {}
    for name, value in values.items():
        if (not isinstance(value, str) or len(value) > 4096
                or any(ord(c) < 32 or ord(c) == 127 for c in value) or '${' in value):
            raise HTTPException(422, '配置格式不正确，请使用单行文本。')
        value = value.strip()
        if name in os.environ:
            raise HTTPException(409, '部分配置由启动环境管理，请修改环境变量并重启服务。')
        if name == 'ARK_BASE_URL':
            try:
                valid = bool(value) and _valid_base(value)
            except ValueError:
                valid = False
            if not valid:
                raise HTTPException(422, '文本服务地址仅支持官方 https://ark.cn-beijing.volces.com/api/v3。')
            value = ARK_BASE
        if name == 'ARK_MODEL' and value and not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}', value):
            raise HTTPException(422, '模型 ID 格式不正确。')
        clean[name] = value
    with _configuration_lock():
        if ENV_PATH.is_symlink():
            raise HTTPException(409, '配置文件为符号链接，请先由家人核对本机配置文件。')
        # Validate the effective destination before accepting a new text key or
        # model, even when this partial update omits the endpoint. The runtime
        # honors environment overrides, then the existing local configuration.
        if {'ARK_API_KEY', 'ARK_MODEL'} & clean.keys():
            prospective = {**_read(), **clean}
            if not _base_allowed(_value('ARK_BASE_URL', prospective)):
                raise HTTPException(422, '请先将文本服务地址改为官方 https://ark.cn-beijing.volces.com/api/v3，再保存文本凭据或模型。')
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.env.settings-', dir=ENV_PATH.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                file.write(ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else '')
                file.flush()
                os.fsync(file.fileno())
            for name, value in clean.items():
                set_key(str(temporary), name, value, quote_mode='always')
            # dotenv.set_key replaces its file, so reapply permissions before
            # the final atomic replacement. Never expose a world-readable key.
            temporary.chmod(0o600)
            with temporary.open('rb') as file:
                os.fsync(file.fileno())
            os.replace(temporary, ENV_PATH)
        finally:
            temporary.unlink(missing_ok=True)
    return configuration()


@router.get('')
async def get_settings():
    return configuration()


@router.post('')
async def update_settings(request: Request):
    if read_only.READ_ONLY:
        raise HTTPException(403, '只读预览不能修改服务配置。')
    # Parse manually so FastAPI/Pydantic validation errors never echo keys.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise HTTPException(413, '配置内容过长。')
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(422, '配置请求格式不正确。') from None
    if not isinstance(payload, dict) or set(payload) != {'values'}:
        raise HTTPException(422, '配置请求只接受 values 字段。')
    try:
        return save_values(payload['values'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, '保存失败，请检查本机配置文件权限；未显示凭据内容。') from None


@router.post('/test/{provider}')
async def test_settings(provider: str):
    if read_only.READ_ONLY:
        raise HTTPException(403, '只读预览不能运行配置检查。')
    if provider not in PROVIDERS:
        raise HTTPException(404, '只支持已接入的内置服务。')
    state = configuration()['providers'][provider]
    if not state['configured']:
        return {'provider': provider, 'configured': False, 'status': 'not_configured',
                'detail': '请先保存服务凭据，再检查连接。'}
    if not state['live_check_available']:
        return {'provider': provider, 'configured': True, 'status': 'not_live_tested',
                'detail': '本机配置已填写；文本和真人语音需在实际对话中验证，不代表已连通。'}
    if _test_lock.locked():
        raise HTTPException(409, '已有连接检查正在进行，请稍等。')
    async with _test_lock:
        if provider == 'fliggy':
            ready = runtime_status()
            if not ready['runtime_ready']:
                return {'provider':provider, 'configured':True, 'status':'needs_setup',
                        'detail':'请先准备飞猪组件；需要 Node.js 18 或以上版本。', **ready}
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo
            departure = (datetime.now(ZoneInfo('Asia/Shanghai')) + timedelta(days=7)).date().isoformat()
            try:
                result = await asyncio.wait_for(Fliggy(ENV_PATH).dispatch({
                    'origin':'北京', 'destination':'上海', 'dep_date':departure, 'direct_only':True}), timeout=35)
                status = 'failed' if result.get('error') else 'passed' if result.get('flights') else 'empty'
            except TimeoutError:
                status = 'timeout'
            except Exception:
                status = 'failed'
            return {'provider':provider, 'configured':True, 'status':status, 'query':status,
                    'transactions_attempted':0, 'detail':'只查询七天后北京至上海的公开航班，不读取乘机人、不创建订单或付款。'}
        from experiments.read_only_service_check import matrix
        result = (await matrix([provider], timeout=35))['checks'][0]
        return {**result, 'status': result['query'],
                'detail': '仅测试公开地标的只读查询，不下单、不查询私人地址或订单。'}


@router.post('/prepare/fliggy')
async def prepare_fliggy():
    if read_only.READ_ONLY:
        raise HTTPException(403, '只读预览不能准备服务组件。')
    if _test_lock.locked():
        raise HTTPException(409, '已有服务准备或检查正在进行，请稍等。')
    async with _test_lock:
        return await prepare_runtime()
