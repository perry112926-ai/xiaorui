import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from app.mcd_scenario import McdScenario


class CartBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls=[]
        self.create=AsyncMock()
        @asynccontextmanager
        async def connection():
            async def call(name,args):
                self.calls.append((name,args))
                if name=='query-meal-detail':return {'rounds':[]}
                if name=='calculate-price':return {'price':4400,'takeWayList':[{'code':'take','title':'外带'}]}
                raise AssertionError(name)
            yield call
        self.manager=Mock()
        self.manager.prepare.return_value={'id':'plan','status':'awaiting_confirmation'}
        self.scenario=McdScenario(self.manager,SimpleNamespace(_connection=connection,create_order=self.create))
        self.session=SimpleNamespace(services={'mcd':{'mode':'pickup','selected_store':{'code':'S'},
            'products':[{'code':'P','name':'麦香鱼'}],'cart':[]}})

    async def test_two_changes_and_checkout_produce_one_full_quote_without_order(self):
        result=await self.scenario.dispatch(self.session,'a','mcd_update_cart',{
            'operations':[{'action':'add','product_index':1},{'action':'update','line_index':1,'quantity':2}],
            'checkout':{'take_way_index':1}},[])
        self.assertIn('plan',result)
        self.assertEqual(len([n for n,a in self.calls if n=='calculate-price']),1)
        request=self.manager.prepare.call_args.kwargs['request']
        self.assertEqual(request['payload']['items'][0]['quantity'],2)
        self.create.assert_not_awaited()

    async def test_failed_batch_restores_cart_and_never_quotes_partial_result(self):
        result=await self.scenario.dispatch(self.session,'a','mcd_update_cart',{
            'operations':[{'action':'add','product_index':1},{'action':'remove','line_index':8}],
            'checkout':{}},[])
        self.assertIn('error',result)
        self.assertFalse(result['cart_changes_applied'])
        self.assertEqual(self.session.services['mcd']['cart'],[])
        self.assertEqual(self.calls,[])
        self.manager.prepare.assert_not_called()

    async def test_invalid_boolean_quantity_rejected_before_any_mutation(self):
        result=await self.scenario.dispatch(self.session,'a','mcd_update_cart',{
            'operations':[{'action':'add','product_index':1},{'action':'update','line_index':1,'quantity':True}]},[])
        self.assertIn('error',result)
        self.assertEqual(self.session.services['mcd']['cart'],[])

    async def test_quantity_only_update_preserves_existing_combo_choices(self):
        state=self.session.services['mcd']
        state['cart']=[{'product':state['products'][0],'quantity':1,'choices':[{'round_id':'R','code':'C'}]}]
        result=await self.scenario.dispatch(self.session,'a','mcd_update_cart',{
            'operations':[{'action':'update','line_index':1,'quantity':2}]},[])
        self.assertTrue(result['cart_changes_applied'])
        self.assertEqual(state['cart'][0]['choices'],[{'round_id':'R','code':'C'}])

    async def test_hosted_tool_keeps_unspecified_choices_through_nested_validation(self):
        from app.skills import build_tools
        state=self.session.services['mcd']
        state['cart']=[{'product':state['products'][0],'quantity':1,'choices':[{'round_id':'R','code':'C'}]}]
        async def dispatch(name,args):return await self.scenario.dispatch(self.session,'a',name,args,[])
        tool=next(t for t in build_tools(dispatch) if t.name=='mcd_update_cart')
        await tool.execute(operations=[{'action':'update','line_index':1,'quantity':2}])
        self.assertEqual(state['cart'][0]['choices'],[{'round_id':'R','code':'C'}])
