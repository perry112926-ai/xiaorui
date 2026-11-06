"""Persistent Personal Agent host; nanobot owns the model/tool execution loop."""
from app.money import format_cents
from app.summaries import normalize_summary, LABELS
import asyncio
from sqlite3 import Error as SQLiteError
import copy
import hashlib
from decimal import Decimal, InvalidOperation
import json
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from app import read_only
from app.amap import Amap, SCHEMAS as AMAP_SCHEMAS, configured as amap_configured, accessibility_boundary, weather_precision_boundary
from app.progress import tool_activity
from pathlib import Path

from dotenv import dotenv_values
from pydantic import ValidationError

from app.foundation_store import FoundationStore
from app.profile_card import is_critical
from app.profile_permissions import profile_write_allowed
from app.nanobot_runtime import build_runtime, data_context, SYSTEM
from app.plans import PlanError
from app.skills import SkillRegistry, SCHEMAS, TOOLS, catalog
from app.service_skills import LifeSkills, SERVICE_SCHEMAS
from app.life_services import connection_status
from app.actions import ActionManager, ActionError
from app.didi_scenario import DidiScenario
from app.mcd_scenario import McdScenario
from app.mcd_recommendations import resolve_selection
from app.location import LocationStore
from app.luckin_scenario import LuckinScenario
from app.contact_events import notify, contact_media, contact_call, contact_reply_mode
from app.text_delivery import quick_answer, lightweight_chat
from app.latency import tool_scope, terminal_reply, candidate_context, current_weather_city
from app.speech import SpeechComposer, context as speech_context, fallback as speech_fallback


from app.model_views import project_result, project_services, project_plans
from app.factual_replies import business_turn, business_reply
from app.task_switching import reminder_request, clear_drafts, cancel_mcd_order, release_completed_drafts, luckin_delivery_boundary
from app.task_switching import turn_domain

# Compatibility name for callers that previously used the blacklist sanitizer.
model_safe = project_result


def choice_cards(result):
    """Render only returned candidates, with explicit selection text, never IDs."""
    if not isinstance(result,dict):
        return []
    groups = [('stores','门店'),('products','商品'),('vehicles','车型'),('addresses','配送地址'),('take_ways','取餐方式')]
    for key,label in groups:
        if not isinstance(result.get(key),list):
            continue
        cards=[]
        for index,item in enumerate(result[key][:5],1):
            if not isinstance(item,dict):
                continue
            name=item.get('name') or item.get('productName') or item.get('product_name') or item.get('productName') or item.get('title') or item.get('address')
            if key=='vehicles':
                name=item.get('productName')
            if not name:
                continue
            number=item.get('index',index)
            detail=item.get('address','') if key=='stores' else item.get('subtitle','') if key=='take_ways' else ''
            if key=='stores' and item.get('open') is False:
                detail='暂不营业' + (f' · {detail}' if detail else '')
            if key=='vehicles' and item.get('priceText'):
                detail=f'本次预估 {item["priceText"]} 元，实际费用以平台为准'
            if key=='products' and item.get('menu_price_yuan'):
                detail=f'菜单参考价 {item["menu_price_yuan"]} 元，尚需核价'
            product_fields = {}
            if key=='products' and ('menu_price_yuan' in item or 'quoted_price_yuan' in item):
                product_fields = {'kind':'product', 'price_kind':'menu'}
                try:
                    price = Decimal(str(item.get('quoted_price_yuan',item.get('menu_price_yuan'))))
                    if price.is_finite() and 0 <= price <= 100000 and price == price.quantize(Decimal('0.01')):
                        product_fields['price_yuan'] = f'{price:.2f}'
                except (InvalidOperation, ValueError, TypeError):
                    pass
            if item.get('recommendation_id'):
                product_fields.update(recommendation_id=item['recommendation_id'],price_kind='quote',contents=item.get('choices',[]),fee_breakdown=item.get('fee_breakdown',''))
                if 'price_yuan' in product_fields:
                    detail=f'本次核价 {product_fields["price_yuan"]} 元；搭配：'+ '、'.join(item.get('choices',[]))
            cards.append({**product_fields,**({'available':item.get('open') is not False} if key=='stores' else {}),'label':str(name),'detail':detail,'image':item.get('image'),
                'prompt':f'选择第{number}份推荐{"餐品" if item.get("meal_type")=="single" else "套餐"}：{name}。' if item.get('recommendation_id') else f'选择第{number}个{label}：{name}。请继续给我核对，先不要执行交易。'})
        return cards
    return []

ROOT = Path(__file__).resolve().parents[1]


def external_request_block(provider):
    path=ROOT/'.local-data/payment-probe'/(provider+'.json')
    if not path.exists():return False
    try:
        record = json.loads(path.read_text())
        status = record.get('status')
        if provider == 'luckin' and status == 'unknown':
            submitted_at = record.get('submitted_at')
            return type(submitted_at) not in {int, float} or time.time() - submitted_at < ActionManager.LUCKIN_DUPLICATE_WINDOW_SECONDS
        return status in {'unknown', 'submitting'}
    except (ValueError,OSError):return True



class AgentError(Exception):
    def __init__(self, message, status=502):
        self.message, self.status = message, status


@dataclass
class Session:
    conversation_id: str = ''
    display: list = field(default_factory=list)
    stores: dict = field(default_factory=dict)
    meals: list = field(default_factory=list)
    plan_id: str | None = None
    forget_epoch: int = 0
    services: dict = field(default_factory=dict)
    speech_turn: dict | None = None
    defer_speech: bool = False
    tool_facts: list = field(default_factory=list)
    model_used: bool = False
    current_input: str = ''
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)

    def snapshot(self):
        return {name: copy.deepcopy(getattr(self, name)) for name in (
            'conversation_id', 'display', 'stores', 'meals', 'plan_id', 'forget_epoch', 'services')}


class AgentService:
    def __init__(self, service, plans, store=None, data_dir=None):
        self.service, self.plans = service, plans
        self.data_dir = Path(data_dir or ROOT / '.local-data/personal-agent')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)
        self.store = store or FoundationStore(self.data_dir / 'foundation.sqlite3', recover_running=False)
        from app.companion_memory import CompanionMemory
        self.memory = CompanionMemory(self.data_dir / 'companion.sqlite3')
        self.skills = SkillRegistry(service, plans)
        self.speech = SpeechComposer()
        self.life_skills = LifeSkills()
        self.actions = ActionManager(self.data_dir / 'actions.sqlite3',
                                     external_blocks=external_request_block if data_dir is None else None)
        self.plans.bind_actions(self.actions)
        self.locations = LocationStore()
        self.amap = Amap(location_provider=self.locations.get)
        self.scenarios = {
            'didi':DidiScenario(self.actions, self.life_skills.didi, self.locations.get),
            'mcd':McdScenario(self.actions, service, self.locations.get, self.life_skills.didi),
            'luckin':LuckinScenario(self.actions, self.life_skills.luckin),
        }
        self.scenario_tools = {}
        for provider, scenario in self.scenarios.items():
            self.actions.register(provider, scenario)
            self.scenario_tools.update({name:scenario for name in scenario.schemas})
        self.sessions = OrderedDict()
        self._speech_jobs = {}
        self._speech_slots = asyncio.Semaphore(2)

    def _config(self):
        env = dotenv_values(ROOT / '.env')
        def get(k, default=''):
            return str(os.environ.get(k, env.get(k) or default)).strip()
        return {'key': get('ARK_API_KEY'), 'model': get('ARK_MODEL'),
                'context_window':int(get('ARK_CONTEXT_WINDOW_TOKENS','64000')),
                'trust_env':get('ARK_TRUST_ENV','false').lower() == 'true',
                'base': get('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3').rstrip('/')}

    @property
    def configured(self):
        cfg = self._config()
        return bool(cfg['key'] and cfg['model'])

    def _session(self, owner):
        state = self.store.session(owner)
        session = self.sessions.get(owner)
        if session is None or session.conversation_id != state['conversation_id']:
            if session and session.lock.locked():
                raise AgentError('个人资料已变更，请等待当前回复结束后重新尝试。', 409)
            session = Session(**state)
            self.sessions[owner] = session
        self.sessions.move_to_end(owner)
        for key in list(self.sessions):
            if len(self.sessions) <= 64:
                break
            if key != owner and not self.sessions[key].lock.locked():
                del self.sessions[key]
        session.touched = time.monotonic()
        # Restore the adapter's lookup cache from server-owned persisted candidates.
        self.service.stores.update(session.stores)
        return session

    def _plan(self, session, owner):
        return self.plans.get(session.plan_id, owner) if session.plan_id else None

    def _guard(self, session, owner):
        return self.skills._guard(session, owner)

    async def reset(self, owner):
        session = self._session(owner)
        if session.lock.locked():
            raise AgentError('小瑞正在处理当前任务，请稍等。', 409)
        async with session.lock:
            plan = self._guard(session, owner)
            if plan and plan['status'] in {'awaiting_confirmation', 'needs_review', 'expired'}:
                self.plans.cancel(plan['id'], owner)
            self.store.new_session(owner)
            self.actions.invalidate_pending(owner, status='cancelled')
            self.sessions.pop(owner, None)
        return {'ok': True}

    def history(self, owner):
        session = self._session(owner)
        messages = copy.deepcopy(session.display)
        for message in messages:
            refreshed = []
            for event in message.get('events', []):
                if event.get('type') == 'plan':
                    try:
                        event['plan'] = self.plans.get(event['plan']['id'], owner)
                    except PlanError:
                        continue
                if event.get('type') == 'action_plan':
                    try:
                        event['plan'] = self.actions.public(self.actions.get(owner,event['plan']['id']))
                    except ActionError:
                        continue
                refreshed.append(event)
            if 'events' in message:
                message['events'] = refreshed
        return {'messages': messages, 'conversation_id': session.conversation_id}

    def foundation_status(self):
        return {'runtime': 'nanobot', 'runtime_version': '0.4.0',
                'amap':{'configured':amap_configured(),'query_only':True},
                'profile_id': self.store.PROFILE_ID, 'session_storage': 'persistent',
                'skills': [{**entry,'tools':[n for n in entry['tools'] if not read_only.READ_ONLY or n in read_only.QUERY_TOOLS]} for entry in catalog()],
                'tools': sorted(set(SCHEMAS)&read_only.QUERY_TOOLS if read_only.READ_ONLY else SCHEMAS),
                'business_expansion': 'beijing-luckin-mcd-didi',
                'services': {p:{**s,'order_execution_enabled':self.actions.enabled(p),
                                  'unresolved_request_block':bool(self.actions.blocked(p))}
                             for p,s in connection_status().items()}, 'autonomous_orders': False}

    def tasks(self, owner):
        epoch = self.store.profile()['forget_epoch']
        tasks = self.store.list_tasks(owner)
        barrier = self.memory.recall_barrier(owner)
        for task in tasks:
            if task.get('forget_epoch') != epoch or task.get('created_at',0) <= barrier:
                task['input'] = '[旧资料删除前的任务，内容不再展示]'
                task['result'] = None
                task['error'] = None
        return {'tasks': tasks}

    async def _tool(self, session, owner, name, arguments, events):
        if name == 'fliggy_search_flights':
            result = project_result(await self.life_skills.dispatch(session, name, arguments),name)
            events.append({'type':'flight_result','data':result})
            return result
        return project_result(await self._dispatch_tool(session, owner, name, arguments, events), name)

    async def _dispatch_tool(self, session, owner, name, arguments, events):
        if read_only.READ_ONLY and name not in read_only.QUERY_TOOLS:
            return {'error': read_only.MESSAGE}
        if name in AMAP_SCHEMAS:
            result=await self.amap.dispatch(session,name,arguments,owner=owner)
            if result.get('needs_location'):events.append({'type':'location_request'})
            return result
        if name in self.scenario_tools:
            if name=='luckin_search_stores' and 'origin_index' in arguments:
                origins=session.services.get('amap',{}).get('origin',[])
                index=arguments['origin_index']
                if type(index) is not int or not 1<=index<=len(origins):
                    return {'error':'请先查询并核对本轮北京地标。'}
                origin=origins[index-1]
                if origin.get('expires_at',float('inf'))<time.time():
                    return {'error':'定位已过期，请重新定位或说出附近地标。'}
                longitude,latitude=map(float,origin['location'].split(','))
                arguments={**arguments,'longitude':longitude,'latitude':latitude}
            result = await self.scenario_tools[name].dispatch(session,owner,name,arguments,events)
            if name.startswith('mcd_') and name in read_only.QUERY_TOOLS:
                events.append({'type': 'query_result', 'provider': 'mcd', 'tool': name,
                               'success': isinstance(result, dict) and 'error' not in result,
                               'source': 'https://open.mcd.cn/mcp', 'data': project_result(result,name)})
            cards=choice_cards(result)
            if name.startswith(('luckin_','didi_')):
                for card in cards:
                    card['prompt']=('瑞幸' if name.startswith('luckin_') else '滴滴')+'：'+card['prompt']
            if cards or result.get('preflighted'):
                events.append({'type':'service_choices','choices':cards})
            return project_result(result,name)
        if name in SERVICE_SCHEMAS:
            return await self.life_skills.dispatch(session, name, arguments)
        if name == 'task_records':
            try:
                args = SCHEMAS[name][0].model_validate(arguments)
                tasks = self.tasks(owner)['tasks']
                if args.action == 'list':
                    return {'tasks': tasks}
                task = self.store.get_task(owner, args.task_id)
                if (task.get('forget_epoch') != self.store.profile()['forget_epoch']
                        or task.get('created_at',0) <= self.memory.recall_barrier(owner)):
                    task.update(input='[旧资料删除前的任务，内容不再展示]', result=None, error=None)
                return {'task': task}
            except (ValidationError, ValueError):
                return {'error': '任务参数无效，或找不到属于当前会话的任务。'}
        if name != 'personal_profile':
            return await self.skills.dispatch(session, owner, name, arguments, events)
        try:
            args = SCHEMAS[name][0].model_validate(arguments)
            if args.action == 'list':
                return self.store.model_profile()
            if is_critical(args.key):
                return {'error': '家庭住址、本人和联系人电话等重要资料，请在右上角“我的资料卡”中填写、核对并确认保存。聊天不能自动修改或删除这些资料。'}
            if not session.lock.locked() or not profile_write_allowed(session.current_input,args.action):
                return {'error':'普通喜好会自动整理，无需重复保存。本次没有改动已确认资料。'}
            if args.action == 'set':
                self.store.set_fact(args.key, args.value)
                profile = self.store.model_profile()
                return {'saved': True, 'key': args.key, 'profile': profile}
            # Invalidating the conversation generation prevents old SDK history recall.
            from app.companion_memory import forget_target
            old_epoch = session.forget_epoch
            old_value = self.store.list_facts().get(args.key)
            self.memory.forget(owner, forget_target(session.current_input) or args.key)
            if old_value:
                # A semantic field name (e.g. nickname) may not occur in the
                # original statement. Remove the known old value as well.
                self.memory.forget(owner, str(old_value), literal=True)
            self.store.delete_fact(args.key)
            profile = self.store.model_profile()
            self.memory.advance_epoch(owner, old_epoch, profile['forget_epoch'])
            current = self.store.session(owner)
            session.conversation_id = current['conversation_id']
            session.forget_epoch = current['forget_epoch']
            session.display.clear()
            session.stores.clear()
            session.meals.clear()
            session.services.clear()
            self.actions.invalidate_pending(owner, status='cancelled')
            # Keep the plan pointer while this turn finishes so writes stay guarded.
            current['plan_id'] = session.plan_id
            return {'forgotten': True, 'key': args.key, 'profile': profile,
                    'history_policy': '旧会话不再用于回答；历史审计文件未物理擦除。'}
        except (ValidationError, ValueError):
            return {'error': '资料操作参数无效，请明确要保存或忘记的内容。'}

    async def _run(self, owner, session, text, events, trace):
        if contact_reply_mode.get()=='text' and not contact_media.get():
            brief=quick_answer(text)
            if brief:
                trace.append({'type':'host.quick_answer'})
                return brief
        if (not session.display and not self.locations.get(owner)
                and re.fullmatch(r'(?:我)?这(?:里|边|儿)(?:现在|今天|明天|这会儿)?(?:会不会|会|在|有没有)?(?:下雨|下不下雨|下雪|天气|冷不冷|热不热)(?:怎么样|如何)?[吗呢啊呀吧？?。！!]*',text.strip())):
            trace.append({'type':'host.weather_location_missing'})
            return '您现在在哪个城市或附近什么地标？我确认位置后再查天气。'
        boundary=accessibility_boundary(text) or weather_precision_boundary(text)
        if boundary:
            trace.append({'type':'host.amap_capability_boundary'})
            return boundary
        domain = turn_domain(text, session.display)
        focused_services = {key:value for key,value in session.services.items() if not domain or key == domain}
        grounded_business = domain != 'amap' and business_turn(text, focused_services)
        weather_reports=[]
        terminal_replies=[]
        flight_results=[]
        async def dispatch(name, arguments):
            notify(tool_activity(name))
            started = time.monotonic()
            try:
                result = await self._tool(session, owner, name, arguments, events)
            finally:
                trace.append({'type': 'timing', 'stage': 'tool',
                              'name': name if name in SCHEMAS else 'unknown',
                              'elapsed_ms': round((time.monotonic() - started) * 1000)})
            terminal_replies.append(terminal_reply(name, result, text))
            if name == 'fliggy_search_flights':
                flight_results.append(result)
            if name.startswith(('mcd_','didi_','luckin_')) or (
                    domain == 'luckin' and name in {'amap_search_places','amap_current_location'}):
                session.tool_facts.append((name, result))
            self.store.save_session(owner, session.snapshot())
            if isinstance(result, dict) and 'error' in result:
                trace.append({'type': 'tool.error', 'name': name})
            if name=='amap_weather' and isinstance(result,dict) and 'error' not in result:
                for row in result.get('weather',[])+result.get('forecasts',[]):
                    if isinstance(row,dict) and isinstance(row.get('reporttime'),str):
                        weather_reports.append(row['reporttime'])
            notify({'type': 'progress', 'stage': 'answer', 'text': '正在整理这一步的结果，您可以继续补充'})
            return result

        city = current_weather_city(text) if not contact_media.get() else None
        if city:
            started = time.monotonic()
            data = await dispatch('amap_weather', {'city': city, 'forecast': False})
            answer = terminal_reply('amap_weather', data, text)
            if answer:
                trace.append({'type':'host.direct_weather'})
                trace.append({'type':'timing','stage':'first_text','elapsed_ms':round((time.monotonic()-started)*1000)})
                notify({'type':'delta','text':answer})
                return answer

        async def context(request):
            return [data_context('conversation_channel', {'mode':'phone' if contact_call.get() else 'chat',
                    'guidance':'正在实时电话通话。像真人打电话一样简短承接用户的话，默认一两句短口语。缺资料时只问当前最必要的一项，不先罗列后续还要提供的多项资料。对方说没听清、不会操作或让你一句一句说时，减少信息量，一步一步引导，不声称已经调整硬件音量或语速。主动问一个推进当前事情所必需的问题，不重复已知条件。需要选择时发真实卡片，并说我给您发了卡片，选好告诉我。不要假设用户正在看屏幕；可语音解释选项。通话不改变真实交易确认规则。' if contact_call.get() else '普通消息聊天。自然承接上下文，必要时主动问一个问题，不机械追加问句。'}),
                    data_context('capabilities', {'tools':sorted(settings['tool_names']),
                        'current_task_domain':domain,
                        'task_guidance':'只处理本轮用户的需求及紧接着的澄清。历史订单和其他任务只能在用户明确要求时提及或继续。短回复承接最近的相关问题。当前查询要使用本轮工具，不能引用旧查询冒充新结果。',
                        'read_only':read_only.READ_ONLY,'execution_enabled':{p:self.actions.enabled(p) and not read_only.READ_ONLY for p in ('mcd','didi','luckin')},
                        'dining_provider':'mcd','payment_tool':False,'scheduled_notifications':False}),
                    data_context('capability_policy', {'read_only': read_only.READ_ONLY, 'message': read_only.MESSAGE if read_only.READ_ONLY else '依实际工具能力执行'}),
                    data_context('recent_displayed_dialogue', [
                        {'role': message['role'], 'text': re.sub(
                            r'https?://[^\s]+|\d{6,}', '[已隐藏]', message['text'][:600])}
                        for message in session.display[-8:]
                        if message.get('role') in {'user', 'assistant'} and isinstance(message.get('text'), str)
                    ]),
                    data_context('canonical_profile', self.store.model_profile()),
                    data_context('companion_memory', self.memory.recall(owner, session.forget_epoch, text)),
                    data_context('service_candidates', project_services(candidate_context(
                        {k:v for k,v in session.services.items() if not domain or k in {domain,'amap'}}))),
                    data_context('recent_actions', project_plans([self.actions.public(p) for p in self.actions.list(owner)
                        if not domain or p['provider']==domain][:8])),
                    data_context('current_candidates', {
                        'stores': list(session.stores.values()),
                        'meals': [{'index': i+1, 'name': m['name'], 'amount_cents': m['amount_cents']}
                                  for i, m in enumerate(session.meals)],
                        'plan': ({k: v for k, v in (self._plan(session, owner) or {}).items()
                                  if k in {'summary', 'amount_cents', 'status'}})})]

        owner_key = hashlib.sha256(owner.encode()).hexdigest()[:32]
        key = f'xiaorui:{owner_key}:{session.conversation_id}:e{session.forget_epoch}'
        settings = {**self._config(), 'tool_names': tool_scope(text, session.services, SCHEMAS),
                    'terminal_replies': lambda: terminal_replies, 'observe': trace.append, 'task_domain':domain}
        if domain:
            settings['tool_names'] &= {name for name in SCHEMAS if name.startswith(domain+'_')
                or (domain=='luckin' and name in {'amap_search_places','amap_current_location'})
                or (domain in {'mcd','didi'} and name=='personal_profile')}
        if read_only.READ_ONLY:
            settings['tool_names'] &= read_only.QUERY_TOOLS
        if (not contact_media.get()
                and not self.actions.pending(owner)
                and lightweight_chat(text)):
            settings = {**settings, 'lightweight_chat': True, 'tool_names':set()}
            trace.append({'type': 'host.lightweight_chat'})
        session.model_used = True
        bot = build_runtime(settings, self.data_dir / 'runtime', dispatch, context)
        result = None
        started = time.monotonic()
        first_text = True
        notify({'type': 'progress', 'stage': 'understanding', 'text': '正在输入…'})
        async with bot:
            media_kwargs = {'media': contact_media.get()} if contact_media.get() else {}
            async for event in bot.stream(text, session_key=key, **media_kwargs):
                if event.type == 'text.delta':
                    if first_text and not grounded_business:
                        first_text = False
                        trace.append({'type': 'timing', 'stage': 'first_text',
                                      'elapsed_ms': round((time.monotonic() - started) * 1000)})
                    if not grounded_business:
                        notify({'type': 'delta', 'text': event.delta})
                if event.type in {'run.started', 'tool.started', 'tool.completed', 'tool.failed', 'run.completed'}:
                    trace.append({'type': event.type, **({'name': event.name} if event.name else {})})
                if event.type == 'run.completed':
                    result = event.result
        trace.append({'type': 'timing', 'stage': 'runtime_including_tools',
                      'elapsed_ms': round((time.monotonic() - started) * 1000)})
        if result is not None and result.error and 'SetLimitExceeded' in str(result.error):
            raise AgentError('豆包模型已达到账号用量上限，服务暂时暂停。请家人在火山方舟控制台核对额度后再试；已接收的消息不会自动重试。', 503)
        if result is not None and result.error and 'ModelNotOpen' in str(result.error):
            raise AgentError('当前配置的文本模型尚未开通，请家人在设置中选择已开通的模型或到服务平台开通；本次没有下单。',503)
        if result is None or result.error or result.stop_reason != 'completed':
            raise AgentError('小瑞本次任务尚未完成，请查看已有结果后重试。')
        if flight_results:
            from app.fliggy import flight_reply
            answer = flight_reply(flight_results[-1])
            notify({'type':'delta','text':answer})
            return answer
        if not isinstance(result.content, str) or not result.content.strip():
            raise AgentError('小瑞暂时没有生成回复，请重试。')
        if grounded_business or session.tool_facts:
            answer=business_reply(text, focused_services, session.tool_facts, events, self.store.model_profile(), domain=domain)
            session.speech_turn = {'text': answer, 'source': 'grounded', 'stage': 'business'}
            session.defer_speech = False
            if session.tool_facts:
                notify({'type':'progress','stage':'facts','text':'已核对真实结果，正在显示'})
            if grounded_business:
                trace.append({'type':'timing','stage':'first_text','elapsed_ms':round((time.monotonic()-started)*1000)})
            trace.append({'type':'timing','stage':'speech_composition','elapsed_ms':0})
            notify({'type':'delta','text':answer})
            return answer
        notify({'type': 'progress', 'stage': 'narration', 'text': '回复已生成，正在整理成简短的话'})
        started = time.monotonic()
        if contact_reply_mode.get()=='text':
            session.speech_turn = speech_fallback(speech_context(text,result.content.strip(),events,session.display,self.store.model_profile()))
            session.defer_speech = session.speech_turn['source'] not in {'grounded','brief'}
        else:
            session.speech_turn = await self.speech.compose(
                self._config(), text, result.content.strip(), events, session.display, profile=self.store.model_profile())
        trace.append({'type': 'timing', 'stage': 'speech_composition',
                      'elapsed_ms': round((time.monotonic() - started) * 1000)})
        answer=result.content.strip()
        if weather_reports and weather_reports[-1] not in answer:
            answer+=f'\n\n高德报告时间：{weather_reports[-1]}。'
        return answer

    def _answer(self, owner, session, text, answer, events, trace, task_id, conversation_reset=False):
        for event in events:
            plan=event.get('plan',{})
            if event.get('type')=='action_plan' and plan.get('action')=='create' and plan.get('id') and plan.get('status') in ActionManager.REVIEW:
                session.services.setdefault(plan['provider'],{})['checkout_plan_id']=plan['id']
        ready=[e for e in events if e.get('type')=='service_choices' and any(c.get('recommendation_id') for c in e.get('choices',[]))]
        if ready:
            events=[e for e in events if e.get('type')!='service_choices' or e is ready[-1]]
        domain = turn_domain(text, session.display)
        focused_services = {key:value for key,value in session.services.items() if not domain or key == domain}
        if any(e.get('type') in {'plan','action_plan'} for e in events):
            answer = business_reply(text, focused_services, session.tool_facts, events, self.store.model_profile(), domain=domain)
            session.speech_turn = {'text':answer,'source':'grounded','stage':'transaction' if any(e.get('type') in {'plan','action_plan'} for e in events) else 'business'}
            session.defer_speech = False
        spoken = session.speech_turn or speech_fallback(speech_context(text, answer, events, session.display, self.store.model_profile()))
        if any(event.get('type') in {'plan','action_plan'} for event in events):
            spoken = speech_fallback(speech_context(text, answer, events, session.display, self.store.model_profile()))
        flight_events = [e for e in events if e.get('type') == 'flight_result']
        if flight_events:
            from app.fliggy import flight_reply
            answer = flight_reply(flight_events[-1]['data'])
            spoken = {'text': flight_events[-1]['data'].get('error') or '本次航班查询结果和飞猪预订链接已显示。尚未订票或付款，请在飞猪核对信息后确认付款。',
                      'source':'grounded', 'stage':'business'}
            session.defer_speech = False
        response = {'text': answer, 'speech_text': spoken['text'], 'speech_source': spoken['source'],
                    'speech_stage': spoken['stage'], 'events': events,
                    'runtime': 'nanobot', 'task_id': task_id, 'trace': trace,
                    'conversation_reset': conversation_reset}
        if session.defer_speech:
            profile=self.store.model_profile()
            self._speech_jobs[task_id]={'owner':owner,'conversation_id':session.conversation_id,
                'version':profile['version'],'profile':profile,'user':text,'answer':answer,
                'events':copy.deepcopy(events),'history':copy.deepcopy(session.display)}
            response['speech_deferred']=True
        session.display.extend([{'role': 'user', 'text': text.strip()},
                                {'role': 'assistant', **copy.deepcopy(response)}])
        session.display = session.display[-48:]
        self.store.save_session(owner, session.snapshot())
        return response

    def discard_speech(self, task_id):
        self._speech_jobs.pop(task_id,None)

    async def complete_speech(self, owner, task_id):
        job=self._speech_jobs.pop(task_id,None)
        if not job or job['owner']!=owner:
            return None
        async with self._speech_slots:
            spoken=await self.speech.compose(self._config(),job['user'],job['answer'],job['events'],job['history'],profile=job['profile'])
        if self.store.profile()['version']!=job['version']:
            return None
        state=self.store.session(owner)
        if state['conversation_id']!=job['conversation_id']:
            return None
        patch={'speech_text':spoken['text'],'speech_source':spoken['source'],'speech_deferred':False}
        found=False
        for message in state['display']:
            if message.get('task_id')==task_id:
                message.update(patch);found=True
        if not found:
            return None
        self.store.save_session(owner,state)
        cached=self.sessions.get(owner)
        if cached and cached.conversation_id==job['conversation_id']:
            for message in cached.display:
                if message.get('task_id')==task_id:
                    message.update(patch)
        return {'type':'speech_ready','task_id':task_id,**patch}

    async def chat(self, owner, text, *, expected_confirmation=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise AgentError('请发送 1 到 2000 字的消息。', 400)
        if not self.configured:
            raise AgentError('请先配置豆包文本模型，再开始对话。', 503)
        session = self._session(owner)
        if session.lock.locked():
            raise AgentError('小瑞正在回复，请稍等。', 409)
        async with session.lock:
            release_completed_drafts(self,session,owner)
            session.current_input = text.strip()
            events, trace = [], []
            session.speech_turn = None
            session.defer_speech = False
            session.tool_facts = []
            session.model_used = False
            initial_conversation = session.conversation_id
            task_id = self.store.start_task(owner, session.conversation_id, text)
            try:
                async with asyncio.timeout(180):
                    phrase = text.strip().rstrip('。！!，, ')
                    pending_action = self.actions.pending(owner)
                    from app.companion_memory import forget_target, topic_terms
                    target = forget_target(text)
                    terms = topic_terms(target) if target else set()
                    canonical_match = target and any(any(term in (key+' '+str(value)).lower() for term in terms)
                        for key,value in self.store.list_facts().items())
                    inferred_removed = self.memory.forget(owner,target) if target and not canonical_match else 0
                    if inferred_removed:
                        # Rotate only model context; preserve unrelated inferred
                        # preferences in the same owner/forget generation.
                        fresh = self.store.new_session(owner)
                        session.conversation_id = fresh['conversation_id']
                        session.display.clear()
                        session.stores.clear();session.meals.clear();session.services.clear()
                        self.actions.invalidate_pending(owner, status='cancelled')
                        answer = '已删除匹配的对话记忆。'
                        trace.append({'type':'host.memory_forget','removed':inferred_removed})
                    elif read_only.READ_ONLY and phrase in {'确认叫车','确认下单','确认取消','确认新增地址'}:
                        answer = read_only.MESSAGE
                    elif phrase in {'确认叫车','确认下单','确认取消','确认新增地址'} and not contact_media.get():
                        if (pending_action is None or phrase != self.actions.phrase(pending_action)
                                or (expected_confirmation is not None and expected_confirmation != [pending_action['id'], pending_action['version']])):
                            answer = '目前没有对应的待确认方案。请先告诉我具体需求，核对方案后再确认。'
                        else:
                            try:
                                current = await self.actions.confirm(owner,pending_action['id'],pending_action['version'],
                                    pending_action['confirmation_token'],phrase)
                                events.append({'type':'action_plan','plan':current})
                                answer = self.action_text(current)
                            except ActionError as exc:
                                answer = exc.message
                        trace.append({'type':'host.confirmation'})
                    elif (answer:=luckin_delivery_boundary(text,session.display)) is not None:
                        self.actions.invalidate_pending(owner)
                        trace.append({'type':'host.luckin_delivery_boundary'})
                    elif reminder_request(text):
                        self.actions.invalidate_pending(owner)
                        answer='目前还不能到时主动提醒您。可以在手机上设置计时器；您也可以直接说其他需求。'
                        trace.append({'type':'host.reminder_boundary'})
                    elif (phrase in {'取消订单','取消麦当劳订单','帮我取消订单','不想付钱了','不付了'}
                          and not read_only.READ_ONLY
                          and (cancel_domain := turn_domain(text, session.display)) in {None, 'mcd'}
                          and (answer := await cancel_mcd_order(
                              self, session, owner, events, explicit=cancel_domain == 'mcd')) is not None):
                        trace.append({'type':'host.cancel_order_query'})
                    elif (not read_only.READ_ONLY and turn_domain(text,session.display) in {None,'mcd'}
                            and (recommendation_id:=resolve_selection(session,text))):
                        result=await self.scenarios['mcd'].dispatch(session,owner,'mcd_choose_recommendation',{'recommendation_id':recommendation_id},events)
                        if 'products' in result:events.append({'type':'service_choices','choices':choice_cards(result)})
                        answer=self.proposal_text(result['plan']) if result.get('plan') else result.get('error') or result.get('note','请重新查询套餐。')
                        trace.append({'type':'host.meal_selection'})
                    elif phrase in {'先不下单','先不叫车','取消方案','先不取消','算了','不点了','先不点了','先不新增地址','这事先不做了','不弄了'} and (pending_action or session.services):
                        if pending_action:
                            current = self.actions.cancel_local(owner,pending_action['id'])
                            events.append({'type':'action_plan','plan':current})
                        answer = '已取消这份待确认方案，没有执行真实交易。' if pending_action else '好的，这次先不点了。购物车已清空；已经创建的真实订单不会因此取消。'
                        if phrase not in {'先不取消'}:
                            clear_drafts(session)
                        answer+=' 您可以直接说新的需求。'
                    else:
                        # Any changed conversation requires a fresh proposal;
                        # old card capabilities cannot approve a modified plan.
                        self.actions.invalidate_pending(owner)
                        answer = await self._run(owner, session, text.strip(), events, trace)
                        proposals=[e['plan'] for e in events if e.get('type')=='action_plan' and e['plan']['status'] in ActionManager.REVIEW]
                        if proposals:
                            answer=self.proposal_text(proposals[-1])
                response = self._answer(owner, session, text, answer, events, trace, task_id,
                                        session.conversation_id != initial_conversation)
                pending = any(e['type'] in {'plan','action_plan'} and e['plan']['status'] in {'awaiting_confirmation', 'needs_review'} for e in events)
                status = 'waiting_confirmation' if pending else 'completed'
                action_states={e['plan']['status'] for e in events if e['type']=='action_plan'}
                if 'unknown' in action_states:
                    status='unknown'
                elif action_states & {'failed','expired'}:
                    status='failed'
                try:
                    memory_status = await self.memory.learn(owner, session.forget_epoch, text, self._config(), reply=response['text'])
                except (OSError, SQLiteError, ValueError):
                    # A memory side effect cannot turn a completed action into a
                    # failed task that invites the user to repeat that action.
                    memory_status = 'unavailable'
                trace.append({'type': 'memory.learn', 'status': memory_status})
                self.store.finish_task(task_id, status, result={'text': response['text'], 'trace': trace})
                return response
            except asyncio.CancelledError:
                self.store.finish_task(task_id, 'interrupted', error='本次任务中断，未自动重试。')
                raise
            except Exception as exc:
                # Preserve already completed real operations and cards without claiming further success.
                self.store.finish_task(task_id, 'failed', error='本次任务未完整完成，未自动重试。')
                if events:
                    answer = '已查询的真实结果见卡片，后续处理暂未完成。请核对，尚未下单。'
                    return self._answer(owner, session, text, answer, events, trace, task_id)
                if isinstance(exc, AgentError):
                    raise exc from None
                raise AgentError('小瑞暂时无法完成任务，请检查模型配置或网络后重试。') from None

    @staticmethod
    def proposal_text(plan):
        labels=LABELS
        parts=[]
        for key,value in normalize_summary(plan['summary']).items():
            if key in {'estimated_fee','cancel_fee'}:
                continue
            label=labels.get(key) or (key if key and '\u4e00' <= key[0] <= '\u9fff' else None)
            if not label or value in (None,'',[]):
                continue
            if isinstance(value,list):
                value='、'.join(str(v) if isinstance(v,str) else
                    f'{v.get("attribute","")} {"、".join(v.get("selected",[]))}' for v in value)
            if not isinstance(value,(str,int,float)):
                continue
            parts.append(f'{label}：{str(value).rstrip("。；; ")}')
        heading='新增配送地址' if plan['action']=='create_address' else '取消方案' if plan['action']=='cancel' else '出行方案' if plan['provider']=='didi' else '点餐方案'
        parts=parts[:10]
        answer=f'{heading}，'+ '；'.join(parts)+f'。本次{"预估" if plan["provider"]=="didi" else ""}费用 {format_cents(plan['amount_cents'])} 元。'
        if plan['execution_enabled']:
            answer+=f'请核对，确定后说“{plan["confirmation_text"]}”。'
        else:
            answer+='家人尚未开启这项真实交易执行，当前只准备方案。'
        return answer

    @staticmethod
    def action_text(plan):
        if plan['status'] == 'address_created':
            return '麦当劳配送地址已创建。请查询配送地址列表，选择新地址继续查店点餐；尚未创建餐饮订单或付款。'
        if plan['status'] == 'created':
            return ('已提交叫车请求，正在等平台匹配司机；还不能说司机已接单。' if plan['provider']=='didi'
                    else '订单已创建。是否已支付、备餐或配送，要以官方订单状态为准；我没有替您付款。')
        if plan['status'] == 'cancelled':
            return '取消请求已返回，请继续核对官方订单状态。'
        if plan['status'] == 'cancellation_requested':
            return '已提交取消请求，是否取消成功还要查询官方订单，暂时不要重复操作。'
        if plan['status'] == 'needs_review':
            return '费用、规格或接送点有变化，请核对新方案后再次确认。'
        return plan.get('error') or '这一步尚未完成，请核对当前方案。'
