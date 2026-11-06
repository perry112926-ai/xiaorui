"""Read-only production HTTP checks with a stale synthetic shopping cart."""
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4
import httpx
from app.agent import AgentService
from app.plans import PlanStore
from experiments.services_acceptance import ReadOnlyMcd, ReadOnlyOfficial

async def run():
    from app import main as host
    logging.disable(logging.CRITICAL)
    root=Path('.local-data/workflow-switch')/uuid4().hex
    root.mkdir(parents=True,mode=0o700)
    agent=AgentService(ReadOnlyMcd(),PlanStore(root/'plans.db'),data_dir=root/'agent')
    agent.actions._enabled=lambda _:False
    for provider in ('luckin', 'didi'):
        agent.scenarios[provider].provider=ReadOnlyOfficial(provider)
    host.agent=agent
    cases=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host.app),base_url='http://localhost',timeout=180) as client:
        await client.get('/api/health')
        owner=client.cookies.get('pa_session')
        assert owner
        session=agent._session(owner)
        session.services={'mcd':{'cart':[{'product':{'name':'合成测试餐'},'quantity':1,'choices':[]}],
            'address_draft':{'city':'测试城市'}}}
        for text in ['给我点一杯瑞幸到 E 世界楼下', '外卖可以吗',
                     '你刚才说的是哪个品牌？只回答品牌名',
                     '一分钟后提醒我', '给我讲一个很短的小故事', '北京现在天气怎么样',
                     '从北京中关村地铁站怎么走到瑞幸？先问我是哪家。']:
            r=await client.post('/api/chat',json={'text':text});r.raise_for_status();d=r.json()
            assert '购物车里的餐品尚未下单' not in d['text'] and '几号楼' not in d['text']
            assert not any(event['type'] in {'plan', 'action_plan'} for event in d['events'])
            if '外卖' in text or '点一杯瑞幸' in text:
                assert '瑞幸外送' in d['text'] and '麦当劳' not in d['text']
            if '哪个品牌' in text:
                assert '瑞幸' in d['text'] and '麦当劳' not in d['text']
            if '怎么走' in text:
                assert not any(x.get('name','').startswith(('mcd_', 'luckin_', 'didi_'))
                               for x in d.get('trace',[]))
                assert '门店' in d['text'] or '哪家' in d['text']
            if '提醒' in text:assert '不能到时主动提醒' in d['text']
            if '故事' in text:assert not any(x.get('name','').startswith('mcd_') for x in d.get('trace',[]))
            if '天气' in text:assert '高德' in d['text']
            cases.append({'input':text,'passed':True})
    report={'passed':True,'production_http_routes':True,'real_model_for_story':True,'real_weather_api':True,
        'business_writes':False,'synthetic_cart':True,'cases':cases}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(run())
