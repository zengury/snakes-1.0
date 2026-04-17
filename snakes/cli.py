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

    run_p = sub.add_parser("run", help="Run a scenario or free-form task")
    run_p.add_argument("--robot", required=True, help="Robot identifier (e.g. agibot-x2)")
    run_p.add_argument("--scenario", default=None, help="Scenario name (e.g. escape-room)")
    run_p.add_argument("--level", type=int, default=1, help="Scenario level")
    run_p.add_argument("--task", default=None, help="Free-form task description")
    run_p.add_argument("--model", default="claude-sonnet-4-20250514", help="LLM model name")
    run_p.add_argument("--max-turns", type=int, default=50, help="Maximum agent turns")

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


def find_robot_md(robot_name: str) -> Path:
    candidates = [
        Path(f"robots/{robot_name}/ROBOT.md"),
        Path(f"ROBOT.md"),
        Path(f"{robot_name}.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"No ROBOT.md found for robot '{robot_name}'")


def load_scenario(name: str, level: int) -> dict[str, Any]:
    scenario_dir = Path("scenarios") / name
    manifest = scenario_dir / "manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"Scenario '{name}' not found at {scenario_dir}")
    data = json.loads(manifest.read_text())
    levels = data.get("levels", {})
    level_key = str(level)
    if level_key not in levels:
        raise ValueError(f"Level {level} not found in scenario '{name}'")
    return {
        "name": name,
        "level": level,
        "config": levels[level_key],
        "description": data.get("description", ""),
    }


def build_system_prompt(robot_md_text: str, scenario: dict[str, Any] | None, task: str | None) -> str:
    parts = [
        "You are an agent controlling a robot. Here is your robot identity:\n",
        robot_md_text,
    ]
    if scenario:
        parts.append(f"\n\nScenario: {scenario['name']} (level {scenario['level']})")
        parts.append(f"Description: {scenario['description']}")
        parts.append(f"Config: {json.dumps(scenario['config'])}")
    if task:
        parts.append(f"\n\nTask: {task}")
    return "\n".join(parts)


async def run_agent(args: argparse.Namespace) -> int:
    from snakes.robot_md import load_robot_md, render_robot_md
    from snakes.tools import make_robot_tools, RobotExecutor

    robot_md_path = find_robot_md(args.robot)
    identity = load_robot_md(robot_md_path)
    robot_md_text = render_robot_md(identity)

    scenario = None
    if args.scenario:
        scenario = load_scenario(args.scenario, args.level)

    system_prompt = build_system_prompt(robot_md_text, scenario, args.task)

    manifest_path = Path(f"robots/{args.robot}/manifest.txt")
    if manifest_path.exists():
        manifest_text = manifest_path.read_text()
    else:
        manifest_text = ""

    executor = RobotExecutor(robot_name=args.robot, use_subprocess=True)
    tools = make_robot_tools(args.robot, manifest_text, executor) if manifest_text else []

    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package required. Install with: pip install anthropic", file=sys.stderr)
        return 1

    client = anthropic.Anthropic()
    messages: list[dict[str, Any]] = []

    if args.task:
        messages.append({"role": "user", "content": args.task})
    elif scenario:
        messages.append({"role": "user", "content": f"Begin {scenario['name']} level {scenario['level']}."})
    else:
        print("Error: either --scenario or --task is required", file=sys.stderr)
        return 1

    tool_schemas = [t.to_schema() for t in tools]
    tool_map = {t.name: t for t in tools}

    for turn in range(args.max_turns):
        response = client.messages.create(
            model=args.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tool_schemas if tool_schemas else anthropic.NOT_GIVEN,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        tool_uses = [b for b in assistant_content if b.type == "tool_use"]
        if not tool_uses:
            for block in assistant_content:
                if hasattr(block, "text"):
                    print(block.text)
            break

        tool_results = []
        for tool_use in tool_uses:
            tool = tool_map.get(tool_use.name)
            if tool is None:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Unknown tool: {tool_use.name}",
                    "is_error": True,
                })
                continue
            try:
                result = await tool.execute(tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result),
                })
            except Exception as exc:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(exc),
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

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
    try:
        from snakes.memory_bridge import create_memory, query_relevant_memory
    except ImportError:
        print("memkit not installed. Install with: pip install snakes[memkit]", file=sys.stderr)
        return 1
    memory = create_memory("default")
    result = query_relevant_memory(memory, "*")
    print(json.dumps(result, indent=2, default=str))
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
