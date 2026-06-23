@echo off
chcp 65001 >nul
title 工具盒子 Dev
cd /d "%~dp0.."
echo [启动] 工具盒子 开发模式
call npm run compile:electron
if %errorlevel% neq 0 (
  echo [启动] TypeScript 编译失败
  pause
  exit /b %errorlevel%
)
call npm run dev
pause
