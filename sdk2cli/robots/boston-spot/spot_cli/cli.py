"""Boston Dynamics Spot CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/spot.sock"

def _client():
    from spot_cli.client import get_client
    return get_client(os.environ.get("SPOT_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"spot: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()
def _simple(cmd):
    def handler(a):
        kw = {k: v for k, v in vars(a).items() if k not in ("func","command","socket","backend","format") and v is not None}
        _fmt(a).emit(_do(a, cmd, **kw)); return 0
    return handler

def _build_parser():
    p = build_base_parser("spot", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # power
    power = sub.add_parser("power", add_help=False)
    psub = power.add_subparsers(dest="power_cmd"); psub.required = True
    psub.add_parser("on", add_help=False).set_defaults(func=_simple("power.on"))
    psub.add_parser("off", add_help=False).set_defaults(func=_simple("power.off"))

    # estop
    estop = sub.add_parser("estop", add_help=False)
    esub = estop.add_subparsers(dest="estop_cmd"); esub.required = True
    esub.add_parser("hard", add_help=False).set_defaults(func=_simple("estop.hard"))
    esub.add_parser("gentle", add_help=False).set_defaults(func=_simple("estop.gentle"))
    esub.add_parser("release", add_help=False).set_defaults(func=_simple("estop.release"))

    # stand/sit/move/selfright/euler
    st = sub.add_parser("stand", add_help=False); st.add_argument("--height", type=float, default=0.0); st.set_defaults(func=_simple("stand"))
    sub.add_parser("sit", add_help=False).set_defaults(func=_simple("sit"))
    mv = sub.add_parser("move", add_help=False)
    mv.add_argument("--vx", type=float, default=0.0); mv.add_argument("--vy", type=float, default=0.0); mv.add_argument("--vyaw", type=float, default=0.0)
    mv.set_defaults(func=_simple("move"))
    wt = sub.add_parser("walk-to", add_help=False)
    wt.add_argument("--x", type=float, required=True); wt.add_argument("--y", type=float, required=True); wt.add_argument("--yaw", type=float, default=0.0)
    wt.set_defaults(func=_simple("walk-to"))
    sub.add_parser("selfright", add_help=False).set_defaults(func=_simple("selfright"))
    eu = sub.add_parser("euler", add_help=False)
    eu.add_argument("--roll", type=float, default=0.0); eu.add_argument("--pitch", type=float, default=0.0); eu.add_argument("--yaw", type=float, default=0.0)
    eu.set_defaults(func=_simple("euler"))

    # arm
    arm = sub.add_parser("arm", add_help=False)
    asub = arm.add_subparsers(dest="arm_cmd"); asub.required = True
    asub.add_parser("stow", add_help=False).set_defaults(func=_simple("arm.stow"))
    asub.add_parser("unstow", add_help=False).set_defaults(func=_simple("arm.unstow"))
    am = asub.add_parser("move", add_help=False)
    for f in ("x","y","z","qw","qx","qy","qz"): am.add_argument(f"--{f}", type=float, default=1.0 if f=="qw" else 0.0)
    am.set_defaults(func=_simple("arm.move"))
    asub.add_parser("joint-get", add_help=False).set_defaults(func=_simple("arm.joint-get"))

    # gripper
    grip = sub.add_parser("gripper", add_help=False)
    gsub = grip.add_subparsers(dest="g_cmd"); gsub.required = True
    gsub.add_parser("open", add_help=False).set_defaults(func=_simple("gripper.open"))
    gsub.add_parser("close", add_help=False).set_defaults(func=_simple("gripper.close"))
    gs = gsub.add_parser("set", add_help=False); gs.add_argument("fraction", type=float); gs.set_defaults(func=_simple("gripper.set"))

    # sensors
    sub.add_parser("state", add_help=False).set_defaults(func=_simple("state"))
    sub.add_parser("battery", add_help=False).set_defaults(func=_simple("battery"))
    img = sub.add_parser("image", add_help=False)
    isub = img.add_subparsers(dest="img_cmd"); isub.required = True
    isub.add_parser("list", add_help=False).set_defaults(func=_simple("image.list"))
    ig = isub.add_parser("get", add_help=False); ig.add_argument("source"); ig.add_argument("--output", default=None)
    ig.set_defaults(func=_simple("image.get"))

    # joint (shared)
    add_joint_commands(sub, _exec)

    # nav
    nav = sub.add_parser("nav", add_help=False)
    nsub = nav.add_subparsers(dest="nav_cmd"); nsub.required = True
    nu = nsub.add_parser("upload", add_help=False); nu.add_argument("--map", required=True); nu.set_defaults(func=_simple("nav.upload"))
    ng = nsub.add_parser("go", add_help=False); ng.add_argument("--waypoint", required=True); ng.set_defaults(func=_simple("nav.go"))
    nsub.add_parser("localize", add_help=False).set_defaults(func=_simple("nav.localize"))
    nsub.add_parser("status", add_help=False).set_defaults(func=_simple("nav.status"))

    # dock
    dk = sub.add_parser("dock", add_help=False); dk.add_argument("--id", type=int, required=True); dk.set_defaults(func=_simple("dock"))
    sub.add_parser("undock", add_help=False).set_defaults(func=_simple("undock"))

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)
    sub.add_parser("manifest", add_help=False).set_defaults(func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1])
    return p

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
