"""Confirmed identity data, conflict handling and chat boundaries; no live API."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.agent import AgentService
from app.foundation_store import FoundationStore
from app.plans import PlanStore
from app.profile_card import ProfileConflict


class ProfileCardStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'foundation.sqlite3'
        self.store = FoundationStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_address_requires_human_review_before_model_can_use_it(self):
        self.store.set_fact('home.address', '测试旧地址')
        self.assertNotIn('home.address', self.store.model_profile()['facts'])
        field = next(x for x in self.store.profile_card()['fields'] if x['key'] == 'home.address')
        self.assertEqual(field['value'], '测试旧地址')
        self.assertIsNone(field['confirmed_at'])
        self.store.save_profile_card(1, {'home.address': '测试核对地址'})
        self.assertEqual(self.store.model_profile()['confirmed_fields']['home.address'], '测试核对地址')

    def test_confirmation_survives_restart_without_rotating_conversation(self):
        old = self.store.session('a')
        old['display'] = [{'role':'user', 'text':'持续聊天'}]
        old['services'] = {'mcd': {'selected_address': {'address':'旧测试地址'}}}
        self.store.save_session('a', old)
        self.store.save_profile_card(0, {'home.address':'测试家庭地址', 'contact.primary.phone':'+86 199-0000-0000'})
        restarted = FoundationStore(self.path)
        self.assertEqual(restarted.session('a')['conversation_id'], old['conversation_id'])
        self.assertEqual(restarted.session('a')['display'], old['display'])
        self.assertEqual(restarted.session('a')['services'], {})
        self.assertEqual(restarted.model_profile()['facts']['contact.primary.phone'], '+8619900000000')
        self.assertTrue(next(x for x in restarted.profile_card()['fields'] if x['key'] == 'home.address')['confirmed_at'])

    def test_stale_save_cannot_overwrite_more_recent_confirmation(self):
        self.store.save_profile_card(0, {'home.address':'较新的测试地址'})
        with self.assertRaises(ProfileConflict):
            self.store.save_profile_card(0, {'home.address':'较旧的测试地址'})
        self.assertEqual(self.store.profile()['facts']['home.address'], '较新的测试地址')

    def test_invalid_field_or_phone_does_not_partially_update(self):
        for fields in ({'made.up':'x'}, {'home.address':'测试地址','contact.primary.phone':'号码待定'},
                       {'home.address':'a'*301}, {}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.save_profile_card(0, fields)
            self.assertEqual(self.store.profile()['version'], 0)
            self.assertEqual(self.store.profile()['facts'], {})

    def test_confirmed_clear_removes_active_value_and_keeps_conversation(self):
        state = self.store.session('a')
        self.store.save_profile_card(0, {'contact.primary.phone':'19900000000'})
        self.store.save_profile_card(1, {'contact.primary.phone':''})
        self.assertNotIn('contact.primary.phone', self.store.model_profile()['facts'])
        self.assertNotIn('contact.primary.phone', self.store.model_profile()['confirmed_fields'])
        self.assertEqual(self.store.session('a')['conversation_id'], state['conversation_id'])


class ProfileCardApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import app.main as api
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.agent = AgentService(SimpleNamespace(stores={}), PlanStore(root/'plans.sqlite3'), data_dir=root/'agent')
        self.patch = patch.object(api, 'agent', self.agent)
        self.patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://localhost')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patch.stop()
        self.tmp.cleanup()

    def body(self, version=0):
        return {'version':version, 'fields':{'home.address':'测试用家庭地址'}, 'confirmation_text':'确认保存资料'}

    async def test_requires_exact_confirmation_and_rejects_cross_origin(self):
        body=self.body();body['confirmation_text']='好的'
        self.assertEqual((await self.client.put('/api/profile/card',json=body)).status_code,422)
        self.assertEqual((await self.client.put('/api/profile/card',json=self.body(),headers={'Origin':'https://foreign.invalid'})).status_code,403)
        self.assertEqual(self.agent.store.profile()['version'],0)

    async def test_removed_new_chat_endpoint_keeps_existing_conversation(self):
        await self.client.get('/api/health')
        owner=self.client.cookies['pa_session']
        old=self.agent.store.session(owner)
        response=await self.client.post('/api/chat/reset',json={})
        self.assertEqual(response.status_code,410)
        self.assertEqual(self.agent.store.session(owner)['conversation_id'],old['conversation_id'])

    async def test_save_invalidates_pending_plan_from_another_browser(self):
        quote={'request':{},'summary':{},'amount_cents':100,'comparison':{}}
        plan=self.agent.actions.prepare('another-browser','didi','create',{},quote)
        old=self.agent.store.session('another-browser')['conversation_id']
        response=await self.client.put('/api/profile/card',json=self.body())
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.agent.actions.get('another-browser',plan['id'])['status'],'superseded')
        self.assertEqual(self.agent.store.session('another-browser')['conversation_id'],old)
        self.assertEqual((await self.client.put('/api/profile/card',json=self.body())).status_code,409)

    async def test_active_chat_blocks_save_and_preserves_draft_version(self):
        async with self.agent._session('a').lock:
            response=await self.client.put('/api/profile/card',json=self.body())
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.agent.store.profile()['version'],0)

    async def test_model_cannot_set_or_forget_critical_fields_or_aliases(self):
        self.agent.store.save_profile_card(0,{'home.address':'测试核对地址'})
        session=self.agent._session('a')
        for key in ('home.address','home_address','contact.primary.phone','person.name','child_phone'):
            for action in ('set','forget'):
                result=await self.agent._tool(session,'a','personal_profile',
                    {'action':action,'key':key,'value':'测试替换'},[])
                self.assertIn('error',result)
        self.assertEqual(self.agent.store.profile()['facts']['home.address'],'测试核对地址')
        session.current_input='请记住我喜欢热饮。'
        async with session.lock:
            result=await self.agent._tool(session,'a','personal_profile',
                {'action':'set','key':'preference.drink','value':'测试热饮偏好'},[])
        self.assertTrue(result['saved'])


if __name__ == '__main__':
    unittest.main()
