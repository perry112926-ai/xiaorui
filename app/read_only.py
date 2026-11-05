"""Startup policy for the companion preview: XIAORUI_READ_ONLY=1."""
import os
import re
READ_ONLY = os.environ.get('XIAORUI_READ_ONLY', '').lower() in {'1', 'true', 'yes'}
QUERY_TOOLS = frozenset({
    'amap_search_places','amap_geocode','amap_route','amap_weather','amap_nearby','amap_current_location',
    'search_stores', 'recommend_meals', 'task_records',
    'mcd_search_pickup', 'mcd_delivery_addresses', 'mcd_delivery_stores',
    'mcd_menu', 'mcd_product_detail', 'mcd_orders', 'mcd_order_status',
})
QUERY_POSTS = frozenset({
    '/api/contact/messages', '/api/contact/calls', '/api/chat', '/api/chat/reset', '/api/voice/tts', '/api/voice/tts/prepare',
    '/api/mcd/stores', '/api/mcd/menu', '/api/mcd/detail', '/api/mcd/recommendations',
})
MESSAGE = '当前为只读查询模式，不能准备或执行下单、取消订单、叫车或支付。'


def query_post(path):
    return path in QUERY_POSTS or bool(re.fullmatch(r'/api/contact/calls/[a-f0-9-]{36}/end', path))
