@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0QinBan.exe" (
  echo QinBan.exe was not found. Please extract the complete portable ZIP first.
  pause
  exit /b 1
)
start "" "%~dp0QinBan.exe"
