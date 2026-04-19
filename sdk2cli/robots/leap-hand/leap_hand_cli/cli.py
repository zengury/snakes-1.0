"""LEAP Hand CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/leap.sock"

def _client():
    from leap_hand_cli.client import get_client
    return get_client(os.environ.get("LEAP_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"leap: {m}\n"); return c
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
    p = build_base_parser("leap", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # joint (shared: get/set/list)
    add_joint_commands(sub, _exec)

    # grasp
    grasp = sub.add_parser("grasp", add_help=False)
    gsub = grasp.add_subparsers(dest="grasp_cmd"); gsub.required = True
    for pose in ("open", "close", "pinch", "point", "thumbs-up"):
        gsub.add_parser(pose, add_help=False).set_defaults(
            func=lambda a, p=pose: (_fmt(a).emit(_do(a, "grasp", pose=p)), 0)[1]
        )

    # control
    ctrl = sub.add_parser("control", add_help=False)
    csub = ctrl.add_subparsers(dest="ctrl_cmd"); csub.required = True
    for mode in ("position", "velocity", "current"):
        csub.add_parser(mode, add_help=False).set_defaults(
            func=lambda a, m=mode: (_fmt(a).emit(_do(a, "control.set", mode=m)), 0)[1]
        )

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
    sys.stderr.write("leap shell (type 'help' or 'quit')\n")
    while True:
        try:
            line = input("leap> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            return 0
        if not line:
            continue
        if line in ("quit", "exit"):
            return 0
        if line == "help":
            sys.stderr.write("Enter any leap subcommand, e.g.: joint list\n")
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
