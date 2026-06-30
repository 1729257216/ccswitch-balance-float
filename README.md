<div align="center">

# CCSwitch Balance Float

A tiny always-on-top balance capsule for CC Switch Codex providers.

[![Windows](https://img.shields.io/badge/Windows-0078D4?style=flat-square&logo=windows&logoColor=white)](#)
[![Python 3](https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![Tkinter](https://img.shields.io/badge/UI-Tkinter-2f80ed?style=flat-square)](#)
[![No extra dependencies](https://img.shields.io/badge/Dependencies-none-22c55e?style=flat-square)](#)

[English](README.md) | [中文](README.zh-CN.md)

</div>

## Overview

CCSwitch Balance Float is a lightweight Windows floating window that shows the current CC Switch Codex provider and its remaining balance, for example `pro $49.32`.

It reads the active provider from `%USERPROFILE%\.cc-switch\cc-switch.db`, queries the provider usage endpoint, and keeps a compact draggable capsule on top of other windows.

## Features

| Feature | Description |
| --- | --- |
| Compact balance display | Shows a shortened provider name and balance, with `USD` rendered as `$`. |
| Always on top | Keeps the balance visible while you work. |
| Soft motion | Uses gentle enter, click, refresh, success, and edge-snap motion. |
| Manual refresh | Single-click the capsule or choose `Refresh now` from the right-click menu. |
| Auto refresh control | Right-click to choose provider default, 1 minute, 3 minutes, 10 minutes, or never auto refresh. |
| Drag and snap | Drag with the left mouse button; release to snap to the nearest screen edge. |
| Startup helper scripts | Includes scripts for starting, stopping, and enabling Windows startup. |
| Single instance guard | Prevents duplicate floating windows from opening. |

## Quick Start

Start only the floating window:

```powershell
.\run_ccswitch_float.bat
```

Start CC Switch and the floating window together:

```powershell
.\start_ccswitch_with_float.bat
```

Enable Windows startup and start the floating window now:

```powershell
.\enable_float_autostart.bat
```

Stop the floating window:

```powershell
.\stop_ccswitch_float.bat
```

Disable Windows startup and close the floating window:

```powershell
.\disable_float_autostart.bat
```

You can also run the script directly:

```powershell
python .\ccswitch_balance_float.py
```

Test one balance read:

```powershell
python .\ccswitch_balance_float.py --once
```

## Controls

| Action | Result |
| --- | --- |
| Single click | Refreshes the balance manually. |
| Left-button drag | Moves the capsule; release snaps it to the nearest left or right edge. |
| Right click | Opens the context menu. |
| `Refresh now` | Runs an immediate balance query. |
| `Open CC Switch` | Focuses or starts the CC Switch desktop app. |
| `Exit` | Closes the floating window. |

## Auto Refresh

By default, the window uses the provider's `autoQueryInterval`. The right-click `Auto refresh` menu can override it with:

- `Provider default`
- `1 minute`
- `3 minutes`
- `10 minutes`
- `Never auto refresh`

Manual refresh remains available even when automatic refresh is disabled.

## Motion

The window follows the Windows animation preference by default. To force reduced motion, edit `%APPDATA%\CCSwitchBalanceFloat\settings.json`:

```json
{
  "reduce_motion": true
}
```

## Configuration

User settings are stored at:

```text
%APPDATA%\CCSwitchBalanceFloat\settings.json
```

Common fields:

| Field | Description |
| --- | --- |
| `x` / `y` | Saved window position. |
| `auto_refresh_seconds` | Auto-refresh override. Use `60`, `180`, `600`, or `null` for never auto refresh. |
| `reduce_motion` | Set to `true` to disable non-essential animation. |

The app discovers CC Switch from:

- `%LOCALAPPDATA%\Programs\CC Switch\cc-switch.exe`
- `%ProgramFiles%\CC Switch\cc-switch.exe`
- `%ProgramFiles(x86)%\CC Switch\cc-switch.exe`

## Troubleshooting

If the capsule stays on `Loading...`, run:

```powershell
python .\ccswitch_balance_float.py --once
```

If the command returns a balance, restart the floating window:

```powershell
.\stop_ccswitch_float.bat
.\run_ccswitch_float.bat
```

If no provider is found, make sure CC Switch has a current Codex provider selected.
