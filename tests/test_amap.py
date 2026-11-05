import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
import httpx
from app.amap import Amap,SCHEMAS,accessibility_boundary,weather_precision_boundary


class AmapTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_location_owner_city_and_expiry(self):
        point={'longitude':116.4,'latitude':39.9,'accuracy':20,'received_at':time.time()}
        client=Amap(location_provider=lambda owner:point if owner=='a' else None)
        client.get=AsyncMock(return_value={'regeocode':{'formatted_address':'北京市公开测试地标',
            'addressComponent':{'city':[],'province':'北京市'}}})
        session=SimpleNamespace(services={})
        other=await client.dispatch(session,'amap_current_location',{},owner='b')
        self.assertTrue(other['needs_location']);client.get.assert_not_awaited()
        result=await client.dispatch(session,'amap_current_location',{},owner='a')
        self.assertEqual(result['places'][0]['city'],'北京市')
        self.assertEqual(client.get.call_args.args[1]['location'],'116.400000,39.900000')
        session.services['amap']['origin'][0]['expires_at']=time.time()-1
        result=await client.dispatch(session,'amap_nearby',{'keyword':'厕所','center_index':1})
        self.assertIn('过期',result['error'])
        session.services['amap']['destination']=[{'name':'B','location':'116.41,39.91','city':'北京'}]
        client.get.reset_mock()
        result=await client.dispatch(session,'amap_route',{'origin_index':1,'destination_index':1})
        self.assertIn('过期',result['error']);client.get.assert_not_awaited()
    async def test_hourly_weather_does_not_invent_probability(self):
        result=weather_precision_boundary('北京今晚八点整下不下雨？能精确到小时吗？')
        self.assertIn('没有逐小时',result)
        self.assertNotIn('大概率',result)
        self.assertIsNone(weather_precision_boundary('北京明天天气怎么样'))
    async def test_accessibility_guarantees_do_not_generate_specific_exits(self):
        result=accessibility_boundary('国家博物馆到天安门东地铁站，保证轮椅全程无台阶')
        self.assertIn('无法核实',result)
        self.assertNotIn('D西南口',result)
        self.assertIsNone(accessibility_boundary('北京西站到国家博物馆怎么走'))
    async def test_missing_key_never_sends_request(self):
        with patch.dict('os.environ',{'AMAP_KEY':''}),patch('app.amap.dotenv_values',return_value={}):
            result=await Amap().dispatch(SimpleNamespace(services={}),'amap_weather',{'city':'北京'})
        self.assertIn('AMAP_KEY',result['error'])

    async def test_official_endpoint_key_and_service_refusal(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'status':'0','info':'sensitive response test-key'})
        client=Amap(lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw))
        with patch.dict('os.environ',{'AMAP_KEY':'test-key'}):
            with self.assertRaisesRegex(ValueError,'权限') as result:
                await client.get('/v3/geocode/geo',{'address':'北京'})
            self.assertNotIn('test-key',str(result.exception))
        self.assertEqual(requests[0].url.host,'restapi.amap.com')
        self.assertEqual(requests[0].url.params['key'],'test-key')
        with self.assertRaises(ValueError):await client.get('https://evil.invalid',{})

    async def test_candidate_selection_route_and_no_fabrication(self):
        client=Amap();session=SimpleNamespace(services={})
        client.get=AsyncMock(side_effect=[
            {'pois':[{'name':'起点','location':'116.4,39.9'}]},
            {'geocodes':[{'formatted_address':'终点','location':'116.41,39.91'}]},
            {'route':{'paths':[{'distance':'1500','cost':{'duration':'1200'},'steps':[{'instruction':'向北步行'}]}]}}])
        await client.dispatch(session,'amap_search_places',{'keyword':'起点','purpose':'origin'})
        await client.dispatch(session,'amap_geocode',{'address':'终点','purpose':'destination'})
        result=await client.dispatch(session,'amap_route',{'origin_index':1,'destination_index':1})
        self.assertEqual(result['routes'][0]['duration_seconds'],'1200')
        self.assertEqual(result['routes'][0]['instructions'],['向北步行'])
        self.assertTrue(result['map_url'].startswith('https://uri.amap.com/navigation?'))
        self.assertEqual(client.get.call_args.args[1]['origin'],'116.4,39.9')
        before=client.get.await_count
        bad=await client.dispatch(session,'amap_route',{'origin_index':True,'destination_index':1})
        self.assertIn('error',bad);self.assertEqual(client.get.await_count,before)

    async def test_failed_research_clears_old_candidates(self):
        client=Amap();client.get=AsyncMock(side_effect=ValueError('服务失败'))
        session=SimpleNamespace(services={'amap':{'origin':[{'name':'old'}]}})
        self.assertIn('error',await client.dispatch(session,'amap_search_places',{'keyword':'new','purpose':'origin'}))
        self.assertNotIn('origin',session.services['amap'])

    async def test_weather_uses_adcode_and_report_time(self):
        client=Amap();client.get=AsyncMock(side_effect=[{'geocodes':[{'adcode':'110000'}]},
            {'lives':[{'city':'北京','weather':'晴','temperature':'20','reporttime':'test-time'}]}])
        result=await client.dispatch(SimpleNamespace(services={}),'amap_weather',{'city':'北京'})
        self.assertEqual(result['weather'][0]['reporttime'],'test-time')
        self.assertEqual(client.get.call_args.args[1]['city'],'110000')

    async def test_tools_registered_and_allowed_in_query_mode(self):
        from app.skills import SCHEMAS as ALL
        from app.read_only import QUERY_TOOLS
        self.assertTrue(set(SCHEMAS)<=set(ALL))
        self.assertTrue(set(SCHEMAS)<=set(QUERY_TOOLS))

    async def test_forecast_has_dates_and_never_uses_lives_as_forecast(self):
        client=Amap();client.get=AsyncMock(side_effect=[{'geocodes':[{'adcode':'110000'}]},
            {'forecasts':[{'city':'北京','reporttime':'test-time','casts':[{'date':'2026-11-06','dayweather':'小雨'}]}]}])
        result=await client.dispatch(SimpleNamespace(services={}),'amap_weather',{'city':'北京','forecast':True})
        self.assertEqual(client.get.call_args.args[1]['extensions'],'all')
        self.assertEqual(result['forecasts'][0]['casts'][0]['date'],'2026-11-06')
        client.get=AsyncMock(side_effect=[{'geocodes':[{'adcode':'110000'}]},{'lives':[{'weather':'晴'}]}])
        result=await client.dispatch(SimpleNamespace(services={}),'amap_weather',{'city':'北京','forecast':True})
        self.assertIn('不能用实时天气',result['error'])

    async def test_empty_or_ambiguous_weather_is_not_success(self):
        for geo,data in (({'geocodes':[]},{}),({'geocodes':[{'adcode':'1'},{'adcode':'2'}]},{}),
                         ({'geocodes':[{'adcode':'1'}]},{'lives':[]})):
            client=Amap();client.get=AsyncMock(side_effect=[geo,data])
            result=await client.dispatch(SimpleNamespace(services={}),'amap_weather',{'city':'朝阳'})
            self.assertIn('error',result)

    async def test_nearby_requires_real_center_returns_straight_line_distance(self):
        client=Amap();client.get=AsyncMock(return_value={'pois':[{'name':'药店','location':'116.41,39.91','distance':'150'}]})
        session=SimpleNamespace(services={})
        self.assertIn('error',await client.dispatch(session,'amap_nearby',{'keyword':'药店','center_index':1}))
        client.get.assert_not_awaited()
        session.services={'amap':{'origin':[{'name':'公开地标','location':'116.4,39.9','city':'北京'}]}}
        result=await client.dispatch(session,'amap_nearby',{'keyword':'药店','center_index':1})
        self.assertEqual(result['places'][0]['distance_meters'],'150')
        self.assertIn('直线',result['note'])
        self.assertEqual(client.get.call_args.args[0],'/v3/place/around')
        self.assertEqual(client.get.call_args.args[1]['sortrule'],'distance')
        client.get.side_effect=ValueError('网络异常')
        self.assertIn('error',await client.dispatch(session,'amap_nearby',{'keyword':'药店','center_index':1}))
        self.assertNotIn('destination',session.services['amap'])

    async def test_transit_uses_official_lines_and_less_walking(self):
        client=Amap();client.get=AsyncMock(return_value={'route':{'transits':[{
            'distance':'5000','duration':'1800','walking_distance':'400','cost':'4',
            'segments':[{'walking':{'distance':'100'},'bus':{'buslines':[{
                'name':'测试线路','departure_stop':{'name':'起点站'},'arrival_stop':{'name':'终点站'},'via_num':'3'}]}}]}]}})
        session=SimpleNamespace(services={'amap':{
            'origin':[{'name':'起点','location':'116.4,39.9','city':'北京'}],
            'destination':[{'name':'终点','location':'116.41,39.91','city':'北京'}]}})
        result=await client.dispatch(session,'amap_route',{'origin_index':1,'destination_index':1,'mode':'transit'})
        self.assertEqual(client.get.call_args.args[1]['strategy'],3)
        self.assertEqual(result['routes'][0]['duration_seconds'],'1800')
        self.assertEqual(result['routes'][0]['walking_distance_meters'],'400')
        self.assertEqual(result['routes'][0]['legs'][1]['line'],'测试线路')
        self.assertEqual(result['routes'][0]['legs'][1]['ride_stops'],4)
        self.assertEqual(result['routes'][0]['legs'][1]['intermediate_stops'],'3')
        from urllib.parse import urlsplit,parse_qs
        link=urlsplit(result['map_url'])
        self.assertEqual(link.netloc,'uri.amap.com')
        self.assertEqual(parse_qs(link.query)['mode'],['bus'])
        self.assertEqual(parse_qs(link.query)['policy'],['2'])
        self.assertNotIn('key',parse_qs(link.query))
        self.assertIn('不保证',result['note'])
        client.get.return_value={'route':{'transits':[]}}
        self.assertIn('不能推测', (await client.dispatch(session,'amap_route',{'origin_index':1,'destination_index':1,'mode':'transit'}))['error'])

    async def test_transit_sorts_returned_options_and_alternatives_are_not_transfers(self):
        client=Amap();session=SimpleNamespace(services={'amap':{
            'origin':[{'name':'A','location':'116,39','city':'北京'}],
            'destination':[{'name':'B','location':'116.1,39','city':'北京'}]}})
        a={'walking_distance':'500','segments':[{'bus':{'buslines':[{'name':'A线','via_num':'0'},{'name':'B线','via_num':'1'}]}}]}
        b={'walking_distance':'100','segments':[{'bus':{'buslines':[{'name':'C线','via_num':'2'}]}}]}
        client.get=AsyncMock(return_value={'route':{'transits':[a,b]}})
        result=await client.dispatch(session,'amap_route',{'origin_index':1,'destination_index':1,'mode':'transit'})
        self.assertEqual(result['routes'][0]['walking_distance_meters'],'100')
        self.assertEqual(len(result['routes'][1]['legs']),1)
        self.assertEqual(result['routes'][1]['legs'][0]['ride_stops'],1)

    async def test_no_route_cross_session_and_bad_index_cannot_invent_result(self):
        client=Amap();client.get=AsyncMock()
        result=await client.dispatch(SimpleNamespace(services={}),'amap_route',{'origin_index':1,'destination_index':1})
        self.assertIn('error',result);client.get.assert_not_awaited()
        for args in ({'keyword':'药店','center_index':True},{'keyword':'药店','center_index':1,'radius':999999}):
            self.assertIn('error',await client.dispatch(SimpleNamespace(services={}),'amap_nearby',args))

    async def test_http_timeout_does_not_echo_credentials_or_retry(self):
        calls=[]
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('secret-key in request URL')
        client=Amap(lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw))
        with patch.dict('os.environ',{'AMAP_KEY':'secret-key'}):
            with self.assertRaises(ValueError) as error:await client.get('/v3/geocode/geo',{'address':'北京'})
        self.assertNotIn('secret-key',str(error.exception));self.assertEqual(len(calls),1)
