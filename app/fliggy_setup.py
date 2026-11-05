"""Install one pinned official bundle; no npm scripts or caller-selected URLs."""
import asyncio
import base64
import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / '.local-data/flyai/cli/dist/flyai-bundle.cjs'
VERSION = '1.0.16'
URL = 'https://registry.npmjs.org/@fly-ai/flyai-cli/-/flyai-cli-1.0.16.tgz'
INTEGRITY = 'Ksi06xvJSJcdhmfoDbpAnA84K4/pF+SkLsa5ZLvNruUc3e2EpoGaI6FcJXKTODvB/evprfy5pdRzW3lVazqfkA=='


def runtime_status():
    node = bool(shutil.which('node'))
    bundle = CLI.is_file()
    return {'node_available': node, 'cli_available': bundle,
            'runtime_ready': node and bundle, 'cli_version': VERSION}


def install_bundle(archive):
    if base64.b64encode(hashlib.sha512(archive).digest()).decode() != INTEGRITY:
        raise ValueError('Official package integrity mismatch')
    # Read precisely one regular member instead of extracting paths from tar.
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
        member = package.getmember('package/dist/flyai-bundle.cjs')
        if not member.isfile() or member.size > 2_000_000:
            raise ValueError('Invalid official bundle')
        with package.extractfile(member) as file:
            bundle = file.read(2_000_001)
    CLI.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.flyai-', dir=CLI.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(bundle)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, CLI)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def prepare_runtime():
    if not shutil.which('node'):
        return {'status':'needs_node', 'detail':'请先安装 Node.js 18 或以上版本，重启小瑞后再准备飞猪组件。', **runtime_status()}
    if CLI.is_file():
        return {'status':'ready', 'detail':'飞猪组件已准备好，可以保存 Key 并检查连接。', **runtime_status()}
    try:
        archive = bytearray()
        async with asyncio.timeout(35):
            async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False) as client:
                async with client.stream('GET', URL) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        archive.extend(chunk)
                        if len(archive) > 2_000_000:
                            raise ValueError('Package too large')
            await asyncio.to_thread(install_bundle, bytes(archive))
        return {'status':'ready', 'detail':'已准备官方飞猪组件；没有下单或开启支付权限。', **runtime_status()}
    except Exception:
        return {'status':'failed', 'detail':'飞猪组件准备失败，请检查网络和本机目录权限后重试。', **runtime_status()}
