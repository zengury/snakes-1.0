"""Inspire Robotics Dexterous Hand CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/inspire.sock"

def _client():
    from inspire_hand_cli.client import get_client
    return get_client(os.environ.get("INSPIRE_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"inspire: {m}\n"); return c
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
    p = build_base_parser("inspire", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # finger open/close/move
    finger = sub.add_parser("finger", add_help=False)
    fsub = finger.add_subparsers(dest="finger_cmd"); fsub.required = True

    fo = fsub.add_parser("open", add_help=False)
    fo.add_argument("name", nargs="?", default="all")
    fo.set_defaults(func=_simple("finger.open"))

    fc = fsub.add_parser("close", add_help=False)
    fc.add_argument("name", nargs="?", default="all")
    fc.set_defaults(func=_simple("finger.close"))

    fm = fsub.add_parser("move", add_help=False)
    fm.add_argument("name")
    fm.add_argument("--pos", type=int, required=True)
    fm.set_defaults(func=_simple("finger.move"))

    # gestures
    gesture = sub.add_parser("gesture", add_help=False)
    gsub = gesture.add_subparsers(dest="gesture_cmd"); gsub.required = True
    for name in ("pinch", "grip"):
        gp = gsub.add_parser(name, add_help=False)
        gp.add_argument("--force", type=int, default=500)
        gp.set_defaults(func=lambda a, g=name: (_fmt(a).emit(_do(a, "gesture", gesture=g, force=a.force)), 0)[1])
    for name in ("point", "thumbs-up"):
        gsub.add_parser(name, add_help=False).set_defaults(
            func=lambda a, g=name: (_fmt(a).emit(_do(a, "gesture", gesture=g)), 0)[1]
        )

    # speed
    speed = sub.add_parser("speed", add_help=False)
    ssub = speed.add_subparsers(dest="speed_cmd"); ssub.required = True
    ss = ssub.add_parser("set", add_help=False)
    ss.add_argument("--value", type=int, required=True)
    ss.set_defaults(func=_simple("speed.set"))

    # force
    force = sub.add_parser("force", add_help=False)
    frsub = force.add_subparsers(dest="force_cmd"); frsub.required = True
    fs = frsub.add_parser("set", add_help=False)
    fs.add_argument("--value", type=int, required=True)
    fs.set_defaults(func=_simple("force.set"))
    frsub.add_parser("get", add_help=False).set_defaults(func=_simple("force.get"))

    # joint (shared: get/set/list)
    add_joint_commands(sub, _exec)

    # angles
    angles = sub.add_parser("angles", add_help=False)
    asub = angles.add_subparsers(dest="angles_cmd"); asub.required = True
    asub.add_parser("get", add_help=False).set_defaults(func=_simple("angles.get"))

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
    sys.stderr.write("inspire shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("inspire> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any inspire subcommand, e.g.: finger open all\n")
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
