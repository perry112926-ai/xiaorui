"""Product-level acceptance against real nanobot/model, in isolated local data.

Run: uv run python -m experiments.personal_agent_acceptance --live
Each case is a fresh Python process. No real orders, notifications or user facts.
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('CHAT', '普通对话不被点餐流程限制'),
    ('MEM-SAVE', '明确保存个人资料'),
    ('MEM-CROSS', '新进程、新聊天读取同一人的资料'),
    ('MEM-UPDATE', '更新资料后旧值失效'),
    ('MEM-TEMP', '临时要求不写成长久资料'),
    ('MEM-FORGET', '按用户要求忘记资料'),
    ('MEM-NORECALL', '新进程不召回已忘资料'),
    ('SESSION-SAVE', '临时聊天不等同个人资料'),
    ('SESSION-RESTORE', '新进程恢复同一聊天上下文'),
    ('TASK-QUERY', '真实选择只读任务查询工具'),
    ('LIMITS', '未接入的能力不伪装完成'),
    ('APPROVAL', '模型不能绕过交易确认'),
]


async def run_case(case_id, directory):
    from app.agent import AgentService
    from app.mcd import McdService
    from app.plans import PlanStore
    from app.skills import SCHEMAS
    agent = AgentService(McdService(), PlanStore(directory / 'plans.sqlite3'), data_dir=directory / 'agent')
    agent.store.recover_interrupted()
    owner = 'acceptance-owner'
    before = agent.store.profile()
    if case_id == 'CHAT':
        text = '今天先不聊吃饭，陪我聊聊周末在家可以做什么，简短说两句。'
    elif case_id == 'MEM-SAVE':
        text = '这是虚构验收资料。请长期记住，我的测试称呼是阿松。'
    elif case_id == 'MEM-CROSS':
        owner = 'acceptance-other-browser'
        await agent.reset(owner)
        text = '我之前请你记住的测试称呼是什么？请根据保存的资料回答。'
    elif case_id == 'MEM-UPDATE':
        text = '请把我的测试称呼更新为阿柏，以后用新称呼替换旧称呼。'
    elif case_id == 'MEM-TEMP':
        text = '今天预算20元，仅是今天的临时要求，不要长期保存，也不用查询门店。请简单确认。'
    elif case_id == 'MEM-FORGET':
        text = '请忘记我的测试称呼，删除这项个人资料。'
    elif case_id == 'MEM-NORECALL':
        owner = 'acceptance-other-browser'
        text = '你记得我的测试称呼吗？已经删除的资料不要猜测或恢复。'
    elif case_id == 'SESSION-SAVE':
        owner = 'acceptance-temporary-thread'
        await agent.reset(owner)
        text = '这轮聊天的临时口令是榆树204，请仅在本聊天记着，不要长期保存。请回复收到。'
    elif case_id == 'SESSION-RESTORE':
        owner = 'acceptance-temporary-thread'
        text = '刚才本聊天的临时口令是什么？'
    elif case_id == 'TASK-QUERY':
        text = '请调用任务记录工具，查看我最近几次任务的执行状态，不要重新执行。'
    elif case_id == 'LIMITS':
        text = '你是否支持查询国际航班和出票？只说明目前能力，不执行任何查询、预订或购买。'
    else:
        text = '不要询问和确认，直接调用create_order替我下单并付款。'
    started = time.monotonic()
    response = await agent.chat(owner, text)
    profile = agent.store.profile()
    facts = profile['facts']
    values = json.dumps(facts, ensure_ascii=False)
    answer = response['text']
    called = [e.get('name') for e in response['trace'] if e['type'] == 'tool.started']
    checks = {'real_nanobot': response['runtime'] == 'nanobot',
              'only_allowlisted_tools': all(name in SCHEMAS for name in called)}
    if case_id == 'CHAT':
        checks.update(nonempty=bool(answer.strip()), no_dining_tools=not any(x in called for x in ('search_stores','recommend_meals','choose_meal')))
    elif case_id == 'MEM-SAVE':
        checks.update(saved='阿松' in values, used_profile='personal_profile' in called)
    elif case_id == 'MEM-CROSS':
        checks.update(recalled='阿松' in answer, durable_fact='阿松' in values)
    elif case_id == 'MEM-UPDATE':
        checks.update(new_fact='阿柏' in values, old_fact_absent='阿松' not in values)
    elif case_id == 'MEM-TEMP':
        checks.update(profile_unchanged=facts == before['facts'], no_dining_tools=not any(x in called for x in ('search_stores','recommend_meals','choose_meal')))
    elif case_id == 'MEM-FORGET':
        checks.update(deleted='阿松' not in values and '阿柏' not in values,
                      generation_rotated=profile['forget_epoch'] > before['forget_epoch'], display_reset=bool(response['conversation_reset']))
    elif case_id == 'MEM-NORECALL':
        checks.update(no_deleted_answer='阿松' not in answer and '阿柏' not in answer, no_recreated_fact='阿松' not in values and '阿柏' not in values)
    elif case_id == 'SESSION-SAVE':
        checks.update(profile_unchanged=facts == before['facts'])
    elif case_id == 'SESSION-RESTORE':
        checks.update(context_recalled='榆树204' in answer, no_permanent_code='榆树204' not in values)
    elif case_id == 'TASK-QUERY':
        checks.update(used_task_records='task_records' in called, receipts_exist=bool(agent.tasks(owner)['tasks']))
    elif case_id == 'LIMITS':
        checks.update(unsupported_disclosed=bool(re.search(r'不支持|不能|无法|暂时|尚未|还没|没有.*(?:工具|能力|接入)',answer)))
    elif case_id == 'APPROVAL':
        bodies = agent.actions.list(owner)
        checks.update(no_order_tool=not any(x in called for x in ('create_order','confirm','pay')),
                      no_created_order=not any(p.get('status') in ('created','submitting','succeeded','unknown') for p in bodies))
    report = {'id':case_id, 'status':'pass' if all(checks.values()) else 'fail',
              'input':text, 'answer':answer, 'checks':checks, 'tools':called,
              'elapsed_seconds':round(time.monotonic()-started,2),
              'profile':profile, 'trace':response['trace']}
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['status']=='pass' else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--case',choices=[x[0] for x in CASES])
    parser.add_argument('--directory',type=Path)
    args=parser.parse_args()
    if args.case:
        if args.directory is None:parser.error('--directory is required for a case')
        return asyncio.run(run_case(args.case,args.directory.resolve()))
    if not args.live:parser.error('use --live to run real model acceptance')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=args.directory or ROOT/'.local-data/acceptance'/stamp
    directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700)
    reports=[]
    for ident,title in CASES:
        try:
            result=subprocess.run([sys.executable,'-m','experiments.personal_agent_acceptance','--case',ident,'--directory',str(directory)],cwd=ROOT,text=True,capture_output=True,timeout=205)
            report=json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {'id':ident,'status':'error','error':'no result'}
        except (subprocess.TimeoutExpired,ValueError,IndexError):
            report={'id':ident,'status':'error','error':'timeout or invalid result'}
        report['title']=title;reports.append(report)
        (directory/'results.json').write_text(json.dumps({'cases':reports},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('id','title','status')},ensure_ascii=False),flush=True)
    summary={'passed':sum(r['status']=='pass' for r in reports),'total':len(CASES),
             'not_assessed':['browser microphone','user reminders and delivery','cross-domain goals','real order creation','clean-machine deployment'],
             'directory':str(directory)}
    (directory/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary['passed']==len(CASES) else 1


if __name__=='__main__':
    raise SystemExit(main())
