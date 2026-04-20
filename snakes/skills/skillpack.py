from __future__ import annotations

"""skillpack (B1) — minimal skill packaging format.

Design goals for 2.0:
- Minimal and offline-friendly (stdlib only) → JSON, not YAML.
- Skills are *tool-backed workflows*: a list of tool calls.
- Execution engine is B2; this module only defines format + loader.

A skillpack file contains:

{
  "version": "0.1",
  "skills": [
    {
      "name": "recover.system.quick_retry",
      "description": "Retry system failures and re-observe.",
      "steps": [
        {"tool": "status.", "args": {}},
        {"tool": "camera.get", "args": {}}
      ]
    }
  ]
}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class SkillStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str = ""
    steps: list[SkillStep] = field(default_factory=list)

    # Optional metadata (kept minimal)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillPack:
    version: str = "0.1"
    skills: list[SkillSpec] = field(default_factory=list)


class SkillPackError(ValueError):
    pass


def load_skillpack(path: str | Path) -> SkillPack:
    p = Path(path)
    if p.is_dir():
        p = p / "skillpack.json"
    if not p.exists():
        raise SkillPackError(f"Skillpack not found: {p}")

    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SkillPackError("skillpack.json must be an object")

    version = str(data.get("version", "0.1"))
    skills_raw = data.get("skills", [])
    if not isinstance(skills_raw, list):
        raise SkillPackError("skills must be a list")

    skills: list[SkillSpec] = []
    for s in skills_raw:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SkillPackError("skill missing valid name")
        desc = s.get("description", "")
        if not isinstance(desc, str):
            desc = str(desc)

        tags = s.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags if t is not None]

        steps_raw = s.get("steps", [])
        if not isinstance(steps_raw, list):
            raise SkillPackError(f"skill {name}: steps must be a list")

        steps: list[SkillStep] = []
        for st in steps_raw:
            if not isinstance(st, dict):
                raise SkillPackError(f"skill {name}: step must be an object")
            tool = st.get("tool")
            if not isinstance(tool, str) or not tool.strip():
                raise SkillPackError(f"skill {name}: step missing tool")
            args = st.get("args", {})
            if not isinstance(args, dict):
                raise SkillPackError(f"skill {name}: step args must be an object")
            steps.append(SkillStep(tool=tool, args=dict(args)))

        skills.append(SkillSpec(name=name, description=desc, steps=steps, tags=tags))

    return SkillPack(version=version, skills=skills)


def load_skillpacks(paths: list[str | Path]) -> list[SkillPack]:
    packs: list[SkillPack] = []
    for p in paths:
        packs.append(load_skillpack(p))
    return packs
