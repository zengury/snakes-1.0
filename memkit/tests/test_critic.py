"""Tests for quarantine store and the rule-based critic."""
from datetime import datetime, timezone

import pytest

from memkit import (
    Command,
    CriticDecision,
    Episode,
    Event,
    MemoryCandidate,
    Outcome,
    Skill,
)
from memkit.critic.critic import LLMCritic, RuleBasedCritic
from memkit.layers.quarantine import InMemoryQuarantineStore


def _candidate(outcome=Outcome.SUCCESS, anomaly_flags=None, with_skill=True,
               success_rate=0.9, sample_count=2, cmd_name="arm.grasp",
               env="indoor_residential"):
    ep = Episode(
        episode_id="ep_1",
        task_id="task_1",
        started_at=datetime.now(timezone.utc),
        outcome=outcome,
        anomaly_flags=anomaly_flags or [],
        env_fingerprint=env,
    )
    proposed = None
    if with_skill:
        proposed = Skill(
            skill_id="sk_proposed",
            cli_sequence=[Command(name=cmd_name, params={"force": 12})],
            preconditions=[],
            environment_class=env,
            success_rate=success_rate,
            sample_count=sample_count,
            confidence=0.5,
            last_used=datetime.now(timezone.utc),
            provenance={"source": "test"},
        )
    return MemoryCandidate(
        candidate_id="cand_1",
        episode=ep,
        proposed_skill=proposed,
        proposed_safety_rule=None,
    )


# ------------- Quarantine store ---------------------------------------------


def test_quarantine_enqueue_and_pending():
    q = InMemoryQuarantineStore()
    q.enqueue(_candidate())
    pending = q.pending()
    assert len(pending) == 1


def test_quarantine_fifo_order():
    q = InMemoryQuarantineStore()
    c1 = _candidate()
    c1.candidate_id = "cand_first"
    c2 = _candidate()
    c2.candidate_id = "cand_second"
    q.enqueue(c1)
    q.enqueue(c2)
    pending = q.pending()
    assert pending[0].candidate_id == "cand_first"
    assert pending[1].candidate_id == "cand_second"


def test_quarantine_mark_reviewed_removes():
    q = InMemoryQuarantineStore()
    c = _candidate()
    q.enqueue(c)
    q.mark_reviewed(c.candidate_id, "promote")
    assert q.pending() == []


def test_quarantine_mark_unknown_raises():
    q = InMemoryQuarantineStore()
    with pytest.raises(KeyError):
        q.mark_reviewed("cand_missing", "promote")


def test_quarantine_prune_expired():
    import time
    q = InMemoryQuarantineStore()
    c = _candidate()
    q.enqueue(c)
    # Manually backdate
    q._enqueued_at[c.candidate_id] = time.time() - 3600 * 48
    pruned = q.prune_expired(ttl_hours=24)
    assert pruned == 1
    assert q.pending() == []


# ------------- Rule-based critic -------------------------------------------


def test_critic_discards_failure():
    critic = RuleBasedCritic()
    review = critic.review(_candidate(outcome=Outcome.FAILURE), [])
    assert review.decision == CriticDecision.DISCARD


def test_critic_flags_anomalies_for_review():
    critic = RuleBasedCritic()
    review = critic.review(_candidate(anomaly_flags=["safety_close_call"]), [])
    assert review.decision == CriticDecision.NEEDS_HUMAN_REVIEW


def test_critic_promotes_clean_success():
    critic = RuleBasedCritic(min_samples=1, min_success_rate=0.5)
    review = critic.review(_candidate(), [])
    assert review.decision == CriticDecision.PROMOTE
    assert review.revised_skill is not None


def test_critic_discards_low_evidence():
    critic = RuleBasedCritic(min_samples=10, min_success_rate=0.5)
    review = critic.review(_candidate(sample_count=1), [])
    assert review.decision == CriticDecision.DISCARD


def test_critic_merges_matching_signature():
    critic = RuleBasedCritic()
    existing = Skill(
        skill_id="sk_existing",
        cli_sequence=[Command(name="arm.grasp", params={"force": 12})],
        preconditions=[],
        environment_class="indoor_residential",
        success_rate=0.85,
        sample_count=10,
        confidence=0.75,
        last_used=datetime.now(timezone.utc),
        provenance={},
    )
    review = critic.review(_candidate(), [existing])
    assert review.decision == CriticDecision.MERGE_INTO_EXISTING
    assert review.merged_into == "sk_existing"


def test_critic_no_proposed_skill_discards():
    critic = RuleBasedCritic()
    review = critic.review(_candidate(with_skill=False), [])
    assert review.decision == CriticDecision.DISCARD


# ------------- LLM critic (mocked) -----------------------------------------


def test_llm_critic_parses_json():
    def fake_llm(prompt: str) -> str:
        return '{"decision": "promote", "reason": "looks good", "merged_into": null}'

    critic = LLMCritic(call_llm=fake_llm)
    review = critic.review(_candidate(), [])
    assert review.decision == CriticDecision.PROMOTE
    assert review.reason == "looks good"


def test_llm_critic_strips_fences():
    def fake_llm(prompt: str) -> str:
        return '```json\n{"decision": "discard", "reason": "r"}\n```'

    critic = LLMCritic(call_llm=fake_llm)
    review = critic.review(_candidate(), [])
    assert review.decision == CriticDecision.DISCARD


def test_llm_critic_invalid_json_falls_back_to_review():
    def fake_llm(prompt: str) -> str:
        return "not json at all"

    critic = LLMCritic(call_llm=fake_llm)
    review = critic.review(_candidate(), [])
    assert review.decision == CriticDecision.NEEDS_HUMAN_REVIEW


def test_llm_critic_raising_call_falls_back():
    def fake_llm(prompt: str) -> str:
        raise RuntimeError("LLM down")

    critic = LLMCritic(call_llm=fake_llm)
    review = critic.review(_candidate(), [])
    assert review.decision == CriticDecision.NEEDS_HUMAN_REVIEW
