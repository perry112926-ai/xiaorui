"""Durable contact inbox. Accept immediately, execute one turn at a time.

Never cancel or replay external writes. Confirmation is bound at arrival to the
exact visible proposal, and queued messages survive as interrupted on restart.
"""
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from app.agent import AgentError
from app.contact_events import contact_observer, contact_media, contact_call, contact_reply_mode
from app.text_delivery import acknowledgement

CONFIRMATIONS = {'确认叫车', '确认下单', '确认取消', '确认新增地址'}


class ContactService:
    def __init__(self, agent, path, images=None):
        self.agent = agent
        self.images = images
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workers = {}
        self.narrations = set()
        self.stopping = False
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, owner TEXT NOT NULL, client_id TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, confirmation TEXT, created REAL, UNIQUE(owner, client_id))')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS contact_owner ON events(owner, id)')
            if 'images' not in {r[1] for r in db.execute('PRAGMA table_info(inbox)')}:
                db.execute("ALTER TABLE inbox ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
            if 'call_id' not in {r[1] for r in db.execute('PRAGMA table_info(inbox)')}:
                db.execute('ALTER TABLE inbox ADD COLUMN call_id TEXT')
            if 'reply_mode' not in {r[1] for r in db.execute('PRAGMA table_info(inbox)')}:
                db.execute("ALTER TABLE inbox ADD COLUMN reply_mode TEXT NOT NULL DEFAULT 'speech'")
            db.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, owner TEXT NOT NULL, started REAL NOT NULL, ended REAL, duration INTEGER)')
        self.path.chmod(0o600)

    def db(self):
        return sqlite3.connect(self.path)

    def emit(self, owner, event):
        with self.db() as db:
            cursor = db.execute('INSERT INTO events(owner,payload) VALUES (?,?)', (owner, json.dumps(event, ensure_ascii=False)))
            return cursor.lastrowid

    def start_call(self, owner):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id,started FROM calls WHERE owner=? AND ended IS NULL', (owner,)).fetchone()
            if old:
                return {'id': old[0], 'started_at': old[1]}
            call = {'id': str(uuid4()), 'started_at': time.time()}
            db.execute('INSERT INTO calls(id,owner,started) VALUES (?,?,?)', (call['id'], owner, call['started_at']))
        return call

    def end_call(self, owner, call_id):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT started,ended,duration FROM calls WHERE id=? AND owner=?', (call_id, owner)).fetchone()
            if row is None:
                raise AgentError('找不到这次通话。', 404)
            ended = row[1] if row[1] is not None else time.time()
            duration = row[2] if row[2] is not None else max(0, int(ended-row[0]))
            result = {'id': call_id, 'started_at': row[0], 'ended_at': ended, 'duration_seconds': duration}
            if row[1] is None:
                db.execute('UPDATE calls SET ended=?,duration=? WHERE id=?', (ended, duration, call_id))
                db.execute('INSERT INTO events(owner,payload) VALUES (?,?)', (owner, json.dumps({'type':'call_ended','call':result})))
        return result

    def recover(self):
        with self.db() as db:
            rows = db.execute("SELECT id,owner,call_id FROM inbox WHERE status IN ('queued','running')").fetchall()
            db.execute("UPDATE inbox SET status='interrupted' WHERE status IN ('queued','running')")
        for mid, owner, call_id in rows:
            self.emit(owner, {'type': 'failed', 'message_id': mid, **({'call_id':call_id} if call_id else {}), 'text': '服务已重启，这条消息未自动重试；请先核对已有结果。'})
        with self.db() as db:
            calls = db.execute('SELECT owner,id FROM calls WHERE ended IS NULL').fetchall()
        for owner, call_id in calls:
            self.end_call(owner, call_id)

    def events(self, owner, after=0):
        with self.db() as db:
            return [{'cursor': row[0], **json.loads(row[1])} for row in db.execute(
                'SELECT id,payload FROM events WHERE owner=? AND id>? ORDER BY id LIMIT 256', (owner, after))]

    def state(self, owner):
        with self.db() as db:
            cursor = db.execute('SELECT coalesce(max(id),0) FROM events WHERE owner=?', (owner,)).fetchone()[0]
            rows = db.execute("SELECT id,payload FROM events WHERE owner=? AND json_extract(payload,'$.type') NOT IN ('delta','progress','started') ORDER BY id DESC LIMIT 160", (owner,)).fetchall()
            pending = db.execute("SELECT count(*) FROM inbox WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0]
            active = db.execute('SELECT id,started FROM calls WHERE owner=? AND ended IS NULL', (owner,)).fetchone()
        # Token deltas are ephemeral in the UI; replay only authoritative results.
        return {'events': [{'cursor': r[0], **json.loads(r[1])} for r in reversed(rows)
                           if json.loads(r[1])['type'] not in {'delta','progress','started'}],
                'cursor': cursor, 'pending': pending,
                'active_call': {'id':active[0], 'started_at':active[1]} if active else None}

    def enqueue(self, owner, text, client_id, image_ids=None, call_id=None, reply_mode='text'):
        if reply_mode not in {'text','speech'}:
            raise AgentError('回复方式无效。',400)
        image_ids=image_ids or []
        if len(image_ids)>4:
            raise AgentError('每条消息最多发送四张图片。',400)
        if image_ids:
            if self.images is None:
                raise AgentError('图片服务暂时不可用。',503)
            for mid in image_ids:
                self.images.resolve(owner,mid)
        if self.stopping:
            raise AgentError('服务正在退出，请稍后再发。', 503)
        if not text.strip() or len(text) > 2000:
            raise AgentError('请发送 1 到 2000 字的消息。', 400)
        with self.db() as db:
            old = db.execute('SELECT id FROM inbox WHERE owner=? AND client_id=?', (owner, client_id)).fetchone()
            if old:
                return self.receipt(db,owner,old[0])
            if call_id and not db.execute('SELECT 1 FROM calls WHERE id=? AND owner=? AND ended IS NULL', (call_id, owner)).fetchone():
                raise AgentError('这次通话已经结束，请重新拨打或发送文字消息。', 409)
            if db.execute("SELECT count(*) FROM inbox WHERE owner=? AND status IN ('queued','running')", (owner,)).fetchone()[0] >= 20:
                raise AgentError('待处理消息较多，请稍等片刻。', 429)
            if sum(not t.done() for t in self.workers.values()) >= 64 and (owner not in self.workers or self.workers[owner].done()):
                raise AgentError('当前会话较多，请稍后再试。', 429)
            phrase = text.strip().rstrip('。！!，, ')
            plan = self.agent.actions.pending(owner) if phrase in CONFIRMATIONS and not image_ids else None
            confirmation = json.dumps([plan['id'], plan['version']]) if plan else '[]'
            mid = str(uuid4())
            db.execute('INSERT INTO inbox (id,owner,client_id,text,status,confirmation,created,images,call_id,reply_mode) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (mid, owner, client_id, text.strip(), 'queued', confirmation, time.time(),json.dumps(image_ids),call_id,'speech' if call_id else reply_mode))
            event={'type': 'accepted', 'message_id': mid, 'client_id': client_id, 'text': text.strip(), **({'call_id':call_id} if call_id else {}),
                 'images':[{'id':i,'url':f'/api/contact/images/{i}'} for i in image_ids]}
            if not call_id:
                event['ack_text']=acknowledgement(text)
            db.execute('INSERT INTO events(owner,payload) VALUES (?,?)', (owner,json.dumps(event,ensure_ascii=False)))
        # A correction invalidates an old approval immediately, before its turn.
        if phrase not in CONFIRMATIONS or image_ids:
            self.invalidate_previous(owner)
        task = self.workers.get(owner)
        if task is None or task.done():
            self.workers = {k:v for k,v in self.workers.items() if not v.done()}
            self.workers[owner] = asyncio.create_task(self.pump(owner))
        return {'message_id': mid, 'accepted': True,'event':event}

    @staticmethod
    def receipt(db, owner, message_id):
        row=db.execute("SELECT payload FROM events WHERE owner=? AND json_extract(payload,'$.type')='accepted' AND json_extract(payload,'$.message_id')=? ORDER BY id LIMIT 1",(owner,message_id)).fetchone()
        result={'message_id':message_id,'accepted':True}
        if row:
            result['event']=json.loads(row[0])
        return result

    async def narrate(self, owner, task_id):
        try:
            event=await self.agent.complete_speech(owner,task_id)
            if event:
                self.emit(owner,event)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # The text reply and grounded fallback remain usable.

    def has_pending_any(self, owner):
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM inbox WHERE owner=? AND status='queued' LIMIT 1", (owner,)).fetchone())

    def has_pending_call(self, owner, call_id):
        # IS deliberately provides NULL-safe equality for ordinary chat (None).
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM inbox WHERE owner=? AND status='queued' AND call_id IS ? LIMIT 1", (owner, call_id)).fetchone())

    def invalidate_previous(self, owner):
        self.agent.actions.invalidate_pending(owner)
        session = self.agent._session(owner)
        plan = self.agent._plan(session, owner)
        if plan and plan['status'] in {'awaiting_confirmation','needs_review','expired'}:
            self.agent.plans.cancel(plan['id'], owner)

    async def pump(self, owner):
        while not self.stopping:
            # Briefly collect consecutive fragments, keeping confirmations separate.
            await asyncio.sleep(.12)
            with self.db() as db:
                rows = db.execute("SELECT id,text,confirmation,images,call_id,reply_mode FROM inbox WHERE owner=? AND status='queued' ORDER BY created,rowid", (owner,)).fetchall()
                if not rows:
                    return
                batch = []
                for row in rows:
                    confirm = row[1].rstrip('。！!，, ') in CONFIRMATIONS
                    if batch and (row[4] != batch[0][4] or confirm or json.loads(row[3]) or json.loads(batch[0][3]) or batch[0][1].rstrip('。！!，, ') in CONFIRMATIONS or sum(len(r[1])+1 for r in batch)+len(row[1]) > 2000):
                        break
                    batch.append(row)
                    if confirm:
                        break
                for row in batch:
                    db.execute("UPDATE inbox SET status='running' WHERE id=?", (row[0],))
            ids = [r[0] for r in batch]
            run = ids[0]
            channel = {'call_id':batch[0][4]} if batch[0][4] else {}
            self.emit(owner, {'type': 'started', 'message_id': run, 'message_ids': ids, **channel})
            token = contact_observer.set(lambda event: self.emit(owner, {'message_id': run, **event, **channel})
                                         if not self.has_pending_call(owner, batch[0][4]) else None)
            media_token=contact_media.set(None)
            call_token=contact_call.set(batch[0][4])
            reply_token=contact_reply_mode.set('speech' if batch[0][4] or any(r[5]=='speech' for r in batch) else 'text')
            try:
                if self.images:
                    contact_media.set([self.images.resolve(owner,mid) for r in batch for mid in json.loads(r[3])])
                # Wait for legacy/card operations rather than racing their lock.
                session = self.agent._session(owner)
                while session.lock.locked():
                    await asyncio.sleep(.05)
                response = await self.agent.chat(owner, '\n'.join(r[1] for r in batch),
                                                 expected_confirmation=json.loads(batch[0][2]))
                if batch[0][4]:
                    from app.speech import call_card_cue
                    response = {**response, 'speech_text': call_card_cue(response)}
                stale = self.has_pending_call(owner, batch[0][4])
                if response.get('conversation_reset'):
                    with self.db() as db:
                        db.execute('DELETE FROM events WHERE owner=?', (owner,))
                        db.execute("DELETE FROM inbox WHERE owner=? AND status NOT IN ('queued','running')", (owner,))
                if stale:
                    self.invalidate_previous(owner)
                self.emit(owner, {'type': 'completed', 'message_id': run, 'message_ids': ids,
                                  'response': response, 'superseded': stale, **channel})
                if response.get('speech_deferred'):
                    if not stale and len(self.narrations)<8:
                        job=asyncio.create_task(self.narrate(owner,response['task_id']))
                        self.narrations.add(job);job.add_done_callback(self.narrations.discard)
                    else:
                        self.agent.discard_speech(response['task_id'])
                status = 'completed'
            except asyncio.CancelledError:
                self.emit(owner, {'type': 'failed', 'message_id': run, 'message_ids': ids,
                                  'text': '处理已中断，请核对已有结果；没有自动重试。', **channel})
                status = 'interrupted'
                raise
            except Exception as exc:
                status = 'failed'
                self.emit(owner, {'type': 'failed', 'message_id': run, 'message_ids': ids,
                                  'text': exc.message if isinstance(exc, AgentError) else '这次处理未完成，请检查连接后重试；已有操作不会自动重放。', **channel})
            finally:
                contact_observer.reset(token)
                contact_media.reset(media_token)
                contact_call.reset(call_token)
                contact_reply_mode.reset(reply_token)
                with self.db() as db:
                    for mid in ids:
                        db.execute('UPDATE inbox SET status=? WHERE id=?', (status, mid))

    async def close(self):
        self.stopping = True
        tasks = [t for t in self.workers.values() if not t.done()]
        tasks += list(self.narrations)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
