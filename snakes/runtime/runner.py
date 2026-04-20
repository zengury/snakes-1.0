from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from snakes.agent import Agent
from snakes.memory_bridge import create_memory_bridge
from snakes.robot_md import assemble_prompt
from snakes.types import AgentEvent, AgentLoopConfig

from snakes.scenarios.base import Scenario, ScenarioRunContext


@dataclass
class RunResult:
    task_id: str
    score: dict[str, Any]
    outcome: str


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default


def _git_sha() -> str | None:
    try:
        import subprocess

        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        sha = (r.stdout or "").strip()
        return sha or None
    except Exception:
        return None


async def run_scenario(
    scenario: Scenario,
    *,
    robot_md_path: str,
    roles_dir: str = "roles",
    level: int = 1,
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-20250514",
    eventlog_dir: str = "eventlog/data",
    seed: int | None = None,
    max_turns: int = 80,
    skillpacks: list[str] | None = None,
) -> RunResult:
    """Run a scenario end-to-end with the Snakes agent loop.

    V2 rule: everything goes through one golden path:
    Agent loop -> tools -> verify -> eventlog.
    """

    task_id = uuid.uuid4().hex[:12]
    robot_id = _infer_robot_id(robot_md_path)

    # Context assembly (ROBOT.md + role) + runtime kernel rules.
    # Scenario-specific prompt must come from the scenario (application layer).
    system_prompt = assemble_prompt(robot_md_path, roles_dir)
    system_prompt = system_prompt + "\n\n" + _kernel_rules_prompt()

    # Scenario reset
    obs0 = await scenario.reset(level, ctx=ScenarioRunContext(robot_id=robot_id, task_id=task_id, seed=seed))

    # Memory/EventLog bridge
    bridge = create_memory_bridge(robot_id=robot_id, eventlog_dir=eventlog_dir)
    bridge.bind_task(task_id)
    bridge.eventlog.write_cognitive({"run_start": {
        "task_id": task_id,
        "scenario": getattr(scenario, "name", ""),
        "level": level,
        "mode": "autonomy",
        "provider": provider,
        "model": model,
        "seed": seed,
        "git_sha": _git_sha(),
        "failure_cfg": getattr(scenario, "failure_cfg", None).__dict__ if getattr(scenario, "failure_cfg", None) else None,
    }})
    bridge.eventlog.write_cognitive({"initial_observation": obs0}, tags=["observe"])

    # Hooks
    turn_state = {
        "n": 0,
        "recovery_injected": False,
        # simple anti-loop counters
        "repeat": {"key": None, "count": 0},
        # guard against the model stopping early without using tools
        "no_tool_streak": 0,
        "continue_injected": 0,
    }

    async def observe_robot_state() -> dict[str, Any]:
        obs = await scenario.observe()
        bridge.eventlog.write_cognitive({"observation": obs}, tags=["observe"])
        return obs

    async def write_episodic_memory(summary: str) -> None:
        # For V2: episodic is an EventLog view, but we keep this hook for
        # compatibility.
        bridge.eventlog.write_cognitive({"episodic": summary}, tags=["episodic"])

    async def on_event(ev: AgentEvent) -> None:
        if ev.type == "turn_start":
            turn_state["n"] = int(ev.data.get("turn", turn_state["n"]))
            turn_state["recovery_injected"] = False

        if ev.type == "message_end" and ev.message and ev.message.role == "assistant":
            text = ev.message.text.strip()
            if text:
                bridge.on_reasoning(turn_state["n"], text)

            # If the model ends a turn without tool calls but the scenario is not done,
            # inject a continuation nudge. This keeps the golden path runnable with
            # real LLMs that sometimes "answer" prematurely.
            if not ev.message.has_tool_use and not scenario.is_done():
                turn_state["no_tool_streak"] += 1
            else:
                turn_state["no_tool_streak"] = 0

            if (
                turn_state["no_tool_streak"] >= 1
                and turn_state["continue_injected"] < 3
                and not scenario.is_done()
            ):
                # Include a fresh observation snapshot to reduce ambiguity.
                obs = None
                try:
                    obs = await scenario.observe()
                    bridge.eventlog.write_cognitive({"observation": obs}, tags=["observe"])
                except Exception:
                    obs = None

                msg = (
                    "[Continue] The task is not complete yet. Use tools to act, observe, and recover. "
                    "Do not just describe plans—execute the next step."
                )
                if obs is not None:
                    msg += f" Current observation: {obs}"

                agent.follow_up(msg)
                turn_state["continue_injected"] += 1
                bridge.eventlog.write_cognitive(
                    {
                        "continue_injected": {
                            "turn": turn_state["n"],
                            "reason": "assistant ended without tool_use",
                            "streak": turn_state["no_tool_streak"],
                        }
                    },
                    tags=["autonomy"],
                )

        if ev.type == "turn_end":
            bridge.on_turn_end(int(ev.data.get("turn", turn_state["n"])))

    # LLM stream function
    if provider == "mock":
        from snakes.runtime.mock_stream import make_mock_stream_fn, MockPolicyConfig

        stream_fn = make_mock_stream_fn(MockPolicyConfig(level=level))
    else:
        from snakes.llm_client import create_llm_client
        from snakes.runtime.llm_adapter import make_stream_fn

        api_key = _env("ANTHROPIC_API_KEY") if provider == "anthropic" else _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                f"Missing API key for provider={provider}. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
            )

        base_url = None
        if provider == "openai":
            base_url = _env("OPENAI_BASE_URL", "") or None

        llm = create_llm_client(provider=provider, model=model, api_key=api_key, base_url=base_url)
        stream_fn = make_stream_fn(llm)

    cfg = AgentLoopConfig(
        max_turns=max_turns,
        execution_mode="parallel",
        observe_robot_state=observe_robot_state,
        write_episodic_memory=write_episodic_memory,
        stream_fn=stream_fn,
    )

    agent = Agent(system_prompt=system_prompt, model=model, config=cfg)

    # B1/B2: optional skillpacks. We expose a single meta-tool `skill.run`.
    if skillpacks:
        try:
            from snakes.skills import load_skillpacks, SkillExecutor

            packs = load_skillpacks(skillpacks)
            # Tool map is populated after registering scenario tools; we will
            # finalize executor later once tools exist.
        except Exception as exc:
            bridge.eventlog.write_cognitive(
                {"skillpack_load_error": str(exc)},
                severity="warn",
                tags=["skills"],
            )
            packs = []
    else:
        packs = []

    async def before_tool_call(ctx: Any) -> None:
        # Optional safety gate hook would live here (sdk2cli / memkit).
        bridge.on_tool_execution_start(ctx.tool_call.tool_name, ctx.tool_call.tool_input)

        # Anti-loop: detect repeated tool calls (same tool+args) in a short window.
        key = (ctx.tool_call.tool_name, tuple(sorted((ctx.tool_call.tool_input or {}).items())))
        if turn_state["repeat"]["key"] == key:
            turn_state["repeat"]["count"] += 1
        else:
            turn_state["repeat"]["key"] = key
            turn_state["repeat"]["count"] = 1

        if turn_state["repeat"]["count"] >= 4 and not turn_state["recovery_injected"]:
            # Nudge the agent to re-observe and change approach.
            agent.follow_up(
                "[Recovery] You are repeating the same action. Stop repeating. "
                "Re-observe (camera.get/status.) and choose a different action."
            )
            turn_state["recovery_injected"] = True

    async def after_tool_call(ctx: Any) -> None:
        # Tool result content is Any; normalize + validate semantics.
        from snakes.semantics.outcome import normalize_tool_outcome, validate_tool_outcome

        content_any = ctx.result.content
        content = normalize_tool_outcome(content_any)
        ok, reason = validate_tool_outcome(content)
        if not ok:
            bridge.eventlog.write_cognitive(
                {
                    "tool_outcome_invalid": {
                        "tool": ctx.tool_call.tool_name,
                        "reason": reason,
                        "raw": str(content_any)[:500],
                    }
                },
                severity="warn",
                tags=["semantics"],
            )

        success = content.get("outcome") == "success"
        bridge.on_tool_execution_end(
            ctx.tool_call.tool_name,
            ctx.tool_call.tool_input,
            content,
            success=bool(success),
        )

        # Autonomy-safe system recovery nudge (not human steering).
        # Only inject at most once per turn to avoid spamming the model.
        if (not success) and content.get("retryable") and not turn_state["recovery_injected"]:
            ft = content.get("failure_type") or "unknown"
            phen = content.get("phenomenon") or ""

            # Template recovery steps (application-agnostic, but tool-aware)
            if ft == "system":
                recovery_steps = "Try status. then camera.get. If that fails, pause and try again." \
                                 " If skills exist, you may call skill.run."
            elif ft == "perception":
                recovery_steps = "Call camera.get (or head.scan/head.look) again before acting."
            elif ft == "manipulation":
                recovery_steps = "Call camera.get to re-check target, then use arm.interact before arm.grab." \
                                 " Consider changing side or target."
            else:
                recovery_steps = "Re-observe (status./camera.get) and choose a safer next action."

            agent.follow_up(
                f"[Recovery] Tool failed: {ctx.tool_call.tool_name} "
                f"failure_type={ft} phenomenon={phen}. {recovery_steps}"
            )
            turn_state["recovery_injected"] = True

    # Attach hooks after agent creation (captures agent.follow_up).
    cfg.before_tool_call = before_tool_call
    cfg.after_tool_call = after_tool_call

    for t in scenario.tools():
        agent.register_tool(t)

    # Register skill meta-tools if packs are present.
    if packs:
        from snakes.skills import SkillExecutor
        from snakes.types import AgentTool

        # Build executor over current tool map (scenario tools only).
        tool_map = {t.name: t for t in agent.tools}

        executor = SkillExecutor(
            packs,
            tool_map=tool_map,
            on_step_start=lambda tool, args, skill=None: bridge.on_tool_execution_start(
                f"skill.step:{skill}:{tool}", args
            ),
            on_step_end=lambda tool, args, out, skill=None: bridge.on_tool_execution_end(
                f"skill.step:{skill}:{tool}", args, out, success=out.get("outcome") == "success"
            ),
        )

        async def _run_skill(params: dict[str, Any]) -> Any:
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return {
                    "outcome": "fail",
                    "failure_type": "system",
                    "phenomenon": "skill.run missing name",
                    "retryable": False,
                }
            try:
                r = await executor.run(name)
                return r.outcome
            except Exception as exc:
                return {
                    "outcome": "fail",
                    "failure_type": "system",
                    "phenomenon": f"skill.run error: {exc}",
                    "retryable": False,
                }

        agent.register_tool(
            AgentTool(
                name="skill.run",
                description="Run a named skill from loaded skillpacks (workflow of tool steps).",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                execute=_run_skill,
                timeout_s=30.0,
                max_retries=0,
                is_concurrency_safe=lambda _in: False,
            )
        )

        # If any recovery skills exist, hint the model in the system prompt.
        # Keep it short.
        try:
            available = executor.list()
            if available:
                bridge.eventlog.write_cognitive(
                    {"skills_loaded": available},
                    tags=["skills"],
                )
        except Exception:
            pass

    agent.on(None, on_event)

    # First prompt: give the model the scenario + initial observation.
    scenario_hint = ""
    try:
        scenario_hint = scenario.prompt_instructions() or ""
    except Exception:
        scenario_hint = ""

    prompt = (
        (scenario_hint + "\n\n" if scenario_hint else "")
        + f"Initial observation: {obs0}"
    )

    await agent.prompt(prompt)

    # Determine outcome
    escaped = scenario.is_done()
    outcome = "success" if escaped else "failure"
    score = scenario.score()

    bridge.on_agent_end(task_id, success=escaped)
    bridge.eventlog.write_cognitive({"run_end": {"task_id": task_id, "outcome": outcome, "score": score}})
    bridge.eventlog.flush()
    bridge.unbind_task()

    return RunResult(task_id=task_id, score=score, outcome=outcome)


def _kernel_rules_prompt() -> str:
    # Runtime-level invariants (keep minimal and scenario-agnostic).
    return (
        "# Runtime Rules (kernel)\n"
        "- Prefer actions over long explanations.\n"
        "- After each action, use observations to verify progress.\n"
        "- Treat failures as normal: recover and continue.\n"
        "- If you are stuck, re-observe (status./camera.get) before trying risky actions.\n"
    )


def _infer_robot_id(robot_md_path: str) -> str:
    # Best-effort robot_id parse from ROBOT.md frontmatter.
    try:
        from snakes.robot_md import load_robot_md

        ident = load_robot_md(robot_md_path)
        if ident.robot_id:
            return ident.robot_id
    except Exception:
        pass
    return "robot"
