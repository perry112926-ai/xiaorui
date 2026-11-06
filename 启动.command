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
  echo "已创建 .env。页面打开后，请在家人设置中配置模型及所需服务。"
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

if ! "$uv_command" run --no-sync python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 8000)); s.close()'; then
  echo "8000 端口已被占用。若小瑞已经运行，请直接打开 http://127.0.0.1:8000；否则先关闭占用端口的程序。"
  exit 1
fi

echo "正在启动小瑞，页面就绪后会自动打开…"
"$uv_command" run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ready=false
for ((attempt=0; attempt<120; attempt++)); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "小瑞启动失败，请查看上方错误信息。"
    wait "$server_pid" || exit $?
    exit 1
  fi
  if curl --noproxy '*' --silent --fail --max-time 1 http://127.0.0.1:8000/api/health >/dev/null; then
    ready=true
    break
  fi
  sleep 0.5
done
if [ "$ready" != true ]; then
  echo "服务启动等待超时，请查看上方错误信息后重新启动。"
  exit 1
fi
echo "小瑞已就绪：http://127.0.0.1:8000 。保持此窗口打开，按 Control+C 停止服务。"
if [ "${PERSONAL_AGENT_NO_BROWSER:-0}" != 1 ]; then
  /usr/bin/open http://127.0.0.1:8000 || echo "请在浏览器手动打开上方地址。"
fi
wait "$server_pid"
