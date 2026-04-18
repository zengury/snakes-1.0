"""Skill registry — manages the robot's skill inventory.

Skills live in memkit.Semantic. This module provides:
- Querying available skills (by name, source, category)
- Installing skills from Fleet
- Registering new learned skills after Critic promotion
- Generating the Skills section for ROBOT.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Skill:
    name: str
    source: str  # "innate" | "installed" | "learned" | "fleet"
    description: str = ""
    learned_date: Optional[str] = None
    success_rate: Optional[float] = None
    from_robot: Optional[str] = None
    category: str = "general"
    dependencies: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)


class SkillRegistry:

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        return name in self._skills

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def by_source(self, source: str) -> list[Skill]:
        return [s for s in self._skills.values() if s.source == source]

    def by_category(self, category: str) -> list[Skill]:
        return [s for s in self._skills.values() if s.category == category]

    @property
    def innate(self) -> list[Skill]:
        return self.by_source("innate")

    @property
    def installed(self) -> list[Skill]:
        return self.by_source("installed")

    @property
    def learned(self) -> list[Skill]:
        return self.by_source("learned")

    @property
    def fleet(self) -> list[Skill]:
        return self.by_source("fleet")

    def install_from_fleet(self, skill: Skill) -> Skill:
        local = Skill(
            name=skill.name,
            source="learned",
            description=skill.description,
            from_robot=skill.from_robot,
            category=skill.category,
            dependencies=skill.dependencies,
            parameters=skill.parameters.copy(),
            success_rate=0.0,
        )
        self._skills[local.name] = local
        return local

    def promote_from_memory(
        self,
        name: str,
        description: str,
        learned_date: str,
        success_rate: float,
        category: str = "general",
        parameters: Optional[dict[str, Any]] = None,
    ) -> Skill:
        skill = Skill(
            name=name,
            source="learned",
            description=description,
            learned_date=learned_date,
            success_rate=success_rate,
            category=category,
            parameters=parameters or {},
        )
        self._skills[name] = skill
        return skill

    def capability_check(self, required: list[str]) -> dict[str, bool]:
        return {name: self.has(name) for name in required}

    def render_for_robot_md(self, max_learned: int = 10) -> str:
        lines: list[str] = []

        innate = self.innate
        if innate:
            names = ", ".join(s.name for s in innate)
            lines.append(f"### 先天（{len(innate)}）")
            lines.append(names)
            lines.append("")

        installed = self.installed
        if installed:
            lines.append(f"### 预装（{len(installed)}）")
            for s in installed:
                status = "✓" if s.success_rate is None or s.success_rate > 0 else "✗（未部署）"
                lines.append(f"- {s.name}: {status}")
            lines.append("")

        learned = sorted(self.learned, key=lambda s: s.learned_date or "", reverse=True)
        lines.append(f"### 习得（{len(learned)}）")
        if not learned:
            lines.append("暂无习得技能。我将通过不断尝试来学习。")
        else:
            shown = learned[:max_learned]
            for s in shown:
                rate = f"{s.success_rate:.0f}%" if s.success_rate is not None else "?"
                date = s.learned_date or "?"
                lines.append(f"- {s.name} ({date}, {rate})")
            if len(learned) > max_learned:
                lines.append(f"... 共 {len(learned)} 个 — `memkit query skills`")
        lines.append("")

        fleet = self.fleet
        lines.append(f"### Fleet 可安装（{len(fleet)}）")
        if not fleet:
            lines.append("暂无 Fleet 技能。")
        else:
            for s in fleet:
                src = f"来自 {s.from_robot}" if s.from_robot else ""
                lines.append(f"- {s.name} ({src})")
        lines.append("")

        return "\n".join(lines)

    def filter_for_role(self, active: list[str], hidden: list[str]) -> list[Skill]:
        if active:
            active_set = set(active)
            return [s for s in self._skills.values() if s.name in active_set]
        if hidden:
            hidden_set = set(hidden)
            return [s for s in self._skills.values() if s.name not in hidden_set]
        return self.all()
