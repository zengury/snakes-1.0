"""Unified `robot` CLI entry point.

    robot list                          # show installed robots
    robot <name> <command> [args...]    # dispatch to a robot
    robot manifest                      # combined manifest (all robots)

Each robot lives in registry/robots/<name>/ with:
  - manifest.txt
  - <pkg>_cli/ (Python package with cli.py containing main())
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Registry root: two levels up from this file (robot_cli_core/main.py → registry/)
REGISTRY_ROOT = Path(__file__).resolve().parent.parent
ROBOTS_DIR = REGISTRY_ROOT / "robots"


def _discover() -> dict[str, Path]:
    robots = {}
    if not ROBOTS_DIR.is_dir():
        return robots
    for d in sorted(ROBOTS_DIR.iterdir()):
        if d.is_dir() and (d / "manifest.txt").exists():
            robots[d.name] = d
    return robots


def _find_cli_pkg(robot_dir: Path) -> str | None:
    for item in robot_dir.iterdir():
        if item.is_dir() and item.name.endswith("_cli") and (item / "cli.py").exists():
            return item.name
    return None


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.stdout.write(
            "robot — universal CLI for any robot.\n\n"
            "  robot list                    show installed robots\n"
            "  robot <name> <command>         run a command on a robot\n"
            "  robot <name> --help            show robot's manifest\n"
            "  robot manifest                 combined manifest (all robots)\n\n"
            f"Registry: {ROBOTS_DIR}\n"
        )
        return 0

    robots = _discover()
    cmd = sys.argv[1]

    if cmd == "list":
        if not robots:
            sys.stderr.write(f"No robots found in {ROBOTS_DIR}\n")
            return 1
        sys.stdout.write(f"{'Name':<22} {'CLI Pkg':<20} {'Manifest'}\n")
        sys.stdout.write(f"{'─'*22} {'─'*20} {'─'*40}\n")
        for name, path in robots.items():
            pkg = _find_cli_pkg(path) or "(manifest only)"
            first_line = ""
            try:
                first_line = (path / "manifest.txt").read_text().strip().splitlines()[0][:50]
            except Exception:
                pass
            sys.stdout.write(f"{name:<22} {pkg:<20} {first_line}\n")
        return 0

    if cmd == "manifest":
        for name, path in robots.items():
            sys.stdout.write(f"# ── {name} ──\n")
            try:
                sys.stdout.write((path / "manifest.txt").read_text())
            except FileNotFoundError:
                pass
            sys.stdout.write("\n")
        return 0

    # robot <name> <args...>
    if cmd not in robots:
        sys.stderr.write(f"error: unknown robot '{cmd}'\n")
        sys.stderr.write(f"available: {', '.join(robots.keys())}\n")
        sys.stderr.write("run: robot list\n")
        return 1

    robot_dir = robots[cmd]
    pkg = _find_cli_pkg(robot_dir)
    if not pkg:
        sys.stderr.write(f"'{cmd}' has manifest but no CLI package.\n")
        if sys.argv[2:] == ["--help"] or sys.argv[2:] == ["-h"] or not sys.argv[2:]:
            sys.stdout.write((robot_dir / "manifest.txt").read_text())
            return 0
        return 1

    # Add paths for import
    sys.path.insert(0, str(REGISTRY_ROOT))
    sys.path.insert(0, str(robot_dir))

    try:
        mod = __import__(f"{pkg}.cli", fromlist=["main"])
        return mod.main(sys.argv[2:])
    except ImportError as exc:
        sys.stderr.write(f"error loading {cmd}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
