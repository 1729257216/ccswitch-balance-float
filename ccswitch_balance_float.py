from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
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

WINDOW_WIDTH = 100
WINDOW_HEIGHT = 30
PROVIDER_NAME_MAX_CHARS = 6
POLL_SECONDS = 2.0
DEFAULT_QUERY_SECONDS = 30
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
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
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

        self.provider_id = ""
        self.provider_name = "CC Switch"
        self.amount = None
        self.unit = "USD"
        self.status = "Loading..."
        self.ok = False
        self.next_query_at = 0.0
        self.query_interval = DEFAULT_QUERY_SECONDS
        self.worker_running = False
        self.querying = False
        self.stop_event = threading.Event()
        self.drag_start: tuple[int, int, int, int] | None = None
        self.drag_moved = False

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Refresh now", command=self.force_refresh)
        self.menu.add_command(label="Open CC Switch", command=focus_or_start_ccswitch)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.quit)

        self.place_window()
        self.bind_events()
        self.draw()
        self.root.after(100, self.tick)

    def place_window(self) -> None:
        config = load_config()
        x = config.get("x")
        y = config.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            screen_w = self.root.winfo_screenwidth()
            x = max(10, screen_w - WINDOW_WIDTH - 24)
            y = 90
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.show_menu)

    def show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def on_press(self, event: tk.Event) -> None:
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.drag_moved = False

    def on_drag(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        start_x, start_y, win_x, win_y = self.drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) > 4:
            self.drag_moved = True
        self.root.geometry(f"+{win_x + dx}+{win_y + dy}")

    def on_release(self, event: tk.Event) -> None:
        if self.drag_moved:
            config = load_config()
            config["x"] = self.root.winfo_x()
            config["y"] = self.root.winfo_y()
            save_config(config)
        else:
            self.force_refresh()
        self.drag_start = None

    def truncate_to_width(self, text: str, max_width: int, font: tkfont.Font) -> str:
        if font.measure(text) <= max_width:
            return text
        ellipsis = "..."
        while text and font.measure(text + ellipsis) > max_width:
            text = text[:-1]
        return text + ellipsis if text else ellipsis

    def draw(self) -> None:
        self.canvas.delete("all")
        rounded_rect(
            self.canvas,
            1,
            1,
            WINDOW_WIDTH - 1,
            WINDOW_HEIGHT - 1,
            16,
            fill="#202226",
            outline="#2f80ed" if self.ok else "#3a3d45",
            width=1,
        )

        dot_color = "#22c55e" if self.ok else "#f59e0b"
        self.canvas.create_oval(10, 11, 18, 19, fill=dot_color, outline="")

        if self.querying:
            display_text = "Updating..."
            text_color = "#c4c8d0"
        elif self.amount:
            name_text = compact_provider_name(self.provider_name)
            value_text = format_balance_value(self.amount, self.unit)
            value_width = self.value_font.measure(value_text)
            name_width = max(8, WINDOW_WIDTH - 34 - value_width - 8)
            name_text = self.truncate_to_width(name_text, name_width, self.value_font)
            self.canvas.create_text(
                24,
                WINDOW_HEIGHT // 2,
                anchor="w",
                text=name_text,
                fill="#f4f7fb",
                font=self.value_font,
            )
            self.canvas.create_text(
                WINDOW_WIDTH - 10,
                WINDOW_HEIGHT // 2,
                anchor="e",
                text=value_text,
                fill="#f4f7fb",
                font=self.value_font,
            )
            return
        else:
            display_text = f"{compact_provider_name(self.provider_name)} {self.status}"
            text_color = "#c4c8d0"

        display_text = self.truncate_to_width(display_text, WINDOW_WIDTH - 34, self.value_font)
        self.canvas.create_text(
            24,
            WINDOW_HEIGHT // 2,
            anchor="w",
            text=display_text,
            fill=text_color,
            font=self.value_font,
        )

    def apply_result(self, result: BalanceResult) -> None:
        self.provider_id = result.provider_id
        self.provider_name = result.provider_name
        self.amount = result.amount
        self.unit = result.unit
        self.status = result.status
        self.query_interval = result.interval_seconds
        self.next_query_at = time.time() + self.query_interval
        self.ok = result.ok
        self.worker_running = False
        self.querying = False
        self.draw()

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
                self.querying = True
                self.draw()
            threading.Thread(target=self.refresh_worker, args=(force,), daemon=True).start()

    def refresh_worker(self, force: bool = False) -> None:
        provider = read_current_provider()
        if provider is None:
            self.root.after(0, self.apply_missing_provider)
            return

        now = time.time()
        provider_changed = provider.provider_id != self.provider_id
        if provider_changed:
            self.root.after(0, self.apply_provider_waiting, provider, "Loading...")

        should_query = force or provider_changed or now >= self.next_query_at
        if should_query:
            self.root.after(0, self.mark_querying)
            result = query_balance(provider)
            self.root.after(0, self.apply_result, result)
        else:
            self.worker_running = False
            self.querying = False
            self.root.after(0, self.draw)

    def mark_querying(self) -> None:
        self.querying = True
        self.draw()

    def apply_missing_provider(self) -> None:
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
