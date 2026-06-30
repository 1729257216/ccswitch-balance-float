@echo off
setlocal

set "CCFLOAT_TARGET=%~dp0start_ccswitch_with_float.bat"
set "CCFLOAT_WORKDIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'CCSwitch Balance Float.lnk'; $shell=New-Object -ComObject WScript.Shell; $link=$shell.CreateShortcut($shortcut); $link.TargetPath=$env:CCFLOAT_TARGET; $link.WorkingDirectory=$env:CCFLOAT_WORKDIR; $link.IconLocation=$env:CCFLOAT_TARGET; $link.Save();"

call "%~dp0run_ccswitch_float.bat"
echo Autostart enabled. The floating window has been started.
pause
