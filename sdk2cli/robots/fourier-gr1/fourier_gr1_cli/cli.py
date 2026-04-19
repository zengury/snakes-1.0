"""Fourier GR-1 humanoid CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/fourier-gr1.sock"

def _client():
    from fourier_gr1_cli.client import get_client
    return get_client(os.environ.get("GR1_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"gr1: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()
def _simple(cmd):
    def handler(a):
        kw = {k: v for k, v in vars(a).items() if k not in ("func","command","socket","backend","format","motor_cmd","upper_cmd") and v is not None}
        _fmt(a).emit(_do(a, cmd, **kw)); return 0
    return handler

def _build_parser():
    p = build_base_parser("gr1", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # ── Lifecycle ────────────────────────────────────────────────
    sub.add_parser("start", add_help=False).set_defaults(func=_simple("start"))
    sub.add_parser("exit", add_help=False).set_defaults(func=_simple("exit"))

    # ── Motor control ────────────────────────────────────────────
    motor = sub.add_parser("motor", add_help=False)
    msub = motor.add_subparsers(dest="motor_cmd"); msub.required = True
    msub.add_parser("enable", add_help=False).set_defaults(func=_simple("motor.enable"))
    msub.add_parser("disable", add_help=False).set_defaults(func=_simple("motor.disable"))
    mm = msub.add_parser("move", add_help=False)
    mm.add_argument("--no", type=int, required=True)
    mm.add_argument("--orientation", default="left", choices=["left", "right"])
    mm.add_argument("--angle", type=float, required=True)
    mm.set_defaults(func=_simple("motor.move"))
    mg = msub.add_parser("get-pvc", add_help=False)
    mg.add_argument("--no", type=int, required=True)
    mg.add_argument("--orientation", default="left", choices=["left", "right"])
    mg.set_defaults(func=_simple("motor.get_pvc"))

    # ── Posture ──────────────────────────────────────────────────
    sub.add_parser("stand", add_help=False).set_defaults(func=_simple("stand"))

    # ── Locomotion ───────────────────────────────────────────────
    wk = sub.add_parser("walk", add_help=False)
    wk.add_argument("--angle", type=float, default=0.0)
    wk.add_argument("--speed", type=float, default=0.5)
    wk.set_defaults(func=_simple("walk"))

    # ── Head control ─────────────────────────────────────────────
    hd = sub.add_parser("head", add_help=False)
    hd.add_argument("--roll", type=float, default=0.0)
    hd.add_argument("--pitch", type=float, default=0.0)
    hd.add_argument("--yaw", type=float, default=0.0)
    hd.set_defaults(func=_simple("head"))

    # ── Upper body actions ───────────────────────────────────────
    ub = sub.add_parser("upper-body", add_help=False)
    usub = ub.add_subparsers(dest="upper_cmd"); usub.required = True
    ua = usub.add_parser("action", add_help=False)
    ua.add_argument("--arm-action", default="NONE",
                     choices=["NONE", "LEFT_ARM_WAVE", "TWO_ARMS_WAVE", "ARMS_SWING", "HELLO"])
    ua.add_argument("--hand-action", default="NONE",
                     choices=["NONE", "TREMBLE", "GRASP", "PINCH", "OPEN"])
    ua.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "upper_body",
        arm_action=a.arm_action, hand_action=a.hand_action)), 0)[1])

    # ── State ────────────────────────────────────────────────────
    sub.add_parser("state", add_help=False).set_defaults(func=_simple("state"))

    # ── Joints (shared from core) ────────────────────────────────
    add_joint_commands(sub, _exec)

    # ── Daemon + bench (shared from core) ────────────────────────
    add_daemon_commands(sub, _client)
    sub.add_parser("manifest", add_help=False).set_defaults(
        func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1])

    return p

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
