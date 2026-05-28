#!/usr/bin/env python3
import json
import os
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_DEST = Path(os.environ.get("TRIM_APPDEST", Path(__file__).resolve().parents[1]))
PKG_VAR = Path(os.environ.get("TRIM_PKGVAR", APP_DEST / "var"))
PORT = int(os.environ.get("TRIM_SERVICE_PORT", os.environ.get("PORT", "18733")))
WWW_ROOT = APP_DEST / "www"
CONFIG_FILE = Path("/etc/default/web-kiosk")
MISSING_DEPS = os.environ.get("FNDESK_MISSING_DEPS", "")


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def run(command):
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def read_config():
    data = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip("'\"")
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW_ROOT), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self.send_json({
                "webKiosk": run(["systemctl", "is-active", "web-kiosk.service"]).stdout.strip(),
                "displayPower": run(["systemctl", "is-active", "web-kiosk-display-power.service"]).stdout.strip(),
                "missingDeps": MISSING_DEPS.split(),
                "config": read_config(),
            })
            return
        if path == "/api/logs":
            result = run(["journalctl", "-u", "web-kiosk.service", "-b", "-n", "120", "--no-pager"])
            self.send_text(result.stdout)
            return
        if path in ("/", "/app/fndesk/", "/fndesk.html", "/vnc_lite.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/service/start":
            self.command_json(["systemctl", "start", "web-kiosk.service"])
            return
        if path == "/api/service/stop":
            self.command_json(["systemctl", "stop", "web-kiosk.service"])
            return
        if path == "/api/service/restart":
            self.command_json(["systemctl", "restart", "web-kiosk.service"])
            return
        if path == "/api/display/tty1":
            self.command_json(["chvt", "1"])
            return
        self.send_error(404)

    def command_json(self, command):
        result = run(command)
        self.send_json({"ok": result.returncode == 0, "code": result.returncode, "output": result.stdout})

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


def main():
    PKG_VAR.mkdir(parents=True, exist_ok=True)
    httpd = ReusableThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
