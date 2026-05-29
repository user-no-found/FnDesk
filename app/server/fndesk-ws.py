#!/usr/bin/env python3
"""Drop-in websockify wrapper that adds POST /clipboard/image to push images
into the Web Edge X11 clipboard via xclip."""

import os
import subprocess
import sys
import time

from websockify import websocketproxy

ALLOWED_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp')
MAX_BYTES = 16 * 1024 * 1024
DISPLAY = os.environ.get('FNDESK_WEB_DISPLAY', ':99')


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

    def do_GET(self):
        if self.path == '/app/fndesk':
            self.send_response(302)
            self.send_header('Location', '/app/fndesk/')
            self.end_headers()
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != '/clipboard/image':
            self.send_error(404, 'Not found')
            return

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

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault('RequestHandlerClass', FnDeskRequestHandler)
        _orig_init(self, *args, **kwargs)

    websocketproxy.WebSocketProxy.__init__ = _patched_init
    sys.exit(websocketproxy.websockify_init() or 0)
