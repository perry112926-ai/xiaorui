import unittest
from app.model_views import project_result, project_services, project_plans
from app.summaries import normalize_summary

class ModelViewTests(unittest.TestCase):
    def test_unknown_and_nested_credentials_never_reach_model(self):
        raw={'accountToken':'SECRET','products':[{'name':'饮品','accountToken':'SECRET','attributes':[{'attribute':'温度','selected':['热'],'accountToken':'SECRET'}]}],
             'plan':{'id':'p','confirmation_token':'SECRET','request':{'anything':'SECRET'},'summary':{'product':'饮品','accountToken':'SECRET'},'order':{'order_id':'O','provider_response':{'token':'SECRET'}}}}
        result=project_result(raw,'luckin_search_products')
        self.assertNotIn('SECRET',str(result))
        self.assertEqual(result['products'][0]['attributes'][0]['selected'],['热'])
        self.assertEqual(result['plan']['order']['order_id'],'O')

    def test_allowed_scalar_cannot_contain_unknown_nested_object(self):
        self.assertIsNone(project_result({'name':{'accountToken':'SECRET'}},'mcd_menu')['name'])

    def test_state_has_separate_whitelist_and_preserves_live_candidates(self):
        state={'didi':{'origin':[{'display_name':'北京西站','location':{'lng':116,'lat':39,'token':'SECRET'}}],
                       'estimate':{'traceId':'SECRET','items':[{'productName':'快车','priceText':'35','accountToken':'SECRET'}]}}}
        result=project_services(state)
        self.assertNotIn('SECRET',str(result))
        self.assertEqual(result['didi']['origin'][0]['location'],{'lng':116,'lat':39})
        self.assertEqual(result['didi']['estimate']['items'][0]['priceText'],'35')

    def test_summary_aliases_are_read_compatible_and_canonical_values_win(self):
        self.assertEqual(normalize_summary({'车型':'快车','实际上车点':'旧点','origin':'新点'}),{'vehicle':'快车','origin':'新点'})
        self.assertEqual(project_plans([{'id':'p','summary':{'车型':'快车'},'confirmation_token':'SECRET'}])[0]['summary']['vehicle'],'快车')

    def test_route_projection_retains_actual_transit_stops_and_walking_instructions(self):
        value={'routes':[{'walking_distance_meters':'200','duration_seconds':'600','cost_yuan':'3',
            'legs':[{'type':'transit','departure_stop':'起点站','arrival_stop':'终点站','ride_stops':3,'accountToken':'SECRET'}],
            'instructions':['沿路向北步行']} ]}
        result=project_result(value,'amap_route')
        self.assertEqual(result['routes'][0]['legs'][0]['arrival_stop'],'终点站')
        self.assertEqual(result['routes'][0]['instructions'],['沿路向北步行'])
        self.assertNotIn('SECRET',str(result))
