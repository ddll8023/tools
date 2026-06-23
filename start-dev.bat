@echo off
chcp 65001 >nul
title 工具盒子 Dev
cd /d "%~dp0"
echo.
echo === 工具盒子 开发模式 ===
echo.
call npx tsc -p electron\tsconfig.json
if %errorlevel% neq 0 (
  echo [错误] TypeScript 编译失败
  pause
  exit /b %errorlevel%
)
echo [启动] 正在启动 后端 + 前端 + Electron ...
echo [提示] 首次启动后端需要约 2GB 模型下载
echo [提示] 修改后端代码后需 Ctrl+C 退出后重新启动
echo.
node electron/dev-runner.js
pause