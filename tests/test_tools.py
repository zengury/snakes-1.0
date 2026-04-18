from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from snakes.tools import RobotTool, SafetyError, parse_manifest_tools
from snakes.robot_md import load_robot_md, assemble_prompt, add_learned_skill
from tests.conftest import MockExecutor


def test_parse_manifest(sample_manifest: str):
    tools = parse_manifest_tools(sample_manifest)
    assert len(tools) >= 3
    names = [t["name"] for t in tools]
    assert any("arm" in n or "move" in n for n in names)


@pytest.mark.asyncio
async def test_robot_tool_execute(mock_executor: MockExecutor):
    mock_executor.results["arm.gripper"] = {"ok": True, "result": "closed"}

    tool = RobotTool(
        name="arm_gripper",
        description="Open or close gripper",
        parameters={"action": {"type": "string", "description": "open or close"}},
        command="arm.gripper",
        executor=mock_executor,
    )

    result = await tool.execute({"action": "close"})
    assert result["ok"] is True
    assert result["result"] == "closed"
    assert len(mock_executor.calls) == 1


@pytest.mark.asyncio
async def test_safety_error(mock_executor: MockExecutor):
    mock_executor.safety_errors.add("arm.move_joint")

    tool = RobotTool(
        name="arm_move_joint",
        description="Move joint",
        parameters={
            "joint_id": {"type": "integer"},
            "angle": {"type": "number"},
        },
        command="arm.move_joint",
        executor=mock_executor,
    )

    with pytest.raises(SafetyError) as exc_info:
        await tool.execute({"joint_id": 0, "angle": 999.0})

    assert exc_info.value.command == "arm.move_joint"


def test_robot_md_load(sample_robot_md: Path):
    identity = load_robot_md(sample_robot_md)
    assert identity.robot_id == "x2-alpha"
    assert identity.model == "X2"
    assert identity.manufacturer == "agibot"
    assert identity.current_role == "hackathon"


def test_robot_md_add_skill(sample_robot_md: Path):
    add_learned_skill(sample_robot_md, "grasp-cup", "2026-04-17", 85.0)

    text = sample_robot_md.read_text()
    assert "grasp-cup" in text
    assert "85%" in text
    assert "暂无习得技能" not in text

    identity = load_robot_md(sample_robot_md)
    assert identity.learned_skills_count == 1
