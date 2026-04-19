"""Robotiq 2F Gripper CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/robotiq.sock"

def _client():
    from robotiq_cli.client import get_client
    return get_client(os.environ.get("ROBOTIQ_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"robotiq: {m}\n"); return c
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
    p = build_base_parser("robotiq", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # activate
    sub.add_parser("activate", add_help=False).set_defaults(func=_simple("activate"))

    # open
    sub.add_parser("open", add_help=False).set_defaults(func=_simple("open"))

    # close
    sub.add_parser("close", add_help=False).set_defaults(func=_simple("close"))

    # move (position 0-255)
    mv = sub.add_parser("move", add_help=False)
    mv.add_argument("--position", type=int, required=True, help="Position 0-255 (0=open, 255=closed)")
    mv.add_argument("--speed", type=int, default=None, help="Speed 0-255")
    mv.add_argument("--force", type=int, default=None, help="Force 0-255")
    mv.set_defaults(func=_simple("move"))

    # move-mm
    mm = sub.add_parser("move-mm", add_help=False)
    mm.add_argument("--distance", type=float, required=True, help="Opening distance in mm")
    mm.set_defaults(func=_simple("move-mm"))

    # status
    sub.add_parser("status", add_help=False).set_defaults(func=_simple("status"))

    # calibrate
    sub.add_parser("calibrate", add_help=False).set_defaults(func=_simple("calibrate"))

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
    sys.stderr.write("robotiq shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("robotiq> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any robotiq subcommand, e.g.: status\n")
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
