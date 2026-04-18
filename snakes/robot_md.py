from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class SkillEntry:
    name: str
    source: str  # "innate" | "installed" | "learned" | "fleet"
    status: str = "available"  # "available" | "not_deployed" | "installable"
    learned_date: Optional[str] = None
    success_rate: Optional[float] = None
    from_robot: Optional[str] = None


@dataclass
class RobotIdentity:
    robot_id: str = "unnamed"
    serial: str = ""
    manufacturer: str = ""
    model: str = ""
    current_role: Optional[str] = None
    fleet_id: Optional[str] = None
    learned_skills_count: int = 0
    last_self_assessment: Optional[str] = None

    personality: list[str] = field(default_factory=list)
    ethics: list[str] = field(default_factory=list)
    body_description: str = ""
    skills_innate: list[SkillEntry] = field(default_factory=list)
    skills_installed: list[SkillEntry] = field(default_factory=list)
    skills_learned: list[SkillEntry] = field(default_factory=list)
    skills_fleet: list[SkillEntry] = field(default_factory=list)
    self_perception: str = ""
    fleet_description: str = ""

    raw_markdown: str = ""


def load_robot_md(path: str | Path) -> RobotIdentity:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    identity = RobotIdentity(raw_markdown=text)

    frontmatter = _parse_frontmatter(text)
    if frontmatter:
        identity.robot_id = frontmatter.get("robot_id", identity.robot_id)
        identity.serial = frontmatter.get("serial", "")
        identity.manufacturer = frontmatter.get("manufacturer", "")
        identity.model = frontmatter.get("model", "")
        identity.current_role = frontmatter.get("current_role")
        identity.fleet_id = frontmatter.get("fleet_id")
        identity.learned_skills_count = int(frontmatter.get("learned_skills_count", 0))
        identity.last_self_assessment = frontmatter.get("last_self_assessment")

    return identity


def load_role(roles_dir: str | Path, role_name: str) -> str:
    p = Path(roles_dir) / f"{role_name}.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def assemble_prompt(robot_md_path: str | Path, roles_dir: str | Path) -> str:
    identity = load_robot_md(robot_md_path)
    body = _strip_frontmatter(identity.raw_markdown)

    parts = [body.strip()]

    if identity.current_role:
        role_text = load_role(roles_dir, identity.current_role)
        if role_text:
            role_body = _strip_frontmatter(role_text)
            parts.append("---")
            parts.append(role_body.strip())

    return "\n\n".join(parts)


def add_learned_skill(
    path: str | Path,
    skill_name: str,
    learned_date: str,
    success_rate: float,
) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    entry_line = f"- {skill_name} ({learned_date}, {success_rate:.0f}%)"

    placeholder = "暂无习得技能。我将通过不断尝试来学习。"
    if placeholder in text:
        text = text.replace(placeholder, entry_line)
    else:
        marker = "### 习得"
        idx = text.find(marker)
        if idx != -1:
            next_section = text.find("\n### ", idx + len(marker))
            if next_section == -1:
                next_section = text.find("\n## ", idx + len(marker))
            if next_section == -1:
                next_section = len(text)
            insert_pos = next_section
            text = text[:insert_pos].rstrip() + "\n" + entry_line + "\n" + text[insert_pos:]

    frontmatter = _parse_frontmatter(text)
    if frontmatter:
        count = int(frontmatter.get("learned_skills_count", 0)) + 1
        text = _update_frontmatter_field(text, "learned_skills_count", str(count))

    p.write_text(text, encoding="utf-8")


def update_self_perception(path: str | Path, assessment: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    marker = "## 自我认知"
    idx = text.find(marker)
    if idx == -1:
        return

    next_section = text.find("\n## ", idx + len(marker))
    if next_section == -1:
        next_section = len(text)

    header_end = text.find("\n", idx)
    new_section = f"{marker} (Self-Perception)\n\n{assessment.strip()}\n"
    text = text[:idx] + new_section + text[next_section:]

    from datetime import date
    text = _update_frontmatter_field(text, "last_self_assessment", date.today().isoformat())

    p.write_text(text, encoding="utf-8")


def install_fleet_skill(path: str | Path, skill_name: str, from_robot: str) -> None:
    add_learned_skill(path, f"{skill_name} (从 Fleet 安装, 来自 {from_robot})",
                      _today(), 0.0)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    result: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            if val in ("null", "None", ""):
                result[key.strip()] = None
            else:
                result[key.strip()] = val
    return result


def _strip_frontmatter(text: str) -> str:
    m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    if m:
        return text[m.end():]
    return text


def _update_frontmatter_field(text: str, key: str, value: str) -> str:
    pattern = rf"^({key}:\s*).*$"
    replacement = rf"\g<1>{value}"
    return re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)
