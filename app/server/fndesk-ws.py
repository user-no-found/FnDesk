#!/usr/bin/env python3
"""Drop-in websockify wrapper for FnDesk Web Edge.

Adds on top of plain websockify:
- POST /clipboard/image : push an image into the Web Edge X11 clipboard via xclip.
- On-demand session lifecycle: the Xvnc+Edge session is started when a client
  connects and torn down after an idle period with no clients, while websockify
  itself keeps listening on the service port. This avoids the session occupying
  the host in the background after the app window is closed.
- A small control API used by the front-end buttons:
    POST /api/web/suspend   -> tear down the Web Edge session now (the X button)
    POST /api/web/wake      -> bring the Web Edge session back up
    POST /api/local/start   -> start the local-display Edge (web-kiosk.service)
    POST /api/local/restart -> restart the local-display Edge + switch to tty1
    POST /api/local/stop    -> stop the local-display Edge
    GET  /api/status        -> JSON status of web session + local service
"""

import json
import multiprocessing
import os
import subprocess
import sys
import time

from websockify import websocketproxy

ALLOWED_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp')
MAX_BYTES = 16 * 1024 * 1024
DISPLAY = os.environ.get('FNDESK_WEB_DISPLAY', ':99')
MAIN_SCRIPT = os.environ.get('FNDESK_MAIN', '')
try:
    IDLE_TIMEOUT = int(os.environ.get('FNDESK_IDLE_TIMEOUT', '180'))
except ValueError:
    IDLE_TIMEOUT = 180


def run_main(action):
    """Invoke cmd/main <action> (web-up / web-down). Safe to call repeatedly."""
    if not MAIN_SCRIPT or not os.path.exists(MAIN_SCRIPT):
        return False
    try:
        subprocess.run([MAIN_SCRIPT, action], timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def systemctl(action):
    try:
        r = subprocess.run(['systemctl', action, 'web-kiosk.service'],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=30)
        return r.returncode, r.stdout
    except Exception as e:
        return 1, str(e)


# 本地显示服务被 udev 规则在 DRM change 时自动 restart。用户主动“关闭本地 Edge”
# 时写下抑制标记，web-kiosk-launch 见到标记即空闲退出，避免立刻被自动拉起；
# “启动/重启本地 Edge”时清除标记。
LOCAL_DISABLE_FLAG = '/etc/web-kiosk/local-disabled'


def set_local_disabled(disabled):
    try:
        if disabled:
            os.makedirs(os.path.dirname(LOCAL_DISABLE_FLAG), exist_ok=True)
            with open(LOCAL_DISABLE_FLAG, 'w') as fh:
                fh.write('1\n')
        elif os.path.exists(LOCAL_DISABLE_FLAG):
            os.remove(LOCAL_DISABLE_FLAG)
    except Exception:
        pass


def service_state(name):
    try:
        r = subprocess.run(['systemctl', 'is-active', name],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=10)
        return r.stdout.strip()
    except Exception:
        return 'unknown'


class FnDeskRequestHandler(websocketproxy.ProxyRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(
            '%s - - [%s] %s path=%s\n' % (
                self.address_string(),
                self.log_date_time_string(),
                fmt % args,
                self.path,
            )
        )

    def new_websocket_client(self):
        # Runs in a forked child. A real VNC client just connected, so make
        # sure the Xvnc+Edge session is up *before* websockify dials the VNC
        # target on localhost:5901, otherwise the first connect would fail.
        run_main('web-up')
        return super().new_websocket_client()

    def _send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/app/fndesk':
            self.send_response(302)
            self.send_header('Location', '/app/fndesk/')
            self.end_headers()
            return
        if self.path.split('?', 1)[0].rstrip('/').endswith('/api/status'):
            self._send_json({
                'webLocal': service_state('web-kiosk.service'),
                'displayPower': service_state('web-kiosk-display-power.service'),
                'idleTimeout': IDLE_TIMEOUT,
            })
            return
        return super().do_GET()

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/')
        if path.endswith('/clipboard/image') or path == '/clipboard/image':
            return self._handle_clipboard_image()

        # Control API (accept both bare and /app/fndesk-prefixed paths).
        if path.endswith('/api/web/suspend'):
            run_main('web-down')
            return self._send_json({'ok': True})
        if path.endswith('/api/web/wake'):
            run_main('web-up')
            return self._send_json({'ok': True})
        if path.endswith('/api/local/start'):
            set_local_disabled(False)
            code, out = systemctl('start')
            return self._send_json({'ok': code == 0, 'output': out})
        if path.endswith('/api/local/restart'):
            set_local_disabled(False)
            code, out = systemctl('restart')
            try:
                subprocess.run(['chvt', '1'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10)
            except Exception:
                pass
            return self._send_json({'ok': code == 0, 'output': out})
        if path.endswith('/api/local/stop'):
            set_local_disabled(True)
            code, out = systemctl('stop')
            return self._send_json({'ok': code == 0, 'output': out})

        self.send_error(404, 'Not found')

    def _handle_clipboard_image(self):
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype not in ALLOWED_TYPES:
            self.send_error(415, 'Unsupported media type')
            return

        try:
            length = int(self.headers.get('Content-Length') or '0')
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BYTES:
            self.send_error(413, 'Invalid size')
            return

        data = self.rfile.read(length)
        if len(data) != length:
            self.send_error(400, 'Truncated body')
            return

        env = dict(os.environ, DISPLAY=DISPLAY)
        try:
            proc = subprocess.Popen(
                ['xclip', '-selection', 'clipboard', '-t', ctype],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.send_error(500, 'xclip not installed')
            return

        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except BrokenPipeError:
            self.send_error(500, 'xclip pipe broken')
            return

        time.sleep(0.1)
        rc = proc.poll()
        if rc is not None and rc != 0:
            self.send_error(500, 'xclip exited unexpectedly')
            return

        self.send_response(204)
        self.end_headers()


if __name__ == '__main__':
    _orig_init = websocketproxy.WebSocketProxy.__init__
    _orig_poll = websocketproxy.WebSocketProxy.poll

    # Idle reaper runs in the *parent* accept-loop process (poll() is called
    # roughly once per second there). websockify forks one child per client, so
    # multiprocessing.active_children() is an accurate live-client count.
    # When it stays at zero for IDLE_TIMEOUT seconds we tear the session down
    # via cmd/main web-down, while websockify keeps listening on the port.
    def _patched_poll(self):
        _orig_poll(self)
        if IDLE_TIMEOUT <= 0:
            return
        now = time.time()
        active = len(multiprocessing.active_children())
        if active > 0:
            self._fndesk_last_active = now
            self._fndesk_suspended = False
            return
        last = getattr(self, '_fndesk_last_active', None)
        if last is None:
            self._fndesk_last_active = now
            return
        if not getattr(self, '_fndesk_suspended', False) and (now - last) > IDLE_TIMEOUT:
            self._fndesk_suspended = True
            run_main('web-down')

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault('RequestHandlerClass', FnDeskRequestHandler)
        _orig_init(self, *args, **kwargs)
        self._fndesk_last_active = time.time()
        self._fndesk_suspended = False

    websocketproxy.WebSocketProxy.__init__ = _patched_init
    websocketproxy.WebSocketProxy.poll = _patched_poll
    sys.exit(websocketproxy.websockify_init() or 0)
