"""Compatibility adapter, using the same approval gateway as every other action."""
import copy
from app.summaries import normalize_summary

class LegacyPickupAdapter:
    def __init__(self, service):
        self.service=service

    async def quote(self, action, request):
        if action!='create':
            raise ValueError('Legacy pickup only supports creation')
        payload=copy.deepcopy(request['payload'])
        quote=await self.service.requote(payload)
        if payload.get('takeWayCode') not in quote['take_way_codes']:
            raise ValueError('取餐方式已变化，请重新选择。')
        return {'request':request,'summary':normalize_summary(request['display_summary']),
                'amount_cents':quote['amount_cents'],
                'comparison':{'payload':payload,'amount_cents':quote['amount_cents']}}

    async def execute(self, action, request):
        return await self.service.create_order(copy.deepcopy(request['payload']))
