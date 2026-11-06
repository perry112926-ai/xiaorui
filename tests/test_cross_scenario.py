import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.task_switching import cancel_mcd_order, turn_domain


class CrossScenarioTests(unittest.IsolatedAsyncioTestCase):
    def test_short_followups_follow_latest_task(self):
        cases = [
            ('给我点瑞幸', '改成自取吧', 'luckin'),
            ('帮我查北京到上海的机票', '继续', 'fliggy'),
            ('给我点瑞幸', '取消订单', 'luckin'),
            ('帮我打车去机场', '取消订单', 'didi'),
            ('麦当劳订单查一下', '瑞幸怎么走', 'amap'),
            ('给我点瑞幸', '麦当劳怎么走', 'amap'),
            ('给我点瑞幸', '麦当劳可以外卖吗', 'mcd'),
            ('帮我打车去医院', '查一下', 'didi'),
            ('北京现在天气怎么样', '继续', 'amap'),
            ('讲个故事', '第一份', None),
        ]
        for previous, followup, expected in cases:
            with self.subTest(previous=previous, followup=followup):
                history = [{'role': 'user', 'text': '点一份麦当劳'},
                           {'role': 'user', 'text': previous}]
                self.assertEqual(turn_domain(followup, history), expected)

    async def test_cancellation_with_multiple_merchants_asks_before_lookup(self):
        orders = [
            {'id': 'cab', 'provider': 'didi', 'action': 'create', 'order': {'order_id': 'cab-order'}},
            {'id': 'meal', 'provider': 'mcd', 'action': 'create', 'order': {'order_id': 'meal-order'}},
        ]
        lookup = AsyncMock(return_value={'order': {'orderStatus': '已取消'}})
        agent = SimpleNamespace(actions=SimpleNamespace(list=lambda _: orders), scenarios={
            'mcd': SimpleNamespace(dispatch=lookup),
        })
        session = SimpleNamespace(services={'luckin': {'products': ['other draft']}, 'mcd': {}},
                                  stores={}, meals=[])
        reply = await cancel_mcd_order(agent, session, 'owner', [])
        self.assertIn('哪家', reply)
        lookup.assert_not_awaited()
        reply = await cancel_mcd_order(agent, session, 'owner', [], explicit=True)
        self.assertIn('已取消', reply)
        self.assertEqual(lookup.call_args.args[3], {'plan_id': 'meal'})
        self.assertIn('luckin', session.services)


    def test_navigation_to_mcd_keeps_route_tools_available(self):
        from app.latency import tool_scope
        names = {'amap_route', 'amap_search_places', 'mcd_search_pickup'}
        self.assertIn('amap_route', tool_scope('麦当劳怎么走', {}, names))

    def test_mixed_flight_and_meal_request_keeps_both_tool_families(self):
        from app.latency import tool_scope
        names = {'fliggy_search_flights', 'mcd_search_pickup'}
        self.assertEqual(tool_scope('查机票，然后帮我点麦当劳', {}, names), names)
