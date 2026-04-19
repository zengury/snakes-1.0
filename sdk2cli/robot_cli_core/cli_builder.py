"""Helpers to build argparse CLIs from robot configs. Shared boilerplate."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable

from robot_cli_core.base_client import RobotClient, SafetyError
from robot_cli_core.daemon import (Daemon, DaemonClient, daemon_running, get_executor)
from robot_cli_core.formatter import Formatter


class ManifestHelpAction(argparse.Action):
    def __init__(self, option_strings, manifest_path, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, help=None):
        self._manifest_path = manifest_path
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            sys.stdout.write(Path(self._manifest_path).read_text())
        except FileNotFoundError:
            sys.stdout.write("(manifest not found)\n")
        parser.exit()


def build_base_parser(prog: str, manifest_path: str | Path, default_socket: str) -> argparse.ArgumentParser:
    """Create a parser with shared global flags (--format, --socket, --backend)."""
    p = argparse.ArgumentParser(prog=prog, add_help=False)
    p.add_argument("-h", "--help", action=ManifestHelpAction, manifest_path=str(manifest_path))
    p.add_argument("--socket", default=os.environ.get(f"{prog.upper().replace('-','_')}_SOCKET", default_socket))
    p.add_argument("--backend", default=os.environ.get(f"{prog.upper().replace('-','_')}_BACKEND", "mock"))
    p.add_argument("--format", default=os.environ.get("ROBOT_FORMAT", "json"), choices=["json", "text"])
    return p


def add_joint_commands(sub, exec_fn: Callable) -> None:
    """Add standard joint get/set/list subcommands."""
    joint = sub.add_parser("joint", add_help=False)
    jsub = joint.add_subparsers(dest="joint_cmd"); jsub.required = True

    jg = jsub.add_parser("get", add_help=False)
    jg.add_argument("id", nargs="?", default="all")
    jg.set_defaults(func=lambda a: _joint_get(a, exec_fn))

    js = jsub.add_parser("set", add_help=False)
    js.add_argument("id")
    js.add_argument("--q", type=float, required=True)
    js.add_argument("--kp", type=float, default=None)
    js.add_argument("--kd", type=float, default=None)
    js.add_argument("--dq", type=float, default=None)
    js.add_argument("--tau", type=float, default=None)
    js.set_defaults(func=lambda a: _joint_set(a, exec_fn))

    jsub.add_parser("list", add_help=False).set_defaults(func=lambda a: _joint_list(a, exec_fn))


def add_daemon_commands(sub, client_factory: Callable[[], RobotClient]) -> None:
    """Add daemon start/stop/status + bench + manifest subcommands."""
    daemon = sub.add_parser("daemon", add_help=False)
    dsub = daemon.add_subparsers(dest="daemon_cmd"); dsub.required = True
    dsub.add_parser("start", add_help=False).set_defaults(func=lambda a: _daemon_start(a, client_factory))
    dsub.add_parser("status", add_help=False).set_defaults(func=_daemon_status)
    dsub.add_parser("stop", add_help=False).set_defaults(func=lambda a: _fail("send SIGTERM to daemon process"))

    bench = sub.add_parser("bench", add_help=False)
    bench.add_argument("--count", type=int, default=1000)
    bench.set_defaults(func=_bench)


def _fmt(args) -> Formatter:
    return Formatter(mode=args.format)


def _fail(msg, code=1):
    sys.stderr.write(f"error: {msg}\n")
    return code


def _exec(args, exec_fn, cmd, **kw):
    ex = exec_fn(args)
    try:
        return ex.call(cmd, **kw)
    finally:
        ex.close()


def _joint_get(args, exec_fn):
    try:
        _fmt(args).emit(_exec(args, exec_fn, "joint.get", id_or_name=args.id))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def _joint_set(args, exec_fn):
    try:
        kw = {"id_or_name": args.id, "q": args.q}
        for k in ("kp", "kd", "dq", "tau"):
            v = getattr(args, k, None)
            if v is not None:
                kw[k] = v
        _fmt(args).emit(_exec(args, exec_fn, "joint.set", **kw))
    except SafetyError as e:
        return _fail(f"safety: {e}", 2)
    return 0


def _joint_list(args, exec_fn):
    _fmt(args).emit(_exec(args, exec_fn, "joint.list"))
    return 0


def _daemon_start(args, client_factory):
    socket_path = Path(args.socket)
    if daemon_running(socket_path):
        return _fail(f"daemon already running at {socket_path}")
    client = client_factory()
    daemon = Daemon(client, socket_path)
    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
    sys.stderr.write(f"daemon on {socket_path} (backend={client.name})\n")
    daemon.serve_forever()
    return 0


def _daemon_status(args):
    socket_path = Path(args.socket)
    if not daemon_running(socket_path):
        Formatter(args.format).emit({"running": False})
        return 1
    c = DaemonClient(socket_path); c.connect()
    try:
        info = c.call("ping")
    finally:
        c.close()
    Formatter(args.format).emit({"running": True, **info})
    return 0


def _bench(args):
    import statistics
    socket_path = Path(args.socket)
    if not daemon_running(socket_path):
        return _fail("daemon not running")
    c = DaemonClient(socket_path); c.connect()
    try:
        for _ in range(20): c.call("ping")
        rtt = []
        for _ in range(args.count):
            t0 = time.perf_counter_ns()
            c.call("ping")
            rtt.append((time.perf_counter_ns() - t0) / 1000.0)
    finally:
        c.close()
    rtt.sort()
    Formatter(args.format).emit({"rtt_us": {
        "n": args.count, "p50": round(rtt[int(len(rtt)*.5)], 1),
        "p99": round(rtt[int(len(rtt)*.99)], 1)}})
    return 0
