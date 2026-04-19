"""
Semantic memory: durable learned skills for this agent.

Critic-gated writes enforced at the Memory facade layer, not here — this store
just provides the data plane.
"""
from __future__ import annotations

import fnmatch

from ..protocols import SemanticStore, Skill


class InMemorySemanticStore:
    """Implements SemanticStore in-memory. For production use SQLite variant."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        # Track superseded chains so query() can filter them
        self._superseded: set[str] = set()

    def add_skill(self, skill: Skill) -> None:
        self._skills[skill.skill_id] = skill
        for old_id in skill.supersedes:
            self._superseded.add(old_id)

    def get_skill(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def query(self, *, task_type: str | None = None,
              environment_class: str | None = None,
              min_confidence: float = 0.0,
              limit: int = 10) -> list[Skill]:
        results: list[Skill] = []
        for skill in self._skills.values():
            if skill.skill_id in self._superseded:
                continue
            if skill.confidence < min_confidence:
                continue
            if environment_class and skill.environment_class != environment_class:
                # Support glob: "indoor_*" matches "indoor_residential"
                if not fnmatch.fnmatch(skill.environment_class, environment_class):
                    continue
            if task_type:
                # Task-type match: check first command name against pattern
                if not skill.cli_sequence:
                    continue
                first_cmd_name = skill.cli_sequence[0].name
                if not (task_type in first_cmd_name or
                        fnmatch.fnmatch(first_cmd_name, task_type)):
                    continue
            results.append(skill)

        # Rank by confidence * recency (recency approximated by sample_count)
        results.sort(
            key=lambda s: s.confidence * (1.0 + 0.01 * s.sample_count),
            reverse=True,
        )
        return results[:limit]

    def update_confidence(self, skill_id: str, new_confidence: float) -> None:
        if skill_id not in self._skills:
            raise KeyError(f"no skill {skill_id}")
        # Clamp to [0, 1]
        clamped = max(0.0, min(1.0, new_confidence))
        # Dataclass replace-in-place
        self._skills[skill_id].confidence = clamped

    def supersede(self, old_id: str, new_skill: Skill) -> None:
        if old_id not in self._skills:
            raise KeyError(f"no skill {old_id} to supersede")
        if old_id not in new_skill.supersedes:
            new_skill.supersedes.append(old_id)
        self._superseded.add(old_id)
        self._skills[new_skill.skill_id] = new_skill

    def decay(self, unused_days: float = 30, rate: float = 0.9) -> int:
        """Apply confidence decay to skills unused for N days.

        Returns count of skills that had their confidence reduced.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=unused_days)
        count = 0
        for skill in self._skills.values():
            if skill.skill_id in self._superseded:
                continue
            if skill.last_used < cutoff:
                skill.confidence = max(0.0, skill.confidence * rate)
                count += 1
        return count


# Protocol check
_: SemanticStore = InMemorySemanticStore()
