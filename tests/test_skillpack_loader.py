from __future__ import annotations

import json
from pathlib import Path

import pytest

from snakes.skills import load_skillpack


def test_load_skillpack(tmp_path: Path) -> None:
    d = tmp_path / "pack"
    d.mkdir()
    (d / "skillpack.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "skills": [
                    {
                        "name": "recover.system.quick",
                        "description": "reconnect and observe",
                        "steps": [
                            {"tool": "status.", "args": {}},
                            {"tool": "camera.get", "args": {}},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    pack = load_skillpack(d)
    assert pack.version == "0.1"
    assert len(pack.skills) == 1
    assert pack.skills[0].name == "recover.system.quick"
    assert pack.skills[0].steps[0].tool == "status."


def test_load_skillpack_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception):
        load_skillpack(tmp_path / "missing")
