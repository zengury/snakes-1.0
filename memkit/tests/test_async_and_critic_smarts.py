"""Tests for AsyncMemory wrapper and upgraded RuleBasedCritic."""
import asyncio
from datetime import datetime, timezone

import pytest

from memkit import (
    AsyncMemory,
    Command,
    CriticDecision,
    Episode,
    MemoryCandidate,
    MemoryConfig,
    Outcome,
    SafetyRule,
    SafetyViolation,
    Severity,
    Skill,
)
from memkit.critic.critic import RuleBasedCritic


# ---------------- AsyncMemory ----------------------------------------------


@pytest.fixture
def amem():
    return AsyncMemory.from_config(MemoryConfig.in_memory())


@pytest.mark.asyncio
async def test_async_begin_and_end(amem):
    ep = await amem.begin_task("task_1", env_fingerprint="indoor_residential")
    assert ep.episode_id.startswith("ep_")
    await amem.record_command(ep.episode_id, Command(name="arm.grasp"))
    await amem.record_result(ep.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    ended = await amem.end_task(ep.episode_id, Outcome.SUCCESS)
    assert ended.outcome == Outcome.SUCCESS


@pytest.mark.asyncio
async def test_async_fast_path_sync_safety(amem):
    """Safety gate stays sync — we still raise from inside a coroutine."""
    amem.safety.add_rule(SafetyRule(
        rule_id="r1",
        severity=Severity.HARD_STOP,
        context_predicate={"fact": "human_near", "value": True},
        forbidden_command_pattern="nav.*",
    ))
    amem.reflex.snapshot({"human_near": True})
    with pytest.raises(SafetyViolation):
        amem.check_command(Command(name="nav.walk"))


@pytest.mark.asyncio
async def test_async_full_promotion_flow(amem):
    ep = await amem.begin_task("task_1", env_fingerprint="indoor_residential")
    await amem.record_command(ep.episode_id, Command(name="arm.grasp",
                                                      params={"force": 12}))
    await amem.record_result(ep.episode_id, Command(name="arm.grasp"), Outcome.SUCCESS)
    await amem.end_task(ep.episode_id, Outcome.SUCCESS)

    counts = await amem.process_quarantine()
    assert counts.get("promote") == 1

    skills = await amem.query_skills()
    assert len(skills) == 1


@pytest.mark.asyncio
async def test_async_concurrent_tasks(amem):
    """Multiple coroutines can run tasks in parallel through the thread pool."""
    async def run_task(task_id: str):
        ep = await amem.begin_task(task_id, env_fingerprint="indoor_residential")
        await amem.record_command(ep.episode_id, Command(name=f"cmd_{task_id}"))
        await amem.record_result(ep.episode_id,
                                 Command(name=f"cmd_{task_id}"), Outcome.SUCCESS)
        await amem.end_task(ep.episode_id, Outcome.SUCCESS)

    await asyncio.gather(*[run_task(f"t_{i}") for i in range(5)])
    assert len(amem.sync.quarantine.pending()) == 5


# ---------------- Critic smarts --------------------------------------------


def _skill(skill_id: str, cmd_name="arm.grasp", params=None,
           env="indoor_residential", success_rate=0.9,
           confidence=0.8, sample_count=5) -> Skill:
    return Skill(
        skill_id=skill_id,
        cli_sequence=[Command(name=cmd_name, params=params or {"force": 12})],
        preconditions=[],
        environment_class=env,
        success_rate=success_rate,
        sample_count=sample_count,
        confidence=confidence,
        last_used=datetime.now(timezone.utc),
        provenance={},
    )


def _candidate(proposed_skill: Skill, outcome=Outcome.SUCCESS,
               anomaly_flags=None, env="indoor_residential") -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="cand_1",
        episode=Episode(
            episode_id="ep_1",
            task_id="t_1",
            started_at=datetime.now(timezone.utc),
            outcome=outcome,
            anomaly_flags=anomaly_flags or [],
            env_fingerprint=env,
        ),
        proposed_skill=proposed_skill,
        proposed_safety_rule=None,
    )


def test_critic_detects_near_duplicate_merges_when_high_confidence():
    """Same command names, different param values. Existing has high confidence."""
    critic = RuleBasedCritic()
    existing = _skill("sk_existing", params={"force": 12}, confidence=0.85)
    # Same command name, different param KEYS so signature differs
    proposed = _skill("sk_new", params={"grip": "firm"}, confidence=0.5)
    review = critic.review(_candidate(proposed), [existing])
    assert review.decision == CriticDecision.MERGE_INTO_EXISTING
    assert review.merged_into == "sk_existing"


def test_critic_near_duplicate_low_confidence_needs_review():
    """Same command names but existing skill confidence too low to auto-merge."""
    critic = RuleBasedCritic()
    existing = _skill("sk_existing", params={"force": 12}, confidence=0.3)
    proposed = _skill("sk_new", params={"grip": "firm"})
    review = critic.review(_candidate(proposed), [existing])
    assert review.decision == CriticDecision.NEEDS_HUMAN_REVIEW


def test_critic_detects_contradiction_flags_for_review():
    """Same signature, high-confidence existing, very different success rate."""
    critic = RuleBasedCritic()
    existing = _skill("sk_existing", confidence=0.9, success_rate=0.95)
    proposed = _skill("sk_contradictor", success_rate=0.3)
    review = critic.review(_candidate(proposed), [existing])
    assert review.decision == CriticDecision.NEEDS_HUMAN_REVIEW
    assert "contradicts" in review.reason.lower()


def test_critic_merges_consistent_signature():
    """Sanity: consistent signature, similar success rate -> merge as before."""
    critic = RuleBasedCritic()
    existing = _skill("sk_existing", confidence=0.9, success_rate=0.95)
    proposed = _skill("sk_new", success_rate=0.90)
    review = critic.review(_candidate(proposed), [existing])
    assert review.decision == CriticDecision.MERGE_INTO_EXISTING


def test_critic_no_match_promotes_normally():
    critic = RuleBasedCritic()
    proposed = _skill("sk_new", cmd_name="completely.different")
    review = critic.review(_candidate(proposed), [])
    assert review.decision == CriticDecision.PROMOTE
