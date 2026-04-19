"""Tests for semantic stores — both in-memory and SQLite."""
from datetime import datetime, timedelta, timezone

import pytest

from memkit import Command, Skill
from memkit.layers.semantic import InMemorySemanticStore
from memkit.stores.sqlite import SQLiteSemanticStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemorySemanticStore()
    else:
        s = SQLiteSemanticStore(tmp_path / "sem.db")
        yield s
        s.close()


def _skill(skill_id: str, env: str = "indoor_residential",
           confidence: float = 0.8, cmd_name: str = "arm.grasp",
           last_used: datetime | None = None) -> Skill:
    return Skill(
        skill_id=skill_id,
        cli_sequence=[Command(name=cmd_name, params={"force": 12})],
        preconditions=[],
        environment_class=env,
        success_rate=0.9,
        sample_count=5,
        confidence=confidence,
        last_used=last_used or datetime.now(timezone.utc),
        provenance={"source": "test"},
    )


def test_add_and_get_skill(store):
    s = _skill("sk_1")
    store.add_skill(s)
    fetched = store.get_skill("sk_1")
    assert fetched is not None
    assert fetched.skill_id == "sk_1"
    assert fetched.cli_sequence[0].name == "arm.grasp"


def test_get_missing_returns_none(store):
    assert store.get_skill("sk_missing") is None


def test_query_filters_by_environment(store):
    store.add_skill(_skill("sk_indoor", env="indoor_residential"))
    store.add_skill(_skill("sk_outdoor", env="outdoor_urban"))
    results = store.query(environment_class="indoor_residential")
    ids = [s.skill_id for s in results]
    assert "sk_indoor" in ids
    assert "sk_outdoor" not in ids


def test_query_filters_by_min_confidence(store):
    store.add_skill(_skill("sk_high", confidence=0.9))
    store.add_skill(_skill("sk_low", confidence=0.2))
    results = store.query(min_confidence=0.5)
    ids = [s.skill_id for s in results]
    assert "sk_high" in ids
    assert "sk_low" not in ids


def test_query_respects_limit(store):
    for i in range(10):
        store.add_skill(_skill(f"sk_{i}"))
    results = store.query(limit=3)
    assert len(results) == 3


def test_update_confidence_clamps(store):
    store.add_skill(_skill("sk_1", confidence=0.5))
    store.update_confidence("sk_1", 1.5)
    assert store.get_skill("sk_1").confidence == 1.0
    store.update_confidence("sk_1", -0.5)
    assert store.get_skill("sk_1").confidence == 0.0


def test_update_confidence_unknown_raises(store):
    with pytest.raises(KeyError):
        store.update_confidence("sk_missing", 0.5)


def test_supersede_hides_old_from_query(store):
    old = _skill("sk_old")
    store.add_skill(old)
    new = _skill("sk_new")
    store.supersede("sk_old", new)
    ids = [s.skill_id for s in store.query()]
    assert "sk_old" not in ids
    assert "sk_new" in ids


def test_decay_reduces_unused(store):
    old_date = datetime.now(timezone.utc) - timedelta(days=60)
    fresh_date = datetime.now(timezone.utc)
    store.add_skill(_skill("sk_stale", confidence=0.8, last_used=old_date))
    store.add_skill(_skill("sk_fresh", confidence=0.8, last_used=fresh_date))
    decayed_count = store.decay(unused_days=30, rate=0.5)
    assert decayed_count == 1
    assert store.get_skill("sk_stale").confidence == pytest.approx(0.4)
    assert store.get_skill("sk_fresh").confidence == pytest.approx(0.8)


def test_query_ranks_by_confidence(store):
    store.add_skill(_skill("sk_low", confidence=0.3))
    store.add_skill(_skill("sk_high", confidence=0.9))
    store.add_skill(_skill("sk_mid", confidence=0.6))
    results = store.query(limit=3)
    assert [s.skill_id for s in results] == ["sk_high", "sk_mid", "sk_low"]
