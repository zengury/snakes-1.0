"""Command-line entry point for the Unitree G1 CLI.

The argparse surface mirrors manifest.txt exactly. `--help` prints
manifest.txt verbatim — it IS the system prompt.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from unitree_cli.client import SafetyError, get_client, resolve_joint, validate_arm_action
from unitree_cli.daemon import (
    DEFAULT_SOCKET_PATH, Daemon, DaemonClient, LocalExecutor,
    daemon_running, get_executor,
)
from unitree_cli.formatter import Formatter

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "manifest.txt"


def _manifest() -> str:
    try:
        return MANIFEST_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "(manifest.txt not found)"


class ManifestHelpAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        sys.stdout.write(_manifest())
        parser.exit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exec(args, cmd: str, **kwargs: Any) -> Any:
    ex = get_executor(Path(args.socket), backend=args.backend)
    try:
        return ex.call(cmd, **kwargs)
    finally:
        ex.close()


def _fmt(args) -> Formatter:
    return Formatter(mode=args.format)


def _fail(msg: str, code: int = 1) -> int:
    sys.stderr.write(f"unitree: {msg}\n")
    return code


# ---------------------------------------------------------------------------
# Locomotion
# ---------------------------------------------------------------------------

def cmd_loco_simple(args) -> int:
    action_map = {
        "damp": "loco.damp", "start": "loco.start", "stop": "loco.stop",
        "zero-torque": "loco.zero-torque", "stand-up": "loco.stand-up",
        "sit": "loco.sit", "squat": "loco.squat",
        "high-stand": "loco.high-stand", "low-stand": "loco.low-stand",
        "balance": "loco.balance",
    }
    cmd = action_map[args.loco_action]
    try:
        _fmt(args).emit(_exec(args, cmd))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def cmd_loco_move(args) -> int:
    _fmt(args).emit(_exec(args, "loco.move", vx=args.vx, vy=args.vy, vyaw=args.vyaw, continuous=args.continuous))
    return 0


def cmd_loco_velocity(args) -> int:
    _fmt(args).emit(_exec(args, "loco.velocity", vx=args.vx, vy=args.vy, omega=args.omega, duration=args.duration))
    return 0


def cmd_loco_wave(args) -> int:
    _fmt(args).emit(_exec(args, "loco.wave-hand", turn=args.turn))
    return 0


def cmd_loco_shake(args) -> int:
    _fmt(args).emit(_exec(args, "loco.shake-hand", stage=args.stage))
    return 0


def cmd_loco_fsm(args) -> int:
    if args.fsm_cmd == "get":
        _fmt(args).emit(_exec(args, "loco.fsm.get"))
    else:
        _fmt(args).emit(_exec(args, "loco.fsm.set", id=args.id))
    return 0


def cmd_loco_prop(args) -> int:
    """Handle stand-height/swing-height/balance-mode get/set."""
    prop = args.loco_prop  # "stand-height", "swing-height", "balance-mode"
    if args.prop_cmd == "get":
        _fmt(args).emit(_exec(args, f"loco.{prop}.get"))
    else:
        _fmt(args).emit(_exec(args, f"loco.{prop}.set", **{args.prop_key: args.value}))
    return 0


# ---------------------------------------------------------------------------
# Arm
# ---------------------------------------------------------------------------

def cmd_arm_do(args) -> int:
    try:
        _fmt(args).emit(_exec(args, "arm.do", action=args.action))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def cmd_arm_list(args) -> int:
    _fmt(args).emit(_exec(args, "arm.list"))
    return 0


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def cmd_audio_tts(args) -> int:
    _fmt(args).emit(_exec(args, "audio.tts", text=args.text, speaker=args.speaker))
    return 0


def cmd_audio_volume(args) -> int:
    if args.vol_cmd == "get":
        _fmt(args).emit(_exec(args, "audio.volume.get"))
    else:
        _fmt(args).emit(_exec(args, "audio.volume.set", level=args.level))
    return 0


def cmd_audio_led(args) -> int:
    _fmt(args).emit(_exec(args, "audio.led", r=args.R, g=args.G, b=args.B))
    return 0


# ---------------------------------------------------------------------------
# Joints
# ---------------------------------------------------------------------------

def cmd_joint_get(args) -> int:
    try:
        _fmt(args).emit(_exec(args, "joint.get", id_or_name=args.id))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def cmd_joint_set(args) -> int:
    try:
        kwargs: dict[str, Any] = {"id_or_name": args.id, "q": args.q}
        if args.dq is not None: kwargs["dq"] = args.dq
        if args.kp is not None: kwargs["kp"] = args.kp
        if args.kd is not None: kwargs["kd"] = args.kd
        if args.tau is not None: kwargs["tau"] = args.tau
        _fmt(args).emit(_exec(args, "joint.set", **kwargs))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def cmd_joint_list(args) -> int:
    _fmt(args).emit(_exec(args, "joint.list"))
    return 0


# ---------------------------------------------------------------------------
# IMU
# ---------------------------------------------------------------------------

def cmd_imu_get(args) -> int:
    fmt = _fmt(args)
    ex = get_executor(Path(args.socket), backend=args.backend)
    try:
        if not args.stream:
            fmt.emit(ex.call("imu.get"))
            return 0
        period = 1.0 / max(1, args.hz)
        try:
            while True:
                fmt.emit(ex.call("imu.get"))
                time.sleep(period)
        except KeyboardInterrupt:
            return 0
    finally:
        ex.close()


# ---------------------------------------------------------------------------
# Mode switcher
# ---------------------------------------------------------------------------

def cmd_mode(args) -> int:
    if args.mode_cmd == "check":
        _fmt(args).emit(_exec(args, "mode.check"))
    elif args.mode_cmd == "select":
        _fmt(args).emit(_exec(args, "mode.select", name=args.name))
    elif args.mode_cmd == "release":
        _fmt(args).emit(_exec(args, "mode.release"))
    return 0


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def cmd_undo(args) -> int:
    _fmt(args).emit(_exec(args, "undo", steps=args.steps))
    return 0


# ---------------------------------------------------------------------------
# Shell (REPL)
# ---------------------------------------------------------------------------

def cmd_shell(args) -> int:
    from unitree_cli.repl import run_repl
    return run_repl(Path(args.socket), _fmt(args))


# ---------------------------------------------------------------------------
# Daemon lifecycle
# ---------------------------------------------------------------------------

def cmd_daemon_start(args) -> int:
    socket_path = Path(args.socket)
    if daemon_running(socket_path):
        return _fail(f"daemon already running at {socket_path}")
    client = get_client(args.backend, interface=getattr(args, "interface", "eth0"))
    daemon = Daemon(client, socket_path)
    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
    sys.stderr.write(f"unitree daemon on {socket_path} (backend={client.name})\n")
    daemon.serve_forever()
    return 0


def cmd_daemon_status(args) -> int:
    socket_path = Path(args.socket)
    if not daemon_running(socket_path):
        _fmt(args).emit({"running": False, "socket": str(socket_path)})
        return 1
    probe = DaemonClient(socket_path)
    probe.connect()
    try:
        info = probe.call("ping")
    finally:
        probe.close()
    _fmt(args).emit({"running": True, "socket": str(socket_path), **info})
    return 0


def cmd_daemon_stop(args) -> int:
    return _fail("send SIGTERM to the daemon process to stop it", 1)


# ---------------------------------------------------------------------------
# Bench
# ---------------------------------------------------------------------------

def cmd_bench(args) -> int:
    import statistics
    import subprocess

    socket_path = Path(args.socket)
    if not daemon_running(socket_path):
        return _fail("daemon not running — start with: unitree daemon start &")

    client = DaemonClient(socket_path)
    client.connect()
    try:
        for _ in range(20):
            client.call("ping")
        rtts_us = []
        for _ in range(args.count):
            t0 = time.perf_counter_ns()
            client.call("ping")
            rtts_us.append((time.perf_counter_ns() - t0) / 1000.0)
    finally:
        client.close()

    rtts_us.sort()
    result: dict[str, Any] = {
        "in_process_rtt_us": {
            "n": args.count,
            "mean": round(statistics.mean(rtts_us), 2),
            "p50": round(rtts_us[int(args.count * 0.50)], 2),
            "p95": round(rtts_us[int(args.count * 0.95)], 2),
            "p99": round(rtts_us[int(args.count * 0.99)], 2),
        }
    }
    if args.with_cold_start:
        cold = []
        for _ in range(args.cold_count):
            t0 = time.perf_counter_ns()
            subprocess.run(
                [sys.executable, "-m", "unitree_cli", "--socket", str(socket_path), "imu", "get"],
                check=True, capture_output=True,
            )
            cold.append((time.perf_counter_ns() - t0) / 1e6)
        cold.sort()
        result["subprocess_cold_ms"] = {
            "n": args.cold_count,
            "p50": round(cold[int(len(cold) * 0.50)], 2),
            "p99": round(cold[int(len(cold) * 0.99)], 2),
        }

    _fmt(args).emit(result)
    p99_ms = result["in_process_rtt_us"]["p99"] / 1000.0
    sys.stderr.write(f"P0 gate (≤50ms): {'PASS' if p99_ms <= 50 else 'FAIL'}  [p99={p99_ms:.2f}ms]\n")
    return 0 if p99_ms <= 50 else 3


def cmd_manifest(args) -> int:
    sys.stdout.write(_manifest())
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="unitree", add_help=False)
    p.add_argument("-h", "--help", action=ManifestHelpAction)
    p.add_argument("--socket", default=str(DEFAULT_SOCKET_PATH), help=argparse.SUPPRESS)
    p.add_argument("--backend", default=os.environ.get("UNITREE_BACKEND", "mock"), help=argparse.SUPPRESS)
    p.add_argument("--format", default=os.environ.get("UNITREE_FORMAT", "json"),
                   choices=["json", "text"], help=argparse.SUPPRESS)
    p.add_argument("--interface", default=os.environ.get("UNITREE_INTERFACE", "eth0"), help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command")
    sub.required = True

    # --- loco ---
    loco = sub.add_parser("loco", add_help=False)
    loco_sub = loco.add_subparsers(dest="loco_cmd")
    loco_sub.required = True

    for action in ["damp", "start", "stop", "zero-torque", "stand-up", "sit", "squat",
                    "high-stand", "low-stand", "balance"]:
        sp = loco_sub.add_parser(action, add_help=False)
        sp.set_defaults(func=cmd_loco_simple, loco_action=action)

    mv = loco_sub.add_parser("move", add_help=False)
    mv.add_argument("--vx", type=float, default=0.0)
    mv.add_argument("--vy", type=float, default=0.0)
    mv.add_argument("--vyaw", type=float, default=0.0)
    mv.add_argument("--continuous", action="store_true")
    mv.set_defaults(func=cmd_loco_move)

    vel = loco_sub.add_parser("velocity", add_help=False)
    vel.add_argument("--vx", type=float, required=True)
    vel.add_argument("--vy", type=float, required=True)
    vel.add_argument("--omega", type=float, required=True)
    vel.add_argument("--duration", type=float, default=1.0)
    vel.set_defaults(func=cmd_loco_velocity)

    wv = loco_sub.add_parser("wave-hand", add_help=False)
    wv.add_argument("--turn", action="store_true")
    wv.set_defaults(func=cmd_loco_wave)

    sh = loco_sub.add_parser("shake-hand", add_help=False)
    sh.add_argument("--stage", type=int, default=-1)
    sh.set_defaults(func=cmd_loco_shake)

    fsm = loco_sub.add_parser("fsm", add_help=False)
    fsm_sub = fsm.add_subparsers(dest="fsm_cmd")
    fsm_sub.required = True
    fsm_sub.add_parser("get", add_help=False).set_defaults(func=cmd_loco_fsm)
    fsm_set = fsm_sub.add_parser("set", add_help=False)
    fsm_set.add_argument("id", type=int)
    fsm_set.set_defaults(func=cmd_loco_fsm)

    for prop, key in [("stand-height", "height"), ("swing-height", "height"), ("balance-mode", "mode")]:
        pp = loco_sub.add_parser(prop, add_help=False)
        pp_sub = pp.add_subparsers(dest="prop_cmd")
        pp_sub.required = True
        pp_sub.add_parser("get", add_help=False).set_defaults(func=cmd_loco_prop, loco_prop=prop, prop_key=key)
        ps = pp_sub.add_parser("set", add_help=False)
        ps.add_argument("value", type=float)
        ps.set_defaults(func=cmd_loco_prop, loco_prop=prop, prop_key=key)

    # --- arm ---
    arm = sub.add_parser("arm", add_help=False)
    arm_sub = arm.add_subparsers(dest="arm_cmd")
    arm_sub.required = True
    ad = arm_sub.add_parser("do", add_help=False)
    ad.add_argument("action")
    ad.set_defaults(func=cmd_arm_do)
    arm_sub.add_parser("list", add_help=False).set_defaults(func=cmd_arm_list)

    # --- audio ---
    audio = sub.add_parser("audio", add_help=False)
    audio_sub = audio.add_subparsers(dest="audio_cmd")
    audio_sub.required = True
    tts = audio_sub.add_parser("tts", add_help=False)
    tts.add_argument("text")
    tts.add_argument("--speaker", type=int, default=0)
    tts.set_defaults(func=cmd_audio_tts)
    vol = audio_sub.add_parser("volume", add_help=False)
    vol_sub = vol.add_subparsers(dest="vol_cmd")
    vol_sub.required = True
    vol_sub.add_parser("get", add_help=False).set_defaults(func=cmd_audio_volume)
    vs = vol_sub.add_parser("set", add_help=False)
    vs.add_argument("level", type=int)
    vs.set_defaults(func=cmd_audio_volume)
    led = audio_sub.add_parser("led", add_help=False)
    led.add_argument("R", type=int)
    led.add_argument("G", type=int)
    led.add_argument("B", type=int)
    led.set_defaults(func=cmd_audio_led)

    # --- joint ---
    joint = sub.add_parser("joint", add_help=False)
    joint_sub = joint.add_subparsers(dest="joint_cmd")
    joint_sub.required = True
    jg = joint_sub.add_parser("get", add_help=False)
    jg.add_argument("id", nargs="?", default="all")
    jg.set_defaults(func=cmd_joint_get)
    js = joint_sub.add_parser("set", add_help=False)
    js.add_argument("id")
    js.add_argument("--q", type=float, required=True)
    js.add_argument("--dq", type=float, default=None)
    js.add_argument("--kp", type=float, default=None)
    js.add_argument("--kd", type=float, default=None)
    js.add_argument("--tau", type=float, default=None)
    js.set_defaults(func=cmd_joint_set)
    joint_sub.add_parser("list", add_help=False).set_defaults(func=cmd_joint_list)

    # --- imu ---
    imu = sub.add_parser("imu", add_help=False)
    imu_sub = imu.add_subparsers(dest="imu_cmd")
    imu_sub.required = True
    ig = imu_sub.add_parser("get", add_help=False)
    ig.add_argument("--stream", action="store_true")
    ig.add_argument("--hz", type=int, default=50)
    ig.set_defaults(func=cmd_imu_get)

    # --- mode ---
    mode = sub.add_parser("mode", add_help=False)
    mode_sub = mode.add_subparsers(dest="mode_cmd")
    mode_sub.required = True
    mode_sub.add_parser("check", add_help=False).set_defaults(func=cmd_mode)
    ms = mode_sub.add_parser("select", add_help=False)
    ms.add_argument("name")
    ms.set_defaults(func=cmd_mode)
    mode_sub.add_parser("release", add_help=False).set_defaults(func=cmd_mode)

    # --- undo ---
    undo = sub.add_parser("undo", add_help=False)
    undo.add_argument("--steps", type=int, default=1)
    undo.set_defaults(func=cmd_undo)

    # --- shell ---
    sub.add_parser("shell", add_help=False).set_defaults(func=cmd_shell)

    # --- daemon ---
    daemon = sub.add_parser("daemon", add_help=False)
    d_sub = daemon.add_subparsers(dest="daemon_cmd")
    d_sub.required = True
    d_sub.add_parser("start", add_help=False).set_defaults(func=cmd_daemon_start)
    d_sub.add_parser("status", add_help=False).set_defaults(func=cmd_daemon_status)
    d_sub.add_parser("stop", add_help=False).set_defaults(func=cmd_daemon_stop)

    # --- bench ---
    bench = sub.add_parser("bench", add_help=False)
    bench.add_argument("--count", type=int, default=1000)
    bench.add_argument("--with-cold-start", action="store_true")
    bench.add_argument("--cold-count", type=int, default=20)
    bench.set_defaults(func=cmd_bench)

    # --- manifest ---
    sub.add_parser("manifest", add_help=False).set_defaults(func=cmd_manifest)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except SafetyError as exc:
        return _fail(f"safety: {exc}", 2)
    except FileNotFoundError as exc:
        return _fail(str(exc), 1)


if __name__ == "__main__":
    raise SystemExit(main())
