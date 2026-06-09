#!/usr/bin/env python3
import json
import os
import subprocess
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
LEGACY_LOCAL_SERVICE = "web-kiosk.service"
LEGACY_DISPLAY_POWER_SERVICE = "web-kiosk-display-power.service"


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def run(command, timeout=30):
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(command, 124, output + "\nCommand timed out.")
    except Exception as exc:
        return subprocess.CompletedProcess(command, 1, str(exc))


def service_value(*args):
    result = run(["systemctl", *args], timeout=10)
    return {
        "ok": result.returncode == 0,
        "code": result.returncode,
        "value": result.stdout.strip(),
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


def command_exists(name):
    return run(["/usr/bin/env", "sh", "-c", f"command -v {name} >/dev/null 2>&1"], timeout=5).returncode == 0


def display_status():
    displays = []
    for path in sorted(Path("/sys/class/drm").glob("*/status")):
        name = path.parent.name
        try:
            status = path.read_text(errors="ignore").strip()
        except OSError:
            status = "unknown"
        displays.append({"name": name, "status": status})
    connected = [item for item in displays if item["status"] == "connected"]
    config = read_config()
    selected = config.get("KIOSK_OUTPUT", "")
    selected_status = ""
    if selected:
        candidates = {selected, f"card0-{selected}"}
        for item in displays:
            if item["name"] in candidates or item["name"].endswith(f"-{selected}"):
                selected_status = item["status"]
                break
        if not selected_status:
            selected_status = "missing"
    return {
        "selected": selected,
        "selectedStatus": selected_status,
        "connected": len(connected),
        "items": displays,
    }


def package_status(name):
    result = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", name], timeout=10)
    return result.returncode == 0 and result.stdout.strip().startswith("ii")


def pidgrep(pattern):
    result = run(["pgrep", "-af", pattern], timeout=10)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def status_payload():
    config = read_config()
    local_active = service_value("is-active", LOCAL_SERVICE)
    local_enabled = service_value("is-enabled", LOCAL_SERVICE)
    local_failed = service_value("is-failed", LOCAL_SERVICE)
    power_active = service_value("is-active", DISPLAY_POWER_SERVICE)
    legacy_active = service_value("is-active", LEGACY_LOCAL_SERVICE)
    legacy_power_active = service_value("is-active", LEGACY_DISPLAY_POWER_SERVICE)
    show = run(["fgconsole"], timeout=5)
    return {
        "time": int(time.time()),
        "services": {
            "local": {
                "name": LOCAL_SERVICE,
                "active": local_active["value"],
                "enabled": local_enabled["value"],
                "failed": local_failed["value"],
                "code": local_active["code"],
            },
            "displayPower": {
                "name": DISPLAY_POWER_SERVICE,
                "active": power_active["value"],
                "code": power_active["code"],
            },
            "legacyLocal": {
                "name": LEGACY_LOCAL_SERVICE,
                "active": legacy_active["value"],
                "code": legacy_active["code"],
            },
            "legacyDisplayPower": {
                "name": LEGACY_DISPLAY_POWER_SERVICE,
                "active": legacy_power_active["value"],
                "code": legacy_power_active["code"],
            },
        },
        "display": display_status(),
        "tty": show.stdout.strip() if show.returncode == 0 else "",
        "config": {
            "kioskUser": config.get("KIOSK_USER", ""),
            "kioskOutput": config.get("KIOSK_OUTPUT", ""),
        },
        "packages": {
            "edge": package_status("microsoft-edge-stable"),
            "cage": package_status("cage"),
            "seatd": package_status("seatd"),
            "fcitx5": package_status("fcitx5"),
        },
        "processes": {
            "edge": pidgrep("microsoft-edge-stable"),
            "cage": pidgrep("cage .*fndesk|fndesk-local-launch"),
        },
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
                result = run(["journalctl", "-u", LOCAL_SERVICE, "-b", "-n", str(line_count), "--no-pager"], timeout=15)
                text = result.stdout
            self.send_text(text)
            return
        if path in ("/", "/app/fndesk/", "/fndesk.html", "/vnc_lite.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/local/start":
            self.command_json(["systemctl", "start", LOCAL_SERVICE], "启动本地 Edge")
            return
        if path == "/api/local/stop":
            self.command_json(["systemctl", "stop", LOCAL_SERVICE], "关闭本地 Edge")
            return
        if path == "/api/local/restart":
            self.command_json(["systemctl", "restart", LOCAL_SERVICE], "重启本地 Edge")
            return
        if path == "/api/local/tty1":
            self.command_json(["chvt", "1"], "切换到 tty1")
            return
        if path == "/api/local/reset-failed":
            self.command_json(["systemctl", "reset-failed", LOCAL_SERVICE], "重置失败状态")
            return
        if path == "/api/local/kill-edge":
            result = run(["systemctl", "kill", "--kill-who=all", "--signal=TERM", LOCAL_SERVICE], timeout=10)
            self.send_json(command_payload(result, "强制结束 FnDesk 本地服务进程"))
            return
        self.send_error(404)

    def command_json(self, command, label):
        result = run(command)
        self.send_json(command_payload(result, label))

    def send_json(self, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text):
        raw = text.encode("utf-8", errors="replace")
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def command_payload(result, label):
    return {
        "ok": result.returncode == 0,
        "message": f"{label}{'成功' if result.returncode == 0 else '失败'}",
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
