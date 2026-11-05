"""Durable, owner-bound approval gateway shared by all life scenarios.

Models can propose actions. Only a host-verified explicit user confirmation can
enter confirm(); adapters never receive a model-provided approval capability.
"""
import asyncio
import hashlib
import copy
import json
import os
import secrets
import sqlite3
import time
from app import read_only
from app.summaries import normalize_summary
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class ActionError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message, self.status = message, status


class ActionManager:
    PROVIDERS = {'luckin', 'mcd', 'didi'}
    REVIEW = {'awaiting_confirmation', 'needs_review'}
    BUSY = {'rechecking', 'submitting', 'unknown'}

    def __init__(self, path, *, enabled=None, external_blocks=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.adapters = {}
        self._enabled = enabled
        self.external_blocks = external_blocks
        self.locks = {}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, body TEXT NOT NULL)')
        self.path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def enabled(self, provider):
        if self._enabled is not None:
            return bool(self._enabled(provider))
        key = {'luckin':'LUCKIN_ORDER_ENABLED','mcd':'MCD_ORDER_ENABLED','didi':'DIDI_ORDER_ENABLED'}[provider]
        return str(os.environ.get(key, dotenv_values(ROOT/'.env').get(key) or 'false')).lower() == 'true'

    def blocked(self, provider):
        if self.external_blocks and self.external_blocks(provider):
            return '此前有一笔请求结果待核查，请先核查官方订单，暂不重复提交。'
        return None

    def register(self, provider, adapter):
        if provider not in self.PROVIDERS:
            raise ActionError('未知服务。')
        self.adapters[provider] = adapter

    @staticmethod
    def _read(db, owner, id):
        row = db.execute('SELECT body FROM actions WHERE id=? AND owner=?', (id, owner)).fetchone()
        if row is None:
            raise ActionError('找不到属于本次会话的操作记录。', 404)
        return json.loads(row['body'])

    @staticmethod
    def _write(db, owner, plan):
        encoded = json.dumps(plan, ensure_ascii=False)
        if len(encoded.encode()) > 1_000_000:
            raise ActionError('操作记录过大，请核查官方订单。')
        db.execute('INSERT OR REPLACE INTO actions VALUES (?,?,?)', (plan['id'], owner, encoded))

    def get(self, owner, id):
        with self.connect() as db:
            return self._read(db, owner, id)

    def list(self, owner, provider=None):
        with self.connect() as db:
            values = [json.loads(row['body']) for row in db.execute(
                'SELECT body FROM actions WHERE owner=? ORDER BY rowid DESC LIMIT 100', (owner,))]
        return [p for p in values if provider is None or p['provider'] == provider]

    def public(self, plan):
        result = {key: copy.deepcopy(plan[key]) for key in (
            'id','provider','action','summary','amount_cents','status','version',
            'confirmation_token','expires_at','created_at','order','error') if key in plan}
        result['summary'] = normalize_summary(result['summary'])
        result['summary_version'] = 1
        result['execution_enabled'] = plan['action']=='create_address' or self.enabled(plan['provider'])
        result['confirmation_text'] = self.phrase(plan)
        if result.get('order'):
            from app.model_views import project, UI_ORDER
            result['order'] = project(result['order'], UI_ORDER)
        return result

    @staticmethod
    def phrase(plan):
        if plan['action'] == 'create_address':
            return '确认新增地址'
        if plan['action'] == 'cancel':
            return '确认取消'
        return '确认叫车' if plan['provider'] == 'didi' else '确认下单'

    @staticmethod
    def _quote(quote):
        if not isinstance(quote, dict) or not isinstance(quote.get('request'),dict) or not isinstance(quote.get('summary'), dict) or not isinstance(quote.get('comparison'), dict):
            raise ActionError('缺少可核对的真实报价。')
        amount = quote.get('amount_cents')
        if type(amount) is not int or not 0 <= amount <= 1_000_000:
            raise ActionError('费用尚不明确，不能请求交易确认。')

    def invalidate_pending(self, owner, *, status='superseded'):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT body FROM actions WHERE owner=?', (owner,)).fetchall():
                plan = json.loads(row['body'])
                if plan['status'] in self.REVIEW or (plan['status']=='expired' and plan['provider']=='mcd' and plan['action']=='create'):
                    plan.update(status=status, confirmation_token=secrets.token_urlsafe(32))
                    self._write(db, owner, plan)

    def invalidate_all_pending(self):
        with self.connect() as db:
            owners = [row[0] for row in db.execute('SELECT DISTINCT owner FROM actions')]
        for owner in owners:
            self.invalidate_pending(owner)

    def prepare(self, owner, provider, action, request, quote):
        if read_only.READ_ONLY:
            raise ActionError(read_only.MESSAGE, 403)
        if provider not in self.PROVIDERS or (action not in {'create','cancel'} and not (provider=='mcd' and action=='create_address')):
            raise ActionError('不支持这项操作。')
        self._quote(quote)
        if action == 'create' and self.blocked(provider):
            raise ActionError(self.blocked(provider))
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = [json.loads(r['body']) for r in db.execute('SELECT body FROM actions WHERE owner=?', (owner,))]
            if any(p['provider'] == provider and p['status'] in self.BUSY for p in previous):
                raise ActionError('上一笔操作结果待核查或正在执行，不能重复提交。')
            for p in previous:
                if p['status'] in self.REVIEW or (p['status']=='expired' and p['provider']=='mcd' and p['action']=='create'):
                    p.update(status='superseded', confirmation_token=secrets.token_urlsafe(32))
                    self._write(db, owner, p)
            plan = {'id':secrets.token_urlsafe(24),'provider':provider,'action':action,
                    'status':'awaiting_confirmation','summary_version':1,'version':1,'confirmation_token':secrets.token_urlsafe(32),
                    'created_at':now,'expires_at':now+300,'request':copy.deepcopy(request),
                    'summary':normalize_summary(copy.deepcopy(quote['summary'])),'amount_cents':quote['amount_cents'],
                    'comparison':copy.deepcopy(quote['comparison']),'order':None,'error':None,
                    'request_hash':self.request_hash(request)}
            self._write(db, owner, plan)
        return self.public(plan)

    def cancel_local(self, owner, id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            plan = self._read(db, owner, id)
            if plan['status'] not in self.REVIEW | {'expired','superseded','cancelled'}:
                raise ActionError('只能取消未执行的本地方案；真实订单须另行核查取消条件。')
            plan.update(status='cancelled', confirmation_token=secrets.token_urlsafe(32))
            self._write(db, owner, plan)
        return self.public(plan)

    def pending(self, owner):
        return next((p for p in self.list(owner) if p['status'] in self.REVIEW), None)

    def recover_interrupted(self):
        with self.connect() as db:
            for row in db.execute('SELECT owner,body FROM actions').fetchall():
                p = json.loads(row['body'])
                if p['status'] in {'rechecking','submitting'}:
                    p.update(status='unknown' if p['status']=='submitting' else 'expired',
                             error='服务中断，请先核查；没有自动重试。', expires_at=0)
                    self._write(db, row['owner'], p)

    def _update(self, owner, id, **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            plan = self._read(db, owner, id)
            plan.update(changes)
            self._write(db, owner, plan)
            return plan

    @staticmethod
    def request_hash(request):
        return hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

    def claim(self, owner, id, version, token, text, *, check_enabled=True):
        if read_only.READ_ONLY:
            raise ActionError(read_only.MESSAGE, 403)
        # A SQLite CAS prevents another process from issuing a second request.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self._read(db, owner, id)
            if p['status'] not in self.REVIEW and not (p['status']=='expired' and p['provider']=='mcd' and p['action']=='create'):
                if p.get('request',{}).get('legacy_pickup') and p['status'] not in self.BUSY | {'created','failed'}:
                    raise ActionError('该方案不能继续下单，请重新查询。')
                return p, False
            if p.get('request_hash') and p['request_hash'] != self.request_hash(p['request']):
                raise ActionError('方案内容校验失败，请重新生成。')
            if type(version) is not int or version != p['version'] or not secrets.compare_digest(str(token), p['confirmation_token']) or text != self.phrase(p):
                raise ActionError('需要确认当前具体方案，请重新核对。')
            expired_quote=p['expires_at'] <= time.time()
            if expired_quote and not (p['provider']=='mcd' and p['action']=='create' and not p['request'].get('legacy_pickup')):
                p.update(status='expired', error='报价过期，请重新查询。')
                self._write(db, owner, p)
                if p['request'].get('legacy_pickup'):
                    raise ActionError('方案已过期，请重新核价。')
                return p, False
            if check_enabled and p['action'] != 'create_address' and not self.enabled(p['provider']):
                raise ActionError('家人尚未开启这项真实订单执行；本次没有提交。')
            if p['action'] == 'create' and self.blocked(p['provider']):
                raise ActionError(self.blocked(p['provider']))
            p['status'] = 'rechecking'
            self._write(db, owner, p)
        return p, True

    async def confirm(self, owner, id, version, token, text):
        p, claimed = self.claim(owner,id,version,token,text)
        if not claimed:
            return self.public(p)
        expired_quote = p['expires_at'] <= time.time()
        adapter = self.adapters.get(p['provider'])
        if adapter is None:
            return self.public(self._update(owner,id,status='failed',error='该服务尚未接好，本次未提交。'))
        try:
            quote = await adapter.quote(p['action'], copy.deepcopy(p['request']))
            self._quote(quote)
        except BaseException as exc:
            self._update(owner,id,status='expired',error='重核价失败，尚未提交，请重新查询。', expires_at=0)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return self.public(self.get(owner,id))
        if expired_quote or quote['comparison'] != p['comparison'] or quote['amount_cents'] != p['amount_cents']:
            return self.public(self._update(owner,id,status='needs_review',summary=normalize_summary(quote['summary']),summary_version=1,
                amount_cents=quote['amount_cents'],comparison=quote['comparison'],request=quote['request'],request_hash=self.request_hash(quote['request']),
                version=p['version']+1,confirmation_token=secrets.token_urlsafe(32),expires_at=time.time()+300,
                error='报价已重新核对，请确认当前内容和总额。' if expired_quote else '费用、规格或接送点有变化，请核对后再次确认。'))
        # Invalidating the token and persisting before the first remote write is
        # essential: timeout/crash cannot turn a later confirmation into a retry.
        self._update(owner,id,status='submitting',request=quote['request'],request_hash=self.request_hash(quote['request']),confirmation_token=secrets.token_urlsafe(32))
        try:
            result = await adapter.execute(p['action'], copy.deepcopy(quote['request']))
            if not isinstance(result, dict) or not result.get('address_id' if p['action']=='create_address' else 'order_id'):
                raise ActionError('未取得可核实的订单结果。')
            response = result.pop('provider_response', None)
            status = 'address_created' if p['action']=='create_address' else 'created' if p['action']=='create' else ('cancelled' if result.get('cancelled') is True or result.get('status')=='cancelled' else 'cancellation_requested')
            return self.public(self._update(owner,id,status=status,
                                            order=result,provider_response=response,error=None))
        except BaseException as exc:
            response = getattr(exc, 'provider_response', None)
            self._update(owner,id,status='unknown',error='请求结果待核查，暂不重复执行。',
                         provider_response=response if isinstance(response,(dict,list)) else None)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return self.public(self.get(owner,id))

    async def refresh(self, owner, id):
        p = self.get(owner,id)
        order = p.get('order') or {}
        if not order.get('order_id'):
            return self.public(p)
        adapter = self.adapters.get(p['provider'])
        if adapter is None or not hasattr(adapter, 'query_order'):
            raise ActionError('该服务暂不支持状态刷新。')
        try:
            status = await adapter.query_order(order['order_id'])
        except Exception:
            raise ActionError('状态查询暂时失败，不能推断已完成或已支付。', 502) from None
        updated = {**order, 'last_status':status, 'checked_at':time.time()}
        return self.public(self._update(owner,id,order=updated))
