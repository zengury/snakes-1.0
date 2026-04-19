"""DexRobot Dexterous Hand CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/dexrobot.sock"

def _client():
    from dexrobot_cli.client import get_client
    return get_client(os.environ.get("DEXROBOT_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"dexrobot: {m}\n"); return c
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
    p = build_base_parser("dexrobot", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # joint (shared: get/set/list)
    add_joint_commands(sub, _exec)

    # grasp
    grasp = sub.add_parser("grasp", add_help=False)
    gsub = grasp.add_subparsers(dest="grasp_cmd"); gsub.required = True
    for pose in ("open", "close"):
        gsub.add_parser(pose, add_help=False).set_defaults(
            func=lambda a, p=pose: (_fmt(a).emit(_do(a, "grasp", pose=p)), 0)[1]
        )

    # tactile
    tactile = sub.add_parser("tactile", add_help=False)
    tsub = tactile.add_subparsers(dest="tactile_cmd"); tsub.required = True
    tg = tsub.add_parser("get", add_help=False)
    tg.add_argument("--finger", default=None)
    tg.add_argument("--stream", action="store_true", default=None)
    tg.set_defaults(func=_tactile_get)

    # fk
    fk = sub.add_parser("fk", add_help=False)
    fk.add_argument("--joints", default=None)
    fk.set_defaults(func=_simple("fk"))

    # ik
    ik = sub.add_parser("ik", add_help=False)
    ik.add_argument("--x", type=float, required=True)
    ik.add_argument("--y", type=float, required=True)
    ik.add_argument("--z", type=float, required=True)
    ik.add_argument("--finger", default="index")
    ik.set_defaults(func=_simple("ik"))

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)

    # shell
    sub.add_parser("shell", add_help=False).set_defaults(func=_shell)

    # manifest
    sub.add_parser("manifest", add_help=False).set_defaults(
        func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1]
    )

    return p

def _tactile_get(args):
    """Handle tactile get, with optional --stream for continuous output."""
    import time
    kw = {}
    if args.finger:
        kw["finger"] = args.finger
    if args.stream:
        try:
            while True:
                _fmt(args).emit(_do(args, "tactile.get", **kw))
                time.sleep(0.1)
        except KeyboardInterrupt:
            sys.stderr.write("\n")
            return 0
    _fmt(args).emit(_do(args, "tactile.get", **kw))
    return 0

def _shell(args):
    """Interactive REPL for sending commands."""
    import readline
    sys.stderr.write("dexrobot shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("dexrobot> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any dexrobot subcommand, e.g.: joint list\n")
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
