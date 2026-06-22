@echo off
setlocal

set "FLOAT=%~dp0run_ccswitch_float.bat"
set "CCSWITCH="

if exist "%LOCALAPPDATA%\Programs\CC Switch\cc-switch.exe" (
  set "CCSWITCH=%LOCALAPPDATA%\Programs\CC Switch\cc-switch.exe"
)

if not defined CCSWITCH if exist "%ProgramFiles%\CC Switch\cc-switch.exe" (
  set "CCSWITCH=%ProgramFiles%\CC Switch\cc-switch.exe"
)

if not defined CCSWITCH if exist "%ProgramFiles(x86)%\CC Switch\cc-switch.exe" (
  set "CCSWITCH=%ProgramFiles(x86)%\CC Switch\cc-switch.exe"
)

if defined CCSWITCH (
  start "" "%CCSWITCH%"
)

call "%FLOAT%"
