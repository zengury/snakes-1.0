#!/usr/bin/env python3
"""Unified multi-robot CLI entry point.

    robot list                          # show installed robots
    robot <name> <command> [args...]    # dispatch to a robot
    robot manifest                      # combined manifest (all robots)
    robot install <name> --from <dir>   # install a robot adapter

Set ROBOT=<name> to skip the name prefix:
    ROBOT=unitree-g1 robot loco start
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    # Lazy import to keep startup fast
    from unitree_cli.registry import (
        ROBOTS_DIR, discover_robots, load_manifest,
        print_robot_list, combined_manifest, install_robot,
    )

    cmd = sys.argv[1]

    # robot list
    if cmd == "list":
        print_robot_list()
        return 0

    # robot manifest — combined all-robot manifest for LLM
    if cmd == "manifest":
        robots = discover_robots()
        sys.stdout.write(combined_manifest(robots))
        return 0

    # robot install <name> --from <dir>
    if cmd == "install":
        if len(sys.argv) < 4 or sys.argv[3] != "--from":
            sys.stderr.write("Usage: robot install <name> --from <directory>\n")
            return 1
        name = sys.argv[2]
        src = Path(sys.argv[4])
        if not (src / "manifest.txt").exists():
            sys.stderr.write(f"error: {src}/manifest.txt not found\n")
            return 1
        dest = ROBOTS_DIR / name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "manifest.txt", dest / "manifest.txt")
        # Copy adapter if exists, otherwise create a stub
        adapter_src = src / "adapter.py"
        if adapter_src.exists():
            shutil.copy2(adapter_src, dest / "adapter.py")
        # Copy the full CLI package if it exists
        for item in src.iterdir():
            if item.is_dir() and item.name.endswith("_cli"):
                shutil.copytree(item, dest / item.name, dirs_exist_ok=True)
        sys.stderr.write(f"Installed {name} → {dest}\n")
        return 0

    # robot <name> <args...>  OR  ROBOT=<name> robot <args...>
    robot_name = os.environ.get("ROBOT")
    if robot_name:
        # ROBOT=xxx robot loco start → dispatch "loco start" to xxx
        remaining = sys.argv[1:]
    else:
        # robot unitree-g1 loco start → dispatch "loco start" to unitree-g1
        robot_name = cmd
        remaining = sys.argv[2:]

    robots = discover_robots()
    if robot_name not in robots:
        sys.stderr.write(
            f"error: robot '{robot_name}' not installed.\n"
            f"Available: {', '.join(robots.keys()) if robots else '(none)'}\n"
            f"Run: robot list\n"
        )
        return 1

    # Dispatch: find and run the robot's CLI
    robot_dir = robots[robot_name]

    # Try to import the robot's CLI module
    cli_dirs = [d for d in robot_dir.iterdir() if d.is_dir() and d.name.endswith("_cli")]
    if cli_dirs:
        # Add robot dir to Python path and run the CLI
        sys.path.insert(0, str(robot_dir))
        mod_name = cli_dirs[0].name
        try:
            mod = __import__(f"{mod_name}.cli", fromlist=["main"])
            return mod.main(remaining)
        except ImportError as exc:
            sys.stderr.write(f"error loading {robot_name} CLI: {exc}\n")
            return 1
    else:
        sys.stderr.write(
            f"Robot '{robot_name}' has manifest but no CLI package.\n"
            f"Regenerate with: /sdk2cli <path-to-sdk>\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
