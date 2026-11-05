"""Explicit capability catalog and strict adapters for the hosted nanobot runtime.

No merchant order, payment, shell, file, or arbitrary MCP tool is registered here.
"""
import copy
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.plans import PlanError
from app.recommendations import recommend
from app.service_skills import SERVICE_SCHEMAS
from app.didi_scenario import SCHEMAS as DIDI_SCHEMAS
from app.mcd_scenario import SCHEMAS as MCD_SCHEMAS
from app.luckin_scenario import SCHEMAS as LUCKIN_SCHEMAS
from app.amap import SCHEMAS as AMAP_SCHEMAS

SCENARIO_SCHEMAS = {**DIDI_SCHEMAS, **MCD_SCHEMAS, **LUCKIN_SCHEMAS}

class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Search(Arguments):
    city: str = Field(min_length=1, max_length=80)
    keyword: str = Field(min_length=1, max_length=120)


class Recommend(Arguments):
    store_code: str = Field(min_length=1, max_length=80)
    budget_cents: int = Field(ge=100, le=100000, strict=True)


class Choose(Arguments):
    index: int = Field(ge=1, le=3, strict=True)


DINING_SCHEMAS = {'search_stores': (Search, '根据用户明确给出的城市和附近地标查找真实麦当劳门店。不要猜测位置。'),
           'recommend_meals': (Recommend, '在本次已搜索出的门店中查询预算内真实套餐。预算以分计。必须先由用户选择门店；预算变化必须重新查询。'),
           'choose_meal': (Choose, '根据用户明确选择的第几份套餐（1到3）重新核价，生成本地待确认方案；这不会下单或支付。'),
           'cancel_plan': (Arguments, '仅取消当前本地待确认方案，不取消已创建的真实订单。')}
class PersonalProfile(Arguments):
    action: Literal['list', 'set', 'forget']
    key: str | None = Field(default=None, min_length=1, max_length=80, pattern=r'^[a-z][a-z0-9_.-]*$', strict=True)
    value: str | None = Field(default=None, min_length=1, max_length=1000, strict=True)

    @model_validator(mode='after')
    def action_fields(self):
        if self.action == 'list' and (self.key is not None or self.value is not None):
            raise ValueError('list takes no key or value')
        if self.action in ('set', 'forget') and self.key is None:
            raise ValueError('key is required')
        if self.action == 'set' and self.value is None:
            raise ValueError('value is required')
        if self.action == 'forget' and self.value is not None:
            raise ValueError('forget takes no value')
        return self


class TaskRecords(Arguments):
    action: Literal['list', 'get']
    task_id: str | None = Field(default=None, min_length=1, max_length=128, strict=True)

    @model_validator(mode='after')
    def action_fields(self):
        if self.action == 'get' and self.task_id is None:
            raise ValueError('get requires task_id')
        if self.action == 'list' and self.task_id is not None:
            raise ValueError('list takes no task_id')
        return self


SCHEMAS = {**SERVICE_SCHEMAS, **SCENARIO_SCHEMAS, **AMAP_SCHEMAS, 'personal_profile': (PersonalProfile,
    '查看、保存或忘记本人长期资料。只有用户明确要求记住长期事实时才set；今天等临时要求不保存。忘记用forget，不能从旧聊天恢复已删除资料。key用home.address或preferences.drinks等稳定英文键，value是用户原意。'),
    'task_records': (TaskRecords,
    '只读查询本人的真实任务台账。list列出近期任务，get按返回的task_id查看详情。只报告实际状态；不执行、重放或取消任务，不能把interrupted说成已恢复完成。')}
TOOLS = [{'type': 'function', 'function': {'name': name, 'description': description,
          'parameters': schema.model_json_schema()}} for name, (schema, description) in SCHEMAS.items()]


def catalog():
    return [{'id':'maps.amap','name':'高德地图查询','tools':list(AMAP_SCHEMAS),'enabled':True,'scope':'conversation','source':'skills/amap/SKILL.md'},
            {'id': 'core.personal', 'name': '个人资料', 'tools': ['personal_profile'],
             'enabled': True, 'scope': 'local-profile', 'source': 'skills/core/SKILL.md'},
            {'id': 'core.tasks', 'name': '任务记录', 'tools': ['task_records'],
             'enabled': True, 'scope': 'owner', 'source': 'skills/tasks/SKILL.md'},
            {'id': 'life.services', 'name': '瑞幸与滴滴查询', 'tools': list(SERVICE_SCHEMAS),
             'enabled': True, 'scope': 'conversation', 'source': 'skills/services/SKILL.md'},
            *[{'id':f'life.{provider}', 'name':name, 'tools':list(schemas), 'enabled':True,
               'scope':'owner-transactions', 'source':f'skills/{provider}/SKILL.md'}
              for provider,name,schemas in [('didi','滴滴出行',DIDI_SCHEMAS),
                ('mcd','麦当劳点餐与外送',MCD_SCHEMAS),('luckin','瑞幸饮品',LUCKIN_SCHEMAS)]]]


def build_tools(dispatch):
    """Bind a host dispatcher; no hidden defaults or dynamic community loading.

    dispatch(name, arguments) is async and returns a JSON-serializable object.
    Host binding supplies owner, conversation and per-turn event collection.
    """
    from nanobot.agent.tools.base import Tool

    class HostedTool(Tool):
        def __init__(self, tool_name):
            self.tool_name = tool_name

        @property
        def name(self):
            return self.tool_name

        @property
        def description(self):
            return SCHEMAS[self.tool_name][1]

        @property
        def parameters(self):
            return SCHEMAS[self.tool_name][0].model_json_schema()

        def cast_params(self, params):
            # Preserve strict int/bool boundaries; do not let upstream cast before validation.
            return params

        def validate_params(self, params):
            try:
                SCHEMAS[self.tool_name][0].model_validate(params)
                return []
            except ValidationError:
                return ['工具参数无效，请根据用户需求补充正确参数。']

        async def execute(self, **kwargs):
            try:
                arguments = SCHEMAS[self.tool_name][0].model_validate(kwargs).model_dump(exclude_none=True, exclude_unset=True)
            except ValidationError:
                return self.error('工具参数无效，请根据用户需求补充正确参数。')
            result = await dispatch(self.tool_name, arguments)
            encoded = json.dumps(result, ensure_ascii=False)
            return self.error(encoded) if isinstance(result, dict) and 'error' in result else encoded

    return [HostedTool(name) for name in SCHEMAS]


class SkillRegistry:
    """Existing dining skill; the host owns personal-profile dispatch and persistence."""
    def __init__(self, service, plans):
        self.service, self.plans = service, plans

    def _plan(self, session, owner):
        return self.plans.get(session.plan_id, owner) if session.plan_id else None

    def _guard(self, session, owner):
        plan = self._plan(session, owner)
        if plan and plan['status'] in {'unknown', 'submitting', 'rechecking'}:
            raise PlanError('上一笔订单结果待核查或正在处理，请勿重复操作。')
        return plan

    async def dispatch(self, session, owner, name, arguments, events):
        if name not in DINING_SCHEMAS:
            return {'error': '该工具未开放。不能下单或支付。'}
        try:
            args = DINING_SCHEMAS[name][0].model_validate(arguments)
            self._guard(session, owner)
            if name == 'search_stores':
                session.meals = []
                session.stores = {}
                pending = self._plan(session, owner)
                if pending and pending['status'] in {'awaiting_confirmation', 'needs_review', 'expired'}:
                    cancelled = self.plans.cancel(pending['id'], owner)
                    events.append({'type': 'plan', 'plan': cancelled})
                stores = await self.service.search_stores(args.city, args.keyword)
                session.stores = {s['code']: copy.deepcopy(s) for s in stores}
                events.append({'type': 'stores', 'stores': stores})
                return {'stores': stores, 'next': '请用户选择门店，再查询套餐'}
            if name == 'recommend_meals':
                if args.store_code not in session.stores:
                    return {'error': '必须先搜索门店，并使用本次结果中的门店。'}
                session.meals = []
                p = self._plan(session, owner)
                if p and p['status'] in {'awaiting_confirmation', 'needs_review', 'expired'}:
                    cancelled = self.plans.cancel(p['id'], owner)
                    events.append({'type': 'plan', 'plan': cancelled})
                result = await recommend(self.service, args.store_code, args.budget_cents, 3)
                session.meals = copy.deepcopy(result['recommendations'])
                events.append({'type': 'meals', 'meals': result['recommendations']})
                return {'meals': [{'index': i+1, 'name': m['name'], 'amount_cents': m['amount_cents'],
                                   'choices': m['choices']} for i, m in enumerate(session.meals)],
                        'speech_text': result['speech_text'], 'mode': 'pickup'}
            if name == 'choose_meal':
                if args.index > len(session.meals):
                    return {'error': '没有对应套餐，请先查询或选择当前推荐中的套餐。'}
                request = copy.deepcopy(session.meals[args.index-1]['request'])
                prepared = await self.service.prepare_plan(request)
                plan = self.plans.create(owner, prepared)
                session.plan_id = plan['id']
                events.append({'type': 'plan', 'plan': plan})
                # Confirmation token is only delivered to the local UI, never the model.
                return {'summary': plan['summary'], 'amount_cents': plan['amount_cents'],
                        'status': plan['status'], 'next': '请用户在网页核对并二次确认，尚未下单'}
            if name == 'cancel_plan':
                if not session.plan_id:
                    return {'error': '当前没有待确认方案。'}
                plan = self.plans.cancel(session.plan_id, owner)
                events.append({'type': 'plan', 'plan': plan})
                session.plan_id = None
                return {'status': 'cancelled', 'order_created': False}
        except ValidationError:
            return {'error': '工具参数无效，请根据用户需求补充正确参数。'}
        except PlanError as exc:
            return {'error': exc.message}
        except ValueError:
            return {'error': '查询或套餐参数不完整，请重新搜索和选择。'}
        except Exception:
            return {'error': '真实服务查询或核价失败，尚未完成，请稍后重试。'}

