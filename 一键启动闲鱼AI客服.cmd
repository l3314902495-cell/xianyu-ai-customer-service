@echo off
setlocal
title Xianyu AI Customer Service Launcher
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-xianyu-ai.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Please copy the error above to Codex.
  pause
)
exit /b %EXIT_CODE%
