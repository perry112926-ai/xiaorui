"""Synthetic personal memory lifecycle through real model and application."""
import asyncio
import json
import tempfile
from pathlib import Path
from app.agent import AgentService
from app.mcd import McdService
from app.plans import PlanStore
from app.contact_events import contact_reply_mode

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        def agent():return AgentService(McdService(),PlanStore(root/'plans.db'),data_dir=root/'agent')
        a=agent();owner='memory-live';mode=contact_reply_mode.set('text');reports=[]
        try:
            for text,expected,absent in [('我平时最喜欢的休闲活动是听越剧。','越剧',None),('我最喜欢什么休闲活动？','越剧',None),('后来口味变了，我现在最喜欢的休闲活动是看京剧，不再听越剧。','京剧',None),('我的休闲活动喜好现在是什么？','京剧',None),('请忘记我的休闲活动喜好。',None,None)]:
                a=agent()  # verify disk persistence each turn
                r=await a.chat(owner,text)
                state=a.memory.recall(owner,a._session(owner).forget_epoch,'休闲活动')['preferences']
                reports.append({'input':text,'answer':r['text'],'preferences':state,'expected_present':expected is None or expected in r['text']})
            a=agent();r=await a.chat(owner,'我的休闲活动喜好是什么？不记得就直说。')
            reports.append({'input':'after forgetting','answer':r['text'],'not_recalled':not any(x in r['text'] for x in ('越剧','京剧')),'recall':a.memory.recall(owner,a._session(owner).forget_epoch,'休闲活动')})
        finally:contact_reply_mode.reset(mode)
        checks={'answers':all(r.get('expected_present',True) for r in reports), 'automatic_memory':bool(reports[0]['preferences']), 'updated':bool(reports[2]['preferences']) and 'Peking' in reports[2]['preferences'][0]['value'], 'question_not_evidence':all('？' not in f['evidence'] for r in reports for f in r.get('preferences',[])), 'forgotten':reports[-1]['not_recalled'], 'no_receipt_prefix':all(not r['answer'].startswith('收到') for r in reports)}
        print(json.dumps({'checks':checks,'passed':all(checks.values()),'turns':reports},ensure_ascii=False,indent=2))
        if not all(checks.values()): raise SystemExit(1)
if __name__=='__main__':asyncio.run(run())
