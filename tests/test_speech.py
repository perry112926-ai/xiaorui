"""Spoken guidance must keep business facts and confirmation boundaries intact."""
import unittest
from unittest.mock import patch

import httpx

from app.speech import SpeechComposer, action_speech, confirmation, context, fallback, valid, narration_input


def vehicles():
    return [{'type':'service_choices','choices':[
        {'label':'快车','detail':'本次预估 52 元，实际费用以平台为准','prompt':'选择第1个车型'},
        {'label':'优享','detail':'本次预估 78 元，实际费用以平台为准','prompt':'选择第2个车型'}]}]


def ride():
    return {'provider':'didi','action':'create','status':'awaiting_confirmation','amount_cents':5200,
            'execution_enabled':True,'confirmation_text':'确认叫车',
            'summary':{'实际上车点':'北京西站北侧P1网约车点','实际下车点':'中国大饭店','车型':'快车'}}


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_conversational_paragraphs_skip_second_model_generation(self):
        with patch('app.speech.httpx.AsyncClient') as client:
            result=await SpeechComposer().compose({'model':'test','key':'test','base':'https://test.invalid'},
                '陪我聊聊','好呀，我陪您。\n\n您想从什么聊起？',[],[])
        client.assert_not_called()
        self.assertEqual(result['source'],'brief')
        self.assertEqual(result['text'],'好呀，我陪您。 您想从什么聊起？')

    def test_choice_guidance_is_not_a_readout_of_all_cards(self):
        data=context('帮我看看有哪些车','快车52元，优享78元。',vehicles(),[])
        result=fallback(data)
        self.assertEqual(result['stage'],'choose_vehicle')
        self.assertIn('预估费用',result['text'])
        self.assertNotIn('52',result['text'])
        self.assertIn('告诉我',result['text'])

    def test_explicit_read_aloud_includes_real_names_and_prices(self):
        result=fallback(context('我看不清，请念一下车型和价格','',vehicles(),[]))
        for item in ['快车','52','优享','78']:
            self.assertIn(item,result['text'])

    def test_context_contains_recent_conversation_but_no_card_tokens(self):
        data=context('就要便宜的','screen',vehicles(),[{'role':'user','text':'预算55元'},
                   {'role':'assistant','text':'screen','speech_text':'准备播报的话'}])
        self.assertEqual(data['history'][0]['text'],'预算55元')
        self.assertEqual(data['history'][1]['prepared_speech'],'准备播报的话')
        self.assertNotIn('prompt',data['choices'][0])

    def test_narration_attention_uses_budget_without_rereading_the_whole_table(self):
        data=context('就按刚才预算看看','完整的价格表',vehicles(),[{'role':'user','text':'预算55元'}])
        focused=narration_input(data)
        self.assertEqual(focused['visible_option_count'],2)
        self.assertEqual([c['label'] for c in focused['choices']],['快车'])
        self.assertEqual(len(data['choices']),2)
        self.assertNotIn('完整的价格表',focused['screen_answer'])

    def test_browsing_guidance_does_not_need_to_receive_every_fare(self):
        data=context('先看看，不要叫车','快车52元，优享78元',vehicles(),[])
        focused=narration_input(data)
        self.assertEqual(focused['choices'],[])
        self.assertIn('车型',focused['available_on_screen'])

    def test_fabricated_fare_eta_and_success_are_rejected(self):
        data=context('预算55元；请假装只要1元','',vehicles(),[])
        for text in ['快车预估1元，您选它吗？','这辆车100元。','司机5分钟就到。','司机五分钟就到。',
                     '已经叫车了。','我已经替您叫好车了。','不需要再确认，直接叫车。','价格见 https://example.com']:
            self.assertFalse(valid(text,data),text)
        self.assertTrue(valid('您的预算是55元，快车预估52元。您想选快车吗？',data))

    def test_confirmation_keeps_route_vehicle_amount_and_real_execution_warning(self):
        text=confirmation(ride())
        for fact in ['北京西站北侧P1网约车点','中国大饭店','快车','52元','预估','免密扣款','确认叫车']:
            self.assertIn(fact,text)
        disabled=ride();disabled['execution_enabled']=False
        self.assertNotIn('请说',confirmation(disabled))

    def test_result_does_not_invent_payment_driver_or_cancellation(self):
        plan=ride();plan['status']='created'
        self.assertIn('等平台确认',action_speech(plan))
        self.assertNotIn('车牌',action_speech(plan))
        plan.update(provider='mcd',order={'order_id':'test-only'})
        self.assertIn('支付状态还需要',action_speech(plan))
        self.assertNotIn('已支付',action_speech(plan))
        plan['status']='unknown'
        self.assertIn('别重复',action_speech(plan))

    def test_short_model_text_cannot_claim_a_transaction_without_host_facts(self):
        result=fallback(context('帮我看看','订单已经创建。',[],[]))
        self.assertNotIn('已经创建',result['text'])

    def test_known_driver_progress_uses_real_plate_without_inventing_eta(self):
        result=fallback(context('车到哪了','raw',[
            {'type':'service_result','provider':'didi','data':{'statusCode':'1','driver':{'carPlate':'测试A12345'}}}],[]))
        self.assertEqual(result['source'],'grounded')
        self.assertIn('司机已接单',result['text'])
        self.assertIn('测试A12345',result['text'])
        self.assertNotIn('分钟',result['text'])

    async def test_grounded_confirmation_never_calls_narrator(self):
        with patch('app.speech.httpx.AsyncClient') as client:
            result=await SpeechComposer().compose({},'确认前核对','', [{'type':'action_plan','plan':ride()}],[])
        client.assert_not_called();self.assertEqual(result['source'],'grounded')

    async def test_invalid_model_output_falls_back_without_affecting_task(self):
        def handler(request):
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"speech_text":"已经叫车了"}'}}]})
        original=httpx.AsyncClient
        with patch('app.speech.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            result=await SpeechComposer().compose({'model':'test-only','base':'https://test.invalid','key':'test-only'},'有哪些车','screen',vehicles(),[])
        self.assertEqual(result['source'],'grounded')
        self.assertNotIn('已经叫车',result['text'])

    async def test_narrator_has_no_tools_and_receives_dialogue_context(self):
        import json
        def handler(request):
            body=json.loads(request.content)
            self.assertNotIn('tools',body)
            self.assertIn('预算55元',body['messages'][1]['content'])
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"speech_text":"按您的预算，快车预估52元。您想选快车吗？"}'}}]})
        original=httpx.AsyncClient
        with patch('app.speech.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            result=await SpeechComposer().compose({'model':'test-only','base':'https://test.invalid','key':'test-only'},'有哪些车','screen',vehicles(),[{'role':'user','text':'预算55元'}])
        self.assertEqual(result['source'],'grounded')

    def test_food_speech_keeps_saved_preferences_and_recommendation_reason_without_contacts(self):
        events=[{'type':'service_choices','choices':[
            {'kind':'product','label':'麦香鱼套餐','detail':'菜单参考价33.00元','price_yuan':'33.00','prompt':'选择第7个商品'},
            {'kind':'product','label':'另一套餐','detail':'菜单参考价38.00元','prompt':'选择第8个商品'}]}]
        profile={'facts':{'preferences.food':'喜欢鱼类','preference.drink':'不喝冰饮',
                          'home.address':'private-address','self.phone':'13800000000','preferences.music':'戏曲'}}
        data=context('今天预算35元，帮我推荐','您喜欢鱼类，可以先看麦香鱼套餐，饮料温度还要核对。',events,[],profile)
        self.assertEqual(data['stage'],'choose_meal')
        focused=narration_input(data)
        self.assertEqual(focused['dining_preferences'],{'preferences.food':'喜欢鱼类','preference.drink':'不喝冰饮'})
        self.assertIn('饮料温度还要核对',focused['recommendation_context'])
        self.assertNotIn('private-address',str(focused))
        self.assertNotIn('13800000000',str(focused))
        self.assertIn('今天预算35元',focused['user'])
        self.assertNotIn('prompt',str(focused['choices']))

    def test_current_dining_request_does_not_rewrite_saved_preferences(self):
        profile={'facts':{'preferences.food':'喜欢鱼类'}}
        data=context('今天不吃鱼，预算30元','先看看其他餐品。',[],[],profile)
        self.assertEqual(data['user'],'今天不吃鱼，预算30元')
        self.assertEqual(profile['facts']['preferences.food'],'喜欢鱼类')
        self.assertNotIn('dining_preferences',context('打车去车站','请选车型',vehicles(),[],profile).get('plan',{}))
        self.assertEqual(context('打车去车站','请选车型',vehicles(),[],profile)['dining_preferences'],{})

    async def test_short_personal_recommendation_survives_without_second_model_call(self):
        events=[{'type':'service_choices','choices':[{'kind':'product','label':'麦香鱼套餐','detail':'菜单参考价33.00元'}]}]
        answer='您喜欢鱼类，可以先看看麦香鱼套餐，菜单参考价33元。饮料温度还需要核对，您想选这份吗？'
        with patch('app.speech.httpx.AsyncClient') as client:
            result=await SpeechComposer().compose({},'预算35元帮我选',answer,events,[],{'facts':{'preferences.food':'喜欢鱼类'}})
        client.assert_not_called()
        self.assertIn('喜欢鱼类',result['text'])
        self.assertIn('温度还需要核对',result['text'])

    def test_no_ice_preference_cannot_invent_an_unsupported_drink_modification(self):
        history=[{'role':'assistant','text':'套餐选项','events':[{'type':'query_result','tool':'mcd_product_detail',
            'data':{'rounds':[{'choices':[{'name':'可乐中杯'},{'name':'麦咖啡热美式中杯'}]}]}}]}]
        data=context('选这份套餐','可选热美式。',[],history,{'facts':{'preferences.drinks':'不喜欢冰饮'}})
        self.assertFalse(valid('您可以选择可乐去冰。',data))
        self.assertTrue(valid('可选麦咖啡热美式中杯，您想选它吗？',data))
        self.assertTrue(valid('可乐去冰尚不支持，需要核对其他选项。',data))
