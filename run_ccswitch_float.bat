@echo off
setlocal
set "SCRIPT=%~dp0ccswitch_balance_float.py"

where pythonw.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" pythonw.exe "%SCRIPT%"
  exit /b 0
)

where py.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" py.exe -3 "%SCRIPT%"
  exit /b 0
)

start "" python.exe "%SCRIPT%"
