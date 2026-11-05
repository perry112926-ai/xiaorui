import unittest
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from app.didi_scenario import DidiScenario


def estimate(trace='new',price='52'):
    return {'traceId':trace,'items':[{'productName':'快车','productCategory':'1','priceText':price}],
            'from':{'name':'真实上车点','longitude':116.3,'latitude':39.9},
            'to':{'name':'真实下车点','longitude':116.4,'latitude':39.9}}


class DidiScenarioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider=SimpleNamespace(call=AsyncMock(),call_confirmed=AsyncMock())
        self.manager=Mock()
        self.scenario=DidiScenario(self.manager,self.provider)
        self.session=SimpleNamespace(services={})
        self.request={'route':{'from_lng':'116.3','from_lat':'39.9','from_name':'起点',
            'to_lng':'116.4','to_lat':'39.9','to_name':'终点'},'product_category':'1'}

    async def dispatch(self,name,args):
        return await self.scenario.dispatch(self.session,'owner',name,args,[])

    async def test_prepare_requires_actual_candidates_and_no_mutation(self):
        result=await self.dispatch('didi_prepare_ride',{'vehicle_index':1})
        self.assertIn('error',result)
        self.provider.call_confirmed.assert_not_awaited()
        self.manager.prepare.assert_not_called()

    async def test_selection_reuses_recent_estimate_but_confirmation_quote_is_fresh(self):
        cached=dict(estimate('cached'),received_at=time.time())
        self.session.services={'didi':{'route':self.request['route'],'estimate':cached}}
        result=await self.dispatch('didi_prepare_ride',{'vehicle_index':1})
        self.assertIn('plan',result)
        self.provider.call.assert_not_awaited()
        request=self.manager.prepare.call_args.kwargs['request']
        self.assertEqual(request['estimate_trace_id'],'cached')
        self.provider.call.return_value=estimate('fresh')
        fresh=await self.scenario.quote('create',request)
        self.provider.call.assert_awaited_once_with('taxi_estimate',self.request['route'])
        self.assertEqual(fresh['request']['estimate_trace_id'],'fresh')
        self.provider.call_confirmed.assert_not_awaited()

    async def test_old_selection_estimate_is_not_reused(self):
        self.session.services={'didi':{'route':self.request['route'],
            'estimate':dict(estimate('old'),received_at=time.time()-31)}}
        self.provider.call.return_value=estimate('new')
        result=await self.dispatch('didi_prepare_ride',{'vehicle_index':1})
        self.assertIn('plan',result)
        self.provider.call.assert_awaited_once()
        self.assertEqual(self.manager.prepare.call_args.kwargs['request']['estimate_trace_id'],'new')

    async def test_quote_trace_refresh_does_not_change_comparison_but_price_does(self):
        self.provider.call.side_effect=[estimate('one'),estimate('two'),estimate('three','53')]
        one=await self.scenario.quote('create',self.request)
        two=await self.scenario.quote('create',self.request)
        three=await self.scenario.quote('create',self.request)
        self.assertEqual(one['comparison'],two['comparison'])
        self.assertNotEqual(one['request']['estimate_trace_id'],two['request']['estimate_trace_id'])
        self.assertNotEqual(two['comparison'],three['comparison'])
        self.assertEqual(one['summary']['origin'],'真实上车点')
        self.provider.call_confirmed.assert_not_awaited()

    async def test_unknown_cancellation_fee_does_not_prepare_or_cancel(self):
        self.manager.get.return_value={'provider':'didi','action':'create','order':{'order_id':'unit'}}
        self.provider.call.return_value={'statusCode':1,'statusText':'已接单'}
        result=await self.dispatch('didi_prepare_cancel',{'action_id':'local'})
        self.assertIn('error',result)
        self.assertIn('取消费',result['error'])
        self.manager.prepare.assert_not_called()
        self.provider.call_confirmed.assert_not_awaited()

    async def test_explicit_cancellation_ineligibility_overrides_zero_fee(self):
        self.manager.get.return_value={'provider':'didi','action':'create','order':{'order_id':'unit'}}
        self.provider.call.return_value={'statusCode':1,'canCancel':False,'cancelFee':0}
        result=await self.dispatch('didi_prepare_cancel',{'action_id':'local'})
        self.assertIn('不可取消',result['error'])
        self.manager.prepare.assert_not_called()
        self.provider.call_confirmed.assert_not_awaited()

    async def test_foreign_record_cannot_query_provider(self):
        self.manager.get.side_effect=ValueError('not owner')
        result=await self.dispatch('didi_query_ride',{'action_id':'foreign'})
        self.assertIn('error',result)
        self.provider.call.assert_not_awaited()

    async def test_query_redacts_phone_and_routes(self):
        self.provider.call.return_value={'statusCode':1,'driver':{'name':'司机','carPlate':'测试车牌','phone':'private'},'routes':['private']}
        result=await self.scenario.query_order('unit')
        self.assertNotIn('phone',str(result));self.assertNotIn('routes',result)
        self.assertEqual(result['driver']['carPlate'],'测试车牌')

    async def test_failed_new_place_search_clears_old_quote(self):
        self.session.services={'didi':{'origin':[{'old':True}],'route':self.request['route'],'estimate':estimate()}}
        self.provider.call.side_effect=RuntimeError('private network error')
        result=await self.dispatch('didi_search_places',{'purpose':'origin','keyword':'新地点'})
        self.assertIn('error',result)
        self.assertNotIn('estimate',self.session.services['didi'])
        self.assertNotIn('origin',self.session.services['didi'])

    async def test_execute_uses_only_requoted_request_and_omits_account(self):
        self.provider.call_confirmed.return_value={'orderId':'unit','status':0,'phoneNumberSuffix':'private'}
        result=await self.scenario.execute('create',dict(self.request,estimate_trace_id='fresh'))
        self.provider.call_confirmed.assert_awaited_once_with('taxi_create_order',{'product_category':'1','estimate_trace_id':'fresh'})
        self.assertEqual(result['order_id'],'unit')
        self.assertNotIn('phoneNumberSuffix',result)

    async def test_boolean_index_is_rejected(self):
        self.assertIn('error',await self.dispatch('didi_prepare_ride',{'vehicle_index':True}))
        self.provider.call.assert_not_awaited()

    async def test_unknown_outcome_retains_response_for_private_reconciliation(self):
        from app.didi_scenario import DidiOutcomeUnknown
        self.provider.call_confirmed.return_value={'status':'pending','diagnostic':'unit'}
        with self.assertRaises(DidiOutcomeUnknown) as caught:
            await self.scenario.execute('create',dict(self.request,estimate_trace_id='fresh'))
        self.assertEqual(caught.exception.provider_response,{'status':'pending','diagnostic':'unit'})
        self.provider.call_confirmed.assert_awaited_once()

    async def test_comparison_ignores_endpoint_incidental_fields(self):
        one=estimate('one');two=estimate('two')
        one['from']['eta']='3';two['from']['eta']='4'
        self.provider.call.side_effect=[one,two]
        a=await self.scenario.quote('create',self.request)
        b=await self.scenario.quote('create',self.request)
        self.assertEqual(a['comparison'],b['comparison'])
