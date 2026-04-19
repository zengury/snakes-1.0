from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LevelMetrics:
    rooms_discovered: int = 0
    map_accuracy: float = 0.0
    clues_found: int = 0
    puzzle_solved: bool = False
    puzzles_solved: int = 0
    rooms_escaped: int = 0
    hints_used: int = 0
    skills_created: int = 0
    memory_retrievals: int = 0
    time_taken: float = 0.0
    total_time: float = 0.0


_LEVEL_CONFIG: dict[int, dict[str, Any]] = {
    1: {
        "name": "Explorer",
        "max_base": 100,
        "time_bonus_threshold": 120.0,
        "time_bonus_max": 30,
    },
    2: {
        "name": "Investigator",
        "max_base": 200,
        "time_bonus_threshold": 180.0,
        "time_bonus_max": 50,
    },
    3: {
        "name": "Escapist",
        "max_base": 500,
        "time_bonus_threshold": 300.0,
        "time_bonus_max": 100,
    },
}


def _score_level_1(m: LevelMetrics) -> dict[str, Any]:
    cfg = _LEVEL_CONFIG[1]
    accuracy_points = int(m.map_accuracy * 80)
    discovery_points = min(m.rooms_discovered * 5, 20)
    base = accuracy_points + discovery_points
    time_bonus = 0
    if m.time_taken > 0 and m.time_taken < cfg["time_bonus_threshold"]:
        ratio = 1.0 - (m.time_taken / cfg["time_bonus_threshold"])
        time_bonus = int(ratio * cfg["time_bonus_max"])
    return {
        "level": 1,
        "level_name": cfg["name"],
        "accuracy_points": accuracy_points,
        "discovery_points": discovery_points,
        "time_bonus": time_bonus,
        "total": base + time_bonus,
        "max_possible": cfg["max_base"] + cfg["time_bonus_max"],
    }


def _score_level_2(m: LevelMetrics) -> dict[str, Any]:
    cfg = _LEVEL_CONFIG[2]
    clue_points = min(m.clues_found * 20, 60)
    solve_points = 100 if m.puzzle_solved else 0
    hint_penalty = m.hints_used * 15
    base = max(clue_points + solve_points - hint_penalty, 0)
    time_bonus = 0
    if m.time_taken > 0 and m.time_taken < cfg["time_bonus_threshold"]:
        ratio = 1.0 - (m.time_taken / cfg["time_bonus_threshold"])
        time_bonus = int(ratio * cfg["time_bonus_max"])
    return {
        "level": 2,
        "level_name": cfg["name"],
        "clue_points": clue_points,
        "solve_points": solve_points,
        "hint_penalty": hint_penalty,
        "time_bonus": time_bonus,
        "total": base + time_bonus,
        "max_possible": cfg["max_base"] + cfg["time_bonus_max"],
    }


def _score_level_3(m: LevelMetrics) -> dict[str, Any]:
    cfg = _LEVEL_CONFIG[3]
    room_points = m.rooms_escaped * 40
    puzzle_points = m.puzzles_solved * 60
    hint_penalty = m.hints_used * 20
    base = max(room_points + puzzle_points - hint_penalty, 0)
    time_used = m.total_time if m.total_time > 0 else m.time_taken
    time_bonus = 0
    if time_used > 0 and time_used < cfg["time_bonus_threshold"]:
        ratio = 1.0 - (time_used / cfg["time_bonus_threshold"])
        time_bonus = int(ratio * cfg["time_bonus_max"])
    skill_bonus = min(m.skills_created * 25, 75)
    memory_bonus = min(m.memory_retrievals * 15, 45)
    efficiency_bonus = 0
    if m.puzzles_solved > 0 and m.hints_used == 0:
        efficiency_bonus = 30
    total = base + time_bonus + skill_bonus + memory_bonus + efficiency_bonus
    return {
        "level": 3,
        "level_name": cfg["name"],
        "room_points": room_points,
        "puzzle_points": puzzle_points,
        "hint_penalty": hint_penalty,
        "time_bonus": time_bonus,
        "skill_bonus": skill_bonus,
        "memory_bonus": memory_bonus,
        "efficiency_bonus": efficiency_bonus,
        "total": total,
        "max_possible": cfg["max_base"] + cfg["time_bonus_max"] + 75 + 45 + 30,
    }


def score_run(level: int, metrics: LevelMetrics) -> dict[str, Any]:
    scorers = {
        1: _score_level_1,
        2: _score_level_2,
        3: _score_level_3,
    }
    scorer = scorers.get(level)
    if scorer is None:
        raise ValueError(f"Unknown level: {level}")
    return scorer(metrics)


@dataclass
class HackathonScorer:
    results: dict[int, dict[str, Any]] = field(default_factory=dict)

    def record_level(self, level: int, metrics: LevelMetrics) -> dict[str, Any]:
        result = score_run(level, metrics)
        self.results[level] = result
        return result

    def total_score(self) -> int:
        return sum(r["total"] for r in self.results.values())

    def summary(self) -> dict[str, Any]:
        return {
            "levels_completed": sorted(self.results.keys()),
            "per_level": dict(self.results),
            "total_score": self.total_score(),
            "bonuses": {
                "skills_created": any(
                    r.get("skill_bonus", 0) > 0 for r in self.results.values()
                ),
                "memory_used": any(
                    r.get("memory_bonus", 0) > 0 for r in self.results.values()
                ),
                "no_hints": all(
                    r.get("hint_penalty", 0) == 0 for r in self.results.values()
                ),
            },
        }
