<div align="center">

# CCSwitch Balance Float

一个轻量的 CC Switch Codex 供应商余额悬浮胶囊。

[![Windows](https://img.shields.io/badge/Windows-0078D4?style=flat-square&logo=windows&logoColor=white)](#)
[![Python 3](https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![Tkinter](https://img.shields.io/badge/UI-Tkinter-2f80ed?style=flat-square)](#)
[![No extra dependencies](https://img.shields.io/badge/Dependencies-none-22c55e?style=flat-square)](#)

[English](README.md) | [中文](README.zh-CN.md)

</div>

## 概览

CCSwitch Balance Float 是一个 Windows 轻量悬浮窗，用于显示当前 CC Switch Codex 供应商及剩余额度，例如 `pro $49.32`。

它会从 `%USERPROFILE%\.cc-switch\cc-switch.db` 读取当前供应商，查询供应商的用量接口，并把一个紧凑、可拖拽、置顶显示的胶囊窗口放在桌面上。

## 功能

| 功能 | 说明 |
| --- | --- |
| 紧凑余额展示 | 显示截短后的供应商名称和余额，`USD` 会显示为 `$`。 |
| 窗口置顶 | 工作时也能持续看到余额。 |
| 柔和动效 | 支持入场、点击、刷新、成功反馈和贴边吸附动效。 |
| 手动刷新 | 单击胶囊，或在右键菜单中选择 `Refresh now`。 |
| 自动刷新控制 | 右键可选择供应商默认、1 分钟、3 分钟、10 分钟或永不自动刷新。 |
| 拖拽吸附 | 按住左键拖拽；松手后自动吸附到最近的屏幕左右边缘。 |
| 启动辅助脚本 | 提供启动、停止、开机自启相关脚本。 |
| 单实例保护 | 防止重复打开多个悬浮窗。 |

## 快速开始

只启动悬浮窗：

```powershell
.\run_ccswitch_float.bat
```

同时启动 CC Switch 和悬浮窗：

```powershell
.\start_ccswitch_with_float.bat
```

启用 Windows 开机自启，并立即启动悬浮窗：

```powershell
.\enable_float_autostart.bat
```

停止悬浮窗：

```powershell
.\stop_ccswitch_float.bat
```

关闭开机自启，并关闭悬浮窗：

```powershell
.\disable_float_autostart.bat
```

也可以直接运行 Python 脚本：

```powershell
python .\ccswitch_balance_float.py
```

测试读取一次余额：

```powershell
python .\ccswitch_balance_float.py --once
```

## 操作

| 操作 | 结果 |
| --- | --- |
| 单击 | 手动刷新余额。 |
| 左键拖拽 | 移动胶囊；松手后吸附到最近的左侧或右侧边缘。 |
| 右键 | 打开上下文菜单。 |
| `Refresh now` | 立即查询一次余额。 |
| `Open CC Switch` | 聚焦或启动 CC Switch 桌面应用。 |
| `Exit` | 关闭悬浮窗。 |

## 自动刷新

默认情况下，悬浮窗使用供应商配置中的 `autoQueryInterval`。右键菜单里的 `Auto refresh` 可以覆盖为：

- `Provider default`
- `1 minute`
- `3 minutes`
- `10 minutes`
- `Never auto refresh`

即使关闭自动刷新，也仍然可以单击胶囊或选择 `Refresh now` 手动刷新。

## 动效

默认跟随 Windows 的动画偏好。如果想强制减弱动效，可以编辑 `%APPDATA%\CCSwitchBalanceFloat\settings.json`：

```json
{
  "reduce_motion": true
}
```

## 配置

用户配置保存在：

```text
%APPDATA%\CCSwitchBalanceFloat\settings.json
```

常见字段：

| 字段 | 说明 |
| --- | --- |
| `x` / `y` | 保存的窗口位置。 |
| `auto_refresh_seconds` | 自动刷新覆盖值。可使用 `60`、`180`、`600`，或使用 `null` 表示永不自动刷新。 |
| `reduce_motion` | 设置为 `true` 后关闭非必要动效。 |

应用会从以下位置查找 CC Switch：

- `%LOCALAPPDATA%\Programs\CC Switch\cc-switch.exe`
- `%ProgramFiles%\CC Switch\cc-switch.exe`
- `%ProgramFiles(x86)%\CC Switch\cc-switch.exe`

## 故障排查

如果胶囊一直停在 `Loading...`，可以运行：

```powershell
python .\ccswitch_balance_float.py --once
```

如果命令能返回余额，重启悬浮窗：

```powershell
.\stop_ccswitch_float.bat
.\run_ccswitch_float.bat
```

如果提示找不到供应商，请确认 CC Switch 已选择当前 Codex 供应商。
