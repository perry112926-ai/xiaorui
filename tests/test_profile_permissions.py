import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.agent import AgentService
from app.plans import PlanStore
from app.profile_permissions import profile_write_allowed

class ProfilePermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_negative_and_ordinary_statements_are_not_write_authorization(self):
        for text in ['我喜欢热饮','不要记住我的偏好','不用帮我记住','请不要忘记我的昵称']:
            self.assertFalse(profile_write_allowed(text,'set' if '忘记' not in text else 'forget'))
        self.assertTrue(profile_write_allowed('请记住我喜欢热饮','set'))
        self.assertTrue(profile_write_allowed('forget my nickname','forget'))

    async def test_model_write_requires_an_active_explicit_user_turn(self):
        with tempfile.TemporaryDirectory() as temp:
            agent=AgentService(SimpleNamespace(stores={}),PlanStore(Path(temp)/'plans.db'),data_dir=Path(temp)/'agent')
            session=agent._session('owner')
            args={'action':'set','key':'preferences.drinks','value':'喜欢热饮'}
            session.current_input='请记住我喜欢热饮'
            self.assertIn('error',await agent._tool(session,'owner','personal_profile',args,[]))
            async with session.lock:
                session.current_input='我喜欢热饮'
                self.assertIn('error',await agent._tool(session,'owner','personal_profile',args,[]))
                session.current_input='请记住我喜欢热饮'
                self.assertTrue((await agent._tool(session,'owner','personal_profile',args,[]))['saved'])
            self.assertEqual(agent.store.list_facts()['preferences.drinks'],'喜欢热饮')
