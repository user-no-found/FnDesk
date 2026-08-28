import importlib.util
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "app" / "server" / "fndesk-server.py"
SOCKET_GUARD_PATH = REPO_ROOT / "app" / "bin" / "fndesk-seatd-socket-guard"


def load_server_module():
    spec = importlib.util.spec_from_file_location("fndesk_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SERVER = load_server_module()


def load_socket_guard_module():
    loader = SourceFileLoader("fndesk_socket_guard", str(SOCKET_GUARD_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


SOCKET_GUARD = load_socket_guard_module()


class ServerRegressionTests(unittest.TestCase):
    def setUp(self):
        SERVER._STATUS_CACHE["payload"] = None
        SERVER._STATUS_CACHE["expires"] = 0.0

    def test_status_uses_one_bounded_systemd_query(self):
        output = "\n".join(
            [
                "LoadState=loaded",
                "ActiveState=inactive",
                "SubState=dead",
                "UnitFileState=disabled",
                "Result=success",
            ]
        )
        completed = subprocess.CompletedProcess(["systemctl"], 0, output)

        with mock.patch.object(SERVER, "run", return_value=completed) as runner:
            with mock.patch.object(SERVER, "read_config", return_value={}):
                payload = SERVER.build_status_payload()

        self.assertEqual(runner.call_count, 1)
        command = runner.call_args.args[0]
        self.assertEqual(command[:2], ["systemctl", "show"])
        self.assertNotIn("fgconsole", command)
        self.assertNotIn("chvt", command)
        self.assertEqual(payload["services"]["local"]["active"], "inactive")
        self.assertFalse(payload["display"]["liveProbe"])

    def test_service_snapshot_handles_a_timed_out_systemd(self):
        completed = subprocess.CompletedProcess(["systemctl"], 124, "timed out")
        with mock.patch.object(SERVER, "run", return_value=completed):
            snapshot = SERVER.service_snapshot(SERVER.LOCAL_SERVICE)

        self.assertEqual(snapshot["active"], "unknown")
        self.assertEqual(snapshot["code"], 124)

    def test_all_lifecycle_actions_are_non_blocking(self):
        self.assertNotIn("/api/local/tty1", SERVER.LOCAL_ACTIONS)
        self.assertNotIn("/api/local/kill-edge", SERVER.LOCAL_ACTIONS)

        for path in ("/api/local/start", "/api/local/stop", "/api/local/restart"):
            command, _ = SERVER.LOCAL_ACTIONS[path]
            self.assertEqual(command[0], "systemctl")
            self.assertIn("--no-block", command)
            self.assertNotIn("fgconsole", command)
            self.assertNotIn("chvt", command)

    def test_command_timeout_is_bounded(self):
        started = time.monotonic()
        result = SERVER.run(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.05,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 124)
        self.assertLess(elapsed, 1.0)
        self.assertIn("timed out", result.stdout)

    def test_status_cache_prevents_repeated_probes(self):
        payload = {
            "time": 1,
            "stale": False,
            "services": {"local": {"active": "inactive"}},
        }
        with mock.patch.object(SERVER, "build_status_payload", return_value=payload) as build:
            first = SERVER.status_payload()
            second = SERVER.status_payload()

        self.assertEqual(build.call_count, 1)
        self.assertEqual(first["services"], second["services"])

    def test_journal_summary_translates_consecutive_start_failure(self):
        journal = "\n".join(
            [
                "Aug 28 19:05:40 host systemd[1]: Starting fndesk-local.service - FnDesk Local Microsoft Edge...",
                "Aug 28 19:05:40 host seatd[1]: Socket file found at socket path /run/seatd.sock, refusing to start",
                "Aug 28 19:05:40 host seatd-launch[2]: seatd exited prematurely",
                "Aug 28 19:05:40 host systemd[1]: fndesk-local.service: Failed with result 'exit-code'.",
            ]
        )

        summary = SERVER.chinese_journal_summary(journal)

        self.assertIn("中文摘要", summary)
        self.assertIn("收到启动请求", summary)
        self.assertIn("残留的 seatd socket", summary)
        self.assertIn("私有 seatd 提前退出", summary)
        self.assertNotIn("refusing to start", summary)


class SocketGuardTests(unittest.TestCase):
    def test_unbound_socket_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "seatd.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            server.close()
            SOCKET_GUARD.SOCKET_PATH = path

            self.assertEqual(SOCKET_GUARD.main(), 0)
            self.assertFalse(Path(path).exists())

    def test_listening_socket_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "seatd.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            server.listen(1)
            SOCKET_GUARD.SOCKET_PATH = path
            try:
                self.assertEqual(SOCKET_GUARD.main(), 1)
                self.assertTrue(Path(path).exists())
            finally:
                server.close()


class PackagingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = (REPO_ROOT / "app" / "install-kiosk.sh").read_text()
        cls.launcher = (REPO_ROOT / "app" / "bin" / "fndesk-local-launch").read_text()
        cls.browser = (REPO_ROOT / "app" / "bin" / "fndesk-local-browser").read_text()
        cls.socket_guard = (REPO_ROOT / "app" / "bin" / "fndesk-seatd-socket-guard").read_text()
        cls.unit = (REPO_ROOT / "app" / "systemd" / "fndesk-local.service").read_text()
        cls.server = SERVER_PATH.read_text()
        cls.web = (REPO_ROOT / "app" / "www" / "index.html").read_text()
        cls.common = (REPO_ROOT / "cmd" / "common").read_text()

    def test_no_control_plane_vt_probes_remain(self):
        combined = self.server + self.web
        self.assertNotIn("fgconsole", combined)
        self.assertNotIn("/api/local/tty1", combined)
        self.assertNotIn("/api/local/kill-edge", combined)

    def test_systemd_unit_does_not_reset_or_vhangup_tty(self):
        self.assertNotIn("ExecStartPre=-/usr/bin/chvt", self.unit)
        self.assertNotIn("TTYReset=yes", self.unit)
        self.assertNotIn("TTYVHangup=yes", self.unit)
        self.assertIn("StandardInput=tty", self.unit)
        self.assertIn("TimeoutStopSec=15s", self.unit)
        self.assertIn("KillMode=control-group", self.unit)

    def test_compositor_is_isolated_and_uses_compatibility_mode(self):
        self.assertIn("/usr/bin/seatd-launch", self.unit)
        self.assertIn("/usr/bin/setpriv", self.unit)
        self.assertIn("--ruid=${KIOSK_USER}", self.unit)
        self.assertIn("Conflicts=getty@tty1.service seatd.service", self.unit)
        self.assertIn("systemctl_bounded disable seatd.service", self.installer)
        self.assertIn("WLR_DRM_NO_ATOMIC=1", self.launcher)
        self.assertIn("WLR_DRM_NO_MODIFIERS=1", self.launcher)
        self.assertIn("WLR_RENDERER=pixman", self.launcher)
        self.assertIn("/usr/lib/x86_64-linux-gnu", self.launcher)
        self.assertIn("cage -m last", self.launcher)
        self.assertNotIn("cage -s", self.launcher)
        self.assertNotIn("grep -qx connected", self.launcher)
        self.assertNotIn("setterm", self.launcher)
        self.assertIn("--disable-gpu", self.browser)

    def test_no_output_exits_via_wayland_without_drm_status_probe(self):
        self.assertIn("wayland-utils", self.installer)
        self.assertIn("wayland-info", self.browser)
        self.assertIn("interface: 'wl_output'", self.browser)
        self.assertIn("record_status_and_stop_cage 75", self.browser)
        self.assertIn("FNDESK_CHILD_STATUS_FILE", self.launcher)
        self.assertNotIn("/sys/class/drm", self.browser)

    def test_stale_seatd_socket_is_removed_only_when_unbound(self):
        self.assertIn("fndesk-seatd-socket-guard", self.installer)
        self.assertIn("fndesk-seatd-socket-guard", self.unit)
        self.assertIn("client.connect(SOCKET_PATH)", self.socket_guard)
        self.assertIn("errno.ECONNREFUSED", self.socket_guard)
        self.assertIn("os.unlink(SOCKET_PATH)", self.socket_guard)
        self.assertIn("仍有服务监听", self.socket_guard)

    def test_kiosk_identity_does_not_inherit_root_home(self):
        self.assertIn('export HOME="${KIOSK_HOME}"', self.launcher)
        self.assertIn('export USER="${KIOSK_USER}"', self.launcher)
        self.assertIn('export LOGNAME="${KIOSK_USER}"', self.launcher)

    def test_package_callbacks_do_not_wait_for_local_display_stop(self):
        self.assertIn("systemctl_bounded --no-block stop fndesk-local.service", self.common)
        self.assertNotIn("systemctl disable --now fndesk-local.service", self.common)
        self.assertNotIn("systemctl restart systemd-logind.service", self.common)
        self.assertIn("systemctl_bounded enable seatd.service", self.common)

        direct_systemctl = [
            line
            for line in self.installer.splitlines()
            if line.lstrip().startswith("systemctl ")
        ]
        self.assertEqual(direct_systemctl, [])

    def test_runtime_files_are_packaged_instead_of_embedded(self):
        self.assertIn('${SCRIPT_DIR}/bin/fndesk-local-launch', self.installer)
        self.assertIn('${SCRIPT_DIR}/systemd/fndesk-local.service', self.installer)
        self.assertNotIn("cat >/usr/local/bin/fndesk-local-launch", self.installer)
        self.assertNotIn("cat >/etc/systemd/system/fndesk-local.service", self.installer)


if __name__ == "__main__":
    unittest.main()
