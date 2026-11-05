"""Settings use isolated temporary files, never real credentials or services."""
import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch, AsyncMock

from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / '.env'
        self.patches = [patch.object(settings, 'ENV_PATH', self.file),
                        patch.object(settings, 'LOCK_PATH', self.root/'settings.lock'),
                        patch.dict(os.environ, {}, clear=True),
                        patch.object(settings.read_only, 'READ_ONLY', False)]
        for p in self.patches: p.start()
        app = FastAPI()
        app.include_router(settings.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def save(self, values):
        return self.client.post('/api/settings', json={'values': values})

    def test_secret_write_only_and_atomic_private_file_preserves_unrelated_values(self):
        self.file.write_text('# existing comment\nMCD_ORDER_ENABLED=false\nUNRELATED=keep\n')
        response = self.save({'MCD_MCP_TOKEN': 'private-marker', 'ARK_MODEL': 'doubao-test'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('private-marker', response.text)
        self.assertNotIn('private-marker', self.client.get('/api/settings').text)
        self.assertTrue(response.json()['fields']['MCD_MCP_TOKEN']['configured'])
        self.assertEqual(response.json()['fields']['ARK_MODEL']['value'], 'doubao-test')
        values = dotenv_values(self.file)
        self.assertEqual(values['MCD_MCP_TOKEN'], 'private-marker')
        self.assertEqual(values['UNRELATED'], 'keep')
        self.assertEqual(values['MCD_ORDER_ENABLED'], 'false')
        self.assertIn('# existing comment', self.file.read_text())
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob('.env.settings-*')), [])

    def test_unknown_fields_transaction_flags_and_secret_validation_never_echo_input(self):
        for values in [{'MCD_ORDER_ENABLED': 'true'}, {'CUSTOM_MCP_COMMAND': 'private-marker'},
                       {'MCD_MCP_TOKEN': {'secret': 'private-marker'}},
                       {'MCD_MCP_TOKEN': 'private-marker\nINJECTED=true'},
                       {'MCD_MCP_TOKEN': '${private-marker}'}]:
            response = self.save(values)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-marker', response.text)
        self.assertFalse(self.file.exists())
        response = self.client.post('/api/settings', json={'values': {}, 'command': 'private-marker'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private-marker', response.text)

    def test_env_override_is_explicit_and_cannot_be_falsely_saved(self):
        with patch.dict(os.environ, {'MCD_MCP_TOKEN': 'environment-private-marker'}):
            response = self.client.get('/api/settings')
            field = response.json()['fields']['MCD_MCP_TOKEN']
            self.assertEqual(field['source'], 'environment')
            self.assertFalse(field['editable'])
            self.assertNotIn('environment-private-marker', response.text)
            saved = self.save({'MCD_MCP_TOKEN': 'other-private-marker'})
            self.assertEqual(saved.status_code, 409)
            self.assertNotIn('private-marker', saved.text)

    def test_ssrf_credential_forwarding_and_endpoint_queries_are_rejected(self):
        for url in ['http://localhost:8000', 'https://127.0.0.1/api/v3',
                    'https://evil.example/api/v3', 'https://ark.cn-beijing.volces.com.evil.example/api/v3',
                    'https://private-marker@ark.cn-beijing.volces.com/api/v3',
                    'https://ark.cn-beijing.volces.com/api/v3?key=private-marker',
                    'https://ark.cn-beijing.volces.com:bad/api/v3']:
            response = self.save({'ARK_BASE_URL': url})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-marker', response.text)
        self.assertEqual(self.save({'ARK_BASE_URL': settings.ARK_BASE + '/'}).status_code, 200)
        self.assertEqual(dotenv_values(self.file)['ARK_BASE_URL'], settings.ARK_BASE)

    def test_partial_text_key_or_model_update_rejects_existing_untrusted_destination(self):
        original = 'ARK_BASE_URL=https://untrusted.invalid/api/v3\nARK_MODEL=legacy-model\n'
        self.file.write_text(original)
        for values in ({'ARK_API_KEY': 'private-marker'}, {'ARK_MODEL': 'new-model'}):
            response = self.save(values)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-marker', response.text)
            self.assertNotIn('untrusted.invalid', response.text)
            self.assertEqual(self.file.read_text(), original)
        self.assertEqual(self.save({'ARK_API_KEY': 'private-marker',
                                   'ARK_BASE_URL': settings.ARK_BASE}).status_code, 200)
        values = dotenv_values(self.file)
        self.assertEqual(values['ARK_BASE_URL'], settings.ARK_BASE)
        self.assertEqual(values['ARK_API_KEY'], 'private-marker')

    def test_effective_environment_endpoint_cannot_be_bypassed_by_partial_update(self):
        self.file.write_text('ARK_BASE_URL=' + settings.ARK_BASE + '\n')
        with patch.dict(os.environ, {'ARK_BASE_URL': 'https://untrusted.invalid/api/v3'}):
            for values in ({'ARK_API_KEY': 'private-marker'}, {'ARK_MODEL': 'new-model'}):
                self.assertEqual(self.save(values).status_code, 422)
            # A file-level correction cannot override an environment setting.
            self.assertEqual(self.save({'ARK_API_KEY': 'private-marker',
                                        'ARK_BASE_URL': settings.ARK_BASE}).status_code, 409)
        self.assertNotIn('ARK_API_KEY', dotenv_values(self.file))

    def test_invalid_existing_text_endpoint_is_not_reported_as_configured(self):
        self.file.write_text('ARK_BASE_URL=https://untrusted.invalid/api/v3\n'
                            'ARK_MODEL=test\nARK_API_KEY=private-marker\n')
        response = self.client.get('/api/settings')
        self.assertFalse(response.json()['providers']['ark']['configured'])
        self.assertFalse(response.json()['providers']['ark']['endpoint_allowed'])
        self.assertEqual(response.json()['fields']['ARK_BASE_URL']['value'], '')
        self.assertNotIn('private-marker', response.text)
        self.assertNotIn('untrusted.invalid', response.text)
        self.assertEqual(self.client.post('/api/settings/test/ark').json()['status'], 'not_configured')

    def test_concurrent_partial_updates_preserve_both_values(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(settings.save_values, [
                {'MCD_MCP_TOKEN': 'first'}, {'LUCKIN_MCP_TOKEN': 'second'}]))
        self.assertEqual(dotenv_values(self.file)['MCD_MCP_TOKEN'], 'first')
        self.assertEqual(dotenv_values(self.file)['LUCKIN_MCP_TOKEN'], 'second')

    def test_missing_keys_are_not_connected_and_ark_speech_checks_do_not_claim_live_success(self):
        self.assertEqual(self.client.post('/api/settings/test/mcd').json()['status'], 'not_configured')
        self.save({'ARK_API_KEY': 'private-marker', 'ARK_MODEL': 'test',
                   'DOUBAO_SPEECH_API_KEY': 'private-marker'})
        for provider in ('ark', 'speech'):
            response = self.client.post('/api/settings/test/' + provider)
            self.assertEqual(response.json()['status'], 'not_live_tested')
            self.assertNotIn('private-marker', response.text)
        self.assertEqual(self.client.post('/api/settings/test/custom').status_code, 404)

    def test_service_test_reuses_only_bounded_public_probe(self):
        self.save({'DIDI_MCP_KEY': 'private-marker'})
        result = {'checks': [{'provider': 'didi', 'configured': True,
                              'discovery': 'passed', 'query': 'failed', 'transactions_attempted': 0}]}
        with patch('experiments.read_only_service_check.matrix', new_callable=AsyncMock, return_value=result) as check:
            response = self.client.post('/api/settings/test/didi')
        check.assert_awaited_once_with(['didi'], timeout=35)
        self.assertEqual(response.json()['discovery'], 'passed')
        self.assertEqual(response.json()['status'], 'failed')
        self.assertNotIn('private-marker', response.text)

    def test_fliggy_key_save_mask_clear_and_environment_override(self):
        saved = self.save({'FLYAI_API_KEY':'flight-private-marker'})
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()['providers']['fliggy']['configured'])
        self.assertIn('runtime_ready', saved.json()['providers']['fliggy'])
        self.assertNotIn('flight-private-marker', saved.text)
        self.assertNotIn('flight-private-marker', self.client.get('/api/settings').text)
        self.assertEqual(dotenv_values(self.file)['FLYAI_API_KEY'], 'flight-private-marker')
        self.assertFalse(self.save({'FLYAI_API_KEY':''}).json()['providers']['fliggy']['configured'])
        with patch.dict(os.environ, {'FLYAI_API_KEY':'environment-private-marker'}):
            config = self.client.get('/api/settings').json()
            self.assertFalse(config['fields']['FLYAI_API_KEY']['editable'])
            self.assertEqual(self.save({'FLYAI_API_KEY':'replacement'}).status_code, 409)

    def test_fliggy_checks_saved_key_with_fixed_public_query_and_no_payload_echo(self):
        self.assertEqual(self.client.post('/api/settings/test/fliggy').json()['status'], 'not_configured')
        self.save({'FLYAI_API_KEY':'flight-private-marker'})
        with patch('app.settings.runtime_status', return_value={'runtime_ready':True}), \
             patch('app.settings.Fliggy') as adapter:
            adapter.return_value.dispatch = AsyncMock(return_value={'flights':[{'private':'payload-marker'}]})
            response = self.client.post('/api/settings/test/fliggy')
        adapter.assert_called_once_with(self.file)
        args = adapter.return_value.dispatch.call_args.args[0]
        self.assertEqual((args['origin'],args['destination']), ('北京','上海'))
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        self.assertEqual(args['dep_date'], (datetime.now(ZoneInfo('Asia/Shanghai'))+timedelta(days=7)).date().isoformat())
        self.assertTrue(args['direct_only'])
        self.assertEqual(response.json()['status'],'passed')
        self.assertEqual(response.json()['transactions_attempted'],0)
        self.assertNotIn('payload-marker',response.text)
        self.assertNotIn('private-marker',response.text)

    def test_fliggy_missing_runtime_empty_failed_timeout_and_setup_boundaries(self):
        self.save({'FLYAI_API_KEY':'flight-private-marker'})
        with patch('app.settings.runtime_status', return_value={'runtime_ready':False}), \
             patch('app.settings.Fliggy') as adapter:
            self.assertEqual(self.client.post('/api/settings/test/fliggy').json()['status'], 'needs_setup')
            adapter.assert_not_called()
        for result, expected in [({'flights':[]}, 'empty'), ({'error':'private-marker'}, 'failed')]:
            with patch('app.settings.runtime_status', return_value={'runtime_ready':True}), \
                 patch('app.settings.Fliggy') as adapter:
                adapter.return_value.dispatch = AsyncMock(return_value=result)
                response=self.client.post('/api/settings/test/fliggy')
                self.assertEqual(response.json()['status'],expected)
                self.assertNotIn('private-marker',response.text)
        with patch('app.settings.runtime_status', return_value={'runtime_ready':True}), \
             patch('app.settings.Fliggy') as adapter:
            adapter.return_value.dispatch = AsyncMock(side_effect=TimeoutError)
            self.assertEqual(self.client.post('/api/settings/test/fliggy').json()['status'],'timeout')
        with patch('app.settings.prepare_runtime',new_callable=AsyncMock,return_value={'status':'ready'}) as prepare:
            self.assertEqual(self.client.post('/api/settings/prepare/fliggy').json()['status'],'ready')
            prepare.assert_awaited_once()
            with patch.object(settings.read_only,'READ_ONLY',True):
                self.assertEqual(self.client.post('/api/settings/prepare/fliggy').status_code,403)
                self.assertEqual(self.client.post('/api/settings/test/fliggy').status_code,403)
                self.assertEqual(self.save({'FLYAI_API_KEY':'new'}).status_code,403)
            self.assertEqual(prepare.await_count,1)

    def test_read_only_mode_and_failed_replace_do_not_modify_existing_file(self):
        self.file.write_text('UNRELATED=original\n')
        with patch.object(settings.read_only, 'READ_ONLY', True):
            self.assertEqual(self.save({'MCD_MCP_TOKEN': 'private-marker'}).status_code, 403)
            self.assertEqual(self.client.post('/api/settings/test/mcd').status_code, 403)
        with patch.object(settings.os, 'replace', side_effect=OSError('private-marker')):
            response = self.save({'MCD_MCP_TOKEN': 'private-marker'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-marker', response.text)
        self.assertEqual(self.file.read_text(), 'UNRELATED=original\n')
        self.assertFalse(list(self.root.glob('.env.settings-*')))
