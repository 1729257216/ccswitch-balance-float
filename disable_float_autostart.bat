@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'CCSwitch Balance Float.lnk'; if (Test-Path $shortcut) { Remove-Item -LiteralPath $shortcut -Force }; Get-CimInstance Win32_Process -Filter 'name = ''pythonw.exe'' or name = ''python.exe''' | Where-Object { $_.CommandLine -like '*ccswitch_balance_float.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Autostart disabled. The floating window has been closed.
pause
