import base64
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from app import fliggy_setup as setup


def archive(name='package/dist/flyai-bundle.cjs', symlink=False):
    target=io.BytesIO()
    with tarfile.open(fileobj=target, mode='w:gz') as file:
        item=tarfile.TarInfo(name)
        if symlink:
            item.type=tarfile.SYMTYPE
            item.linkname='/tmp/elsewhere'
            file.addfile(item)
        else:
            data=b'console.log("official fixture")'
            item.size=len(data)
            file.addfile(item,io.BytesIO(data))
    return target.getvalue()


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_requires_node_and_reuses_existing_bundle_without_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(setup,'CLI',Path(directory)/'bundle.cjs') as path:
            with patch.object(setup.shutil,'which',return_value=None),patch.object(setup.httpx,'AsyncClient') as client:
                self.assertEqual((await setup.prepare_runtime())['status'],'needs_node')
                client.assert_not_called()
            path.write_bytes(b'existing')
            with patch.object(setup.shutil,'which',return_value='/node'),patch.object(setup.httpx,'AsyncClient') as client:
                self.assertEqual((await setup.prepare_runtime())['status'],'ready')
                client.assert_not_called()
                self.assertEqual(path.read_bytes(),b'existing')

    def test_installs_only_verified_regular_bundle_and_preserves_existing_on_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(setup,'CLI',Path(directory)/'dist/bundle.cjs') as path:
            data=archive()
            integrity=base64.b64encode(hashlib.sha512(data).digest()).decode()
            with patch.object(setup,'INTEGRITY',integrity):
                setup.install_bundle(data)
                self.assertIn(b'official fixture',path.read_bytes())
                with self.assertRaises(ValueError):setup.install_bundle(data+b'tampered')
            self.assertIn(b'official fixture',path.read_bytes())
            for bad in (archive('../escape'), archive(symlink=True)):
                with patch.object(setup,'INTEGRITY',base64.b64encode(hashlib.sha512(bad).digest()).decode()):
                    with self.assertRaises((ValueError,KeyError)):setup.install_bundle(bad)
            self.assertEqual(list(path.parent.glob('.flyai-*')),[])
