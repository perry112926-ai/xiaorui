"""Deprecated pickup API facade. All authorization/state lives in ActionManager.

Old SQLite rows are imported once, idempotently. Original rows remain untouched
for rollback/audit; no legacy code issues a remote write or owns a state machine.
"""
import copy
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from app.actions import ActionError, ActionManager
from app.summaries import normalize_summary

PlanError=ActionError


def fingerprint(request):
    return hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class PlanStore:
    def __init__(self,path,*,recover_running=True):
        self.path=Path(path)
        target=self.path
        if self.path.exists():
            with sqlite3.connect(self.path) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gateway_binding'").fetchone():
                    row=db.execute('SELECT path FROM gateway_binding WHERE id=1').fetchone()
                    if row:
                        target=Path(row[0]).resolve()
                        if not target.is_relative_to(self.path.parent.resolve()):raise PlanError('无效的交易数据迁移目标。')
        self.manager=ActionManager(target)
        self._import_old_rows()
        if recover_running:self.recover_interrupted()

    def _import_old_rows(self):
        with sqlite3.connect(self.path) as source:
            if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='plans'").fetchone():return
            rows=source.execute('SELECT owner,body FROM plans').fetchall()
        with self.manager.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for owner,body in rows:
                old=json.loads(body)
                digest=fingerprint(old)
                existing=db.execute('SELECT owner,body FROM actions WHERE id=?',(old['id'],)).fetchone()
                if existing:
                    if existing['owner']!=owner:raise PlanError('交易记录迁移冲突。')
                    current=json.loads(existing['body'])
                    previous=current.get('legacy_source_digest')
                    if previous and previous!=digest:
                        # An old process changed the archive after import. Do not
                        # treat either old authorization as current or replay it.
                        risky=current['status'] in self.manager.BUSY|{'created'} or old['status'] in self.manager.BUSY|{'created'}
                        current.update(status='unknown' if risky else 'superseded',expires_at=0,
                            error='检测到旧版记录在迁移后变化，请核查官方订单；未自动重试。',legacy_source_digest=digest)
                        self.manager._write(db,owner,current)
                    continue
                payload=old['request']
                request={'legacy_pickup':True,'payload':payload,'display_summary':normalize_summary(old['summary'])}
                plan={**old,'provider':'mcd','action':'create','request':request,'summary_version':1,
                      'summary':normalize_summary(old['summary']),'created_at':old.get('created_at',time.time()),
                      'comparison':{'payload':payload,'amount_cents':old['amount_cents']},
                      'request_hash':fingerprint(request),'legacy_source_digest':digest,'order':old.get('order'),'error':old.get('error')}
                if old.get('request_hash') and old['request_hash']!=fingerprint(payload):
                    plan.update(status='failed',error='旧方案内容校验失败，请重新生成。')
                self.manager._write(db,owner,plan)

    def bind_actions(self,manager):
        if manager is self.manager:return
        with self.manager.connect() as source,manager.connect() as target:
            target.execute('BEGIN IMMEDIATE')
            for row in source.execute('SELECT owner,body FROM actions').fetchall():
                existing=target.execute('SELECT owner FROM actions WHERE id=?',(json.loads(row['body'])['id'],)).fetchone()
                if existing and existing['owner']!=row['owner']:raise PlanError('交易记录迁移冲突。')
                if not existing:manager._write(target,row['owner'],json.loads(row['body']))
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS gateway_binding (id INTEGER PRIMARY KEY CHECK(id=1), path TEXT NOT NULL)')
            db.execute('INSERT OR REPLACE INTO gateway_binding VALUES (1,?)',(str(manager.path.resolve()),))
        self.manager=manager

    def recover_interrupted(self):
        self.manager.recover_interrupted()

    def connect(self):
        return self.manager.connect()

    @staticmethod
    def public(plan):
        keys={'id','version','status','amount_cents','summary','expires_at','confirmation_token','order','error',
              'provider','action','execution_enabled','confirmation_text','created_at','summary_version'}
        result={k:copy.deepcopy(v) for k,v in plan.items() if k in keys}
        summary=normalize_summary(result.get('summary',{}))
        # HTTP compatibility only: stored summaries and modern ActionManager
        # responses remain canonical. Older pickup pages expect these aliases.
        for canonical,old in {'store':'store_name','address':'store_address','product':'product_name','fulfillment':'take_way'}.items():
            if canonical in summary:summary[old]=summary[canonical]
        result['summary']=summary
        return result

    def create(self,owner,prepared):
        request={'legacy_pickup':True,'payload':copy.deepcopy(prepared['request']),
                 'display_summary':normalize_summary(prepared['summary'])}
        return self.public(self.manager.prepare(owner,'mcd','create',request,{
            'request':request,'summary':request['display_summary'],'amount_cents':prepared['amount_cents'],
            'comparison':{'payload':request['payload'],'amount_cents':prepared['amount_cents']}}))

    def get(self,plan_id,owner):
        p=self.manager.get(owner,plan_id)
        if p['status'] in self.manager.REVIEW and time.time()>p['expires_at']:
            p=self.manager._update(owner,plan_id,status='expired')
        return self.public(self.manager.public(p))

    def cancel(self,plan_id,owner):
        return self.public(self.manager.cancel_local(owner,plan_id))

    def update(self,plan_id,owner,**fields):
        # Kept for administrative/test compatibility, not used by HTTP handlers.
        if 'request' in fields:
            previous=self.manager.get(owner,plan_id)['request']
            fields['request']={**previous,'payload':fields['request']}
        return self.public(self.manager.public(self.manager._update(owner,plan_id,**fields)))

    def claim(self,plan_id,owner,version,token):
        return self.manager.claim(owner,plan_id,version,token,'确认下单',check_enabled=False)

    async def confirm(self,service,owner,plan_id,version,token,text,*,enabled):
        from app.legacy_pickup import LegacyPickupAdapter
        # Standalone old API users still execute through the unified gateway.
        # In AgentService this manager already routes modern and legacy requests.
        adapter=self.manager.adapters.get('mcd')
        if adapter is None:
            self.manager.register('mcd',LegacyPickupAdapter(service))
        if not enabled:raise PlanError('当前仅核价，真实下单尚未开启。')
        return self.public(await self.manager.confirm(owner,plan_id,version,token,text))
