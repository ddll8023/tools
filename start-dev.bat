@echo off
setlocal
chcp 65001 >nul
title 工具盒子 Dev
cd /d "%~dp0"

echo.
echo === 工具盒子 开发模式 ===
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Node.js，请先安装 Node.js 18 或更高版本。
  pause
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 npm，请检查 Node.js 安装。
  pause
  exit /b 1
)
where uv >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 uv，请先安装 uv。
  pause
  exit /b 1
)

set NEED_ROOT_INSTALL=0
if not exist "node_modules\.bin\tsc.cmd" set NEED_ROOT_INSTALL=1
if not exist "node_modules\.bin\electron.cmd" set NEED_ROOT_INSTALL=1
if "%NEED_ROOT_INSTALL%"=="1" (
  echo [依赖] 安装根目录 Node 依赖...
  call npm install
  if errorlevel 1 (
    echo [错误] 根目录 Node 依赖安装失败。
    pause
    exit /b 1
  )
)

if not exist "frontend\node_modules\.bin\vite.cmd" (
  echo [依赖] 安装前端 Node 依赖...
  call npm --prefix frontend install
  if errorlevel 1 (
    echo [错误] 前端 Node 依赖安装失败。
    pause
    exit /b 1
  )
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [依赖] 创建后端 Python 环境并同步依赖...
  call uv sync --directory backend
  if errorlevel 1 (
    echo [错误] 后端依赖环境创建失败。
    pause
    exit /b 1
  )
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [错误] 未找到后端 Python 环境，请执行：uv sync --directory backend
  pause
  exit /b 1
)

echo [提示] 模型不会在启动时下载，请在软件“设置”页面手动下载。
echo [提示] 修改后端代码后需 Ctrl+C 退出并重新启动。
echo [启动] 正在启动 后端 + 前端 + Electron ...
echo.

node electron/dev-runner.js
set EXIT_CODE=%errorlevel%
pause
exit /b %EXIT_CODE%
