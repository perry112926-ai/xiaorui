"""Full AgentService synthetic lifecycle. Only local profile/task tools allowed.

Cloud model calls are real; all service tools are blocked by the probe boundary.
"""
import asyncio
import json
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
from app.agent import AgentService
from app.plans import PlanStore
from app.contact_events import contact_reply_mode

async def run(output):
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);rows=[];blocked=[]
        def make():
            agent=AgentService(SimpleNamespace(stores={}),PlanStore(root/'plans.db'),data_dir=root/'agent')
            original=agent._tool
            async def guarded(session,owner,name,args,events):
                if name not in {'personal_profile','task_records'}:
                    blocked.append(name);return {'error':'验收环境禁止外部服务操作，请只进行对话。'}
                return await original(session,owner,name,args,events)
            agent._tool=guarded
            return agent
        mode=contact_reply_mode.set('text')
        try:
            script=[('今天我决定以后最喜欢的戏曲是京剧。','京剧'),('请不要忘记我喜欢京剧。',None),('我喜欢哪种戏曲？','京剧'),('我喜欢的饮品是热茶。','热茶'),('你为什么会忘记事情？',None),('我喜欢的饮品是什么？','热茶'),('请忘记我的京剧爱好。',None),('我还喜欢什么饮品？','热茶'),('我喜欢哪种戏曲？不记得就说不记得。',None)]
            for text,expected in script:
                agent=make();response=await agent.chat('capability-user',text)
                rows.append({'input':text,'answer':response['text'],'trace':response['trace'],'expected':expected,'expected_present':expected is None or (expected in response['text'] and not any(word in response['text'] for word in ('没有记','没记','不记得','没存','没正式','请记住','还没有'))), 'preferences':agent.memory.recall('capability-user',agent._session('capability-user').forget_epoch,'偏好')['preferences']})
            checks={'expected_answers':all(r['expected_present'] for r in rows),'forgotten_not_recalled':bool(re.search(r'不记得|没有.*记录|没.*记|不知道',rows[-1]['answer'])) and not bool(re.search(r'您(?:最)?喜欢(?:的戏曲)?(?:是)?京剧',rows[-1]['answer'])) and not any('京剧' in f['evidence'] for f in rows[-1]['preferences']), 'unrelated_preference_preserved':any('热茶' in f['evidence'] for f in rows[7]['preferences']), 'automatic_save_not_reasked':not any(re.search(r'要不要.{0,10}(?:记|保存)|(?:请说|说一句|重复说).{0,8}请记住',r['answer']) for r in rows),'no_receipt_prefix':all(not r['answer'].startswith('收到') for r in rows),'no_external_tool_executed':True}
        finally:contact_reply_mode.reset(mode)
        report={'passed':all(checks.values()),'checks':checks,'blocked_tool_attempts':blocked,'turns':rows};output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(checks,ensure_ascii=False))
        return report['passed']

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(0 if asyncio.run(run(a.output)) else 1)
