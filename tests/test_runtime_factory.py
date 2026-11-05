import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
import httpx
from app.runtime import RuntimeServices

class RuntimeFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_and_factory_do_not_construct_persistent_dependencies(self):
        import app.main as module
        with patch('app.runtime.build_services',side_effect=AssertionError('eager initialization')):
            importlib.reload(module)
            application=module.create_app(services_factory=Mock(side_effect=AssertionError('eager initialization')))
            self.assertIsNone(application.state.runtime._services)
        importlib.reload(module)
        # No startup or network was needed merely to build the router.

    async def test_two_injected_apps_do_not_share_request_dependencies(self):
        from app.main import create_app
        def dependencies(name):
            store=SimpleNamespace(profile=lambda:{'name':name})
            return RuntimeServices(None,None,SimpleNamespace(store=store),None,None,None)
        a,b=create_app(services=dependencies('a')),create_app(services=dependencies('b'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a),base_url='http://localhost') as ca,httpx.AsyncClient(transport=httpx.ASGITransport(app=b),base_url='http://localhost') as cb:
            ra,rb=await asyncio.gather(ca.get('/api/profile'),cb.get('/api/profile'))
            self.assertEqual(ra.json(),{'name':'a'});self.assertEqual(rb.json(),{'name':'b'})

    async def test_rejected_origin_does_not_initialize_any_dependency(self):
        from app.main import create_app
        factory=Mock(side_effect=AssertionError('must not initialize'))
        application=create_app(services_factory=factory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://evil.invalid') as client:
            self.assertEqual((await client.get('/api/profile')).status_code,403)
        factory.assert_not_called()

    async def test_lifespan_owns_recovery_and_shutdown(self):
        from app.main import create_app
        plans=SimpleNamespace(recover_interrupted=Mock())
        agent=SimpleNamespace(store=SimpleNamespace(recover_interrupted=Mock()),actions=SimpleNamespace(recover_interrupted=Mock()))
        contact=SimpleNamespace(recover=Mock(),close=AsyncMock())
        scheduler=SimpleNamespace(start=AsyncMock(),stop=AsyncMock())
        application=create_app(services=RuntimeServices(None,plans,agent,None,contact,scheduler))
        async with application.router.lifespan_context(application):scheduler.start.assert_awaited_once()
        plans.recover_interrupted.assert_called_once();contact.close.assert_awaited_once();scheduler.stop.assert_awaited_once()
