"""Recommendations are buildable and priced before either text or call selection."""
import tempfile
import unittest
from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.actions import ActionManager
from app.mcd_scenario import McdScenario
from app.agent import choice_cards
from app.mcd_recommendations import resolve_selection


class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.manager=ActionManager(Path(self.temp.name)/'actions.db',enabled=lambda _:False)
        self.calls=[]
        self.menu={'bad':{'name':'坏规则单人套餐','image':'https://example.com/bad.png','currentPrice':'20'},
            'family':{'name':'四人套餐','image':'https://example.com/family.png'},
            'fish':{'name':'麦香鱼单人套餐','image':'https://example.com/fish.png','currentPrice':'30'},
            'chicken':{'name':'鸡肉单人套餐','image':'https://example.com/chicken.png','currentPrice':'25'}}
        self.rounds=[{'id':'drink','name':'选择饮料','minQuantity':1,'maxQuantity':1,'choices':[
            {'code':'cold','name':'冰美式','quantity':1},{'code':'hot','name':'热美式','quantity':0}]}]
        self.price=3000
        self.live_stores=[{'storeCode':'S','beCode':'B','businessStatus':True}]
        @asynccontextmanager
        async def connection():
            async def call(name,args):
                self.calls.append((name,args))
                if name=='query-meals':return {'meals':self.menu}
                if name=='query-meal-detail':return {'code':args['code'],'rounds':[] if args['code']=='simple' else self.rounds if args['code']!='bad' else [{'minQuantity':2,'maxQuantity':4}]}
                if name=='calculate-price':return {'price':self.price,'deliveryPrice':600,'takeWayList':[{'code':'pickup','title':'外带'}]}
                if name=='delivery-query-stores':return self.live_stores
                if name=='delivery-query-addresses':return [{'addressId':'A','fullAddress':'北京市测试楼','phone':'138****0000'}]
                raise AssertionError('unexpected tool '+name)
            yield call
        self.gateway=SimpleNamespace(_connection=connection,create_order=AsyncMock())
        self.scenario=McdScenario(self.manager,self.gateway);self.manager.register('mcd',self.scenario)
        self.session=SimpleNamespace(services={'mcd':{'mode':'delivery','selected_address':{'addressId':'A','address':'北京市测试楼'},
            'stores':[{'storeCode':'S','beCode':'B','storeName':'测试店','businessStatus':True}]}},display=[])

    async def dispatch(self,name,args):
        return await self.scenario.dispatch(self.session,'owner',name,args,[])

    async def test_only_supported_single_meals_with_photos_and_price_are_recommended(self):
        result=await self.dispatch('mcd_recommend_meals',{'avoid_iced_drinks':True,'budget_cents':3500})
        self.assertTrue(result['preflighted'])
        self.assertEqual(len(result['products']),2)
        for p in result['products']:
            self.assertIn('单人套餐',p['name']);self.assertNotIn('坏规则',p['name'])
            self.assertEqual(p['choices'],['热美式']);self.assertEqual(p['quoted_price_yuan'],'30.00')
        self.assertIsNone(self.manager.pending('owner'))
        self.gateway.create_order.assert_not_awaited()
        cards=choice_cards(result)
        self.assertEqual(cards[0]['price_kind'],'quote')
        self.assertTrue(cards[0]['recommendation_id'])
        self.assertIn('推荐套餐',cards[0]['prompt'])

    async def test_choose_goes_straight_to_full_final_confirmation_with_defaults(self):
        result=await self.dispatch('mcd_recommend_meals',{'budget_cents':3500})
        selected=result['products'][0]
        self.session.display=[{'role':'assistant','events':[{'type':'service_choices','choices':choice_cards(result)}]}]
        self.assertEqual(resolve_selection(self.session,'第二个'),result['products'][1]['recommendation_id'])
        self.assertEqual(resolve_selection(self.session,choice_cards(result)[0]['prompt']),selected['recommendation_id'])
        chosen=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':selected['recommendation_id']})
        self.assertFalse(chosen['order_created'])
        plan=chosen['plan'];self.assertEqual(plan['status'],'awaiting_confirmation')
        self.assertEqual(plan['summary']['choices'],['冰美式'])
        self.assertEqual(plan['summary']['tableware'],'需要餐具')
        self.assertEqual(plan['amount_cents'],3000)
        self.assertEqual(plan['summary']['phone_tail'],'0000')
        self.assertTrue(plan['summary']['image'].startswith('https://'))
        self.gateway.create_order.assert_not_awaited()

    async def test_changed_budget_invalid_choices_refresh_and_other_candidates_do_not_submit(self):
        result=await self.dispatch('mcd_recommend_meals',{'budget_cents':3500})
        id=result['products'][0]['recommendation_id']
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':id,'choice_overrides':{'drink':'fake'}})
        self.assertIn('error',r);self.assertIsNone(self.manager.pending('owner'))
        self.price=4000
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':id})
        self.assertIn('超过明确预算',r['error'])
        self.assertIsNone(self.manager.pending('owner'))
        result=await self.dispatch('mcd_recommend_meals',{'budget_cents':3500})
        self.assertEqual(result['products'],[])
        self.assertIn('error',await self.dispatch('mcd_choose_recommendation',{'recommendation_id':id}))

    async def test_explicit_drink_change_is_repriced_without_changing_other_defaults(self):
        r=await self.dispatch('mcd_recommend_meals',{})
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':r['products'][0]['recommendation_id'],'choice_overrides':{'drink':'hot'}})
        self.assertEqual(r['plan']['summary']['choices'],['热美式'])
        self.assertFalse(r['order_created'])

    async def test_explicit_quantity_tableware_and_remark_change_only_need_final_confirmation(self):
        r=await self.dispatch('mcd_recommend_meals',{})
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':r['products'][0]['recommendation_id'],
            'quantity':2,'need_tableware':False,'remark':'放前台'})
        self.assertEqual(r['plan']['summary']['quantity'],2)
        self.assertEqual(r['plan']['summary']['tableware'],'不需要餐具')
        self.assertEqual(r['plan']['summary']['remark'],'放前台')
        self.assertFalse(r['order_created'])

    async def test_only_explicit_final_confirmation_creates_one_order_with_payment_handoff(self):
        r=await self.dispatch('mcd_recommend_meals',{})
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':r['products'][0]['recommendation_id']})
        p=r['plan'];self.manager._enabled=lambda _:True
        self.gateway.create_order.return_value={'order_id':'fixture-order','payment_url':'https://example.invalid/test-payment'}
        self.gateway.create_order.assert_not_awaited()
        created=await self.manager.confirm('owner',p['id'],p['version'],p['confirmation_token'],'确认下单')
        self.assertEqual(created['status'],'created')
        self.assertEqual(created['order']['payment_url'],'https://example.invalid/test-payment')
        await self.manager.confirm('owner',p['id'],p['version'],p['confirmation_token'],'确认下单')
        self.gateway.create_order.assert_awaited_once()

    async def test_closed_delivery_store_is_replaced_before_presenting_choices(self):
        self.live_stores=[{'storeCode':'S','beCode':'B','businessStatus':False},
                          {'storeCode':'NEXT','beCode':'NB','storeName':'另一家可配送店','businessStatus':True}]
        r=await self.dispatch('mcd_recommend_meals',{})
        self.assertTrue(r['products'])
        self.assertEqual(self.session.services['mcd']['selected_store']['storeCode'],'NEXT')
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':r['products'][0]['recommendation_id']})
        self.assertEqual(r['plan']['summary']['store'],'另一家可配送店')
        self.gateway.create_order.assert_not_awaited()

    async def test_slow_selection_rechecks_same_available_meal_without_an_extra_choice(self):
        r=await self.dispatch('mcd_recommend_meals',{})
        old=r['products'][0]['recommendation_id']
        self.session.services['mcd']['recommended_meals'][0]['expires_at']=0
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':old})
        self.assertEqual(r['plan']['status'],'awaiting_confirmation')
        self.assertIn('重新核对',r['plan']['summary']['信息更新'])
        self.gateway.create_order.assert_not_awaited()

    async def test_bare_number_and_delegated_default_are_only_draft_selection(self):
        r=await self.dispatch('mcd_recommend_meals',{})
        cards=choice_cards(r)
        self.session.display=[{'role':'assistant','events':[{'type':'service_choices','choices':cards}]}]
        self.assertEqual(resolve_selection(self.session,'1'),cards[0]['recommendation_id'])
        self.assertEqual(resolve_selection(self.session,'第二份就行'),cards[1]['recommendation_id'])
        self.assertEqual(resolve_selection(self.session,'你帮我选'),cards[0]['recommendation_id'])
        self.assertIsNone(resolve_selection(self.session,'不要你帮我选'))
        self.assertIsNone(resolve_selection(self.session,'确认下单'))
        self.gateway.create_order.assert_not_awaited()

    async def test_adding_food_retains_known_tableware_remark_and_current_meal_in_cart(self):
        r=await self.dispatch('mcd_recommend_meals',{'need_tableware':False,'remark':'送前台'})
        await self.dispatch('mcd_choose_recommendation',{'recommendation_id':r['products'][0]['recommendation_id']})
        self.assertEqual(len(self.session.services['mcd']['cart']),1)
        await self.dispatch('mcd_cart',{'action':'add','product_index':2,'choices':[{'round_id':'drink','code':'hot'}]})
        result=await self.dispatch('mcd_prepare_cart',{})
        self.assertNotIn('needs_tableware',result)
        self.assertNotIn('error',result)
        self.assertEqual(result['plan']['summary']['tableware'],'不需要餐具')
        self.assertEqual(result['plan']['summary']['remark'],'送前台')
        self.assertEqual(len(result['plan']['summary']['images']),2)
        self.gateway.create_order.assert_not_awaited()

    async def test_explicit_single_item_request_does_not_force_a_combo_or_drink(self):
        self.menu['simple']={'name':'麦香鱼','image':'https://example.com/simple.png','currentPrice':'20'}
        r=await self.dispatch('mcd_recommend_meals',{'meal_type':'single','keyword':'麦香鱼'})
        self.assertEqual([p['name'] for p in r['products']],['麦香鱼'])
        card=choice_cards(r)[0]
        self.assertIn('推荐餐品',card['prompt'])
        self.session.display=[{'role':'assistant','events':[{'type':'service_choices','choices':[card]}]}]
        self.assertEqual(resolve_selection(self.session,card['prompt']),card['recommendation_id'])
        r=await self.dispatch('mcd_choose_recommendation',{'recommendation_id':card['recommendation_id']})
        self.assertEqual(r['plan']['summary']['choices'],[])
        self.gateway.create_order.assert_not_awaited()
