import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class LauncherTests(unittest.TestCase):
    def test_launcher_uses_existing_uv_and_locked_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'frontend/dist').mkdir(parents=True)
            (root/'frontend/dist/index.html').write_text('test')
            (root/'.env').write_text('TEST_ONLY=1\n')
            script=root/'启动.command';script.write_bytes((ROOT/'启动.command').read_bytes())
            binary=root/'bin';binary.mkdir()
            uv=binary/'uv';uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_UV_LOG"\n');uv.chmod(0o700)
            log=root/'uv.log'
            result=subprocess.run(['/bin/bash',str(script)],env={**os.environ,'PATH':str(binary)+':/usr/bin:/bin','TEST_UV_LOG':str(log),'PERSONAL_AGENT_NO_BROWSER':'1'},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(log.read_text().splitlines(),['sync --locked','run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000'])
            self.assertEqual((root/'.env').read_text(),'TEST_ONLY=1\n')
    def test_launcher_has_no_remote_script_execution(self):
        script=(ROOT/'启动.command').read_text()
        self.assertNotIn('curl ',script)
        self.assertNotIn('install-uv.sh',script)
        subprocess.run(['/bin/bash','-n',str(ROOT/'启动.command')],check=True)
