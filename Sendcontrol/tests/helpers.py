import json
import os
import socket
import sqlite3
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory


class FakeQzoneServer:
    """Simple Unix domain socket server that mimics the QZone UDS endpoint."""

    def __init__(self, socket_path: Path, responses=None):
        self.socket_path = Path(socket_path)
        self._responses = deque(responses or [])
        self.received_payloads = []
        self._thread = None
        self._stop_event = threading.Event()
        self._server = None

    def start(self):
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._stop_event.clear()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self._server.listen(1)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()

    def _next_response(self) -> str:
        if self._responses:
            return self._responses.popleft()
        return "success"

    def _serve_loop(self):
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                data = bytearray()
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
                if data:
                    try:
                        self.received_payloads.append(data.decode())
                    except UnicodeDecodeError:
                        self.received_payloads.append(data.decode(errors="ignore"))
                response = self._next_response()
                conn.sendall(response.encode())

    def stop(self):
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self.socket_path.exists():
            self.socket_path.unlink()


class SendcontrolTestEnv:
    """Sets up an isolated workspace for invoking sendcontrol.sh in tests."""

    def __init__(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cache_dir = self.root / "cache"
        self.logs_dir = self.root / "logs"
        self.prepost_dir = self.cache_dir / "prepost"
        self.db_path = self.cache_dir / "OQQWall.db"
        self.cookies_dir = self.root
        self.sock_path = self.root / "qzone_uds.sock"
        self.toolkit_log = self.logs_dir / "toolkit.log"
        self.crash_log = self.cache_dir / "SendControl_CrashReport.txt"
        self.main_qq = "123456789"
        self.sendcontrol_script = Path(__file__).resolve().parents[1] / "sendcontrol.sh"
        self._setup_directories()
        self._write_toolkit_stub()
        self._write_fake_socat()
        self.write_base_config()
        self.write_account_config()
        self._init_database()

    def cleanup(self):
        self.stop_temp_processes()
        self._tmp.cleanup()

    def stop_temp_processes(self):
        # Placeholder for future resource cleanup if needed.
        pass

    # ------------------------------------------------------------------#
    # Workspace preparation helpers
    # ------------------------------------------------------------------#

    def _setup_directories(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.prepost_dir.mkdir(parents=True, exist_ok=True)
        self.toolkit_log.touch()
        self._unexpected_toolkit_log = self.logs_dir / "toolkit_unexpected.log"
        self._unexpected_toolkit_log.touch()
        if self.crash_log.exists():
            self.crash_log.unlink()
        self.crash_log.touch()

    def _write_toolkit_stub(self):
        toolkit = self.root / "Global_toolkit.sh"
        content = """#!/bin/bash
TOOLKIT_LOG="./logs/toolkit.log"

_toolkit_record() {
    local entry="$1"
    if [[ "${TOOLKIT_EXPECT_NO_CALLS:-0}" == "1" ]]; then
        echo "$entry" >> ./logs/toolkit_unexpected.log
    elif [[ "${TOOLKIT_DISABLE_LOG:-0}" != "1" ]]; then
        echo "$entry" >> "$TOOLKIT_LOG"
    fi
}

renewqzoneloginauto() {
    local qqid="$1"
    printf '{"qqid":"%s","renewed":true}' "$qqid" > "./cookies-$qqid.json"
    _toolkit_record "renew:$qqid"
    return 0
}

sendmsggroup() {
    _toolkit_record "group:$*"
}

sendmsgpriv_givenport() {
    _toolkit_record "priv:$1:$2:$3"
}
"""
        toolkit.write_text(content)

    def _write_fake_socat(self):
        socat_path = self.root / "socat"
        content = """#!/usr/bin/env python3
import os
import socket
import sys

def main():
    if os.environ.get("FAKE_SOCAT_FAIL") == "1":
        sys.stderr.write("fake socat forced failure\\n")
        return 1
    target = None
    args = sys.argv[1:]
    for arg in args:
        if arg.startswith("UNIX-CONNECT:"):
            target = arg.split(":", 1)[1].strip('"')
            break
    if not target:
        sys.stderr.write("fake socat: unsupported arguments\\n")
        return 1
    data = sys.stdin.buffer.read()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(target)
        if data:
            sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
        response = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
    sys.stdout.buffer.write(response)
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""
        socat_path.write_text(content)
        socat_path.chmod(0o755)

    def write_base_config(self, max_attempts=2, at_unprived_sender="false"):
        config = self.root / "oqqwall.config"
        config.write_text(
            f'max_attempts_qzone_autologin="{max_attempts}"\n'
            f'at_unprived_sender="{at_unprived_sender}"\n'
        )

    def write_account_config(self, max_post_stack=2, max_image_number_one_post=30):
        cfg = self.root / "AcountGroupcfg.json"
        data = {
            "TestGroup": {
                "acgroup": "TestGroup",
                "mangroupid": "TestGroupID",
                "mainqqid": self.main_qq,
                "mainqq_http_port": "18080",
                "minorqq_http_port": [],
                "minorqqid": [],
                "max_post_stack": max_post_stack,
                "max_image_number_one_post": max_image_number_one_post,
            }
        }
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preprocess (
                tag TEXT PRIMARY KEY,
                senderid TEXT,
                receiver TEXT,
                comment TEXT,
                AfterLM TEXT,
                ACgroup TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------#
    # Test data helpers
    # ------------------------------------------------------------------#

    def add_preprocess_entry(
        self,
        tag: str,
        senderid: str = "20001",
        receiver: str = None,
        comment=None,
        afterlm: str = "{}",
        acgroup: str = "TestGroup",
    ):
        receiver = receiver or self.main_qq
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO preprocess (tag, senderid, receiver, comment, AfterLM, ACgroup) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tag, senderid, receiver, comment, afterlm, acgroup),
        )
        conn.commit()
        conn.close()

    def set_cookie(self, qqid: str, content: str):
        (self.root / f"cookies-{qqid}.json").write_text(content)

    def read_crash_log(self) -> str:
        return self.crash_log.read_text() if self.crash_log.exists() else ""

    def read_toolkit_log(self) -> str:
        return self.toolkit_log.read_text()

    def reset_logs(self):
        self.toolkit_log.write_text("")
        self._unexpected_toolkit_log.write_text("")
        self.crash_log.write_text("")

    # ------------------------------------------------------------------#
    # Command execution
    # ------------------------------------------------------------------#

    def _base_env(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.root}:{env.get('PATH', '')}"
        env["SENDCONTROL_DEBUG"] = env.get("SENDCONTROL_DEBUG", "0")
        env["GLOBAL_TOOLKIT_PATH"] = str(self.root / "Global_toolkit.sh")
        return env

    def run_sendcontrol(self, args, input_data=None, timeout=15, extra_env=None):
        env = self._base_env()
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [str(self.sendcontrol_script), *args],
            input=input_data,
            text=True if input_data is not None else None,
            capture_output=True,
            cwd=self.root,
            env=env,
            timeout=timeout,
        )
        return result

    # ------------------------------------------------------------------#
    # Context helpers
    # ------------------------------------------------------------------#

    def start_qzone_server(self, responses=None):
        server = FakeQzoneServer(self.sock_path, responses=responses)
        server.start()
        return server

    # ------------------------------------------------------------------#
    # Assertions helpers
    # ------------------------------------------------------------------#

    def create_image_files(self, tag: str, count: int):
        dir_path = self.prepost_dir / tag
        dir_path.mkdir(parents=True, exist_ok=True)
        for idx in range(count):
            (dir_path / f"img_{idx}.jpg").write_text("fake")

    def fetch_storage_tags(self, groupname="TestGroup"):
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT tag FROM sendstorge_{groupname}"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()
        return [row[0] for row in rows]

    def read_unexpected_toolkit_log(self):
        return self._unexpected_toolkit_log.read_text()
