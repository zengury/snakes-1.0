"""End-to-end tests of the Memory facade.

This exercises the full path: task start -> commands -> safety gate ->
episode end -> quarantine -> critic -> semantic memory.
"""
import pytest

from memkit import (
    Command,
    Memory,
    MemoryConfig,
    Outcome,
    SafetyRule,
    SafetyViolation,
    Severity,
)


@pytest.fixture
def mem():
    return Memory.from_config(MemoryConfig.in_memory())


@pytest.fixture
def durable_mem(tmp_path):
    return Memory.from_config(MemoryConfig.local_only(data_dir=str(tmp_path / "memkit")))


# ---------------- Basic lifecycle -------------------------------------------


def test_begin_and_end_task(mem):
    ep = mem.begin_task("task_escape_room_door_3", env_fingerprint="indoor_residential")
    assert ep.episode_id.startswith("ep_")
    mem.record_command(ep.episode_id, Command(name="perception.scan_room"))
    mem.record_result(
        ep.episode_id,
        Command(name="perception.scan_room"),
        Outcome.SUCCESS,
    )
    ended = mem.end_task(ep.episode_id, Outcome.SUCCESS)
    assert ended.outcome == Outcome.SUCCESS


def test_end_task_auto_quarantines(mem):
    ep = mem.begin_task("t1", env_fingerprint="indoor_residential")
    mem.record_command(ep.episode_id, Command(name="arm.grasp", params={"force": 12}))
    mem.record_result(
        ep.episode_id,
        Command(name="arm.grasp"),
        Outcome.SUCCESS,
    )
    mem.end_task(ep.episode_id, Outcome.SUCCESS)
    pending = mem.quarantine.pending()
    assert len(pending) == 1
    assert pending[0].proposed_skill is not None


def test_end_task_failure_still_quarantines_for_learning(mem):
    """Even failures get quarantined — the critic decides what to do."""
    ep = mem.begin_task("t1")
    mem.record_command(ep.episode_id, Command(name="arm.grasp"))
    mem.end_task(ep.episode_id, Outcome.FAILURE)
    assert len(mem.quarantine.pending()) == 1


def test_end_task_no_auto_quarantine_flag(mem):
    ep = mem.begin_task("t1")
    mem.end_task(ep.episode_id, Outcome.SUCCESS, auto_quarantine=False)
    assert mem.quarantine.pending() == []


# ---------------- Safety gate integration -----------------------------------


def test_check_command_blocks_and_raises(mem):
    mem.safety.add_rule(SafetyRule(
        rule_id="r1",
        severity=Severity.HARD_STOP,
        context_predicate={"fact": "human_nearby", "value": True},
        forbidden_command_pattern="locomotion.*",
    ))
    mem.reflex.snapshot({"human_nearby": True})
    with pytest.raises(SafetyViolation) as exc:
        mem.check_command(Command(name="locomotion.walk"))
    assert exc.value.rule.rule_id == "r1"


def test_check_command_uses_reflex_context_by_default(mem):
    mem.safety.add_rule(SafetyRule(
        rule_id="r1",
        severity=Severity.HARD_STOP,
        context_predicate={"fact": "human_nearby", "value": True},
        forbidden_command_pattern="locomotion.*",
    ))
    # No humans in reflex state -> allowed
    mem.reflex.snapshot({"human_nearby": False})
    mem.check_command(Command(name="locomotion.walk"))  # no raise


def test_command_allowed_returns_bool(mem):
    mem.safety.add_rule(SafetyRule(
        rule_id="r1",
        severity=Severity.SOFT_STOP,
        context_predicate={"fact": "battery_pct", "below": 5},
        forbidden_command_pattern="locomotion.*",
    ))
    mem.reflex.snapshot({"battery_pct": 3})
    assert mem.command_allowed(Command(name="locomotion.walk")) is False
    assert mem.command_allowed(Command(name="arm.grasp")) is True


# ---------------- Critic promotion flow -------------------------------------


def test_process_quarantine_promotes_success(mem):
    ep = mem.begin_task("t1", env_fingerprint="indoor_residential")
    mem.record_command(ep.episode_id, Command(name="arm.grasp", params={"force": 12}))
    mem.record_result(ep.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    mem.end_task(ep.episode_id, Outcome.SUCCESS)

    counts = mem.process_quarantine()
    assert counts.get("promote") == 1

    # Should now have a skill in semantic memory
    skills = mem.semantic.query()
    assert len(skills) == 1


def test_process_quarantine_discards_failure(mem):
    ep = mem.begin_task("t1")
    mem.record_command(ep.episode_id, Command(name="arm.grasp"))
    mem.end_task(ep.episode_id, Outcome.FAILURE)

    counts = mem.process_quarantine()
    assert counts.get("discard") == 1
    assert mem.semantic.query() == []


def test_process_quarantine_needs_review_stays_pending(mem):
    """NEEDS_HUMAN_REVIEW decisions keep the candidate in the queue."""
    ep = mem.begin_task("t1", env_fingerprint="indoor_residential")
    mem.record_command(ep.episode_id, Command(name="arm.grasp"))
    mem.record_result(ep.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    mem.end_task(ep.episode_id, Outcome.SUCCESS, anomaly_flags=["safety_close_call"])

    counts = mem.process_quarantine()
    assert counts.get("needs_human_review") == 1
    # Still in quarantine — a human needs to review
    assert len(mem.quarantine.pending()) == 1


def test_process_quarantine_merges_duplicate(mem):
    """A second successful attempt of the same command sequence should merge."""
    # First episode — promotes a new skill
    ep1 = mem.begin_task("t1", env_fingerprint="indoor_residential")
    mem.record_command(ep1.episode_id, Command(name="arm.grasp", params={"force": 12}))
    mem.record_result(ep1.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    mem.end_task(ep1.episode_id, Outcome.SUCCESS)
    mem.process_quarantine()
    skills_after_first = mem.semantic.query()
    assert len(skills_after_first) == 1
    initial_sample_count = skills_after_first[0].sample_count

    # Second episode — same command, should merge
    ep2 = mem.begin_task("t2", env_fingerprint="indoor_residential")
    mem.record_command(ep2.episode_id, Command(name="arm.grasp", params={"force": 12}))
    mem.record_result(ep2.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    mem.end_task(ep2.episode_id, Outcome.SUCCESS)
    counts = mem.process_quarantine()

    assert counts.get("merge_into_existing") == 1
    skills_after_merge = mem.semantic.query()
    assert len(skills_after_merge) == 1  # still just one skill
    assert skills_after_merge[0].sample_count == initial_sample_count + 1


# ---------------- Housekeeping ---------------------------------------------


def test_tick_housekeeping_runs_cleanly(mem):
    result = mem.tick_housekeeping()
    assert set(result.keys()) == {"episodes_evicted", "quarantine_expired", "skills_decayed"}


# ---------------- Durable config roundtrip ---------------------------------


def test_durable_memory_roundtrip(tmp_path):
    """Data survives Memory instance reconstruction via SQLite."""
    data_dir = str(tmp_path / "memkit_durable")

    mem1 = Memory.from_config(MemoryConfig.local_only(data_dir=data_dir))
    ep = mem1.begin_task("t1", env_fingerprint="indoor_residential")
    mem1.record_command(ep.episode_id, Command(name="arm.grasp", params={"force": 12}))
    mem1.record_result(ep.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    mem1.end_task(ep.episode_id, Outcome.SUCCESS)
    mem1.process_quarantine()
    skill_ids_before = {s.skill_id for s in mem1.semantic.query()}

    # New instance, same data dir
    mem2 = Memory.from_config(MemoryConfig.local_only(data_dir=data_dir))
    skill_ids_after = {s.skill_id for s in mem2.semantic.query()}
    assert skill_ids_before == skill_ids_after
    assert len(skill_ids_after) >= 1
