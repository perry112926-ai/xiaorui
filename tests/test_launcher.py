import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def run_launcher(self, server_behavior, health_behavior):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'frontend/dist').mkdir(parents=True)
            (root / 'frontend/dist/index.html').write_text('test')
            (root / '.env').write_text('TEST_ONLY=1\n')
            script = root / '启动.command'
            script.write_bytes((ROOT / '启动.command').read_bytes())
            binary = root / 'bin'
            binary.mkdir()
            uv = binary / 'uv'
            uv.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_UV_LOG"\n'
                'case "$*" in\n*uvicorn*)\n' + server_behavior + '\n;;\nesac\n'
            )
            uv.chmod(0o700)
            curl = binary / 'curl'
            curl.write_text('#!/bin/sh\n' + health_behavior + '\n')
            curl.chmod(0o700)
            log = root / 'uv.log'
            result = subprocess.run(
                ['/bin/bash', str(script)],
                env={
                    **os.environ, 'PATH': str(binary) + ':/usr/bin:/bin',
                    'TEST_UV_LOG': str(log), 'TEST_READY': str(root / 'ready'),
                    'PERSONAL_AGENT_NO_BROWSER': '1',
                },
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual((root / '.env').read_text(), 'TEST_ONLY=1\n')
            return result, log.read_text().splitlines()

    def test_waits_for_health_after_slow_startup(self):
        result, calls = self.run_launcher(
            'sleep 2.5\necho ready > "$TEST_READY"\nsleep 1',
            'test -f "$TEST_READY"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('小瑞已就绪', result.stdout)
        self.assertEqual(calls[0], 'sync --locked')
        self.assertIn('socket', calls[1])
        self.assertEqual(
            calls[2],
            'run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000',
        )

    def test_startup_failure_does_not_report_ready(self):
        result, _ = self.run_launcher('exit 3', 'exit 1')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('启动失败', result.stdout)
        self.assertNotIn('小瑞已就绪', result.stdout)

    def test_launcher_has_no_remote_script_execution(self):
        script = (ROOT / '启动.command').read_text()
        self.assertNotIn('install-uv.sh', script)
        self.assertNotIn('| sh', script)
        self.assertNotIn('| bash', script)
        subprocess.run(['/bin/bash', '-n', str(ROOT / '启动.command')], check=True)
