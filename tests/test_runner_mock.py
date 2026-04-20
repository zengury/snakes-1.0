from __future__ import annotations

import tempfile

import pytest

from snakes.runtime.runner import run_scenario
from snakes.scenarios import EscapeRoomMockScenario, FailureInjectionConfig


@pytest.mark.asyncio
async def test_run_escape_room_level2_with_mock_provider() -> None:
    # No failures injected: the mock policy should solve level 2.
    scenario = EscapeRoomMockScenario(
        failure_cfg=FailureInjectionConfig(
            seed=123,
            p_vision_fail=0.0,
            p_manip_fail=0.0,
            p_system_timeout=0.0,
            p_system_disconnect=0.0,
        )
    )

    with tempfile.TemporaryDirectory() as d:
        result = await run_scenario(
            scenario,
            robot_md_path="ROBOT.md",
            roles_dir="roles",
            level=2,
            provider="mock",
            model="mock",
            eventlog_dir=d,
            seed=123,
            max_turns=20,
        )

    assert result.outcome == "success"


@pytest.mark.asyncio
async def test_run_escape_room_level3_with_mock_provider() -> None:
    scenario = EscapeRoomMockScenario(
        failure_cfg=FailureInjectionConfig(
            seed=0,
            p_vision_fail=0.0,
            p_manip_fail=0.0,
            p_system_timeout=0.0,
            p_system_disconnect=0.0,
        )
    )

    with tempfile.TemporaryDirectory() as d:
        result = await run_scenario(
            scenario,
            robot_md_path="ROBOT.md",
            roles_dir="roles",
            level=3,
            provider="mock",
            model="mock",
            eventlog_dir=d,
            seed=0,
            max_turns=60,
        )

    assert result.outcome == "success"


@pytest.mark.asyncio
async def test_run_escape_room_level2_with_forced_failures() -> None:
    # Forced failures should not break the golden path; mock policy retries and
    # toolchain retries system timeouts.
    scenario = EscapeRoomMockScenario(
        failure_cfg=FailureInjectionConfig(
            seed=1,
            force_system_timeout=1,
            force_manip_fail=1,
            force_vision_fail=1,
        )
    )

    with tempfile.TemporaryDirectory() as d:
        result = await run_scenario(
            scenario,
            robot_md_path="ROBOT.md",
            roles_dir="roles",
            level=2,
            provider="mock",
            model="mock",
            eventlog_dir=d,
            seed=1,
            max_turns=40,
        )

    assert result.outcome == "success"
