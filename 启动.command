#!/bin/bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_root"
mkdir -p .local-data
export UV_CACHE_DIR="$project_root/.local-data/uv-cache"
export UV_PYTHON_INSTALL_DIR="$project_root/.local-data/python"

if command -v uv >/dev/null 2>&1; then
  uv_command="$(command -v uv)"
elif [ -x /opt/homebrew/bin/uv ]; then
  uv_command=/opt/homebrew/bin/uv
elif [ -x "$project_root/.local-data/tools/uv" ]; then
  uv_command="$project_root/.local-data/tools/uv"
else
  echo "请先安装 uv，再双击启动。可由家人运行 brew install uv。"
  echo "安装说明：https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "已创建 .env。可先打开页面；查询前请填写麦当劳 Token。"
fi

echo "检查 Python 及依赖（首次需要联网）…"
"$uv_command" sync --locked

if [ ! -f frontend/dist/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "缺少已构建网页。开发源码需要先安装 Node.js，执行 npm --prefix frontend ci 和 npm --prefix frontend run build。"
    exit 1
  fi
  echo "构建网页…"
  npm --prefix frontend ci
  npm --prefix frontend run build
fi

echo "打开 http://127.0.0.1:8000 。关闭此窗口或按 Control+C 停止服务。"
if [ "${PERSONAL_AGENT_NO_BROWSER:-0}" != 1 ]; then
  (sleep 2; /usr/bin/open http://127.0.0.1:8000) &
fi
exec "$uv_command" run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
