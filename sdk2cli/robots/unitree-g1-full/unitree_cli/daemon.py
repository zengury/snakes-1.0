"""Unix-socket daemon, thin client, and fallback executor.

Protocol: newline-delimited JSON over AF_UNIX / SOCK_STREAM.
Request:   {"cmd": "loco.move", "args": {"vx": 0.3, "vy": 0, "vyaw": 0}}\n
Response:  {"ok": true, "result": {...}}\n
Error:     {"ok": false, "error": "...", "code": "SAFETY|INTERNAL|PROTOCOL"}\n
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

from unitree_cli.client import (
    SafetyError, UnitreeClient, get_client,
    resolve_joint, validate_arm_action, validate_joint_q, validate_kp, validate_kd,
    G1_ARM_ACTIONS,
)
from unitree_cli.undo import UndoStack

DEFAULT_SOCKET_PATH = Path(
    os.environ.get("UNITREE_SOCKET", "/tmp/unitree-daemon.sock")
)

# Commands that mutate state → undo stack saves before execution
MUTATING_COMMANDS = {
    "joint.set", "loco.damp", "loco.start", "loco.stop", "loco.stand-up",
    "loco.sit", "loco.squat", "loco.zero-torque", "loco.high-stand",
    "loco.low-stand", "loco.balance", "loco.move", "loco.velocity",
    "loco.wave-hand", "loco.shake-hand", "loco.fsm.set",
    "loco.stand-height.set", "loco.swing-height.set", "loco.balance-mode.set",
    "arm.do", "mode.select", "mode.release",
}


def dispatch(client: UnitreeClient, cmd: str, args: dict[str, Any]) -> Any:
    """Route a command to the matching client method."""
    # Meta
    if cmd == "ping":
        return {"pong": time.time_ns(), "backend": client.name}

    # Locomotion
    if cmd == "loco.damp":      return client.loco_damp()
    if cmd == "loco.start":     return client.loco_start()
    if cmd == "loco.stand-up":  return client.loco_stand_up()
    if cmd == "loco.sit":       return client.loco_sit()
    if cmd == "loco.squat":     return client.loco_squat()
    if cmd == "loco.zero-torque": return client.loco_zero_torque()
    if cmd == "loco.stop":      return client.loco_stop()
    if cmd == "loco.high-stand": return client.loco_high_stand()
    if cmd == "loco.low-stand": return client.loco_low_stand()
    if cmd == "loco.balance":   return client.loco_balance(args.get("mode", 0))
    if cmd == "loco.move":
        return client.loco_move(
            args.get("vx", 0.0), args.get("vy", 0.0), args.get("vyaw", 0.0),
            args.get("continuous", False))
    if cmd == "loco.velocity":
        return client.loco_velocity(
            args.get("vx", 0.0), args.get("vy", 0.0), args.get("omega", 0.0),
            args.get("duration", 1.0))
    if cmd == "loco.wave-hand": return client.loco_wave_hand(args.get("turn", False))
    if cmd == "loco.shake-hand": return client.loco_shake_hand(args.get("stage", -1))
    if cmd == "loco.fsm.get":   return client.loco_get_fsm_id()
    if cmd == "loco.fsm.set":   return client.loco_set_fsm_id(int(args["id"]))
    if cmd == "loco.stand-height.get": return client.loco_get_stand_height()
    if cmd == "loco.stand-height.set": return client.loco_set_stand_height(float(args["height"]))
    if cmd == "loco.swing-height.get": return client.loco_get_swing_height()
    if cmd == "loco.swing-height.set": return client.loco_set_swing_height(float(args["height"]))
    if cmd == "loco.balance-mode.get": return client.loco_get_balance_mode()
    if cmd == "loco.balance-mode.set": return client.loco_set_balance_mode(int(args["mode"]))

    # Arm
    if cmd == "arm.do":
        action_id = validate_arm_action(str(args["action"]))
        return client.arm_do(action_id)
    if cmd == "arm.list":       return client.arm_list()

    # Audio
    if cmd == "audio.tts":      return client.audio_tts(args["text"], args.get("speaker", 0))
    if cmd == "audio.volume.get": return client.audio_volume_get()
    if cmd == "audio.volume.set": return client.audio_volume_set(int(args["level"]))
    if cmd == "audio.led":      return client.audio_led(int(args["r"]), int(args["g"]), int(args["b"]))

    # Joint
    if cmd == "joint.get":
        id_or_name = args.get("id_or_name", "all")
        if id_or_name == "all":
            return client.joint_list()
        idx = resolve_joint(id_or_name)
        return client.joint_get(idx)
    if cmd == "joint.set":
        idx = resolve_joint(args["id_or_name"])
        q = float(args["q"])
        validate_joint_q(idx, q)
        dq = float(args.get("dq", 0.0))
        kp = float(args["kp"]) if "kp" in args else None
        kd = float(args["kd"]) if "kd" in args else None
        tau = float(args.get("tau", 0.0))
        if kp is not None: validate_kp(kp)
        if kd is not None: validate_kd(kd)
        return client.joint_set(idx, q, dq, kp, kd, tau)
    if cmd == "joint.list":     return client.joint_list()

    # IMU
    if cmd == "imu.get":        return client.imu_get()

    # Mode
    if cmd == "mode.check":     return client.mode_check()
    if cmd == "mode.select":    return client.mode_select(args["name"])
    if cmd == "mode.release":   return client.mode_release()

    raise ValueError(f"unknown command: {cmd!r}")


def _wrap_response(fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": fn()}
    except SafetyError as exc:
        return {"ok": False, "error": str(exc), "code": "SAFETY"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "code": "INTERNAL"}


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class Daemon:
    def __init__(self, client: UnitreeClient, socket_path: Path = DEFAULT_SOCKET_PATH) -> None:
        self.client = client
        self.socket_path = Path(socket_path)
        self.undo = UndoStack(client)
        self._server: socket.socket | None = None
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        self._bind()
        try:
            assert self._server is not None
            self._server.settimeout(0.5)
            while not self._stop.is_set():
                try:
                    conn, _ = self._server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        finally:
            self._cleanup()

    def stop(self) -> None:
        self._stop.set()

    def _bind(self) -> None:
        with suppress(FileNotFoundError):
            self.socket_path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.socket_path))
        os.chmod(self.socket_path, stat.S_IRUSR | stat.S_IWUSR)
        srv.listen(32)
        self._server = srv

    def _cleanup(self) -> None:
        if self._server is not None:
            with suppress(OSError):
                self._server.close()
        with suppress(FileNotFoundError):
            self.socket_path.unlink()

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
                        cmd = req["cmd"]
                        args = req.get("args") or {}
                        resp = self._dispatch_with_undo(cmd, args)
                    except (json.JSONDecodeError, KeyError, TypeError) as exc:
                        resp = {"ok": False, "error": f"bad request: {exc}", "code": "PROTOCOL"}
                    try:
                        conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
                    except OSError:
                        return

    def _dispatch_with_undo(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        # Special: undo command
        if cmd == "undo":
            steps = int(args.get("steps", 1))
            return _wrap_response(lambda: self.undo.undo(steps))
        if cmd == "undo.info":
            return _wrap_response(lambda: self.undo.info())

        # Save to undo stack before mutating commands
        if cmd in MUTATING_COMMANDS:
            try:
                self.undo.save(cmd, args)
            except Exception:
                pass  # don't fail the command if undo snapshot fails

        return _wrap_response(lambda: dispatch(self.client, cmd, args))


# ---------------------------------------------------------------------------
# Thin client
# ---------------------------------------------------------------------------

class DaemonClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET_PATH) -> None:
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
        assert self._sock is not None
        payload = json.dumps({"cmd": cmd, "args": args}).encode("utf-8") + b"\n"
        self._sock.sendall(payload)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("daemon closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        resp = json.loads(line)
        if not resp["ok"]:
            if resp.get("code") == "SAFETY":
                raise SafetyError(resp["error"])
            raise RuntimeError(resp["error"])
        return resp["result"]

    def close(self) -> None:
        if self._sock is not None:
            with suppress(OSError):
                self._sock.close()
            self._sock = None


class LocalExecutor:
    def __init__(self, client: UnitreeClient) -> None:
        self.client = client
        self.undo = UndoStack(client)

    def call(self, cmd: str, **args: Any) -> Any:
        if cmd == "undo":
            return self.undo.undo(int(args.get("steps", 1)))
        if cmd == "undo.info":
            return self.undo.info()
        if cmd in MUTATING_COMMANDS:
            try:
                self.undo.save(cmd, args)
            except Exception:
                pass
        return dispatch(self.client, cmd, args)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Transport selection
# ---------------------------------------------------------------------------

def daemon_running(socket_path: Path = DEFAULT_SOCKET_PATH) -> bool:
    if not socket_path.exists():
        return False
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.1)
        probe.connect(str(socket_path))
        probe.close()
        return True
    except OSError:
        return False


def get_executor(
    socket_path: Path = DEFAULT_SOCKET_PATH,
    backend: str | None = None,
) -> DaemonClient | LocalExecutor:
    if daemon_running(socket_path):
        client = DaemonClient(socket_path)
        client.connect()
        return client
    return LocalExecutor(get_client(backend))
