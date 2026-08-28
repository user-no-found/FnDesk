#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DEST = Path(os.environ.get("TRIM_APPDEST", Path(__file__).resolve().parents[1]))
PKG_VAR = Path(os.environ.get("TRIM_PKGVAR", APP_DEST / "var"))
PORT = int(os.environ.get("TRIM_SERVICE_PORT", os.environ.get("PORT", "18733")))
WWW_ROOT = APP_DEST / "www"
CONFIG_FILE = Path("/etc/default/fndesk")
LEGACY_CONFIG_FILE = Path("/etc/default/web-kiosk")
LOG_FILE = PKG_VAR / "fndesk.log"
LOCAL_SERVICE = "fndesk-local.service"
DISPLAY_POWER_SERVICE = "fndesk-display-power.service"

COMMAND_TIMEOUT = 3
COMMAND_REAP_TIMEOUT = 0.25
STATUS_CACHE_SECONDS = 2

MONTH_NUMBERS = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run(command, timeout=COMMAND_TIMEOUT):
    """Run a helper without letting a stuck child pin an HTTP thread.

    subprocess.run() kills and then waits without another bound after a
    TimeoutExpired exception.  That wait can be permanent if the helper has
    entered uninterruptible kernel sleep, so both termination and reaping are
    bounded here.
    """

    command = [str(part) for part in command]
    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as exc:
        return subprocess.CompletedProcess(command, 1, str(exc))

    try:
        output, _ = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, output or "")
    except subprocess.TimeoutExpired as exc:
        output = _text(exc.output)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass

        try:
            final_output, _ = process.communicate(timeout=COMMAND_REAP_TIMEOUT)
            if final_output:
                output = final_output
        except subprocess.TimeoutExpired:
            # A D-state process cannot be reaped until its kernel operation
            # returns.  Leave it signalled instead of waiting on this request.
            if process.stdout is not None:
                process.stdout.close()

        suffix = "Command timed out; its process group was terminated."
        return subprocess.CompletedProcess(command, 124, f"{output}\n{suffix}".lstrip())


def parse_properties(output):
    properties = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            properties[key] = value
    return properties


def service_snapshot(unit):
    result = run(
        [
            "systemctl",
            "show",
            unit,
            "--no-pager",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--property=UnitFileState",
            "--property=Result",
        ]
    )
    properties = parse_properties(result.stdout)
    active = properties.get("ActiveState", "unknown")
    return {
        "name": unit,
        "active": active,
        "enabled": properties.get("UnitFileState", "unknown"),
        "failed": "failed" if active == "failed" else "inactive",
        "sub": properties.get("SubState", "unknown"),
        "result": properties.get("Result", "unknown"),
        "load": properties.get("LoadState", "unknown"),
        "code": result.returncode,
    }


def read_config_file(path):
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def read_config():
    data = read_config_file(CONFIG_FILE)
    if not data:
        data = read_config_file(LEGACY_CONFIG_FILE)
    return data


def journal_timestamp(line):
    parts = line.split(maxsplit=3)
    if len(parts) < 3:
        return ""
    month = MONTH_NUMBERS.get(parts[0], parts[0])
    return f"{month}-{parts[1].zfill(2)} {parts[2]}"


def localize_journal_line(line):
    if "Starting fndesk-local.service" in line:
        return "收到启动请求。"
    if "Started fndesk-local.service" in line:
        return "systemd 已启动 FnDesk 本地显示进程。"
    if "Stopping fndesk-local.service" in line:
        return "收到停止请求。"
    if "Stopped fndesk-local.service" in line:
        return "本地显示服务已停止。"
    if "Deactivated successfully" in line:
        return "本地显示服务已安全退出。"
    if "Created VT-bound seat" in line:
        return "已创建绑定 tty 的私有 seat。"
    if "seatd started" in line:
        return "私有 seatd 已启动。"
    if "New client connected" in line:
        return "Cage 已连接私有 seatd。"
    if "Client disconnected" in line:
        return "Cage 已断开私有 seatd。"
    if "FnDesk：" in line:
        return line.split("FnDesk：", 1)[1].strip()
    if "FnDesk local display: using DRM device " in line:
        device = line.split("FnDesk local display: using DRM device ", 1)[1].rstrip(".")
        return f"使用 DRM 设备：{device}。"
    if "no active Wayland output" in line:
        return "未检测到可用显示输出：未连接显示器或显示模式设置失败，正在安全退出。"
    if "Socket file found at socket path /run/seatd.sock" in line:
        return "检测到上一次运行残留的 seatd socket，本次启动被拒绝。"
    if "seatd exited prematurely" in line:
        return "私有 seatd 提前退出。"
    if "Main process exited" in line:
        detail = line.rsplit(":", 1)[-1].strip()
        return f"主进程退出：{detail}。"
    if "Failed with result" in line:
        return "服务启动失败，systemd 已记录失败状态。"
    if "amdgpu: unknown" in line:
        return "当前 Mesa 无法识别 AMD GPU，已进入兼容/软件渲染路径。"
    if "EGL_NOT_INITIALIZED" in line or "Failed to initialize EGL" in line:
        return "EGL 硬件渲染初始化失败。"
    if "Failed to initialize glamor" in line:
        return "Xwayland 硬件加速不可用，已回退到软件渲染。"
    if '"/root"' in line and ("权限不够" in line or "Permission denied" in line):
        return "旧版本错误地使用了 /root；当前版本已修复用户 HOME。"
    if "msedge_crashpad_handler: --database is required" in line:
        return "旧版本 Edge Crashpad 因 HOME 配置错误而启动失败。"
    if "wl_display_terminate: Assertion" in line:
        return "Cage 0.1.4 退出时触发上游断言；本次进程已退出，未形成 D 状态。"
    return None


def chinese_journal_summary(text):
    events = []
    last_event = None
    for line in text.splitlines():
        event = localize_journal_line(line)
        if event is None:
            continue
        timestamp = journal_timestamp(line)
        rendered = f"{timestamp}  {event}" if timestamp else event
        if rendered == last_event:
            continue
        events.append(rendered)
        last_event = rendered

    header = [
        "FnDesk 本地显示日志（中文摘要）",
        "仅显示关键事件；如需完整诊断信息，请点击“原始日志”。",
        "",
    ]
    if not events:
        return "\n".join(header + ["暂无可识别的关键事件。", ""])
    return "\n".join(header + events + [""])


def _unknown_service(unit):
    return {
        "name": unit,
        "active": "unknown",
        "enabled": "unknown",
        "failed": "unknown",
        "sub": "unknown",
        "result": "unknown",
        "load": "unknown",
        "code": 124,
    }


def build_status_payload():
    config = read_config()
    return {
        "time": int(time.time()),
        "stale": False,
        "services": {
            "local": service_snapshot(LOCAL_SERVICE),
            # Kept for response compatibility.  The UI intentionally performs
            # only one bounded systemd query per refresh.
            "displayPower": _unknown_service(DISPLAY_POWER_SERVICE),
        },
        # Never probe DRM connector files or the current VT from the Web
        # control plane: those reads can themselves enter D state after a KMS
        # hang.  The compositor reports display failures in its journal.
        "display": {
            "selected": config.get("KIOSK_OUTPUT", ""),
            "device": config.get("FNDESK_DRM_DEVICE", ""),
            "liveProbe": False,
            "items": [],
        },
        "tty": "",
        "config": {
            "kioskUser": config.get("KIOSK_USER", ""),
            "kioskOutput": config.get("KIOSK_OUTPUT", ""),
            "drmDevice": config.get("FNDESK_DRM_DEVICE", ""),
        },
    }


_STATUS_LOCK = threading.Lock()
_STATUS_CACHE = {"payload": None, "expires": 0.0}


def invalidate_status_cache():
    _STATUS_CACHE["expires"] = 0.0


def _cached_payload(stale):
    payload = _STATUS_CACHE["payload"]
    if payload is None:
        return {
            "time": int(time.time()),
            "stale": True,
            "services": {"local": _unknown_service(LOCAL_SERVICE)},
            "display": {"liveProbe": False, "items": []},
            "tty": "",
            "config": {},
        }
    payload = dict(payload)
    payload["stale"] = stale
    return payload


def status_payload():
    now = time.monotonic()
    if _STATUS_CACHE["payload"] is not None and now < _STATUS_CACHE["expires"]:
        return _cached_payload(False)

    if not _STATUS_LOCK.acquire(blocking=False):
        return _cached_payload(True)

    try:
        payload = build_status_payload()
        _STATUS_CACHE["payload"] = payload
        _STATUS_CACHE["expires"] = time.monotonic() + STATUS_CACHE_SECONDS
        return payload
    finally:
        _STATUS_LOCK.release()


LOCAL_ACTIONS = {
    "/api/local/start": (
        ["systemctl", "--no-block", "start", LOCAL_SERVICE],
        "启动本地 Edge",
    ),
    "/api/local/stop": (
        ["systemctl", "--no-block", "stop", LOCAL_SERVICE],
        "关闭本地 Edge",
    ),
    "/api/local/restart": (
        ["systemctl", "--no-block", "restart", LOCAL_SERVICE],
        "重启本地 Edge",
    ),
    "/api/local/reset-failed": (
        ["systemctl", "reset-failed", LOCAL_SERVICE],
        "重置失败状态",
    ),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path == "/api/status":
            self.send_json({"ok": True, "data": status_payload()})
            return
        if path == "/api/logs":
            lines = query.get("lines", ["160"])[0]
            try:
                line_count = max(20, min(800, int(lines)))
            except ValueError:
                line_count = 160
            unit = query.get("unit", ["local"])[0]
            if unit == "control":
                text = tail_file(LOG_FILE, line_count)
            else:
                result = run(
                    [
                        "journalctl",
                        "-u",
                        LOCAL_SERVICE,
                        "-b",
                        "-n",
                        str(line_count),
                        "--no-pager",
                    ],
                    timeout=5,
                )
                if query.get("format", ["summary"])[0] == "raw":
                    text = result.stdout
                else:
                    text = chinese_journal_summary(result.stdout)
            self.send_text(text)
            return
        if path in ("/", "/app/fndesk/", "/fndesk.html", "/vnc_lite.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        action = LOCAL_ACTIONS.get(path)
        if action is None:
            self.send_error(404)
            return
        command, label = action
        self.command_json(command, label)

    def command_json(self, command, label):
        result = run(command)
        invalidate_status_cache()
        self.send_json(command_payload(result, label))

    def send_json(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_text(self, text):
        raw = text.encode("utf-8", errors="replace")
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


def command_payload(result, label):
    accepted = result.returncode == 0
    return {
        "ok": accepted,
        "message": f"{label}{'请求已提交' if accepted else '失败'}",
        "code": result.returncode,
        "output": result.stdout,
    }


def tail_file(path, line_count):
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-line_count:]) + ("\n" if lines else "")


def main():
    PKG_VAR.mkdir(parents=True, exist_ok=True)
    httpd = ReusableThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
