from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from snakes.skills import SkillExecutor, load_skillpack
from snakes.types import AgentTool


@pytest.mark.asyncio
async def test_skill_executor_runs_steps(tmp_path: Path) -> None:
    (tmp_path / "skillpack.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "skills": [
                    {
                        "name": "recover.system.quick",
                        "steps": [
                            {"tool": "status.", "args": {}},
                            {"tool": "camera.get", "args": {}},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pack = load_skillpack(tmp_path)

    calls = []

    async def status(_):
        calls.append("status")
        return {"outcome": "success", "result": {"ok": True}}

    async def cam(_):
        calls.append("cam")
        return {"outcome": "success", "result": {"ok": True}}

    tool_map = {
        "status.": AgentTool("status.", "", {"type": "object", "properties": {}}, status),
        "camera.get": AgentTool("camera.get", "", {"type": "object", "properties": {}}, cam),
    }

    ex = SkillExecutor([pack], tool_map=tool_map)
    r = await ex.run("recover.system.quick")
    assert r.ok is True
    assert calls == ["status", "cam"]
