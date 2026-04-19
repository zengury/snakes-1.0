"""Generic daemon, thin client, and fallback — shared by all robot CLIs.

Protocol: newline-delimited JSON over AF_UNIX / SOCK_STREAM.
Request:  {"cmd": "joint.get", "args": {"id_or_name": "LeftKnee"}}\n
Response: {"ok": true, "result": {...}}\n
"""
from __future__ import annotations

import json
import os
import socket
import stat
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from robot_cli_core.base_client import RobotClient, SafetyError


def generic_dispatch(client: RobotClient, cmd: str, args: dict[str, Any]) -> Any:
    """Route common commands, then delegate to client.dispatch() for robot-specific."""
    if cmd == "ping":
        return {"pong": time.time_ns(), "backend": client.name}
    if cmd == "joint.get":
        id_or_name = args.get("id_or_name", "all")
        if id_or_name == "all":
            return client.list_joints()
        jd = client.joint_map.resolve(id_or_name)
        return client.get_joint(jd.index)
    if cmd == "joint.set":
        jd = client.joint_map.resolve(args["id_or_name"])
        q = float(args["q"])
        client.joint_map.validate_position(jd, q)
        kw = {k: v for k, v in args.items() if k not in ("id_or_name", "q")}
        return client.set_joint(jd.index, q, **kw)
    if cmd == "joint.list":
        return client.list_joints()
    return client.dispatch(cmd, args)


class Daemon:
    def __init__(self, client: RobotClient, socket_path: Path) -> None:
        self.client = client
        self.socket_path = Path(socket_path)
        self._server: socket.socket | None = None
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        with suppress(FileNotFoundError):
            self.socket_path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.socket_path))
        os.chmod(self.socket_path, stat.S_IRUSR | stat.S_IWUSR)
        srv.listen(32)
        srv.settimeout(0.5)
        self._server = srv
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        finally:
            with suppress(OSError):
                srv.close()
            with suppress(FileNotFoundError):
                self.socket_path.unlink()

    def stop(self) -> None:
        self._stop.set()

    def _handle(self, conn: socket.socket) -> None:
        buf = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        req = json.loads(line)
                        result = generic_dispatch(self.client, req["cmd"], req.get("args") or {})
                        resp = {"ok": True, "result": result}
                    except SafetyError as e:
                        resp = {"ok": False, "error": str(e), "code": "SAFETY"}
                    except Exception as e:
                        resp = {"ok": False, "error": f"{type(e).__name__}: {e}", "code": "INTERNAL"}
                    try:
                        conn.sendall(json.dumps(resp).encode() + b"\n")
                    except OSError:
                        return


class DaemonClient:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = Path(socket_path)
        self._sock: socket.socket | None = None
        self._buf = b""

    def connect(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(self.socket_path))
        self._sock = s

    def call(self, cmd: str, **args: Any) -> Any:
        if self._sock is None:
            self.connect()
        self._sock.sendall(json.dumps({"cmd": cmd, "args": args}).encode() + b"\n")
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("daemon closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        resp = json.loads(line)
        if not resp["ok"]:
            if resp.get("code") == "SAFETY":
                raise SafetyError(resp["error"])
            raise RuntimeError(resp["error"])
        return resp["result"]

    def close(self) -> None:
        if self._sock:
            with suppress(OSError):
                self._sock.close()
            self._sock = None


class LocalExecutor:
    def __init__(self, client: RobotClient) -> None:
        self.client = client

    def call(self, cmd: str, **args: Any) -> Any:
        return generic_dispatch(self.client, cmd, args)

    def close(self) -> None:
        pass


def daemon_running(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.1)
        s.connect(str(socket_path))
        s.close()
        return True
    except OSError:
        return False


def get_executor(socket_path: Path, client_factory: Callable[[], RobotClient]) -> DaemonClient | LocalExecutor:
    if daemon_running(socket_path):
        c = DaemonClient(socket_path)
        c.connect()
        return c
    return LocalExecutor(client_factory())
