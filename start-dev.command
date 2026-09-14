#!/bin/bash
# 工具盒子开发模式启动脚本（macOS）
# 仅负责准备依赖环境并启动后端、前端和 Electron；模型由设置页手动下载。

cd "$(dirname "$0")" || exit 1

echo ""
echo "=== 工具盒子 开发模式 ==="

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
release_port 4740
release_port 5173

echo ""

if ! command -v node >/dev/null 2>&1; then
  echo "[错误] 未找到 Node.js，请先安装 Node.js 18 或更高版本。" >&2
  read -rsp $'按回车键退出...\n'
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[错误] 未找到 npm，请检查 Node.js 安装。" >&2
  read -rsp $'按回车键退出...\n'
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[错误] 未找到 uv，请先安装 uv。" >&2
  read -rsp $'按回车键退出...\n'
  exit 1
fi

if [ ! -x "node_modules/.bin/tsc" ] || [ ! -x "node_modules/.bin/electron" ]; then
  echo "[依赖] 安装根目录 Node 依赖..."
  npm install || {
    echo "[错误] 根目录 Node 依赖安装失败。" >&2
    read -rsp $'按回车键退出...\n'
    exit 1
  }
fi

if [ ! -x "frontend/node_modules/.bin/vite" ]; then
  echo "[依赖] 安装前端 Node 依赖..."
  npm --prefix frontend install || {
    echo "[错误] 前端 Node 依赖安装失败。" >&2
    read -rsp $'按回车键退出...\n'
    exit 1
  }
fi

if [ ! -x "backend/.venv/bin/python" ]; then
  echo "[依赖] 创建后端 Python 环境并同步依赖..."
  uv sync --directory backend || {
    echo "[错误] 后端依赖环境创建失败。" >&2
    read -rsp $'按回车键退出...\n'
    exit 1
  }
fi

if [ ! -x "backend/.venv/bin/python" ]; then
  echo "[错误] 未找到后端 Python 环境，请执行：uv sync --directory backend" >&2
  read -rsp $'按回车键退出...\n'
  exit 1
fi

echo "[提示] 模型不会在启动时下载，请在软件“设置”页面手动下载。"
echo "[提示] 修改后端代码后需关闭 Terminal 重新启动。"
echo "[启动] 正在启动 后端 + 前端 + Electron ..."
echo ""

node electron/dev-runner.js
EXIT_CODE=$?
read -rsp $'按回车键退出...\n'
exit "$EXIT_CODE"
