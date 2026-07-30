#!/bin/bash
# 工具盒子 开发模式启动脚本（macOS）
# 双击此文件可在终端中启动开发环境（后端 + 前端 + Electron）

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
release_port 4740  # 后端
release_port 5173  # Vite

# 1. 编译 Electron 主进程
echo "[启动] 1/4 编译 Electron 主进程..."

if ! npx tsc -p electron/tsconfig.json; then
  echo "[错误] TypeScript 编译失败" >&2
  read -rsp $'按回车键退出...\n'
  exit 1
fi

echo "[启动] ✓ TypeScript 编译完成"

# 2. 确保 Python 虚拟环境存在
if [ ! -f "backend/.venv/bin/python" ]; then
  echo "[启动] Python 虚拟环境未找到，请先运行 cd backend && uv sync"
  read -rsp $'按回车键退出...\n'
  exit 1
fi

echo "[提示] 首次启动深度模式需下载约 2GB 模型"
echo "[提示] 修改后端代码后需关闭 Terminal 重新启动"
echo "[启动] 正在启动 后端 + 前端 + Electron ..."
echo ""

node electron/dev-runner.js

read -rsp $'按回车键退出...\n'
