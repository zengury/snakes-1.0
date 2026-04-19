"""
Critic: reviews quarantine candidates and decides promotion.

Two implementations here:
- RuleBasedCritic: deterministic, for tests and bootstrapping
- LLMCritic: protocol-conforming adapter that takes a `call_llm` callable,
  so projects can wire in their own LLM client without memkit depending on
  any specific provider.
"""
from __future__ import annotations

import json
from typing import Callable

from ..protocols import (
    Critic,
    CriticDecision,
    CriticReview,
    MemoryCandidate,
    Outcome,
    Skill,
)


class RuleBasedCritic:
    """A minimal critic for tests and as a sanity-check pre-filter.

    Rules:
    - FAILURE outcome -> DISCARD
    - anomaly_flags non-empty -> NEEDS_HUMAN_REVIEW
    - proposed_skill matches an existing skill's command signature (exact
      sequence of command names + param keys) -> MERGE
    - proposed_skill is a near-duplicate (same command names, different param
      values) -> MERGE when the existing skill has high confidence, otherwise
      NEEDS_HUMAN_REVIEW
    - proposed_skill contradicts an existing high-confidence skill (same
      signature, very different success rate) -> NEEDS_HUMAN_REVIEW
    - SUCCESS with sample_count >= min_samples -> PROMOTE
    - otherwise -> DISCARD (not enough evidence)
    """

    def __init__(self, min_samples: int = 1, min_success_rate: float = 0.5,
                 near_duplicate_merge_confidence: float = 0.7,
                 contradiction_success_rate_delta: float = 0.4,
                 contradiction_confidence_threshold: float = 0.7):
        self.min_samples = min_samples
        self.min_success_rate = min_success_rate
        self.near_duplicate_merge_confidence = near_duplicate_merge_confidence
        self.contradiction_success_rate_delta = contradiction_success_rate_delta
        self.contradiction_confidence_threshold = contradiction_confidence_threshold

    def review(self, candidate: MemoryCandidate,
               existing_skills: list[Skill]) -> CriticReview:
        ep = candidate.episode

        if ep.outcome == Outcome.FAILURE:
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision.DISCARD,
                reason="episode outcome was failure",
            )

        if ep.anomaly_flags:
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision.NEEDS_HUMAN_REVIEW,
                reason=f"anomalies detected: {ep.anomaly_flags}",
            )

        proposed = candidate.proposed_skill
        if proposed is None:
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision.DISCARD,
                reason="no proposed skill",
            )

        # 1. Exact signature match -> merge
        proposed_sig = tuple(c.signature() for c in proposed.cli_sequence)
        for existing in existing_skills:
            existing_sig = tuple(c.signature() for c in existing.cli_sequence)
            if (existing_sig == proposed_sig and
                    existing.environment_class == proposed.environment_class):
                # Contradiction check: high-confidence existing skill vs.
                # proposed with very different success rate
                if (existing.confidence >= self.contradiction_confidence_threshold and
                        abs(existing.success_rate - proposed.success_rate)
                        >= self.contradiction_success_rate_delta):
                    return CriticReview(
                        candidate_id=candidate.candidate_id,
                        decision=CriticDecision.NEEDS_HUMAN_REVIEW,
                        reason=(
                            f"contradicts high-confidence skill {existing.skill_id} "
                            f"(existing success_rate={existing.success_rate:.2f}, "
                            f"proposed success_rate={proposed.success_rate:.2f})"
                        ),
                    )
                return CriticReview(
                    candidate_id=candidate.candidate_id,
                    decision=CriticDecision.MERGE_INTO_EXISTING,
                    reason="matching signature + environment",
                    merged_into=existing.skill_id,
                )

        # 2. Near-duplicate: same command names in same order, different params
        proposed_names = tuple(c.name for c in proposed.cli_sequence)
        for existing in existing_skills:
            existing_names = tuple(c.name for c in existing.cli_sequence)
            if (existing_names == proposed_names and
                    existing.environment_class == proposed.environment_class):
                # Same names but different signatures (different param keys)
                if existing.confidence >= self.near_duplicate_merge_confidence:
                    return CriticReview(
                        candidate_id=candidate.candidate_id,
                        decision=CriticDecision.MERGE_INTO_EXISTING,
                        reason=(
                            f"near-duplicate of high-confidence skill "
                            f"{existing.skill_id} (same command sequence, "
                            f"different params)"
                        ),
                        merged_into=existing.skill_id,
                    )
                else:
                    return CriticReview(
                        candidate_id=candidate.candidate_id,
                        decision=CriticDecision.NEEDS_HUMAN_REVIEW,
                        reason=(
                            f"near-duplicate of {existing.skill_id} but existing "
                            f"confidence {existing.confidence:.2f} too low to "
                            f"auto-merge"
                        ),
                    )

        # 3. Promote if it clears thresholds
        if (proposed.sample_count >= self.min_samples and
                proposed.success_rate >= self.min_success_rate):
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision.PROMOTE,
                reason="meets sample and success thresholds",
                revised_skill=proposed,
            )

        return CriticReview(
            candidate_id=candidate.candidate_id,
            decision=CriticDecision.DISCARD,
            reason="insufficient evidence for promotion",
        )


class LLMCritic:
    """LLM-backed critic.

    Takes a `call_llm(prompt: str) -> str` callable. This keeps memkit free
    of any LLM SDK dependency; projects wire in Anthropic, OpenAI, local, etc.

    The LLM is expected to return a JSON object matching the CriticReview
    schema. Malformed output falls back to NEEDS_HUMAN_REVIEW.
    """

    def __init__(self, call_llm: Callable[[str], str],
                 prompt_template: str | None = None):
        self.call_llm = call_llm
        self.prompt_template = prompt_template or _DEFAULT_PROMPT

    def review(self, candidate: MemoryCandidate,
               existing_skills: list[Skill]) -> CriticReview:
        prompt = self.prompt_template.format(
            candidate_json=_serialize_candidate(candidate),
            existing_skills_json=_serialize_skills(existing_skills),
        )
        try:
            raw = self.call_llm(prompt)
            decision_data = json.loads(_strip_fences(raw))
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision(decision_data["decision"]),
                reason=decision_data.get("reason", ""),
                merged_into=decision_data.get("merged_into"),
            )
        except Exception as e:
            return CriticReview(
                candidate_id=candidate.candidate_id,
                decision=CriticDecision.NEEDS_HUMAN_REVIEW,
                reason=f"critic LLM output invalid: {e}",
            )


_DEFAULT_PROMPT = """You are reviewing a candidate memory for promotion to a robot's skill library.

Candidate:
{candidate_json}

Existing skills (for merge/contradiction check):
{existing_skills_json}

Return a JSON object with this shape:
{{"decision": "promote|discard|needs_human_review|merge_into_existing",
  "reason": "brief explanation",
  "merged_into": "skill_id if merging, else null"}}

Rules:
- If outcome is failure or anomaly flags present, do not promote.
- If the candidate contradicts an existing skill with >0.7 confidence, return needs_human_review.
- If the candidate duplicates an existing skill, merge_into_existing.
- Return JSON only, no prose."""


def _serialize_candidate(c: MemoryCandidate) -> str:
    ep = c.episode
    obj = {
        "episode_id": ep.episode_id,
        "task_id": ep.task_id,
        "outcome": ep.outcome.value,
        "anomaly_flags": ep.anomaly_flags,
        "env_fingerprint": ep.env_fingerprint,
        "command_sequence": ep.command_sequence(),
    }
    if c.proposed_skill:
        obj["proposed_skill"] = {
            "environment_class": c.proposed_skill.environment_class,
            "cli_sequence": [cmd.signature() for cmd in c.proposed_skill.cli_sequence],
            "success_rate": c.proposed_skill.success_rate,
            "sample_count": c.proposed_skill.sample_count,
        }
    return json.dumps(obj, default=str)


def _serialize_skills(skills: list[Skill]) -> str:
    return json.dumps([
        {
            "skill_id": s.skill_id,
            "environment_class": s.environment_class,
            "cli_sequence": [cmd.signature() for cmd in s.cli_sequence],
            "confidence": s.confidence,
        }
        for s in skills
    ], default=str)


def _strip_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        # drop first line (```json or ```) and last ```
        lines = s.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        lines = lines[1:]
        s = "\n".join(lines)
    return s


# Protocol checks
_: Critic = RuleBasedCritic()
