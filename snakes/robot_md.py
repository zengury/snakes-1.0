from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RobotIdentity:
    name: str = "unnamed"
    type: str = "unknown"
    dof: int = 0
    sensors: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    learned_skills: list[str] = field(default_factory=list)
    location: str = "unknown"
    battery: float = 100.0
    current_task: str = ""
    owner: str = ""


def load_robot_md(path: str | Path) -> RobotIdentity:
    text = Path(path).read_text()
    identity = RobotIdentity()

    def _extract(key: str) -> str | None:
        m = re.search(rf"^\*?\*?{key}\*?\*?:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _extract_list(key: str) -> list[str]:
        val = _extract(key)
        if not val:
            return []
        return [item.strip().lstrip("- ") for item in val.split(",") if item.strip()]

    if v := _extract("name"):
        identity.name = v
    if v := _extract("type"):
        identity.type = v
    if v := _extract("dof"):
        try:
            identity.dof = int(v)
        except ValueError:
            pass
    identity.sensors = _extract_list("sensors")
    identity.capabilities = _extract_list("capabilities")
    identity.learned_skills = _extract_list("learned.skills") or _extract_list("learned skills")
    if v := _extract("location"):
        identity.location = v
    if v := _extract("battery"):
        try:
            identity.battery = float(v.replace("%", ""))
        except ValueError:
            pass
    if v := _extract("current.task") or _extract("current task"):
        identity.current_task = v
    if v := _extract("owner"):
        identity.owner = v

    return identity


def render_robot_md(identity: RobotIdentity) -> str:
    sensors = ", ".join(identity.sensors) if identity.sensors else "none"
    capabilities = ", ".join(identity.capabilities) if identity.capabilities else "none"
    learned = ", ".join(identity.learned_skills) if identity.learned_skills else "none"

    return (
        f"# ROBOT.md\n"
        f"\n"
        f"**Name**: {identity.name}\n"
        f"**Type**: {identity.type}\n"
        f"**DOF**: {identity.dof}\n"
        f"**Sensors**: {sensors}\n"
        f"**Capabilities**: {capabilities}\n"
        f"**Learned Skills**: {learned}\n"
        f"**Location**: {identity.location}\n"
        f"**Battery**: {identity.battery}%\n"
        f"**Current Task**: {identity.current_task or 'idle'}\n"
        f"**Owner**: {identity.owner or 'unassigned'}\n"
    )


def update_robot_md(path: str | Path, identity: RobotIdentity) -> None:
    Path(path).write_text(render_robot_md(identity))
