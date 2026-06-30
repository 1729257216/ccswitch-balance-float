# CCSwitch Balance Float

A small always-on-top balance floating window for CC Switch.

## Features

- Shows the current Codex provider name and balance, for example `aixj.v... $23.72`
- Stays on top
- Uses soft motion for enter, click feedback, refresh status, and drag edge snapping
- Drag with left mouse button; the position is saved
- Single-click the capsule to query the balance manually
- Right-click menu supports manual refresh, auto-refresh interval, open CC Switch, and exit
- Reads the current provider from `%USERPROFILE%\.cc-switch\cc-switch.db`
- Stores the floating window position under `%APPDATA%\CCSwitchBalanceFloat`
- Finds CC Switch from `%LOCALAPPDATA%\Programs\CC Switch`, `%ProgramFiles%\CC Switch`, or `%ProgramFiles(x86)%\CC Switch`
- Uses the provider's `autoQueryInterval` by default, with menu overrides for 1 minute, 3 minutes, 10 minutes, or never auto refresh
- Prevents duplicate floating windows from opening

## Start

Double-click `run_ccswitch_float.bat` to start only the floating window.

Double-click `start_ccswitch_with_float.bat` to start CC Switch and the floating window together.

Double-click `enable_float_autostart.bat` to start the floating window now and enable Windows startup.

Double-click `disable_float_autostart.bat` to close the floating window and disable Windows startup.

Double-click `stop_ccswitch_float.bat` to close the floating window without changing startup.

You can also run:

```powershell
python .\ccswitch_balance_float.py
```

Test one balance read:

```powershell
python .\ccswitch_balance_float.py --once
```

## Motion

The floating window follows the Windows animation preference by default. To force reduced motion, edit `%APPDATA%\CCSwitchBalanceFloat\settings.json`:

```json
{
  "reduce_motion": true
}
```

Auto-refresh menu choices are saved in the same file as `auto_refresh_seconds`.
