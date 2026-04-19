#!/usr/bin/env python3
"""End-to-end escape room runner.

Demonstrates the full Snakes stack:
  ROBOT.md → context assembly → agent loop → tools → escape room → EventLog → scoring

Usage:
    # With mock LLM (no API key needed):
    python scripts/run_escape_room.py --level 1 --mock

    # With real Claude:
    ANTHROPIC_API_KEY=sk-... python scripts/run_escape_room.py --level 1

    # With real OpenAI:
    OPENAI_API_KEY=sk-... python scripts/run_escape_room.py --level 1 --provider openai
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.hackathon.escape_room import create_level
from apps.hackathon.x2_mock import X2HackathonMock
from apps.hackathon.scoring import HackathonScorer, LevelMetrics
from eventlog.writer import EventLogWriter
from snakes.memory_bridge import MemoryBridge
from snakes.robot_md import assemble_prompt


MOCK_PLAN = [
    {"reasoning": "Let me look around this room first.", "tool": "camera.get", "args": {}},
    {"reasoning": "I see some exits. Let me check what's here.", "tool": "lidar.get", "args": {}},
    {"reasoning": "I'll move north to explore.", "tool": "walk.to", "args": {"direction": "north"}},
    {"reasoning": "Let me look at this new room.", "tool": "camera.get", "args": {}},
    {"reasoning": "I should check the objects here.", "tool": "lidar.get", "args": {}},
    {"reasoning": "Let me go east.", "tool": "walk.to", "args": {"direction": "east"}},
    {"reasoning": "Another room. Let me look around.", "tool": "camera.get", "args": {}},
    {"reasoning": "Going south to explore more.", "tool": "walk.to", "args": {"direction": "south"}},
    {"reasoning": "Final check of this area.", "tool": "camera.get", "args": {}},
]


def run_mock(level: int, eventlog_dir: Path) -> dict:
    """Run with predefined mock actions (no LLM needed)."""
    room = create_level(level)
    mock = X2HackathonMock(escape_room=room)
    writer = EventLogWriter(str(eventlog_dir), robot_id="x2-001")
    bridge = MemoryBridge(eventlog=writer)
    task_id = f"escape-L{level}-{uuid.uuid4().hex[:8]}"
    bridge.bind_task(task_id)

    print(f"\n{'='*60}")
    print(f"  Snakes 1.0 — Escape Room Level {level}")
    print(f"  Task ID: {task_id}")
    print(f"  Robot: X2-001 (mock)")
    print(f"{'='*60}\n")

    import time
    start = time.time()
    steps = 0
    rooms_seen = set()

    for i, action in enumerate(MOCK_PLAN):
        steps += 1
        print(f"  Turn {i+1}: {action['reasoning']}")
        bridge.on_reasoning(i+1, action["reasoning"])
        bridge.on_tool_execution_start(action["tool"], action["args"])

        result = mock.execute(action["tool"], action["args"])
        success = result.get("ok", False)
        bridge.on_tool_execution_end(action["tool"], action["args"], result, success)

        if action["tool"] == "camera.get" and success:
            room_name = result.get("result", {}).get("room", "?")
            rooms_seen.add(room_name)
            objects = result.get("result", {}).get("objects", [])
            print(f"           Room: {room_name}, Objects: {objects}")
        elif action["tool"] == "walk.to" and success:
            print(f"           Moved successfully")
        elif action["tool"] == "lidar.get" and success:
            exits = result.get("result", {}).get("open_directions", [])
            print(f"           Exits: {exits}")
        else:
            print(f"           Result: {json.dumps(result, ensure_ascii=False)[:80]}")

        bridge.on_turn_end(i+1)

        if room.escaped:
            print(f"\n  ESCAPED in {steps} steps!")
            break

    elapsed = time.time() - start

    total_rooms = len(room.rooms)
    discovered = sum(1 for r in room.rooms.values() if r.discovered)
    accuracy = discovered / total_rooms if total_rooms > 0 else 0

    bridge.on_agent_end(task_id, success=room.escaped or accuracy > 0.5)
    writer.close()

    metrics = LevelMetrics(
        rooms_discovered=discovered,
        map_accuracy=accuracy,
        time_taken=elapsed,
        total_time=elapsed,
    )

    scorer = HackathonScorer()
    scorer.record_level(level, metrics)
    summary = scorer.summary()

    print(f"\n{'='*60}")
    print(f"  Results")
    print(f"{'='*60}")
    print(f"  Rooms discovered: {discovered}/{total_rooms}")
    print(f"  Map accuracy: {accuracy:.0%}")
    print(f"  Steps taken: {steps}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Score: {summary['total_score']}")
    print(f"  EventLog: {eventlog_dir}/")
    print(f"{'='*60}\n")

    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Run Snakes escape room scenario")
    p.add_argument("--level", type=int, default=1, choices=[1, 2, 3])
    p.add_argument("--mock", action="store_true", default=True, help="Use mock LLM (default)")
    p.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    p.add_argument("--eventlog-dir", default="eventlog/data")
    args = p.parse_args()

    eventlog_dir = Path(args.eventlog_dir)
    eventlog_dir.mkdir(parents=True, exist_ok=True)

    if args.mock:
        run_mock(args.level, eventlog_dir)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: set ANTHROPIC_API_KEY or OPENAI_API_KEY", file=sys.stderr)
            return 1
        print("Real LLM mode not yet implemented. Use --mock for now.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
