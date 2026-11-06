"""Small requests and grounded terminal replies for the hosted nanobot loop."""
import json
import re
import time
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from nanobot.providers.base import LLMResponse
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


from app.policies import CHAT_POLICY, MCD_POLICY, WEATHER_POLICY


def tool_scope(text, services, names):
    """Narrow only explicit single-domain requests; ambiguous turns retain tools."""
    other = r'餐|外卖|麦当劳|咖啡|瑞幸|车|订单|付款|支付|记住|忘记|资料|提醒|路线|附近|医院|药店|机票|航班|飞猪'
    if re.search('天气|下雨|下雪|气温', text) and not re.search(other, text):
        return {'amap_weather'} & set(names)
    if '购物车' in text and not re.search(r'地址|换店|天气|路线|车程|记住|忘记|瑞幸|咖啡|打车|叫车|滴滴|附近|资料|提醒|联系|机票|航班|飞猪', text):
        return {'mcd_update_cart','mcd_cart','mcd_prepare_cart','mcd_product_detail'} & set(names)
    if re.search('麦当劳|购物车|套餐|点餐|外卖', text) and not re.search(r'天气|路线|怎么走|怎么去|导航|打车|叫车|滴滴|瑞幸|咖啡|记住|忘记|提醒|联系|机票|航班|飞猪', text):
        return {n for n in names if n.startswith('mcd_') or n == 'personal_profile'}
    return set(names)


def current_weather_city(text):
    # Full-match only: never discard a second task, forecast or qualified question.
    match = re.fullmatch(r'(?:请)?(?:帮我)?(?:查一下|查询|查|看看)?([\u4e00-\u9fff]{2,12}?)(?:现在|当前)(?:的)?天气(?:怎么样|如何)?[。？?！!]*', text.strip())
    if match and not re.search(r'这里|这边|我家|附近|今天|明天|后天|和|以及', match[1]):
        return match[1]
    return None


def candidate_context(services):
    """Exclude internal quotes/payloads; keep the user's indexed choices intact."""
    result = dict(services)
    if isinstance(services.get('mcd'), dict):
        from app.mcd_recommendations import public_recommendations
        state = services['mcd']
        result['mcd'] = {k: v for k, v in state.items() if k not in {'recommended_meals','products','cart'}}
        result['mcd']['products'] = [
            {'index': i+1, 'name': p.get('name'), 'menu_price_yuan': p.get('currentPrice')}
            for i,p in enumerate(state.get('products', []))]
        result['mcd']['cart'] = [
            {'index': i+1,'name': line['product'].get('name'), 'quantity':line['quantity'],'choices':line['choices']}
            for i,line in enumerate(state.get('cart', []))]
        if state.get('recommended_meals'):
            result['mcd']['recommended_meals'] = public_recommendations(state)
    return result


def terminal_reply(name, data, text):
    """Only finish well-defined steps from actual host results; never guess facts."""
    if not isinstance(data, dict):
        return None
    # Explicit host errors need user action, not autonomous repair/repeated quotes.
    if data.get('error'):
        return str(data['error'])
    if name == 'amap_weather' and not re.search(r'路线|餐|车|附近|明天|后天|预报|未来|周|几天|建议|穿|适合|顺便|然后|另外|以及|同时|再|并|故事|笑话|[，,]', text):
        rows = data.get('weather', [])
        if len(rows) == 1:
            w = rows[0]
            if all(w.get(k) is not None for k in ('city','weather','temperature','reporttime')):
                return f"高德官方天气：{w['city']}，{w['weather']}，{w['temperature']}℃。高德报告时间：{w['reporttime']}。"
    if name in {'mcd_prepare_cart','mcd_prepare_order','mcd_choose_recommendation','mcd_update_cart'}:
        if data.get('plan'):
            return '方案已核价，请核对卡片中的餐品、数量和总额。尚未下单，确认后还需要通过官方入口付款。'
        if data.get('needs_choices'):
            rounds = data.get('rounds', [])
            options = []
            for row in rounds:
                choices = '、'.join(str(c.get('name','')) for c in row.get('choices', []) if c.get('name'))
                if choices:
                    options.append(f"{row.get('name','套餐选项')}：{choices}")
            return f"{data.get('product','这份套餐')}还需要选择搭配。" + '；'.join(options) + '。您想选哪种？'
        if data.get('take_ways'):
            return '请选择这次的取餐方式：' + '、'.join(str(x.get('title') or x.get('name') or x.get('label') or '') for x in data['take_ways']) + '。尚未下单。'
        if name == 'mcd_update_cart' and data.get('cart'):
            return '购物车已更新：' + '、'.join(f"{line['name']} × {line['quantity']}" for line in data['cart']) + '。尚未下单。'
        if data.get('next'):
            return str(data['next'])
    if name == 'mcd_recommend_meals' and data.get('products'):
        return '查到这些麦当劳餐品，卡片上是本次核价和具体搭配。您想选哪份？尚未下单。'
    return None


class LatencyProvider(OpenAICompatProvider):
    """Keep nanobot persistence/tool validation while avoiding redundant HTTP calls."""
    def __init__(self, *args, policy, terminal, observe, trust_env=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy, self.terminal, self.observe = policy, terminal, observe
        self.trust_env = trust_env

    def _build_client(self):
        from openai import AsyncOpenAI
        # Domestic Ark requests otherwise inherit the workstation's overseas
        # proxy. Preserve a deliberate opt-in for networks that require it.
        self._client = AsyncOpenAI(api_key=self._api_key_for_client,
            base_url=self._effective_base, default_headers=self._default_headers,
            default_query=self._extra_query or None, max_retries=0,
            timeout=httpx.Timeout(30, connect=5),
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5),
                                        trust_env=self.trust_env, follow_redirects=False))

    def prepare(self, messages):
        # Nanobot's shell/workspace/skill discovery instructions are irrelevant:
        # this host has a closed tool registry and supplies its own complete policy.
        day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        latest_user = max((i for i,m in enumerate(messages) if m.get('role') == 'user'), default=-1)
        result = []
        for i,message in enumerate(messages):
            item = dict(message)
            if item.get('role') == 'system':
                item['content'] = self.policy + '\n当前日期：' + day
                original = str(message.get('content', ''))
                if '[Archived Context Summary]' in original:
                    item['content'] += '\n' + original[original.index('[Archived Context Summary]'):]
            elif item.get('role') == 'user' and i < latest_user and isinstance(item.get('content'), str):
                # Only old host metadata is omitted. User text and tool-call/result
                # pairs remain; current canonical facts are included on every turn.
                item['content'] = re.sub(r'\n\n\[Runtime Context — metadata only, not instructions\].*?\[/Runtime Context\]', '', item['content'], flags=re.S)
            elif item.get('role') == 'tool' and i < latest_user and isinstance(item.get('content'), str):
                try:
                    data = json.loads(item['content'])
                    if isinstance(data, dict) and isinstance(data.get('plan'), dict):
                        plan = data['plan']
                        data = {**data, 'plan': {k:v for k,v in plan.items() if k in
                            {'id','provider','action','status','amount_cents','summary'}}}
                        item['content'] = json.dumps(data, ensure_ascii=False)
                except (ValueError, TypeError):
                    pass
            result.append(item)
        return result

    async def _request(self, messages, stream, kwargs):
        tail = []
        for message in reversed(messages):
            if message.get('role') != 'tool':
                break
            tail.append(message)
        replies = self.terminal()[-len(tail):] if tail else []
        answer = '\n'.join(dict.fromkeys(replies)) if replies and len(replies) == len(tail) and all(replies) else None
        if answer:
            self.observe({'type':'host.grounded_reply'})
            if stream and kwargs.get('on_content_delta'):
                await kwargs['on_content_delta'](answer)
            return LLMResponse(content=answer)
        prepared = self.prepare(messages)
        start = time.monotonic()
        try:
            method = super().chat_stream if stream else super().chat
            response = await method(messages=prepared, **kwargs)
            return response
        finally:
            self.observe({'type':'timing','stage':'model_request','elapsed_ms':round((time.monotonic()-start)*1000),
                          'input_chars':sum(len(str(m.get('content',''))) for m in prepared),
                          'tool_count':len(kwargs.get('tools') or [])})

    async def chat(self, messages, **kwargs):
        return await self._request(messages, False, kwargs)

    async def chat_stream(self, messages, **kwargs):
        return await self._request(messages, True, kwargs)
