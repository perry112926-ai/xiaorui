import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from app.actions import ActionManager
from app.plans import PlanStore,fingerprint

class LegacyMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_is_idempotent_retains_owner_and_never_replays_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'plans.db';payload={'storeCode':'test','takeWayCode':'test','items':[]}
            old={'id':'old','version':1,'status':'submitting','confirmation_token':'old-token','expires_at':time.time()+300,
                 'request':payload,'request_hash':fingerprint(payload),'summary':{'product_name':'测试餐品'},'amount_cents':100}
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE plans (id TEXT PRIMARY KEY,owner TEXT,body TEXT)')
                db.execute('INSERT INTO plans VALUES (?,?,?)',('old','owner',json.dumps(old)))
            facade=PlanStore(path);gateway=ActionManager(root/'agent/actions.db',enabled=lambda _:True)
            facade.bind_actions(gateway)
            self.assertEqual(gateway.get('owner','old')['status'],'unknown')
            self.assertEqual(facade.get('old','owner')['summary']['product'],'测试餐品')
            with self.assertRaises(ValueError):facade.get('old','someone-else')
            restarted=PlanStore(path);self.assertEqual(restarted.manager.path.resolve(),gateway.path.resolve())
            self.assertEqual(len(restarted.manager.list('owner')),1)
            adapter=SimpleNamespace(quote=AsyncMock(),execute=AsyncMock());gateway.register('mcd',adapter)
            await gateway.confirm('owner','old',1,'old-token','确认下单')
            adapter.execute.assert_not_awaited()
            with sqlite3.connect(path) as db:self.assertEqual(json.loads(db.execute('SELECT body FROM plans').fetchone()[0])['status'],'submitting')

    async def test_old_and_new_proposals_invalidate_each_other_in_one_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);facade=PlanStore(root/'plans.db');manager=ActionManager(root/'agent/actions.db')
            facade.bind_actions(manager)
            old=facade.create('owner',{'request':{'test':1},'summary':{'product_name':'测试'},'amount_cents':100})
            manager.prepare('owner','mcd','create',{}, {'request':{},'summary':{},'comparison':{},'amount_cents':100})
            self.assertEqual(facade.get(old['id'],'owner')['status'],'superseded')
            self.assertIs(facade.manager,manager)

    async def test_late_write_by_old_process_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'plans.db';payload={'storeCode':'test'}
            old={'id':'old','status':'awaiting_confirmation','version':1,'confirmation_token':'old-token','expires_at':time.time()+300,
                 'request':payload,'request_hash':fingerprint(payload),'summary':{},'amount_cents':100}
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE plans (id TEXT PRIMARY KEY,owner TEXT,body TEXT)')
                db.execute('INSERT INTO plans VALUES (?,?,?)',('old','owner',json.dumps(old)))
            facade=PlanStore(path);manager=ActionManager(Path(temp)/'agent/actions.db');facade.bind_actions(manager)
            old['status']='submitting'
            with sqlite3.connect(path) as db:db.execute('UPDATE plans SET body=?',(json.dumps(old),))
            restored=PlanStore(path)
            self.assertEqual(restored.get('old','owner')['status'],'unknown')

    async def test_compatibility_view_preserves_old_labels_without_polluting_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            facade=PlanStore(Path(temp)/'plans.db')
            view=facade.create('owner',{'request':{},'amount_cents':100,'summary':{'product_name':'测试餐品','store_name':'测试门店'}})
            self.assertEqual(view['summary']['product_name'],'测试餐品')
            stored=facade.manager.get('owner',view['id'])
            self.assertEqual(stored['summary'],{'product':'测试餐品','store':'测试门店'})
            self.assertNotIn('request',view)
