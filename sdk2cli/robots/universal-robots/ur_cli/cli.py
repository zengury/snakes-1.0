"""Universal Robots UR CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/ur.sock"

def _client():
    from ur_cli.client import get_client
    return get_client(os.environ.get("UR_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"ur: {m}\n"); return c
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

def _parse_int_list(s):
    """Parse a comma-separated string of ints."""
    return [int(x.strip()) for x in s.split(",")]

def _move_joint(args):
    joints = _parse_float_list(args.joints)
    if len(joints) != 6:
        return _fail("--joints requires exactly 6 comma-separated values")
    kw = {"joints": joints}
    if args.speed is not None: kw["speed"] = args.speed
    if args.accel is not None: kw["accel"] = args.accel
    _fmt(args).emit(_do(args, "move-joint", **kw)); return 0

def _move_line(args):
    pose = _parse_float_list(args.pose)
    if len(pose) != 6:
        return _fail("--pose requires exactly 6 comma-separated values (x,y,z,rx,ry,rz)")
    kw = {"pose": pose}
    if args.speed is not None: kw["speed"] = args.speed
    if args.accel is not None: kw["accel"] = args.accel
    _fmt(args).emit(_do(args, "move-line", **kw)); return 0

def _servo_joint(args):
    joints = _parse_float_list(args.joints)
    if len(joints) != 6:
        return _fail("--joints requires exactly 6 comma-separated values")
    _fmt(args).emit(_do(args, "servo-joint", joints=joints)); return 0

def _speed_joint(args):
    speeds = _parse_float_list(args.speeds)
    if len(speeds) != 6:
        return _fail("--speeds requires exactly 6 comma-separated values")
    kw = {"speeds": speeds}
    if args.accel is not None: kw["accel"] = args.accel
    _fmt(args).emit(_do(args, "speed-joint", **kw)); return 0

def _force_mode(args):
    kw = {}
    if args.task_frame: kw["task_frame"] = _parse_float_list(args.task_frame)
    if args.selection: kw["selection"] = _parse_int_list(args.selection)
    if args.wrench: kw["wrench"] = _parse_float_list(args.wrench)
    if args.type is not None: kw["type"] = args.type
    if args.limits: kw["limits"] = _parse_float_list(args.limits)
    _fmt(args).emit(_do(args, "force-mode", **kw)); return 0

def _build_parser():
    p = build_base_parser("ur", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # move-joint
    mj = sub.add_parser("move-joint", add_help=False)
    mj.add_argument("--joints", required=True, help="6 joint angles (rad), comma-separated")
    mj.add_argument("--speed", type=float, default=None)
    mj.add_argument("--accel", type=float, default=None)
    mj.set_defaults(func=_move_joint)

    # move-line
    ml = sub.add_parser("move-line", add_help=False)
    ml.add_argument("--pose", required=True, help="6 TCP pose values (x,y,z,rx,ry,rz), comma-separated")
    ml.add_argument("--speed", type=float, default=None)
    ml.add_argument("--accel", type=float, default=None)
    ml.set_defaults(func=_move_line)

    # servo-joint
    sj = sub.add_parser("servo-joint", add_help=False)
    sj.add_argument("--joints", required=True, help="6 joint angles (rad), comma-separated")
    sj.set_defaults(func=_servo_joint)

    # speed-joint
    spj = sub.add_parser("speed-joint", add_help=False)
    spj.add_argument("--speeds", required=True, help="6 joint speeds (rad/s), comma-separated")
    spj.add_argument("--accel", type=float, default=None)
    spj.set_defaults(func=_speed_joint)

    # force-mode
    fm = sub.add_parser("force-mode", add_help=False)
    fm.add_argument("--task-frame", dest="task_frame", default=None)
    fm.add_argument("--selection", default=None)
    fm.add_argument("--wrench", default=None)
    fm.add_argument("--type", type=int, default=None)
    fm.add_argument("--limits", default=None)
    fm.set_defaults(func=_force_mode)

    # teach-mode
    teach = sub.add_parser("teach-mode", add_help=False)
    teach.add_argument("state", choices=["on", "off"])
    teach.set_defaults(func=_simple("teach-mode"))

    # freedrive
    fd = sub.add_parser("freedrive", add_help=False)
    fd.add_argument("state", choices=["on", "off"])
    fd.set_defaults(func=_simple("freedrive"))

    # get-pose
    sub.add_parser("get-pose", add_help=False).set_defaults(func=_simple("get-pose"))

    # get-force
    sub.add_parser("get-force", add_help=False).set_defaults(func=_simple("get-force"))

    # get-mode
    sub.add_parser("get-mode", add_help=False).set_defaults(func=_simple("get-mode"))

    # get-temps (joint temperatures)
    sub.add_parser("get-temps", add_help=False).set_defaults(func=_simple("get-temps"))

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
    sys.stderr.write("ur shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("ur> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any ur subcommand, e.g.: get-pose\n")
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
