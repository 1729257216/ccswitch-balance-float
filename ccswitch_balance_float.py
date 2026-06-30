from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import math
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import font as tkfont


APP_NAME = "CCSwitch Balance Float"
MUTEX_NAME = "Local\\CCSwitchBalanceFloat"
MUTEX_HANDLE = None
USER_HOME = Path(os.environ.get("USERPROFILE") or Path.home())
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA") or (USER_HOME / "AppData" / "Local"))
ROAMING_APPDATA = Path(os.environ.get("APPDATA") or (USER_HOME / "AppData" / "Roaming"))

DB_PATH = USER_HOME / ".cc-switch" / "cc-switch.db"
SETTINGS_JSON_PATH = USER_HOME / ".cc-switch" / "settings.json"

CONFIG_DIR = ROAMING_APPDATA / "CCSwitchBalanceFloat"
CONFIG_PATH = CONFIG_DIR / "settings.json"

WINDOW_WIDTH = 110
WINDOW_HEIGHT = 30
PROVIDER_NAME_MAX_CHARS = 6
POLL_SECONDS = 2.0
DEFAULT_QUERY_SECONDS = 30
AUTO_REFRESH_CONFIG_KEY = "auto_refresh_seconds"
AUTO_REFRESH_PROVIDER = "provider"
AUTO_REFRESH_NEVER = "never"
AUTO_REFRESH_OPTIONS = (
    ("Provider default", AUTO_REFRESH_PROVIDER, None),
    ("1 minute", "60", 60),
    ("3 minutes", "180", 180),
    ("10 minutes", "600", 600),
    ("Never auto refresh", AUTO_REFRESH_NEVER, None),
)
NORMAL_ALPHA = 0.96
PRESSED_ALPHA = 0.88
ANIMATION_FRAME_MS = 16
ENTER_DURATION_MS = 240
ENTER_START_SCALE = 0.85
PRESS_DURATION_MS = 90
RELEASE_DURATION_MS = 140
SNAP_DURATION_MS = 180
SUCCESS_FLASH_MS = 220
PULSE_SECONDS = 1.2
DRAG_THRESHOLD = 4
TRANSPARENT = "#010203"


@dataclass
class ProviderConfig:
    provider_id: str
    name: str
    meta: dict[str, Any]
    settings_config: dict[str, Any]


@dataclass
class BalanceResult:
    provider_id: str
    provider_name: str
    amount: str | None
    unit: str
    status: str
    interval_seconds: int
    ok: bool


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config() -> dict[str, Any]:
    return load_json_file(CONFIG_PATH)


def save_config(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


def ease_out_cubic(progress: float) -> float:
    progress = clamp(progress, 0.0, 1.0)
    return 1 - (1 - progress) ** 3


def ease_out_back(progress: float) -> float:
    progress = clamp(progress, 0.0, 1.0)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (progress - 1) ** 3 + c1 * (progress - 1) ** 2


def smoothstep(progress: float) -> float:
    progress = clamp(progress, 0.0, 1.0)
    return progress * progress * (3 - 2 * progress)


def blend_color(start: str, end: str, progress: float) -> str:
    progress = clamp(progress, 0.0, 1.0)
    start = start.lstrip("#")
    end = end.lstrip("#")
    channels = []
    for index in range(0, 6, 2):
        start_value = int(start[index : index + 2], 16)
        end_value = int(end[index : index + 2], 16)
        channels.append(round(lerp(start_value, end_value, progress)))
    return f"#{channels[0]:02x}{channels[1]:02x}{channels[2]:02x}"


def windows_allows_animation() -> bool:
    if os.name != "nt":
        return True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enabled = wintypes.BOOL()
        if user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except Exception:
        pass
    return True


def animations_enabled(config: dict[str, Any]) -> bool:
    reduce_motion = config.get("reduce_motion")
    if isinstance(reduce_motion, bool):
        return not reduce_motion
    return windows_allows_animation()


def auto_refresh_mode(config: dict[str, Any]) -> str:
    if AUTO_REFRESH_CONFIG_KEY not in config:
        return AUTO_REFRESH_PROVIDER

    value = config.get(AUTO_REFRESH_CONFIG_KEY)
    if value == AUTO_REFRESH_PROVIDER:
        return AUTO_REFRESH_PROVIDER
    if value is None:
        return AUTO_REFRESH_NEVER

    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return AUTO_REFRESH_PROVIDER

    valid_seconds = {seconds_value for _, _, seconds_value in AUTO_REFRESH_OPTIONS if seconds_value is not None}
    return str(seconds) if seconds in valid_seconds else AUTO_REFRESH_PROVIDER


def cc_switch_exe_candidates() -> list[Path]:
    candidates = [
        LOCAL_APPDATA / "Programs" / "CC Switch" / "cc-switch.exe",
    ]
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "CC Switch" / "cc-switch.exe")
    return candidates


def find_ccswitch_exe() -> Path | None:
    for candidate in cc_switch_exe_candidates():
        if candidate.exists():
            return candidate
    return None


def sqlite_ro_connection() -> sqlite3.Connection:
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_current_provider() -> ProviderConfig | None:
    if not DB_PATH.exists():
        return None

    try:
        with sqlite_ro_connection() as conn:
            row = conn.execute(
                """
                select id, name, meta, settings_config
                from providers
                where app_type = 'codex' and is_current = 1
                limit 1
                """
            ).fetchone()

            if row is None:
                settings = load_json_file(SETTINGS_JSON_PATH)
                provider_id = settings.get("currentProviderCodex")
                if provider_id:
                    row = conn.execute(
                        """
                        select id, name, meta, settings_config
                        from providers
                        where app_type = 'codex' and id = ?
                        limit 1
                        """,
                        (provider_id,),
                    ).fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        return None

    return ProviderConfig(
        provider_id=str(row["id"]),
        name=str(row["name"] or "CC Switch"),
        meta=parse_json_object(row["meta"]),
        settings_config=parse_json_object(row["settings_config"]),
    )


def nested_get(data: dict[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def find_api_key(provider: ProviderConfig, usage_script: dict[str, Any]) -> str:
    return str(
        first_present(
            usage_script.get("apiKey"),
            nested_get(provider.settings_config, "auth", "OPENAI_API_KEY"),
            nested_get(provider.settings_config, "auth", "apiKey"),
            nested_get(provider.settings_config, "env", "OPENAI_API_KEY"),
            nested_get(provider.settings_config, "env", "ANTHROPIC_AUTH_TOKEN"),
        )
        or ""
    )


def js_unescape(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except Exception:
        return value


def extract_js_string(source: str, key: str) -> str | None:
    pattern = rf"(?<![\w$]){re.escape(key)}\s*:\s*([\"'`])((?:\\.|(?!\1).)*?)\1"
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        return None
    return js_unescape(match.group(2))


def extract_js_headers(source: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    match = re.search(r"headers\s*:\s*\{(?P<body>.*?)\}", source, re.DOTALL)
    if not match:
        return headers

    body = match.group("body")
    for item in re.finditer(
        r"(?:[\"'](?P<qkey>[^\"']+)[\"']|(?P<ukey>[A-Za-z0-9_-]+))\s*:\s*([\"'`])(?P<value>(?:\\.|(?!\3).)*?)\3",
        body,
        re.DOTALL,
    ):
        key = item.group("qkey") or item.group("ukey")
        value = js_unescape(item.group("value"))
        if key:
            headers[key] = value
    return headers


def render_template(value: str, replacements: dict[str, str]) -> str:
    rendered = value
    for key, replacement in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", replacement)
    return rendered


def usage_interval(usage_script: dict[str, Any]) -> int:
    raw = usage_script.get("autoQueryInterval", DEFAULT_QUERY_SECONDS)
    try:
        interval = int(float(raw))
        return max(5, min(interval, 3600))
    except Exception:
        return DEFAULT_QUERY_SECONDS


def get_provider_interval(provider: ProviderConfig) -> int:
    usage_script = provider.meta.get("usage_script")
    if not isinstance(usage_script, dict):
        return DEFAULT_QUERY_SECONDS
    return usage_interval(usage_script)


def build_request(provider: ProviderConfig) -> tuple[str, str, dict[str, str], bytes | None, int]:
    usage_script = provider.meta.get("usage_script")
    if not isinstance(usage_script, dict):
        usage_script = {}

    code = str(usage_script.get("code") or "")
    api_key = find_api_key(provider, usage_script)
    base_url = str(usage_script.get("baseUrl") or "").rstrip("/")
    replacements = {
        "apiKey": api_key,
        "OPENAI_API_KEY": api_key,
        "baseUrl": base_url,
    }

    url = extract_js_string(code, "url")
    if not url and base_url:
        url = f"{base_url}/v1/usage"
    if not url:
        raise RuntimeError("No usage URL")

    method = extract_js_string(code, "method") or "GET"
    headers = extract_js_headers(code)

    url = render_template(url, replacements)
    headers = {key: render_template(value, replacements) for key, value in headers.items()}

    if "Authorization" not in headers and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.setdefault("Accept", "application/json")
    headers.setdefault("User-Agent", "CCSwitchBalanceFloat/1.0")

    body = extract_js_string(code, "body")
    data = render_template(body, replacements).encode("utf-8") if body else None
    timeout = int(float(usage_script.get("timeout", 10) or 10))

    return url, method.upper(), headers, data, max(3, min(timeout, 60))


def to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def pick_amount(data: Any) -> tuple[Decimal | None, str]:
    if not isinstance(data, dict):
        return None, "USD"

    containers: list[dict[str, Any]] = [data]
    for key in ("data", "usage", "quota", "subscription", "account"):
        nested = data.get(key)
        if isinstance(nested, dict):
            containers.append(nested)

    keys = (
        "remaining",
        "balance",
        "available_balance",
        "availableBalance",
        "available",
        "credit",
        "credits",
        "quota_remaining",
        "remaining_quota",
        "remain",
    )

    for container in containers:
        for key in keys:
            amount = to_decimal(container.get(key))
            if amount is not None:
                unit = str(
                    first_present(
                        container.get("unit"),
                        container.get("currency"),
                        data.get("unit"),
                        data.get("currency"),
                        "USD",
                    )
                ).upper()
                return amount, unit

    return None, str(first_present(data.get("unit"), data.get("currency"), "USD")).upper()


def format_amount(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("0.01"))
    return f"{rounded:,.2f}"


def compact_provider_name(name: str) -> str:
    name = name.strip() or "CC"
    if len(name) <= PROVIDER_NAME_MAX_CHARS:
        return name
    return f"{name[:PROVIDER_NAME_MAX_CHARS]}..."


def format_balance_value(amount: str, unit: str) -> str:
    unit = (unit or "").strip().upper()
    if unit == "USD":
        return f"${amount}"
    if unit:
        return f"{amount} {unit}"
    return amount


def query_balance(provider: ProviderConfig) -> BalanceResult:
    usage_script = provider.meta.get("usage_script")
    if not isinstance(usage_script, dict) or usage_script.get("enabled") is False:
        return BalanceResult(
            provider.provider_id,
            provider.name,
            None,
            "USD",
            "Usage script disabled",
            DEFAULT_QUERY_SECONDS,
            False,
        )

    interval = usage_interval(usage_script)

    try:
        url, method, headers, data, timeout = build_request(provider)
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8-sig"))
        amount, unit = pick_amount(payload)
        if amount is None:
            return BalanceResult(provider.provider_id, provider.name, None, unit, "No balance field", interval, False)
        return BalanceResult(provider.provider_id, provider.name, format_amount(amount), unit, "Updated", interval, True)
    except urllib.error.HTTPError as exc:
        return BalanceResult(provider.provider_id, provider.name, None, "USD", f"HTTP {exc.code}", interval, False)
    except (TimeoutError, socket.timeout):
        return BalanceResult(provider.provider_id, provider.name, None, "USD", "Timeout", interval, False)
    except urllib.error.URLError:
        return BalanceResult(provider.provider_id, provider.name, None, "USD", "Network error", interval, False)
    except Exception as exc:
        return BalanceResult(provider.provider_id, provider.name, None, "USD", type(exc).__name__, interval, False)


def find_ccswitch_window() -> int | None:
    user32 = ctypes.windll.user32
    candidates: list[int] = []

    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip().lower()
        if title == "cc switch" or (title.startswith("cc switch") and "balance" not in title):
            candidates.append(hwnd)
        return True

    user32.EnumWindows(enum_proc_type(enum_proc), 0)
    return candidates[0] if candidates else None


def focus_or_start_ccswitch() -> None:
    try:
        hwnd = find_ccswitch_window()
        if hwnd:
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return
    except Exception:
        pass

    cc_switch_exe = find_ccswitch_exe()
    if cc_switch_exe:
        try:
            subprocess.Popen([str(cc_switch_exe)], close_fds=True)
        except Exception:
            pass


def rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs: Any) -> None:
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


class BalanceWindow:
    def __init__(self) -> None:
        self.config = load_config()
        self.motion_enabled = animations_enabled(self.config)

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0 if self.motion_enabled else NORMAL_ALPHA)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=TRANSPARENT,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.value_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.status_font = tkfont.Font(family="Segoe UI", size=8)
        self.font_cache: dict[int, tkfont.Font] = {}

        self.provider_id = ""
        self.provider_name = "CC Switch"
        self.amount = None
        self.unit = "USD"
        self.status = "Loading..."
        self.ok = False
        self.next_query_at = 0.0
        self.query_interval = DEFAULT_QUERY_SECONDS
        self.auto_refresh_mode = auto_refresh_mode(self.config)
        self.auto_refresh_var = tk.StringVar(value=self.auto_refresh_mode)
        self.worker_running = False
        self.querying = False
        self.stop_event = threading.Event()
        self.drag_start: tuple[int, int, int, int] | None = None
        self.drag_moved = False
        self.real_x = 0
        self.real_y = 0
        self.visual_scale = ENTER_START_SCALE if self.motion_enabled else 1.0
        self.window_alpha = 0.0 if self.motion_enabled else NORMAL_ALPHA
        self.flash_progress = 0.0
        self.animation_tokens: dict[str, int] = {}
        self.pulse_after_id: str | None = None

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Refresh now", command=self.force_refresh)
        self.auto_refresh_menu = tk.Menu(self.menu, tearoff=False)
        for label, value, _seconds in AUTO_REFRESH_OPTIONS:
            self.auto_refresh_menu.add_radiobutton(
                label=label,
                value=value,
                variable=self.auto_refresh_var,
                command=self.apply_auto_refresh_selection,
            )
        self.menu.add_cascade(label="Auto refresh", menu=self.auto_refresh_menu)
        self.menu.add_command(label="Open CC Switch", command=focus_or_start_ccswitch)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.quit)

        self.place_window()
        self.bind_events()
        self.draw()
        self.start_enter_animation()
        self.root.after(100, self.tick)

    def place_window(self) -> None:
        x = self.config.get("x")
        y = self.config.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            screen_w = self.root.winfo_screenwidth()
            x = max(10, screen_w - WINDOW_WIDTH - 24)
            y = 90
        x, y = self.clamp_position(x, y)
        self.set_position(x, y)

    def set_position(self, x: float, y: float) -> None:
        self.real_x = int(round(x))
        self.real_y = int(round(y))
        self.apply_window_geometry()

    def scaled_size(self) -> tuple[int, int]:
        scale = clamp(self.visual_scale, 0.7, 1.15)
        return max(1, round(WINDOW_WIDTH * scale)), max(1, round(WINDOW_HEIGHT * scale))

    def apply_window_geometry(self) -> None:
        width, height = self.scaled_size()
        visual_x = round(self.real_x + (WINDOW_WIDTH - width) / 2)
        visual_y = round(self.real_y + (WINDOW_HEIGHT - height) / 2)
        self.root.geometry(f"{width}x{height}+{visual_x}+{visual_y}")
        self.canvas.configure(width=width, height=height)

    def clamp_position(self, x: float, y: float) -> tuple[int, int]:
        max_x = max(0, self.root.winfo_screenwidth() - WINDOW_WIDTH)
        max_y = max(0, self.root.winfo_screenheight() - WINDOW_HEIGHT)
        return int(round(clamp(x, 0, max_x))), int(round(clamp(y, 0, max_y)))

    def save_position(self) -> None:
        config = load_config()
        config["x"] = self.real_x
        config["y"] = self.real_y
        save_config(config)

    def apply_auto_refresh_selection(self) -> None:
        mode = self.auto_refresh_var.get()
        self.auto_refresh_mode = mode
        config = load_config()
        if mode == AUTO_REFRESH_PROVIDER:
            config.pop(AUTO_REFRESH_CONFIG_KEY, None)
        elif mode == AUTO_REFRESH_NEVER:
            config[AUTO_REFRESH_CONFIG_KEY] = None
        else:
            try:
                config[AUTO_REFRESH_CONFIG_KEY] = int(mode)
            except ValueError:
                config.pop(AUTO_REFRESH_CONFIG_KEY, None)
                self.auto_refresh_mode = AUTO_REFRESH_PROVIDER
                self.auto_refresh_var.set(AUTO_REFRESH_PROVIDER)
        save_config(config)

        self.query_interval = self.current_query_interval(self.query_interval)
        self.next_query_at = float("inf") if self.query_interval <= 0 else time.time() + self.query_interval

    def current_query_interval(self, provider_interval: int) -> int:
        mode = self.auto_refresh_mode
        if mode == AUTO_REFRESH_NEVER:
            return 0
        if mode == AUTO_REFRESH_PROVIDER:
            return provider_interval
        try:
            return max(1, int(mode))
        except ValueError:
            return provider_interval

    def set_window_alpha(self, alpha: float) -> None:
        self.window_alpha = clamp(alpha, 0.0, NORMAL_ALPHA)
        try:
            self.root.attributes("-alpha", self.window_alpha)
        except tk.TclError:
            pass

    def animate(
        self,
        name: str,
        duration_ms: int,
        update: Any,
        easing: Any = ease_out_cubic,
        done: Any | None = None,
    ) -> None:
        self.animation_tokens[name] = self.animation_tokens.get(name, 0) + 1
        token = self.animation_tokens[name]

        if not self.motion_enabled or duration_ms <= 0:
            update(1.0)
            if done:
                done()
            return

        started_at = time.monotonic()

        def step() -> None:
            if self.stop_event.is_set() or self.animation_tokens.get(name) != token:
                return

            raw_progress = ((time.monotonic() - started_at) * 1000) / duration_ms
            progress = easing(raw_progress)
            update(progress)

            if raw_progress >= 1:
                update(easing(1.0))
                if done:
                    done()
                return

            self.root.after(ANIMATION_FRAME_MS, step)

        step()

    def cancel_animation(self, name: str) -> None:
        self.animation_tokens[name] = self.animation_tokens.get(name, 0) + 1

    def animate_visual_to(self, scale: float, alpha: float, duration_ms: int, easing: Any = ease_out_cubic) -> None:
        start_scale = self.visual_scale
        start_alpha = self.window_alpha

        def update(progress: float) -> None:
            self.visual_scale = lerp(start_scale, scale, progress)
            self.apply_window_geometry()
            self.set_window_alpha(lerp(start_alpha, alpha, progress))
            self.draw()

        self.animate("visual", duration_ms, update, easing)

    def start_enter_animation(self) -> None:
        if not self.motion_enabled:
            self.visual_scale = 1.0
            self.set_window_alpha(NORMAL_ALPHA)
            self.draw()
            return

        self.animate_visual_to(1.0, NORMAL_ALPHA, ENTER_DURATION_MS, ease_out_back)

    def bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.show_menu)

    def show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def on_press(self, event: tk.Event) -> None:
        self.cancel_animation("position")
        self.drag_start = (event.x_root, event.y_root, self.real_x, self.real_y)
        self.drag_moved = False
        self.animate_visual_to(0.94, PRESSED_ALPHA, PRESS_DURATION_MS, smoothstep)

    def on_drag(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        start_x, start_y, win_x, win_y = self.drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) > DRAG_THRESHOLD and not self.drag_moved:
            self.drag_moved = True
            self.animate_visual_to(1.0, NORMAL_ALPHA, RELEASE_DURATION_MS, ease_out_cubic)
        self.set_position(win_x + dx, win_y + dy)

    def on_release(self, event: tk.Event) -> None:
        if self.drag_moved:
            self.animate_visual_to(1.0, NORMAL_ALPHA, RELEASE_DURATION_MS, ease_out_cubic)
            self.snap_to_edge()
        else:
            self.animate_visual_to(1.0, NORMAL_ALPHA, RELEASE_DURATION_MS, ease_out_back)
            self.force_refresh()
        self.drag_start = None

    def snap_to_edge(self) -> None:
        current_x, current_y = self.clamp_position(self.real_x, self.real_y)
        screen_w = self.root.winfo_screenwidth()
        target_x = 0 if current_x + WINDOW_WIDTH / 2 < screen_w / 2 else screen_w - WINDOW_WIDTH
        target_x, target_y = self.clamp_position(target_x, current_y)

        if not self.motion_enabled:
            self.set_position(target_x, target_y)
            self.save_position()
            return

        start_x = self.real_x
        start_y = self.real_y

        def update(progress: float) -> None:
            self.set_position(lerp(start_x, target_x, progress), lerp(start_y, target_y, progress))

        self.animate("position", SNAP_DURATION_MS, update, ease_out_cubic, self.save_position)

    def scaled_font(self, base_size: int) -> tkfont.Font:
        size = max(6, round(base_size * clamp(self.visual_scale, 0.7, 1.15)))
        font = self.font_cache.get(size)
        if font is None:
            font = tkfont.Font(family="Segoe UI", size=size, weight="bold")
            self.font_cache[size] = font
        return font

    def start_query_pulse(self) -> None:
        if not self.motion_enabled or self.pulse_after_id is not None:
            return

        def pulse() -> None:
            self.pulse_after_id = None
            if self.stop_event.is_set() or not self.querying:
                return
            self.draw()
            self.pulse_after_id = self.root.after(ANIMATION_FRAME_MS, pulse)

        self.pulse_after_id = self.root.after(ANIMATION_FRAME_MS, pulse)

    def stop_query_pulse(self) -> None:
        if self.pulse_after_id is None:
            return
        try:
            self.root.after_cancel(self.pulse_after_id)
        except tk.TclError:
            pass
        self.pulse_after_id = None

    def start_success_flash(self) -> None:
        self.flash_progress = 1.0

        def update(progress: float) -> None:
            self.flash_progress = 1.0 - progress
            self.draw()

        self.animate("flash", SUCCESS_FLASH_MS, update, ease_out_cubic)

    def truncate_to_width(self, text: str, max_width: int, font: tkfont.Font) -> str:
        if font.measure(text) <= max_width:
            return text
        ellipsis = "..."
        while text and font.measure(text + ellipsis) > max_width:
            text = text[:-1]
        return text + ellipsis if text else ellipsis

    def draw(self) -> None:
        self.canvas.delete("all")
        width, height = self.scaled_size()
        scale_x = width / WINDOW_WIDTH
        scale_y = height / WINDOW_HEIGHT
        scale = min(scale_x, scale_y)

        def sx(value: float) -> int:
            return round(value * scale_x)

        def sy(value: float) -> int:
            return round(value * scale_y)

        base_outline = "#2f80ed" if self.ok else "#3a3d45"
        outline = blend_color(base_outline, "#9dccff", self.flash_progress)
        rounded_rect(
            self.canvas,
            sx(1),
            sy(1),
            width - sx(1),
            height - sy(1),
            max(8, sx(16)),
            fill="#202226",
            outline=outline,
            width=max(1, round(scale)),
        )

        dot_color = "#22c55e" if self.ok else "#f59e0b"
        dot_scale = 1.0
        if self.querying and self.motion_enabled:
            wave = (math.sin((time.monotonic() * math.tau) / PULSE_SECONDS) + 1) / 2
            pulse = smoothstep(wave)
            dot_scale = 1.0 + 0.08 * pulse
            dot_color = blend_color(dot_color, "#d7fbe8" if self.ok else "#fde68a", 0.28 * pulse)
        dot_radius = max(3, round(4 * scale * dot_scale))
        dot_x = sx(14)
        dot_y = sy(15)
        self.canvas.create_oval(
            dot_x - dot_radius,
            dot_y - dot_radius,
            dot_x + dot_radius,
            dot_y + dot_radius,
            fill=dot_color,
            outline="",
        )

        value_font = self.scaled_font(10)

        if self.querying:
            display_text = "Updating..."
            text_color = "#c4c8d0"
        elif self.amount:
            name_text = compact_provider_name(self.provider_name)
            value_text = format_balance_value(self.amount, self.unit)
            value_width = value_font.measure(value_text)
            name_x = sx(24)
            value_x = width - sx(10)
            name_width = max(sx(8), value_x - name_x - value_width - sx(8))
            name_text = self.truncate_to_width(name_text, name_width, value_font)
            self.canvas.create_text(
                name_x,
                height // 2,
                anchor="w",
                text=name_text,
                fill="#f4f7fb",
                font=value_font,
            )
            self.canvas.create_text(
                value_x,
                height // 2,
                anchor="e",
                text=value_text,
                fill="#f4f7fb",
                font=value_font,
            )
            return
        else:
            display_text = f"{compact_provider_name(self.provider_name)} {self.status}"
            text_color = "#c4c8d0"

        display_text = self.truncate_to_width(display_text, width - sx(34), value_font)
        self.canvas.create_text(
            sx(24),
            height // 2,
            anchor="w",
            text=display_text,
            fill=text_color,
            font=value_font,
        )

    def apply_result(self, result: BalanceResult) -> None:
        self.stop_query_pulse()
        self.provider_id = result.provider_id
        self.provider_name = result.provider_name
        self.amount = result.amount
        self.unit = result.unit
        self.status = result.status
        self.query_interval = self.current_query_interval(result.interval_seconds)
        self.next_query_at = float("inf") if self.query_interval <= 0 else time.time() + self.query_interval
        self.ok = result.ok
        self.worker_running = False
        self.querying = False
        self.draw()
        if result.ok:
            self.start_success_flash()

    def apply_provider_waiting(self, provider: ProviderConfig, status: str) -> None:
        self.provider_id = provider.provider_id
        self.provider_name = provider.name
        self.amount = None
        self.status = status
        self.ok = False
        self.draw()

    def force_refresh(self) -> None:
        if self.worker_running:
            return
        self.next_query_at = 0
        self.status = "Refreshing..."
        self.draw()
        self.start_refresh_worker(force=True)

    def tick(self) -> None:
        self.start_refresh_worker(force=False)
        self.root.after(int(POLL_SECONDS * 1000), self.tick)

    def start_refresh_worker(self, force: bool) -> None:
        if not self.worker_running:
            self.worker_running = True
            if force:
                self.mark_querying()
            threading.Thread(target=self.refresh_worker, args=(force,), daemon=True).start()

    def refresh_worker(self, force: bool = False) -> None:
        try:
            provider = read_current_provider()
            if provider is None:
                self.root.after(0, self.apply_missing_provider)
                return

            now = time.time()
            provider_changed = provider.provider_id != self.provider_id
            if provider_changed:
                self.root.after(0, self.apply_provider_waiting, provider, "Loading...")

            auto_refresh_enabled = self.current_query_interval(get_provider_interval(provider)) > 0
            should_query = force or provider_changed or (auto_refresh_enabled and now >= self.next_query_at)
            if should_query:
                self.root.after(0, self.mark_querying)
                result = query_balance(provider)
                self.root.after(0, self.apply_result, result)
            else:
                self.root.after(0, self.apply_idle)
        except Exception as exc:
            self.root.after(0, self.apply_worker_error, type(exc).__name__)

    def apply_idle(self) -> None:
        self.worker_running = False
        self.querying = False
        self.stop_query_pulse()
        self.draw()

    def apply_worker_error(self, status: str) -> None:
        self.amount = None
        self.status = status
        self.ok = False
        self.worker_running = False
        self.querying = False
        self.stop_query_pulse()
        self.draw()

    def mark_querying(self) -> None:
        self.querying = True
        self.start_query_pulse()
        self.draw()

    def apply_missing_provider(self) -> None:
        self.stop_query_pulse()
        self.flash_progress = 0.0
        self.provider_id = ""
        self.provider_name = "CC Switch"
        self.amount = None
        self.unit = "USD"
        self.status = "No current provider"
        self.ok = False
        self.worker_running = False
        self.querying = False
        self.draw()

    def quit(self) -> None:
        self.stop_event.set()
        self.stop_query_pulse()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def run_once() -> int:
    provider = read_current_provider()
    if provider is None:
        print("No current Codex provider found.")
        return 1
    result = query_balance(provider)
    if result.amount:
        print(f"{compact_provider_name(result.provider_name)} {format_balance_value(result.amount, result.unit)}")
        return 0
    print(f"{compact_provider_name(result.provider_name)} {result.status}")
    return 2


def already_running() -> bool:
    global MUTEX_HANDLE
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    MUTEX_HANDLE = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    return ctypes.get_last_error() == 183


def main() -> int:
    if "--once" in sys.argv:
        return run_once()
    if already_running():
        return 0
    BalanceWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
