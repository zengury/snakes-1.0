"""Tests for SQLite-backed quarantine and fleet stores."""
import time
from datetime import datetime, timezone

import pytest

from memkit import (
    Command,
    Episode,
    Event,
    MemoryCandidate,
    Outcome,
    SafetyRule,
    Severity,
    Skill,
)
from memkit.stores.sqlite_extras import (
    InMemoryFleetStore,
    SQLiteFleetStore,
    SQLiteQuarantineStore,
)


def _skill(skill_id: str, env: str = "indoor_residential",
           cmd_name: str = "arm.grasp", confidence: float = 0.8,
           samples: int = 5) -> Skill:
    return Skill(
        skill_id=skill_id,
        cli_sequence=[Command(name=cmd_name, params={"force": 12})],
        preconditions=[],
        environment_class=env,
        success_rate=0.9,
        sample_count=samples,
        confidence=confidence,
        last_used=datetime.now(timezone.utc),
        provenance={"source": "test"},
    )


def _candidate_with_events() -> MemoryCandidate:
    """Build a candidate with a real episode, skill, and safety rule for
    round-trip testing."""
    ep = Episode(
        episode_id="ep_test",
        task_id="task_test",
        started_at=datetime.now(timezone.utc),
        events=[
            Event(t=0.1, kind="cmd_issued", payload={"x": 1}),
            Event(t=0.2, kind="cmd_result", payload={"ok": True}),
        ],
        outcome=Outcome.SUCCESS,
        anomaly_flags=["minor_drift"],
        env_fingerprint="indoor_residential",
    )
    return MemoryCandidate(
        candidate_id="cand_test",
        episode=ep,
        proposed_skill=_skill("sk_1"),
        proposed_safety_rule=SafetyRule(
            rule_id="r_test",
            severity=Severity.WARN,
            context_predicate={"fact": "x", "value": True},
            forbidden_command_pattern="y.*",
        ),
    )


# ---------------- SQLite quarantine -----------------------------------------


def test_sqlite_quarantine_roundtrip(tmp_path):
    q = SQLiteQuarantineStore(tmp_path / "q.db")
    c = _candidate_with_events()
    q.enqueue(c)

    pending = q.pending()
    assert len(pending) == 1
    got = pending[0]
    assert got.candidate_id == "cand_test"
    assert got.episode.outcome == Outcome.SUCCESS
    assert got.episode.anomaly_flags == ["minor_drift"]
    assert len(got.episode.events) == 2
    assert got.proposed_skill is not None
    assert got.proposed_skill.skill_id == "sk_1"
    assert got.proposed_safety_rule is not None
    assert got.proposed_safety_rule.rule_id == "r_test"


def test_sqlite_quarantine_survives_reopen(tmp_path):
    db = tmp_path / "q.db"
    q1 = SQLiteQuarantineStore(db)
    q1.enqueue(_candidate_with_events())
    q1.close()

    q2 = SQLiteQuarantineStore(db)
    assert len(q2.pending()) == 1


def test_sqlite_quarantine_mark_reviewed(tmp_path):
    q = SQLiteQuarantineStore(tmp_path / "q.db")
    c = _candidate_with_events()
    q.enqueue(c)
    q.mark_reviewed(c.candidate_id, "promote")
    assert q.pending() == []


def test_sqlite_quarantine_mark_unknown_raises(tmp_path):
    q = SQLiteQuarantineStore(tmp_path / "q.db")
    with pytest.raises(KeyError):
        q.mark_reviewed("cand_missing", "promote")


def test_sqlite_quarantine_prune_expired(tmp_path):
    q = SQLiteQuarantineStore(tmp_path / "q.db")
    c = _candidate_with_events()
    q.enqueue(c)
    # Force it old
    q._conn.execute(
        "UPDATE quarantine_candidates SET enqueued_at = ? WHERE candidate_id = ?",
        (time.time() - 48 * 3600, c.candidate_id),
    )
    pruned = q.prune_expired(ttl_hours=24)
    assert pruned == 1
    assert q.pending() == []


def test_sqlite_quarantine_prune_skips_reviewed(tmp_path):
    """Reviewed candidates are already removed from the pending set; prune
    should not double-count them."""
    q = SQLiteQuarantineStore(tmp_path / "q.db")
    c = _candidate_with_events()
    q.enqueue(c)
    q.mark_reviewed(c.candidate_id, "promote")
    # Even if we backdate, a reviewed candidate shouldn't be pruned by prune_expired
    # (it's only supposed to remove UNREVIEWED expired entries)
    pruned = q.prune_expired(ttl_hours=0)  # ultra-aggressive
    assert pruned == 0


# ---------------- Fleet stores (both impls) --------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def fleet(request, tmp_path):
    if request.param == "memory":
        yield InMemoryFleetStore()
    else:
        f = SQLiteFleetStore(tmp_path / "fleet.db")
        yield f
        f.close()


def test_fleet_requires_min_validations(fleet):
    # Only one agent contributes — shouldn't surface with default min_validations=2
    fleet.contribute(_skill("sk_1"), source_agent_id="robot_a")
    results = fleet.query(min_validations=2)
    assert results == []


def test_fleet_surfaces_when_validated(fleet):
    s1 = _skill("sk_a1", cmd_name="arm.grasp")
    s2 = _skill("sk_b1", cmd_name="arm.grasp")
    fleet.contribute(s1, source_agent_id="robot_a")
    fleet.contribute(s2, source_agent_id="robot_b")
    results = fleet.query(min_validations=2)
    assert len(results) == 1
    assert results[0].provenance["source"] == "fleet"


def test_fleet_aggregates_sample_counts(fleet):
    fleet.contribute(_skill("sk_a1", samples=3), source_agent_id="robot_a")
    fleet.contribute(_skill("sk_b1", samples=5), source_agent_id="robot_b")
    results = fleet.query(min_validations=2)
    assert results[0].sample_count == 8


def test_fleet_filters_by_environment(fleet):
    fleet.contribute(_skill("sk_in_a", env="indoor"), source_agent_id="robot_a")
    fleet.contribute(_skill("sk_in_b", env="indoor"), source_agent_id="robot_b")
    fleet.contribute(_skill("sk_out_a", env="outdoor"), source_agent_id="robot_a")
    fleet.contribute(_skill("sk_out_b", env="outdoor"), source_agent_id="robot_b")
    indoor = fleet.query(environment_fingerprint="indoor", min_validations=2)
    outdoor = fleet.query(environment_fingerprint="outdoor", min_validations=2)
    assert len(indoor) == 1 and indoor[0].environment_class == "indoor"
    assert len(outdoor) == 1 and outdoor[0].environment_class == "outdoor"


def test_fleet_same_agent_twice_does_not_validate(fleet):
    """A single agent contributing twice should still count as one validator."""
    fleet.contribute(_skill("sk_a1"), source_agent_id="robot_a")
    fleet.contribute(_skill("sk_a2"), source_agent_id="robot_a")
    # Still only one distinct contributor
    results = fleet.query(min_validations=2)
    assert results == []


def test_fleet_task_type_filter(fleet):
    fleet.contribute(_skill("sk_grasp_a", cmd_name="arm.grasp"),
                     source_agent_id="robot_a")
    fleet.contribute(_skill("sk_grasp_b", cmd_name="arm.grasp"),
                     source_agent_id="robot_b")
    fleet.contribute(_skill("sk_walk_a", cmd_name="nav.walk"),
                     source_agent_id="robot_a")
    fleet.contribute(_skill("sk_walk_b", cmd_name="nav.walk"),
                     source_agent_id="robot_b")
    grasp_skills = fleet.query(task_type="grasp", min_validations=2)
    assert len(grasp_skills) == 1
    assert grasp_skills[0].cli_sequence[0].name == "arm.grasp"
