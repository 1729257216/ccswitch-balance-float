@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter 'name = ''pythonw.exe'' or name = ''python.exe''' | Where-Object { $_.CommandLine -like '*ccswitch_balance_float.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo The floating window has been closed.
pause
