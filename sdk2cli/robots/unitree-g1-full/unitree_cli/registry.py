"""Multi-robot registry.

Discovers installed robot CLI plugins and provides a unified entry point.
Each robot is a manifest.txt + client adapter in a known directory.

Directory layout:
    ~/.unitree-cli/robots/
    ├── unitree-g1/
    │   ├── manifest.txt
    │   └── adapter.py
    ├── unitree-go2/
    │   ├── manifest.txt
    │   └── adapter.py
    ├── fourier-gr1/
    │   ├── manifest.txt
    │   └── adapter.py
    └── boston-spot/
        ├── manifest.txt
        └── adapter.py

Usage:
    robot list                           # show all installed robots
    robot unitree-g1 loco start          # dispatch to specific robot
    robot unitree-g1 manifest            # show robot's capability manifest
    ROBOT=unitree-g1 robot loco start    # env var shortcut
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROBOTS_DIR = Path(os.environ.get(
    "ROBOT_REGISTRY", str(Path.home() / ".robot-cli" / "robots")
))


def discover_robots() -> dict[str, Path]:
    """Scan the registry directory for installed robot adapters."""
    robots = {}
    if not ROBOTS_DIR.is_dir():
        return robots
    for d in sorted(ROBOTS_DIR.iterdir()):
        if d.is_dir() and (d / "manifest.txt").exists():
            robots[d.name] = d
    return robots


def load_manifest(robot_dir: Path) -> str:
    return (robot_dir / "manifest.txt").read_text(encoding="utf-8")


def install_robot(name: str, manifest: str, adapter_code: str) -> Path:
    """Install a robot adapter into the registry."""
    robot_dir = ROBOTS_DIR / name
    robot_dir.mkdir(parents=True, exist_ok=True)
    (robot_dir / "manifest.txt").write_text(manifest, encoding="utf-8")
    (robot_dir / "adapter.py").write_text(adapter_code, encoding="utf-8")
    return robot_dir


def print_robot_list() -> None:
    robots = discover_robots()
    if not robots:
        sys.stderr.write(
            f"No robots installed. Registry: {ROBOTS_DIR}\n"
            f"Run /sdk2cli to generate a robot CLI, then:\n"
            f"  robot install <name> --manifest manifest.txt --adapter adapter.py\n"
        )
        return
    sys.stdout.write("Installed robots:\n\n")
    for name, path in robots.items():
        manifest = load_manifest(path)
        first_line = manifest.strip().splitlines()[0] if manifest.strip() else "(no description)"
        sys.stdout.write(f"  {name:20s}  {first_line}\n")
    sys.stdout.write(f"\nRegistry: {ROBOTS_DIR}\n")
    sys.stdout.write(f"Usage: robot <name> <command> [args...]\n")


def combined_manifest(robots: dict[str, Path] | None = None) -> str:
    """Generate a combined manifest of ALL installed robots.

    This is what goes into an LLM system prompt when the agent
    controls a fleet or needs to know all available hardware.
    """
    robots = robots or discover_robots()
    if not robots:
        return "(no robots installed)\n"
    parts = []
    for name, path in robots.items():
        parts.append(f"# {name}")
        parts.append(load_manifest(path).strip())
        parts.append("")
    return "\n".join(parts) + "\n"
