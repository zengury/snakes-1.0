from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snakes",
        description="Agent Runtime for Robots — Claude Code for Robotics",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a scenario (V2 golden-path runtime)")
    run_p.add_argument("--scenario", default="escape-room", help="Scenario name")
    run_p.add_argument("--level", type=int, default=1, help="Scenario level")
    run_p.add_argument("--seed", type=int, default=None, help="Random seed (reproducible failures)")

    run_p.add_argument("--robot-md", default="ROBOT.md", help="Path to ROBOT.md")
    run_p.add_argument("--roles-dir", default="roles", help="Roles directory")

    run_p.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "mock"], help="LLM provider")
    run_p.add_argument("--model", default="claude-sonnet-4-20250514", help="LLM model name")
    run_p.add_argument("--max-turns", type=int, default=80, help="Maximum agent turns")
    run_p.add_argument("--max-tokens", type=int, default=1024, help="Max tokens per model response")
    run_p.add_argument("--eventlog-dir", default="eventlog/data", help="EventLog output directory")
    run_p.add_argument("--skillpack", action="append", default=[], help="Path to a skillpack (directory or skillpack.json)")

    # Failure injection (mock scenarios)
    run_p.add_argument("--p-vision-fail", type=float, default=0.0, help="Probability of vision failure")
    run_p.add_argument("--p-manip-fail", type=float, default=0.0, help="Probability of manipulation failure")
    run_p.add_argument("--p-system-timeout", type=float, default=0.0, help="Probability of system timeout")
    run_p.add_argument("--p-system-disconnect", type=float, default=0.0, help="Probability of system disconnect")

    score_p = sub.add_parser("score", help="Score a run from EventLog")
    score_p.add_argument("--eventlog-dir", default="eventlog/data")
    score_p.add_argument("--task-id", required=True)

    replay_p = sub.add_parser("replay", help="Replay a run from EventLog (text)")
    replay_p.add_argument("--eventlog-dir", default="eventlog/data")
    replay_p.add_argument("--task-id", required=True)
    replay_p.add_argument("--limit", type=int, default=200)

    watch_p = sub.add_parser("watch", help="Watch a run live from EventLog")
    watch_p.add_argument("--eventlog-dir", default="eventlog/data")
    watch_p.add_argument("--task-id", required=True)
    watch_p.add_argument("--interval", type=float, default=0.5)

    status_p = sub.add_parser("status", help="Show current agent state")
    status_p.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")

    memory_p = sub.add_parser("memory", help="Memory operations")
    memory_sub = memory_p.add_subparsers(dest="memory_command")
    memory_sub.add_parser("show", help="Show memory contents")

    hack_p = sub.add_parser("hackathon", help="Hackathon mode")
    hack_sub = hack_p.add_subparsers(dest="hackathon_command")
    start_p = hack_sub.add_parser("start", help="Start hackathon session")
    start_p.add_argument("--level", type=int, default=1, help="Starting level")
    start_p.add_argument("--team", required=True, help="Team name")
    hack_sub.add_parser("score", help="Show current scores")

    return parser


async def run_agent(args: argparse.Namespace) -> int:
    from snakes.runtime.runner import run_scenario
    from snakes.scenarios import EscapeRoomMockScenario, FailureInjectionConfig

    if args.scenario != "escape-room":
        raise ValueError(f"Unsupported scenario in V2 runtime: {args.scenario}")

    scenario = EscapeRoomMockScenario(
        failure_cfg=FailureInjectionConfig(
            seed=args.seed,
            p_vision_fail=args.p_vision_fail,
            p_manip_fail=args.p_manip_fail,
            p_system_timeout=args.p_system_timeout,
            p_system_disconnect=args.p_system_disconnect,
        )
    )

    result = await run_scenario(
        scenario,
        robot_md_path=args.robot_md,
        roles_dir=args.roles_dir,
        level=args.level,
        provider=args.provider,
        model=args.model,
        eventlog_dir=args.eventlog_dir,
        seed=args.seed,
        max_turns=args.max_turns,
        max_tokens=args.max_tokens,
        skillpacks=args.skillpack,
    )

    print(json.dumps({
        "task_id": result.task_id,
        "outcome": result.outcome,
        "score": result.score,
    }, ensure_ascii=False, indent=2))

    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from snakes.runtime.score import aggregate_task

    agg = aggregate_task(args.eventlog_dir, args.task_id)
    if agg.events == 0:
        print(f"No entries found for task_id={args.task_id}")
        return 1

    print(json.dumps(agg.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from eventlog import EventLogReader

    reader = EventLogReader(args.eventlog_dir)
    entries = reader.query(task_id=args.task_id, limit=args.limit)
    if not entries:
        print(f"No entries found for task_id={args.task_id}")
        return 1

    for e in entries:
        # Print compact timeline
        if e.source == "cognitive" and e.cognitive:
            if "reasoning" in e.cognitive:
                print(f"{e.ts} [reasoning] {e.cognitive['reasoning']}")
            elif "observation" in e.cognitive:
                obs = e.cognitive["observation"]
                print(f"{e.ts} [observe] room={obs.get('room')} objs={len(obs.get('visible_objects', []))} exits={obs.get('exits')}")
            elif "tool_call" in e.cognitive:
                tc = e.cognitive["tool_call"]
                print(f"{e.ts} [tool_call] {tc.get('name')} {tc.get('arguments')}")
            elif "tool_result" in e.cognitive:
                tr = e.cognitive["tool_result"]
                if tr.get("success") is True:
                    print(f"{e.ts} [tool_result] {tr.get('name')} success=True")
                else:
                    print(
                        f"{e.ts} [tool_result] {tr.get('name')} success=False "
                        f"failure_type={tr.get('failure_type')} phenomenon={tr.get('phenomenon')}"
                    )
            elif "run_start" in e.cognitive:
                print(f"{e.ts} [run_start] {e.cognitive['run_start']}")
            elif "run_end" in e.cognitive:
                print(f"{e.ts} [run_end] {e.cognitive['run_end']}")
            else:
                print(f"{e.ts} [cognitive] {e.cognitive}")
        elif e.tags and "task_end" in e.tags:
            print(f"{e.ts} [task_end] outcome={e.outcome} reason={e.failure_reason}")
        else:
            print(f"{e.ts} [{e.source}] tags={e.tags}")

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    import time
    from eventlog import EventLogReader

    reader = EventLogReader(args.eventlog_dir)
    last_seq = 0
    failures: dict[str, int] = {}
    start_ts = None

    print(f"Watching task_id={args.task_id} (Ctrl+C to stop)")

    try:
        while True:
            entries = reader.query(task_id=args.task_id)
            new = [e for e in entries if e.seq > last_seq]
            for e in new:
                last_seq = max(last_seq, e.seq)

                if start_ts is None and e.cognitive and "run_start" in e.cognitive:
                    start_ts = e.ts

                # Tool results
                if e.cognitive and "tool_result" in e.cognitive:
                    tr = e.cognitive["tool_result"]
                    name = tr.get("name")
                    success = tr.get("success")
                    outcome = tr.get("outcome")
                    ft = tr.get("failure_type")
                    phen = tr.get("phenomenon")
                    extra = ""
                    attempts = None
                    metrics = tr.get("metrics")
                    if isinstance(metrics, dict):
                        attempts = metrics.get("attempts")
                    if success is False:
                        extra = f" failure_type={ft} phenomenon={phen}"
                    if attempts and attempts > 1:
                        extra += f" attempts={attempts}"
                    print(f"{e.ts} tool_result {name} outcome={outcome} success={success}{extra}")

                # Invalid semantics warnings
                if e.cognitive and "tool_outcome_invalid" in e.cognitive:
                    info = e.cognitive["tool_outcome_invalid"]
                    print(f"{e.ts} [WARN] invalid outcome for {info.get('tool')}: {info.get('reason')}")

                # Observations
                if e.cognitive and "observation" in e.cognitive:
                    obs = e.cognitive["observation"]
                    print(f"{e.ts} observe room={obs.get('room')} exits={obs.get('exits')} objs={len(obs.get('visible_objects', []))}")

                # Count failures from structured outcomes (if present)
                if e.cognitive and "tool_result" in e.cognitive:
                    tr = e.cognitive["tool_result"]
                    if tr.get("success") is False:
                        ft = tr.get("failure_type") or "unknown"
                        failures[ft] = failures.get(ft, 0) + 1

                # Task end
                if e.tags and "task_end" in e.tags:
                    print(f"{e.ts} task_end outcome={e.outcome} reason={e.failure_reason}")

            if failures:
                summary = ", ".join(f"{k}={v}" for k, v in sorted(failures.items()))
                print(f"  failures: {summary}")

            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_path = Path(".snakes_state.json")
    if not state_path.exists():
        print("No active agent session.")
        return 0
    state = json.loads(state_path.read_text())
    if args.as_json:
        print(json.dumps(state, indent=2))
    else:
        print(f"Robot: {state.get('robot', 'unknown')}")
        print(f"Task: {state.get('task', 'none')}")
        print(f"Turns: {state.get('turns', 0)}")
        print(f"Status: {state.get('status', 'unknown')}")
    return 0


def cmd_memory_show() -> int:
    print(
        "Memory CLI is not yet implemented in Snakes 2.0. "
        "In V2, episodic memory is a view over EventLog, and semantic skills "
        "are promoted by the critic pipeline."
    )
    print("Use: cat eventlog/data/*.jsonl | tail -n 50")
    return 0


def cmd_hackathon_start(args: argparse.Namespace) -> int:
    state = {
        "mode": "hackathon",
        "team": args.team,
        "level": args.level,
        "score": 0,
        "status": "running",
    }
    Path(".snakes_state.json").write_text(json.dumps(state, indent=2))
    print(f"Hackathon started for team '{args.team}' at level {args.level}")
    return 0


def cmd_hackathon_score() -> int:
    state_path = Path(".snakes_state.json")
    if not state_path.exists():
        print("No active hackathon session.")
        return 1
    state = json.loads(state_path.read_text())
    if state.get("mode") != "hackathon":
        print("Not in hackathon mode.")
        return 1
    print(f"Team: {state['team']}")
    print(f"Level: {state['level']}")
    print(f"Score: {state['score']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        return asyncio.run(run_agent(args))
    elif args.command == "score":
        return cmd_score(args)
    elif args.command == "replay":
        return cmd_replay(args)
    elif args.command == "watch":
        return cmd_watch(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "memory":
        if args.memory_command == "show":
            return cmd_memory_show()
        parser.parse_args(["memory", "--help"])
        return 1
    elif args.command == "hackathon":
        if args.hackathon_command == "start":
            return cmd_hackathon_start(args)
        elif args.hackathon_command == "score":
            return cmd_hackathon_score()
        parser.parse_args(["hackathon", "--help"])
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
