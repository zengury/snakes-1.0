"""Interactive REPL shell over the daemon socket.

Usage:
    unitree shell

Eliminates Python cold-start overhead (~135ms) by maintaining a persistent
connection to the daemon. Each command is a ~0.2ms round-trip.

Features:
- readline history + tab completion
- Shorthand: `joint get 3` instead of `unitree joint get 3`
- `undo` / `history` / `help` / `quit` built-in
- Streams (imu get --stream) run until Ctrl+C
"""
from __future__ import annotations

import json
import readline
import shlex
import sys
import time
from pathlib import Path
from typing import Any

from unitree_cli.daemon import DaemonClient, daemon_running
from unitree_cli.formatter import Formatter

HISTORY_FILE = Path.home() / ".unitree_shell_history"

# All known top-level commands for tab completion
COMMANDS = [
    "loco damp", "loco start", "loco stop", "loco zero-torque",
    "loco stand-up", "loco sit", "loco squat",
    "loco high-stand", "loco low-stand", "loco balance",
    "loco move", "loco velocity", "loco wave-hand", "loco shake-hand",
    "loco fsm get", "loco fsm set",
    "loco stand-height get", "loco stand-height set",
    "loco swing-height get", "loco swing-height set",
    "loco balance-mode get", "loco balance-mode set",
    "arm do", "arm list",
    "audio tts", "audio volume get", "audio volume set", "audio led",
    "joint get", "joint set", "joint list",
    "imu get",
    "mode check", "mode select", "mode release",
    "undo", "history", "help", "quit", "exit",
]


class Completer:
    def __init__(self) -> None:
        self.matches: list[str] = []

    def __call__(self, text: str, state: int) -> str | None:
        if state == 0:
            line = readline.get_line_buffer().strip()
            self.matches = [c for c in COMMANDS if c.startswith(line)]
        return self.matches[state] if state < len(self.matches) else None


def run_repl(socket_path: Path, fmt: Formatter) -> int:
    if not daemon_running(socket_path):
        sys.stderr.write(
            "unitree shell: daemon not running. Start it first:\n"
            "  unitree daemon start &\n"
        )
        return 1

    client = DaemonClient(socket_path)
    client.connect()

    # Setup readline
    readline.set_completer(Completer())
    readline.parse_and_bind("tab: complete")
    try:
        readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError:
        pass

    # Banner
    try:
        info = client.call("ping")
        sys.stderr.write(
            f"unitree shell — connected to daemon (backend={info.get('backend', '?')})\n"
            f"Type 'help' for commands, 'quit' to exit. Tab completion available.\n\n"
        )
    except Exception as exc:
        sys.stderr.write(f"unitree shell: connection failed: {exc}\n")
        return 1

    while True:
        try:
            line = input("unitree> ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\n")
            break

        if not line or line.startswith("#"):
            continue

        if line in ("quit", "exit"):
            break

        if line == "help":
            _print_help()
            continue

        if line == "history":
            _print_history(client)
            continue

        # Parse and dispatch
        try:
            result = _dispatch_line(client, line)
            if result is not None:
                fmt.emit(result)
        except Exception as exc:
            sys.stderr.write(f"error: {exc}\n")

    # Save history
    try:
        readline.write_history_file(HISTORY_FILE)
    except OSError:
        pass

    client.close()
    return 0


def _dispatch_line(client: DaemonClient, line: str) -> Any:
    """Parse a REPL line and call the daemon."""
    parts = shlex.split(line)
    # Strip leading "unitree" if present
    if parts and parts[0] == "unitree":
        parts = parts[1:]
    if not parts:
        return None

    cmd_parts = []
    kwargs: dict[str, Any] = {}
    positionals: list[str] = []
    i = 0
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            key = token[2:].replace("-", "_")
            if i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                val = parts[i + 1]
                # Auto-type
                kwargs[key] = _auto_type(val)
                i += 2
            else:
                kwargs[key] = True
                i += 1
        elif not cmd_parts or (len(cmd_parts) < 3 and not _looks_like_value(token)):
            cmd_parts.append(token)
            i += 1
        else:
            positionals.append(token)
            i += 1

    if not cmd_parts:
        return None

    # Build daemon command string: "loco.move", "joint.set", etc.
    cmd = ".".join(cmd_parts[:2]) if len(cmd_parts) >= 2 else cmd_parts[0]

    # Map positionals to expected arg names based on command
    args = dict(kwargs)
    _map_positionals(cmd, positionals, args)

    return client.call(cmd, **args)


def _looks_like_value(s: str) -> bool:
    """Heuristic: is this a value (number, quoted string) rather than a subcommand?"""
    try:
        float(s)
        return True
    except ValueError:
        pass
    return s.startswith('"') or s.startswith("'")


def _auto_type(val: str) -> Any:
    """Convert string to int/float/bool if possible."""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _map_positionals(cmd: str, positionals: list[str], args: dict[str, Any]) -> None:
    """Map positional args to named args based on command type."""
    if cmd == "joint.get" and positionals:
        args["id_or_name"] = _auto_type(positionals[0])
    elif cmd == "joint.set" and positionals:
        args["id_or_name"] = _auto_type(positionals[0])
    elif cmd == "arm.do" and positionals:
        args["action"] = positionals[0]
    elif cmd == "audio.tts" and positionals:
        args["text"] = " ".join(positionals)
    elif cmd == "audio.led" and len(positionals) >= 3:
        args["r"] = int(positionals[0])
        args["g"] = int(positionals[1])
        args["b"] = int(positionals[2])
    elif cmd == "loco.fsm" and positionals:
        # "loco fsm set 200" → sub_cmd="set", positionals=["200"]
        pass  # already handled by cmd_parts
    elif cmd == "mode.select" and positionals:
        args["name"] = positionals[0]
    elif cmd == "undo" and positionals:
        args["steps"] = int(positionals[0])


def _print_help() -> None:
    sys.stderr.write("""
Commands (omit 'unitree' prefix):
  loco damp|start|stop|sit|squat|stand-up|high-stand|low-stand
  loco move --vx 0.3 --vy 0 --vyaw 0
  loco wave-hand | shake-hand
  arm do <action> | arm list
  audio tts "hello" | audio volume get|set <n> | audio led <R> <G> <B>
  joint get <id|name|all> | joint set <id> --q 1.5 --kp 60
  joint list
  imu get [--stream --hz 10]
  mode check | mode select <name> | mode release
  undo [steps]
  history
  help | quit
""")


def _print_history(client: DaemonClient) -> None:
    try:
        info = client.call("undo.info")
        sys.stderr.write(f"Undo stack: {info.get('depth', 0)} entries\n")
        for e in info.get("entries", []):
            sys.stderr.write(f"  {e['cmd']}  ({time.strftime('%H:%M:%S', time.localtime(e['timestamp']))})\n")
    except Exception:
        sys.stderr.write("No undo history available.\n")
