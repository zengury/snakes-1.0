from __future__ import annotations

import pytest

from scenarios.escape_room import EscapeRoom, create_level
from scenarios.scoring import HackathonScorer, LevelMetrics, score_run
from scenarios.x2_mock import X2HackathonMock


def test_level1_explore():
    room = create_level(1)
    assert room.current_room != ""

    info = room.look()
    assert "room" in info
    assert "exits" in info

    exits = info["exits"]
    assert len(exits) > 0

    for exit_name in exits[:2]:
        result = room.move(exit_name)
        assert result.get("ok") is True or "error" in result

    discovered = [name for name, r in room.rooms.items() if r.discovered]
    assert len(discovered) >= 2


def test_level2_find_clue():
    room = create_level(2)
    info = room.look()
    assert len(info.get("objects", [])) > 0

    for obj_name in info.get("objects", []):
        result = room.interact(obj_name)
        assert isinstance(result, dict)
        assert "ok" in result


def test_level3_escape():
    room = create_level(3)
    assert room.current_room != ""
    assert room.escaped is False


def test_scoring():
    metrics_l1 = LevelMetrics(
        rooms_discovered=4,
        map_accuracy=0.9,
        time_taken=60.0,
    )
    result = score_run(1, metrics_l1)
    assert "total" in result
    assert result["total"] > 0

    metrics_l3 = LevelMetrics(
        rooms_discovered=5,
        rooms_escaped=5,
        puzzles_solved=3,
        skills_created=2,
        memory_retrievals=5,
        hints_used=0,
        time_taken=200.0,
        total_time=200.0,
    )
    result_l3 = score_run(3, metrics_l3)
    assert result_l3["total"] > 200
    assert result_l3["efficiency_bonus"] == 30


def test_x2_mock_integration():
    escape_room = create_level(1)
    mock = X2HackathonMock(escape_room=escape_room)

    camera_result = mock.execute("camera.get", {})
    assert camera_result["ok"] is True
    assert "room" in camera_result["result"]
    assert camera_result["result"]["room"] == "Entrance Hall"

    lidar_result = mock.execute("lidar.get", {})
    assert lidar_result["ok"] is True
    assert "obstacles" in lidar_result["result"]

    walk_result = mock.execute("walk.to", {"direction": "north"})
    assert walk_result["ok"] is True

    camera_after = mock.execute("camera.get", {})
    assert camera_after["result"]["room"] == "Library"

    status = mock.execute("status.", {})
    assert status["ok"] is True
    assert status["result"]["moves"] == 1


def test_hackathon_scorer():
    scorer = HackathonScorer()
    scorer.record_level(1, LevelMetrics(
        rooms_discovered=4,
        map_accuracy=0.8,
        time_taken=60.0,
    ))
    summary = scorer.summary()
    assert 1 in summary["levels_completed"]
    assert len(summary["per_level"]) == 1
    assert summary["total_score"] > 0
