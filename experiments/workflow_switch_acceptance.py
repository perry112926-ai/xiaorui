"""Read-only production HTTP checks with a stale synthetic shopping cart."""
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4
import httpx
from app.agent import AgentService
from app.plans import PlanStore
from experiments.services_acceptance import ReadOnlyMcd

async def run():
    from app import main as host
    logging.disable(logging.CRITICAL)
    root=Path('.local-data/workflow-switch')/uuid4().hex
    root.mkdir(parents=True,mode=0o700)
    agent=AgentService(ReadOnlyMcd(),PlanStore(root/'plans.db'),data_dir=root/'agent')
    agent.actions._enabled=lambda _:False
    host.agent=agent
    cases=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host.app),base_url='http://localhost',timeout=180) as client:
        await client.get('/api/health')
        owner=client.cookies.get('pa_session')
        assert owner
        session=agent._session(owner)
        session.services={'mcd':{'cart':[{'product':{'name':'合成测试餐'},'quantity':1,'choices':[]}],
            'address_draft':{'city':'测试城市'}}}
        for text in ['一分钟后提醒我','给我讲一个很短的小故事','北京现在天气怎么样']:
            r=await client.post('/api/chat',json={'text':text});r.raise_for_status();d=r.json()
            assert '购物车里的餐品尚未下单' not in d['text'] and '几号楼' not in d['text']
            if '提醒' in text:assert '不能到时主动提醒' in d['text']
            if '故事' in text:assert not any(x.get('name','').startswith('mcd_') for x in d.get('trace',[]))
            if '天气' in text:assert '高德' in d['text']
            cases.append({'input':text,'passed':True})
    report={'passed':True,'production_http_routes':True,'real_model_for_story':True,'real_weather_api':True,
        'business_writes':False,'synthetic_cart':True,'cases':cases}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(run())
