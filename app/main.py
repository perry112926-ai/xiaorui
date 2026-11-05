"""Local chat, voice and confirmation API. Remote writes require exact approval."""
import os
import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from app import read_only
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from app.mcd import McdService, McdRejectedError, mcd_token
from app.plans import PlanStore, PlanError
from app.recommendations import recommend
from app.voice import router as voice_router
from app.settings import router as settings_router
from app.agent import AgentService, AgentError
from app.foundation_scheduler import FoundationScheduler
from app.actions import ActionError
from app.contact import ContactService
from app.attachments import ImageStore
from app.profile_card import ProfileConflict
from typing import Literal
from app.runtime import RuntimeSlot, ServiceProxy, current_runtime, default_runtime, build_services

ROOT = Path(__file__).resolve().parents[1]
settings = dotenv_values(ROOT / '.env')
ORDER_ENABLED = str(os.environ.get('MCD_ORDER_ENABLED', settings.get('MCD_ORDER_ENABLED') or 'false')).lower() == 'true'


@asynccontextmanager
async def lifespan(application):
    token=current_runtime.set(application.state.runtime)
    dependencies=application.state.runtime.get()
    try:
        dependencies.plans.recover_interrupted()
        dependencies.agent.store.recover_interrupted()
        dependencies.agent.actions.recover_interrupted()
        dependencies.contact.recover()
        await dependencies.scheduler.start()
        try:
            yield
        finally:
            await dependencies.contact.close()
            await dependencies.scheduler.stop()
    finally:
        current_runtime.reset(token)


router=APIRouter()
service=ServiceProxy('service')
plans=ServiceProxy('plans')
agent=ServiceProxy('agent')
images=ServiceProxy('images')
contact=ServiceProxy('contact')
scheduler=ServiceProxy('scheduler')


async def local_boundary(request: Request, call_next):
    host = urlsplit('http://' + request.headers.get('host', '')).hostname
    if host not in {'localhost', '127.0.0.1', '::1'}:
        return JSONResponse({'detail': '仅允许本机访问。'}, status_code=403)
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
        return JSONResponse({'detail': '不允许跨来源操作。'}, status_code=403)
    if request.method in {'POST', 'PUT', 'PATCH'} and not request.headers.get('content-type', '').startswith('application/json'):
        return JSONResponse({'detail': '请使用 JSON 请求。'}, status_code=415)
    if (read_only.READ_ONLY and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
            and not read_only.query_post(request.url.path)):
        return JSONResponse({'detail': read_only.MESSAGE}, status_code=403)
    session = request.cookies.get('pa_session')
    fresh = not session or len(session) < 32 or len(session) > 128
    request.state.owner = secrets.token_urlsafe(32) if fresh else session
    token=current_runtime.set(request.app.state.runtime)
    try:
        response = await call_next(request)
    finally:
        current_runtime.reset(token)
    if fresh:
        response.set_cookie('pa_session', request.state.owner, httponly=True, samesite='strict', max_age=30*86400)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


async def plan_error(request, error):
    return JSONResponse({'detail': error.message}, status_code=error.status)


async def agent_error(request, error):
    return JSONResponse({'detail': error.message}, status_code=error.status)


async def action_error(request, error):
    return JSONResponse({'detail':error.message},status_code=error.status)


@router.get('/api/actions')
async def action_list(request: Request):
    return {'actions':[agent.actions.public(p) for p in agent.actions.list(request.state.owner)]}


@router.get('/api/actions/{id}')
async def action_get(id: str, request: Request):
    return {'plan':agent.actions.public(agent.actions.get(request.state.owner,id))}


@router.post('/api/actions/{id}/cancel-plan')
async def action_cancel_local(id: str, request: Request):
    return {'plan':agent.actions.cancel_local(request.state.owner,id)}


@router.post('/api/actions/{id}/refresh')
async def action_refresh(id: str, request: Request):
    return {'plan':await agent.actions.refresh(request.state.owner,id)}


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ChatRequest(Body):
    text: str = Field(min_length=1, max_length=2000, strict=True)


from app.location import BrowserLocation


@router.post('/api/location')
async def set_location(body: BrowserLocation, request: Request):
    try:
        agent.locations.put(request.state.owner,body)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    agent.actions.invalidate_pending(request.state.owner)
    return {'ok':True,'expires_in':120,'accuracy':body.accuracy}


@router.delete('/api/location')
async def clear_location(request: Request):
    agent.locations.clear(request.state.owner)
    agent.actions.invalidate_pending(request.state.owner)
    return {'ok':True}


class ContactMessage(ChatRequest):
    client_id: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    image_ids: list[str] = Field(default_factory=list,max_length=4)
    call_id: str | None = Field(default=None, max_length=64, strict=True)
    reply_mode: Literal['text','speech'] = 'text'


class ImageUpload(Body):
    data_url: str = Field(min_length=20,max_length=10_700_000,strict=True)


@router.post('/api/contact/images',status_code=201)
async def upload_image(body: ImageUpload,request: Request):
    return images.save(request.state.owner,body.data_url)


@router.get('/api/contact/images/{image_id}')
async def read_image(image_id: str,request: Request):
    return FileResponse(images.resolve(request.state.owner,image_id),media_type='image/jpeg',
                        headers={'Content-Security-Policy':"default-src 'none'; sandbox"})


@router.post('/api/contact/messages', status_code=202)
async def contact_message(body: ContactMessage, request: Request):
    return contact.enqueue(request.state.owner, body.text, body.client_id, body.image_ids, body.call_id, body.reply_mode)


@router.post('/api/contact/calls')
async def start_contact_call(request: Request):
    return contact.start_call(request.state.owner)


@router.post('/api/contact/calls/{call_id}/end')
async def end_contact_call(call_id: str, request: Request):
    return contact.end_call(request.state.owner, call_id)


@router.get('/api/contact/state')
async def contact_state(request: Request):
    return contact.state(request.state.owner)


@router.get('/api/contact/events')
async def contact_events(request: Request, after: int = 0):
    owner = request.state.owner
    try:
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
    except ValueError:
        raise HTTPException(422, '消息游标无效。') from None
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            events = contact.events(owner, cursor)
            for event in events:
                cursor = event['cursor']
                yield f'id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
            if not events:
                yield ': heartbeat\n\n'
                await asyncio.sleep(.25)
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})


@router.post('/api/chat')
async def chat(body: ChatRequest, request: Request):
    if not body.text.strip():
        raise HTTPException(422, '请先说一句话或输入消息。')
    return await agent.chat(request.state.owner, body.text.strip())


@router.post('/api/chat/reset')
async def reset_chat(body: Body, request: Request):
    raise HTTPException(410, '小瑞保留同一个持续对话，不再提供新对话入口。重要资料请在“我的资料卡”中管理。')


@router.get('/api/chat/history')
async def chat_history(request: Request):
    return agent.history(request.state.owner)


@router.get('/api/foundation')
async def foundation_status():
    return {**agent.foundation_status(), 'scheduler': scheduler.status()}


@router.get('/api/profile')
async def personal_profile():
    return agent.store.profile()


class ProfileCardUpdate(Body):
    version: int = Field(ge=0, strict=True)
    fields: dict[str, str] = Field(min_length=1, max_length=9)
    confirmation_text: Literal['确认保存资料']


@router.get('/api/profile/card')
async def profile_card():
    return agent.store.profile_card()


@router.put('/api/profile/card')
async def update_profile_card(body: ProfileCardUpdate):
    # Synchronous mutation after these checks cannot interleave with a chat tool.
    if any(session.lock.locked() for session in agent.sessions.values()):
        raise HTTPException(409, '小瑞正在处理消息，请等本轮回复结束后再保存资料。')
    try:
        card = agent.store.save_profile_card(body.version, body.fields)
        agent.sessions.clear()
        agent.actions.invalidate_all_pending()
        return card
    except ProfileConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/api/tasks')
async def personal_tasks(request: Request):
    return agent.tasks(request.state.owner)


class StoreSearch(Body):
    city: str = Field(min_length=1, max_length=80)
    keyword: str = Field(min_length=1, max_length=120)


class StoreChoice(Body):
    store_code: str = Field(min_length=1, max_length=80)


class ProductChoice(StoreChoice):
    product_code: str = Field(min_length=1, max_length=80)


class RecommendationRequest(StoreChoice):
    budget_cents: int = Field(default=3500, ge=100, le=100000, strict=True)
    limit: int = Field(default=3, ge=1, le=3, strict=True)


class Round(Body):
    round_id: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1, le=5, strict=True)


class PlanRequest(ProductChoice):
    quantity: int = Field(default=1, ge=1, le=5, strict=True)
    rounds: list[Round] = Field(default_factory=list, max_length=30)


class Confirmation(Body):
    version: int = Field(ge=1, strict=True)
    confirmation_token: str = Field(min_length=1, max_length=200)
    confirmation_text: str


@router.post('/api/actions/{id}/prepare-cancel')
async def prepare_cancel(id: str, body: Body, request: Request):
    owner=request.state.owner
    session=agent._session(owner)
    if session.lock.locked():
        raise HTTPException(409,'小瑞正在处理，请稍后查询取消条件。')
    async with session.lock:
        original=agent.actions.get(owner,id)
        if original['provider'] not in {'didi','mcd'} or original['action']!='create':
            raise HTTPException(409,'请选择本人的真实订单记录。')
        events=[]
        provider=original['provider']
        parameters={'action_id':id} if provider=='didi' else {'plan_id':id}
        result=await agent.scenarios[provider].dispatch(session,owner,provider+'_prepare_cancel',parameters,events)
        if result.get('error'):
            raise HTTPException(409,result['error'])
        return {'plan':result['plan'],'speech_text':agent.proposal_text(result['plan'])}


@router.post('/api/actions/{id}/confirm')
async def action_confirm(id: str, body: Confirmation, request: Request):
    session = agent._session(request.state.owner)
    if session.lock.locked():
        raise HTTPException(409,'小瑞正在处理，请勿重复确认。')
    async with session.lock:
        plan = await agent.actions.confirm(request.state.owner,id,body.version,
            body.confirmation_token,body.confirmation_text)
    return {'plan':plan,'speech_text':agent.action_text(plan)}


async def read_call(fn, *args):
    try:
        return await fn(*args)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError:
        raise HTTPException(502, '麦当劳查询暂时失败，请稍后重新查询。') from None
    except Exception:
        raise HTTPException(502, '暂时无法连接麦当劳，请检查网络和配置。') from None


@router.get('/api/health')
async def health():
    return {'ok': True, 'order_execution_enabled': ORDER_ENABLED and not read_only.READ_ONLY,
            'read_only': read_only.READ_ONLY,
            'mcd_configured': bool(mcd_token()),
            'agent_configured': agent.configured}


@router.post('/api/mcd/stores')
async def stores(body: StoreSearch):
    return {'stores': await read_call(service.search_stores, body.city, body.keyword)}


@router.post('/api/mcd/menu')
async def menu(body: StoreChoice):
    return {'products': await read_call(service.menu, body.store_code)}


@router.post('/api/mcd/detail')
async def detail(body: ProductChoice):
    return {'detail': await read_call(service.detail, body.store_code, body.product_code)}


@router.post('/api/mcd/recommendations')
async def recommendations(body: RecommendationRequest):
    return await read_call(recommend, service, body.store_code, body.budget_cents, body.limit)


@router.post('/api/plans')
async def new_plan(body: PlanRequest, request: Request):
    prepared = await read_call(service.prepare_plan, body.model_dump())
    return {'plan': plans.create(request.state.owner, prepared)}


@router.get('/api/plans/{plan_id}')
async def get_plan(plan_id: str, request: Request):
    return {'plan': plans.get(plan_id, request.state.owner)}


@router.post('/api/plans/{plan_id}/cancel')
async def cancel(plan_id: str, request: Request):
    return {'plan': plans.cancel(plan_id, request.state.owner)}


@router.post('/api/plans/{plan_id}/confirm')
async def confirm(plan_id: str, body: Confirmation, request: Request):
    if body.confirmation_text != '确认下单':
        raise HTTPException(400, '需要明确确认下单。')
    if not ORDER_ENABLED:
        raise HTTPException(409, '当前仅核价和查看方案，真实下单尚未开启。')
    return {'plan':await plans.confirm(service,request.state.owner,plan_id,body.version,
        body.confirmation_token,body.confirmation_text,enabled=ORDER_ENABLED)}


DIST = ROOT / 'frontend/dist'



@router.get('/')
async def home():
    if not (DIST / 'index.html').exists():
        raise HTTPException(503, '前端尚未构建，请先运行启动脚本。')
    return FileResponse(DIST / 'index.html')


def create_app(*, services=None, services_factory=None):
    application=FastAPI(title='小瑞 · 本地生活助手',docs_url=None,redoc_url=None,lifespan=lifespan)
    application.state.runtime=RuntimeSlot(services,services_factory or build_services)
    application.middleware('http')(local_boundary)
    for kind,handler in ((PlanError,plan_error),(AgentError,agent_error),(ActionError,action_error)):
        application.add_exception_handler(kind,handler)
    application.include_router(voice_router)
    application.include_router(settings_router)
    application.include_router(router)
    application.mount('/assets',StaticFiles(directory=DIST/'assets',check_dir=False),name='assets')
    application.mount('/mascot',StaticFiles(directory=DIST/'mascot',check_dir=False),name='mascot')
    return application


app=create_app()
# Direct imports outside a request resolve this app's lazy slot.
import app.runtime as _runtime_module
_runtime_module.default_runtime=app.state.runtime
