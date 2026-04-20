from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict

from snakes.runtime.runner import run_scenario
from snakes.scenarios import EscapeRoomMockScenario, FailureInjectionConfig


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--p-vision", type=float, default=0.1)
    ap.add_argument("--p-manip", type=float, default=0.1)
    ap.add_argument("--p-timeout", type=float, default=0.05)
    args = ap.parse_args()

    results = []
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
        results.append({"seed": s, "outcome": r.outcome, "score": r.score, "cfg": asdict(cfg)})

    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
