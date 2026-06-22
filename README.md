# CCSwitch Balance Float

A small always-on-top balance floating window for CC Switch.

## Features

- Shows the current Codex provider name and balance, for example `aixj.vip 23.72 USD`
- Stays on top
- Drag with left mouse button; the position is saved
- Single left click opens or focuses the CC Switch main window
- Click the visible `刷新` button to query the balance manually
- Right-click menu supports refresh, open CC Switch, and exit
- Reads the current provider from `%USERPROFILE%\.cc-switch\cc-switch.db`
- Stores the floating window position under `%APPDATA%\CCSwitchBalanceFloat`
- Finds CC Switch from `%LOCALAPPDATA%\Programs\CC Switch`, `%ProgramFiles%\CC Switch`, or `%ProgramFiles(x86)%\CC Switch`
- Uses the provider's `autoQueryInterval` as the balance refresh interval
- Prevents duplicate floating windows from opening

## Start

Double-click `run_ccswitch_float.bat` to start only the floating window.

Double-click `start_ccswitch_with_float.bat` to start CC Switch and the floating window together.

You can also run:

```powershell
python .\ccswitch_balance_float.py
```

Test one balance read:

```powershell
python .\ccswitch_balance_float.py --once
```
