from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from snakes.runtime.runner import run_scenario
from snakes.runtime.score import aggregate_task, TaskAggregate
from snakes.scenarios import EscapeRoomMockScenario, FailureInjectionConfig


def _fmt_kv(d: dict[str, Any]) -> str:
    if not d:
        return "(none)"
    return ", ".join(f"{k}={v}" for k, v in sorted(d.items()))


def _render_markdown(
    args: argparse.Namespace,
    rows: list[dict[str, Any]],
) -> str:
    total = len(rows)
    passed = sum(1 for r in rows if r["outcome"] == "success")
    sum_failures: dict[str, int] = {}
    sum_latency_by_group: dict[str, int] = {}
    sum_timeouts = 0
    sum_retry_attempts = 0

    for r in rows:
        agg: TaskAggregate = r["agg"]
        sum_timeouts += agg.timeouts
        sum_retry_attempts += agg.retry_attempts_total
        for k, v in agg.failure_counts.items():
            sum_failures[k] = sum_failures.get(k, 0) + v
        for k, v in agg.tool_latency_by_group.items():
            sum_latency_by_group[k] = sum_latency_by_group.get(k, 0) + v

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = dt.date.today().isoformat()

    lines: list[str] = []
    lines.append(f"# Run Report — mock matrix ({today})")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")
    lines.append(
        "Purpose: regression of the golden path under probabilistic failures "
        "(provider=mock, no external API keys)."
    )
    lines.append("")
    lines.append("Command:")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "python3 scripts/run_matrix_mock.py "
        f"--level {args.level} --seeds {args.seeds} "
        f"--p-vision {args.p_vision} --p-manip {args.p_manip} "
        f"--p-timeout {args.p_timeout}"
    )
    lines.append("```")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Seeds: {total}")
    lines.append(f"- Passed: {passed}/{total}")
    lines.append(f"- Total timeouts: {sum_timeouts}")
    lines.append(f"- Total retry attempts: {sum_retry_attempts}")
    lines.append(f"- Failures by type: {_fmt_kv(sum_failures)}")
    lines.append(f"- Tool latency (ms) by group: {_fmt_kv(sum_latency_by_group)}")
    lines.append("")
    lines.append("## Per-seed")
    lines.append("")
    lines.append(
        "| seed | outcome | time_s | sim_time_s | events | timeouts | "
        "retries | failures | latency_by_group |"
    )
    lines.append(
        "|------|---------|--------|------------|--------|----------|"
        "---------|----------|-------------------|"
    )
    for r in rows:
        agg = r["agg"]
        score = r["score"] or {}
        time_s = score.get("time_s")
        sim_time_s = score.get("sim_time_s")
        lines.append(
            "| {seed} | {outcome} | {time_s} | {sim_time_s} | {events} | {timeouts} | "
            "{retries} | {failures} | {latency} |".format(
                seed=r["seed"],
                outcome=r["outcome"],
                time_s=f"{time_s:.4f}" if isinstance(time_s, (int, float)) else "-",
                sim_time_s=f"{sim_time_s:.2f}" if isinstance(sim_time_s, (int, float)) else "-",
                events=agg.events,
                timeouts=agg.timeouts,
                retries=agg.retry_attempts_total,
                failures=_fmt_kv(agg.failure_counts),
                latency=_fmt_kv(agg.tool_latency_by_group),
            )
        )
    lines.append("")
    lines.append("## Raw results")
    lines.append("")
    lines.append("```json")
    raw = [{k: v for k, v in r.items() if k != "agg"} for r in rows]
    lines.append(json.dumps({"results": raw}, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--p-vision", type=float, default=0.1)
    ap.add_argument("--p-manip", type=float, default=0.1)
    ap.add_argument("--p-timeout", type=float, default=0.05)
    ap.add_argument(
        "--report",
        default=None,
        help=(
            "Optional path to write a Markdown report. "
            "Pass 'auto' to write docs/dev/RUN_REPORT_mock_matrix_<date>.md."
        ),
    )
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    for s in range(args.seeds):
        cfg = FailureInjectionConfig(
            seed=s,
            p_vision_fail=args.p_vision,
            p_manip_fail=args.p_manip,
            p_system_timeout=args.p_timeout,
        )
        scenario = EscapeRoomMockScenario(failure_cfg=cfg)
        with tempfile.TemporaryDirectory() as d:
            r = await run_scenario(
                scenario,
                robot_md_path="ROBOT.md",
                roles_dir="roles",
                level=args.level,
                provider="mock",
                model="mock",
                eventlog_dir=d,
                seed=s,
                max_turns=80,
            )
            agg = aggregate_task(d, r.task_id)
        rows.append({
            "seed": s,
            "task_id": r.task_id,
            "outcome": r.outcome,
            "score": r.score,
            "cfg": asdict(cfg),
            "failure_counts": agg.failure_counts,
            "timeouts": agg.timeouts,
            "retry_attempts_total": agg.retry_attempts_total,
            "tool_latency_by_group": agg.tool_latency_by_group,
            "events": agg.events,
            "agg": agg,
        })

    raw = [{k: v for k, v in r.items() if k != "agg"} for r in rows]
    print(json.dumps({"results": raw}, ensure_ascii=False, indent=2))

    if args.report:
        if args.report == "auto":
            today = dt.date.today().isoformat()
            out_path = Path("docs/dev") / f"RUN_REPORT_mock_matrix_{today}.md"
        else:
            out_path = Path(args.report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_render_markdown(args, rows), encoding="utf-8")
        print(f"Report written: {out_path}")

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
