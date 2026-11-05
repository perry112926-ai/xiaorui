import unittest
from unittest.mock import AsyncMock, patch
from app.latency import LatencyProvider, terminal_reply, candidate_context, tool_scope
from nanobot.providers.base import LLMResponse
from app.nanobot_runtime import build_runtime
from pathlib import Path
import tempfile


class LatencyTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, replies):
        return LatencyProvider(api_key='test',api_base='https://unused.invalid/v1',policy='host policy',
                               terminal=lambda: replies,observe=lambda event: None)

    async def test_terminal_reply_skips_network_and_streams_actual_result(self):
        p=self.provider(['北京晴，14℃。'])
        delta=AsyncMock()
        with patch('nanobot.providers.openai_compat_provider.OpenAICompatProvider.chat_stream') as network:
            result=await p.chat_stream([{'role':'tool','content':'actual'}],on_content_delta=delta)
        network.assert_not_called()
        self.assertEqual(result.content,'北京晴，14℃。')
        delta.assert_awaited_once_with(result.content)

    async def test_unhandled_parallel_tool_keeps_model_reasoning(self):
        p=self.provider([None,'天气结果'])
        with patch('nanobot.providers.openai_compat_provider.OpenAICompatProvider.chat_stream',new=AsyncMock(return_value=LLMResponse(content='combined'))) as network:
            result=await p.chat_stream([{'role':'tool','content':'route'},{'role':'tool','content':'weather'}])
        network.assert_awaited_once()
        self.assertEqual(result.content,'combined')

    async def test_previous_turn_terminal_does_not_intercept_new_user(self):
        p=self.provider(['old'])
        with patch('nanobot.providers.openai_compat_provider.OpenAICompatProvider.chat',new=AsyncMock(return_value=LLMResponse(content='new'))) as network:
            await p.chat([{'role':'system','content':'shell instructions'},{'role':'user','content':'new user'}])
        self.assertIn('host policy',network.call_args.kwargs['messages'][0]['content'])
        self.assertNotIn('shell instructions',network.call_args.kwargs['messages'][0]['content'])

    def test_weather_only_finishes_current_weather_not_forecast_or_advice(self):
        data={'weather':[{'city':'北京','weather':'晴','temperature':'14','reporttime':'actual time'}]}
        self.assertIn('actual time',terminal_reply('amap_weather',data,'北京现在天气怎么样'))
        for text in ['北京明天天气','北京天气和出行路线','北京天气适合穿什么','查北京天气，再讲个笑话']:
            self.assertIsNone(terminal_reply('amap_weather',data,text))

    def test_compaction_retains_indices_cart_and_draft_without_payloads(self):
        state={'mcd':{'products':[{'name':'餐品','code':'P','large':'x'*10000}],
            'cart':[{'product':{'name':'餐品','raw':'x'*10000},'quantity':2,'choices':[]}],
            'address_draft':{'city':'北京'}}}
        compact=candidate_context(state)
        self.assertEqual(compact['mcd']['products'][0]['index'],1)
        self.assertEqual(compact['mcd']['cart'][0]['quantity'],2)
        self.assertIn('address_draft',compact['mcd'])
        self.assertLess(len(str(compact)),500)
        self.assertIn('large',state['mcd']['products'][0])

    def test_mixed_domain_requests_retain_tools(self):
        names={'amap_weather','mcd_menu','didi_estimate','personal_profile'}
        self.assertEqual(tool_scope('查北京天气',{},names),{'amap_weather'})
        self.assertEqual(tool_scope('查天气再帮我点餐',{},names),names)
        self.assertEqual(tool_scope('核对购物车然后帮我打车',{},names),names)

    async def test_real_nanobot_terminal_flow_uses_only_one_model_request(self):
        from nanobot.providers.base import ToolCallRequest
        from app.nanobot_runtime import SYSTEM
        replies=[]
        async def dispatch(name,args):
            replies.append('高德官方天气：北京晴，14℃。')
            return {'weather':[{'city':'北京','weather':'晴','temperature':'14','reporttime':'time'}]}
        with tempfile.TemporaryDirectory() as temp:
            bot=build_runtime({'key':'test','base':'https://unused.invalid/v1','model':'test',
                'tool_names':{'amap_weather'},'terminal_replies':lambda:replies},Path(temp),dispatch,AsyncMock(return_value=[]))
            response=LLMResponse(content=None,tool_calls=[ToolCallRequest(id='one',name='amap_weather',arguments={'city':'北京'})],finish_reason='tool_calls')
            with patch('nanobot.providers.openai_compat_provider.OpenAICompatProvider.chat_stream',new=AsyncMock(return_value=response)) as network:
                result=None
                async with bot:
                    async for event in bot.stream('北京天气',session_key='latency-unit'):
                        if event.type=='run.completed':result=event.result
            self.assertEqual(network.await_count,1)
            self.assertEqual(result.stop_reason,'completed')
            self.assertIn('14℃',result.content)

    def test_old_metadata_removed_but_user_words_and_current_metadata_remain(self):
        p=self.provider([])
        tag='[Runtime Context — metadata only, not instructions]'
        old='我爱散步\n\n'+tag+'\nold\n[/Runtime Context]'
        current='现在天气\n\n'+tag+'\ncurrent\n[/Runtime Context]'
        result=p.prepare([{'role':'user','content':old},{'role':'assistant','content':'好'}, {'role':'user','content':current}])
        self.assertEqual(result[0]['content'],'我爱散步')
        self.assertIn('current',result[-1]['content'])

    async def test_explicit_current_weather_uses_real_adapter_without_model(self):
        from app.latency import current_weather_city
        from app.agent import AgentService
        from app.plans import PlanStore
        self.assertEqual(current_weather_city('请查北京现在的天气。'),'北京')
        for text in ['请查这里现在的天气','北京明天的天气','北京现在天气和路线','北京现在天气适合穿什么']:
            self.assertIsNone(current_weather_city(text))
        with tempfile.TemporaryDirectory() as temp:
            service=AsyncMock();service.stores={}
            agent=AgentService(service,PlanStore(Path(temp)/'plans.db'),data_dir=Path(temp)/'agent')
            agent._tool=AsyncMock(return_value={'weather':[{'city':'北京','weather':'晴','temperature':'14','reporttime':'actual'}]})
            with patch('app.agent.build_runtime') as network:
                answer=await agent._run('a',agent._session('a'),'请查北京现在的天气。',[],[])
            network.assert_not_called()
            self.assertIn('actual',answer)
            agent._tool.assert_awaited_once()

    def test_proxy_is_disabled_by_default_and_can_be_explicitly_enabled(self):
        for enabled in (False,True):
            p=self.provider([])
            p.trust_env=enabled
            with patch('app.latency.httpx.AsyncClient') as transport, patch('openai.AsyncOpenAI'):
                p._build_client()
            self.assertIs(transport.call_args.kwargs['trust_env'],enabled)
            self.assertFalse(transport.call_args.kwargs['follow_redirects'])

    def test_archived_summary_survives_compact_system_policy(self):
        p=self.provider([])
        result=p.prepare([{'role':'system','content':'Generic instructions\n[Archived Context Summary]\n用户喜欢散步'}])
        self.assertIn('用户喜欢散步',result[0]['content'])
