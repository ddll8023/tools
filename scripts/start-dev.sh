#!/bin/bash
# 工具盒子开发模式启动脚本（macOS）。
#
# 只做前置环境检查与端口释放，不安装依赖、不下载 Electron：缺什么就拦下并提示获取方式，
# 避免启动过程在后台改写 node_modules 或 backend/.venv，让失败原因留在终端上。
# 模型由设置页手动下载，不在启动时自动拉取。

set -u

cd "$(dirname "$0")/.." || exit 1

echo ""
echo "=== 工具盒子 开发模式 ==="
echo ""

# 缺依赖时停下等回车，正常退出则直接结束，让终端随退出关闭。
abort() {
  echo "[错误] $1" >&2
  if [ -n "${2:-}" ]; then
    echo "       $2" >&2
  fi
  read -rsp $'按回车键退出...\n'
  exit 1
}

# 检测端口占用并释放
release_port() {
  local PORT=$1
  local PID
  PID=$(lsof -ti tcp:"$PORT" 2>/dev/null)
  if [ -n "$PID" ]; then
    echo "[端口] 端口 $PORT 已被 PID=$PID 占用，正在停止..."
    kill -9 "$PID" 2>/dev/null
    sleep 1
    if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
      echo "[端口] ⚠ 端口 $PORT 释放失败，请手动检查"
    else
      echo "[端口] ✓ 端口 $PORT 已释放"
    fi
  fi
}

echo "[端口] 检查端口占用..."
release_port 18740
release_port 5173
echo ""

command -v node >/dev/null 2>&1 \
  || abort "未找到 Node.js，请先安装 Node.js 18 或更高版本。"
command -v npm >/dev/null 2>&1 \
  || abort "未找到 npm，请检查 Node.js 安装。"
command -v uv >/dev/null 2>&1 \
  || abort "未找到 uv，请先安装 uv。" "安装说明: https://docs.astral.sh/uv/getting-started/installation/"

[ -f "node_modules/electron/package.json" ] && [ -x "node_modules/.bin/tsc" ] \
  || abort "根目录 Node 依赖未安装。" "请在项目根目录运行: npm install"

[ -d "node_modules/electron/dist" ] \
  || abort "Electron 二进制缺失，无法启动桌面外壳。" "请运行: node node_modules/electron/install.js"

[ -x "frontend/node_modules/.bin/vite" ] \
  || abort "前端依赖未安装。" "请在项目根目录运行: npm --prefix frontend install"

[ -x "backend/.venv/bin/python" ] \
  || abort "后端 Python 环境未创建。" "请在项目根目录运行: uv sync --directory backend"

# USB 原生依赖只在 macOS 上随包分发，开发态同样需要它加载有线传输能力。
[ -f "build/usb-native/dist/manifest.json" ] \
  || abort "USB 原生依赖未构建，有线传输功能不可用。" "请在项目根目录运行: npm run build:usb-native"

echo "[提示] 模型不会在启动时下载，请在软件“设置”页面手动下载。"
echo "[提示] 修改后端代码后需关闭 Terminal 重新启动。"
echo "[启动] 正在启动 后端 + 前端 + Electron ..."
echo ""

node electron/dev-runner.js
exit $?
