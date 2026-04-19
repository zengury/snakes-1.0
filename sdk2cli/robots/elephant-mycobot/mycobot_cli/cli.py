"""Elephant Robotics myCobot CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/mycobot.sock"

def _client():
    from mycobot_cli.client import get_client
    return get_client(os.environ.get("MYCOBOT_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"mycobot: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()
def _simple(cmd):
    def handler(a):
        kw = {k: v for k, v in vars(a).items() if k not in ("func","command","socket","backend","format") and v is not None}
        _fmt(a).emit(_do(a, cmd, **kw)); return 0
    return handler

def _parse_float_list(s):
    """Parse a comma-separated string of floats."""
    return [float(x.strip()) for x in s.split(",")]

def _move_angles(args):
    angles = _parse_float_list(args.angles)
    if len(angles) != 6:
        return _fail("--angles requires exactly 6 comma-separated values (degrees)")
    kw = {"angles": angles}
    if args.speed is not None: kw["speed"] = args.speed
    _fmt(args).emit(_do(args, "move-angles", **kw)); return 0

def _move_coords(args):
    coords = _parse_float_list(args.coords)
    if len(coords) != 6:
        return _fail("--coords requires exactly 6 comma-separated values (x,y,z,rx,ry,rz)")
    kw = {"coords": coords}
    if args.speed is not None: kw["speed"] = args.speed
    _fmt(args).emit(_do(args, "move-coords", **kw)); return 0

def _build_parser():
    p = build_base_parser("mycobot", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # move-angles
    ma = sub.add_parser("move-angles", add_help=False)
    ma.add_argument("--angles", required=True, help="6 joint angles (degrees), comma-separated")
    ma.add_argument("--speed", type=int, default=None, help="Speed 0-100")
    ma.set_defaults(func=_move_angles)

    # move-coords
    mc = sub.add_parser("move-coords", add_help=False)
    mc.add_argument("--coords", required=True, help="6 coords (x,y,z,rx,ry,rz), comma-separated")
    mc.add_argument("--speed", type=int, default=None, help="Speed 0-100")
    mc.set_defaults(func=_move_coords)

    # get-angles
    sub.add_parser("get-angles", add_help=False).set_defaults(func=_simple("get-angles"))

    # get-coords
    sub.add_parser("get-coords", add_help=False).set_defaults(func=_simple("get-coords"))

    # gripper
    grip = sub.add_parser("gripper", add_help=False)
    gsub = grip.add_subparsers(dest="gripper_cmd"); gsub.required = True
    gsub.add_parser("open", add_help=False).set_defaults(func=_simple("gripper-open"))
    gsub.add_parser("close", add_help=False).set_defaults(func=_simple("gripper-close"))
    gs = gsub.add_parser("set", add_help=False)
    gs.add_argument("--value", type=int, required=True, help="Gripper value 0-100")
    gs.add_argument("--speed", type=int, default=None, help="Speed 0-100")
    gs.set_defaults(func=_simple("gripper-set"))

    # power
    power = sub.add_parser("power", add_help=False)
    psub = power.add_subparsers(dest="power_cmd"); psub.required = True
    psub.add_parser("on", add_help=False).set_defaults(func=_simple("power-on"))
    psub.add_parser("off", add_help=False).set_defaults(func=_simple("power-off"))

    # release
    sub.add_parser("release", add_help=False).set_defaults(func=_simple("release"))

    # drag teach
    drag = sub.add_parser("drag", add_help=False)
    dsub = drag.add_subparsers(dest="drag_cmd"); dsub.required = True
    dsub.add_parser("start", add_help=False).set_defaults(func=_simple("drag-start"))
    dsub.add_parser("stop", add_help=False).set_defaults(func=_simple("drag-stop"))
    dp = dsub.add_parser("play", add_help=False)
    dp.add_argument("--speed", type=int, default=None)
    dp.set_defaults(func=_simple("drag-play"))

    # is-moving
    sub.add_parser("is-moving", add_help=False).set_defaults(func=_simple("is-moving"))

    # joint (shared: get/set/list)
    add_joint_commands(sub, _exec)

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)

    # shell
    sub.add_parser("shell", add_help=False).set_defaults(func=_shell)

    # manifest
    sub.add_parser("manifest", add_help=False).set_defaults(
        func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1]
    )

    return p

def _shell(args):
    """Interactive REPL for sending commands."""
    import readline
    sys.stderr.write("mycobot shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("mycobot> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any mycobot subcommand, e.g.: get-angles\n")
            continue
        try:
            argv = line.split()
            rc = main(argv)
            if rc and rc != 0:
                sys.stderr.write(f"(exit {rc})\n")
        except SystemExit as e:
            if e.code: sys.stderr.write(f"(exit {e.code})\n")
        except Exception as e:
            sys.stderr.write(f"error: {e}\n")

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
