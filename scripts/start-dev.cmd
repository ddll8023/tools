@echo off
rem 工具盒子开发模式启动脚本（Windows）。
rem
rem 只做前置环境检查，不安装依赖、不下载 Electron：缺什么就拦下并提示获取方式，
rem 避免启动过程在后台改写 node_modules 或 backend\.venv。模型由设置页手动下载。
rem 退出前恢复开始时的代码页，不把 65001 留给调用它的终端。

for /f "tokens=2 delims=:" %%c in ('chcp') do set "oldcp=%%c"
chcp 65001 >nul
setlocal
title 工具盒子 Dev
cd /d "%~dp0.."

echo.
echo === 工具盒子 开发模式 ===
echo.

where node >nul 2>&1 || goto :no_node
where npm >nul 2>&1 || goto :no_npm
where uv >nul 2>&1 || goto :no_uv

if not exist "node_modules\electron\package.json" goto :no_root_deps
if not exist "node_modules\.bin\tsc.cmd" goto :no_root_deps
if not exist "node_modules\electron\dist\electron.exe" goto :no_electron_bin
if not exist "frontend\node_modules\.bin\vite.cmd" goto :no_frontend_deps
if not exist "backend\.venv\Scripts\python.exe" goto :no_backend_env

echo [提示] 模型不会在启动时下载，请在软件“设置”页面手动下载。
echo [提示] 修改后端代码后需关闭本窗口重新启动。
echo [启动] 正在启动 后端 + 前端 + Electron ...
echo.

node electron/dev-runner.js
set "code=%errorlevel%"

if defined oldcp chcp %oldcp% >nul
endlocal & exit /b %code%

:no_node
echo [错误] 未找到 Node.js，请先安装 Node.js 18 或更高版本。
goto :halt

:no_npm
echo [错误] 未找到 npm，请检查 Node.js 安装。
goto :halt

:no_uv
echo [错误] 未找到 uv，请先安装 uv。
echo        安装说明: https://docs.astral.sh/uv/getting-started/installation/
goto :halt

:no_root_deps
echo [错误] 根目录 Node 依赖未安装。
echo        请在本目录运行: npm install
goto :halt

:no_electron_bin
echo [错误] Electron 二进制缺失，无法启动桌面外壳。
echo        请运行: node node_modules\electron\install.js
goto :halt

:no_frontend_deps
echo [错误] 前端依赖未安装。
echo        请在本目录运行: npm --prefix frontend install
goto :halt

:no_backend_env
echo [错误] 后端 Python 环境未创建。
echo        请在本目录运行: uv sync --directory backend
goto :halt

:halt
echo.
pause
if defined oldcp chcp %oldcp% >nul
endlocal & exit /b 1
