"""AGIBOT G2 CLI entry point."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from typing import Any
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/agibot-g2.sock"

def _client():
    from agibot_g2_cli.client import get_client
    return get_client(os.environ.get("AGIBOT_G2_BACKEND", "mock"))

def _exec(args):
    return get_executor(Path(args.socket), _client)

def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"agibot-g2: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()

# ── Command handlers ──────────────────────────────────────────────────

def cmd_arm_joint_get(a):
    _fmt(a).emit(_do(a, "arm.joint-get", side=a.side)); return 0
def cmd_arm_joint_set(a):
    positions = [float(x) for x in a.positions.split(",")]
    try: _fmt(a).emit(_do(a, "arm.joint-set", side=a.side, positions=positions))
    except SafetyError as e: return _fail(f"safety: {e}", 2)
    return 0
def cmd_arm_ee(a):
    _fmt(a).emit(_do(a, "arm.ee-pose", side=a.side)); return 0
def cmd_arm_moveto(a):
    _fmt(a).emit(_do(a, "arm.moveto", x=a.x, y=a.y, z=a.z, qw=a.qw, qx=a.qx, qy=a.qy, qz=a.qz, side=a.side)); return 0
def cmd_gripper_open(a):
    _fmt(a).emit(_do(a, "gripper.open", side=a.side, width=a.width)); return 0
def cmd_gripper_close(a):
    _fmt(a).emit(_do(a, "gripper.close", side=a.side, force=a.force)); return 0
def cmd_gripper_get(a):
    _fmt(a).emit(_do(a, "gripper.get", side=a.side)); return 0
def cmd_waist_set(a):
    kw = {f"j{i}": getattr(a, f"j{i}") for i in range(1,6) if getattr(a, f"j{i}", None) is not None}
    _fmt(a).emit(_do(a, "waist.set", **kw)); return 0
def cmd_waist_get(a):
    _fmt(a).emit(_do(a, "waist.get")); return 0
def cmd_head_set(a):
    kw = {f"j{i}": getattr(a, f"j{i}") for i in range(1,4) if getattr(a, f"j{i}", None) is not None}
    _fmt(a).emit(_do(a, "head.set", **kw)); return 0
def cmd_head_get(a):
    _fmt(a).emit(_do(a, "head.get")); return 0
def cmd_chassis_move(a):
    _fmt(a).emit(_do(a, "chassis.move", vx=a.vx, vy=a.vy, vyaw=a.vyaw)); return 0
def cmd_chassis_stop(a):
    _fmt(a).emit(_do(a, "chassis.stop")); return 0
def cmd_record_start(a):
    _fmt(a).emit(_do(a, "record.start")); return 0
def cmd_record_stop(a):
    _fmt(a).emit(_do(a, "record.stop")); return 0
def cmd_manifest(a):
    try: sys.stdout.write(MANIFEST.read_text())
    except FileNotFoundError: pass
    return 0

def _build_parser():
    p = build_base_parser("agibot-g2", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # joint (shared)
    add_joint_commands(sub, _exec)

    # arm
    arm = sub.add_parser("arm", add_help=False)
    asub = arm.add_subparsers(dest="arm_cmd"); asub.required = True
    ag = asub.add_parser("joint-get", add_help=False)
    ag.add_argument("--side", default="both", choices=["left","right","both"])
    ag.set_defaults(func=cmd_arm_joint_get)
    aset = asub.add_parser("joint-set", add_help=False)
    aset.add_argument("--side", required=True, choices=["left","right"])
    aset.add_argument("--positions", required=True, help="comma-separated 7 joint angles in rad")
    aset.set_defaults(func=cmd_arm_joint_set)
    ae = asub.add_parser("ee-pose", add_help=False)
    ae.add_argument("--side", default="left", choices=["left","right"])
    ae.set_defaults(func=cmd_arm_ee)
    amt = asub.add_parser("moveto", add_help=False)
    for f in ("x","y","z","qw","qx","qy","qz"): amt.add_argument(f"--{f}", type=float, required=True)
    amt.add_argument("--side", required=True, choices=["left","right"])
    amt.set_defaults(func=cmd_arm_moveto)

    # gripper
    grip = sub.add_parser("gripper", add_help=False)
    gsub = grip.add_subparsers(dest="grip_cmd"); gsub.required = True
    go = gsub.add_parser("open", add_help=False)
    go.add_argument("--side", required=True, choices=["left","right"])
    go.add_argument("--width", type=float, default=1.0)
    go.set_defaults(func=cmd_gripper_open)
    gc = gsub.add_parser("close", add_help=False)
    gc.add_argument("--side", required=True, choices=["left","right"])
    gc.add_argument("--force", type=float, default=0.5)
    gc.set_defaults(func=cmd_gripper_close)
    gg = gsub.add_parser("get", add_help=False)
    gg.add_argument("--side", required=True, choices=["left","right"])
    gg.set_defaults(func=cmd_gripper_get)

    # waist
    waist = sub.add_parser("waist", add_help=False)
    wsub = waist.add_subparsers(dest="waist_cmd"); wsub.required = True
    ws = wsub.add_parser("set", add_help=False)
    for i in range(1,6): ws.add_argument(f"--j{i}", type=float)
    ws.set_defaults(func=cmd_waist_set)
    wsub.add_parser("get", add_help=False).set_defaults(func=cmd_waist_get)

    # head
    head = sub.add_parser("head", add_help=False)
    hsub = head.add_subparsers(dest="head_cmd"); hsub.required = True
    hs = hsub.add_parser("set", add_help=False)
    for i in range(1,4): hs.add_argument(f"--j{i}", type=float)
    hs.set_defaults(func=cmd_head_set)
    hsub.add_parser("get", add_help=False).set_defaults(func=cmd_head_get)

    # chassis
    chassis = sub.add_parser("chassis", add_help=False)
    csub = chassis.add_subparsers(dest="chassis_cmd"); csub.required = True
    cm = csub.add_parser("move", add_help=False)
    cm.add_argument("--vx", type=float, default=0.0)
    cm.add_argument("--vy", type=float, default=0.0)
    cm.add_argument("--vyaw", type=float, default=0.0)
    cm.set_defaults(func=cmd_chassis_move)
    csub.add_parser("stop", add_help=False).set_defaults(func=cmd_chassis_stop)

    # record
    record = sub.add_parser("record", add_help=False)
    rsub = record.add_subparsers(dest="rec_cmd"); rsub.required = True
    rsub.add_parser("start", add_help=False).set_defaults(func=cmd_record_start)
    rsub.add_parser("stop", add_help=False).set_defaults(func=cmd_record_stop)

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)

    # manifest
    sub.add_parser("manifest", add_help=False).set_defaults(func=cmd_manifest)
    return p

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)

if __name__ == "__main__":
    raise SystemExit(main())
