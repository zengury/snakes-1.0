"""
Memory: the facade that composes all layers into one usable object.

This is the runtime's entrypoint. Layers can be swapped individually for tests,
alternative backends, or different deployment shapes.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .critic.critic import RuleBasedCritic
from .layers.episodic import InMemoryEpisodicStore
from .layers.quarantine import InMemoryQuarantineStore
from .layers.reflex import RingReflexStore
from .layers.safety import RuleBasedSafetyGate
from .layers.semantic import InMemorySemanticStore
from .protocols import (
    Command,
    Critic,
    CriticDecision,
    Episode,
    EpisodicStore,
    Event,
    MemoryCandidate,
    Outcome,
    QuarantineStore,
    ReflexStore,
    SafetyGate,
    SafetyRule,
    SafetyViolation,
    SemanticStore,
    Skill,
)


# FleetStore has the same shape as SemanticStore but with a contribute() method.
# Typed loosely here as Any-like to avoid a hard dependency on FleetStore in the
# facade when no fleet is configured.
FleetStoreLike = object


@dataclass
class MemoryConfig:
    """Declarative configuration for common deployment shapes."""
    data_dir: str | None = None
    agent_id: str = "agent_default"
    reflex_capacity: int = 256
    quarantine_ttl_hours: float = 24
    episodic_ttl_seconds: float = 3600
    semantic_decay_days: float = 30
    semantic_decay_rate: float = 0.9
    # Fleet settings — None means no fleet wired in
    fleet_db_path: str | None = None
    fleet_min_validations: int = 2
    fleet_contribute_on_promote: bool = True

    @classmethod
    def local_only(cls, data_dir: str = "./memkit_data",
                   agent_id: str = "agent_default") -> "MemoryConfig":
        return cls(data_dir=data_dir, agent_id=agent_id)

    @classmethod
    def in_memory(cls, agent_id: str = "agent_default") -> "MemoryConfig":
        return cls(data_dir=None, agent_id=agent_id)

    @classmethod
    def with_fleet(cls, data_dir: str, fleet_db_path: str,
                   agent_id: str) -> "MemoryConfig":
        return cls(data_dir=data_dir, fleet_db_path=fleet_db_path, agent_id=agent_id)


class Memory:
    """Top-level facade. Compose layers, get a unified API."""

    def __init__(
        self,
        *,
        reflex: ReflexStore,
        episodic: EpisodicStore,
        quarantine: QuarantineStore,
        semantic: SemanticStore,
        safety: SafetyGate,
        critic: Critic,
        fleet: FleetStoreLike | None = None,
        config: MemoryConfig | None = None,
    ):
        self.reflex = reflex
        self.episodic = episodic
        self.quarantine = quarantine
        self.semantic = semantic
        self.safety = safety
        self.critic = critic
        self.fleet = fleet
        self.config = config or MemoryConfig()

    # -----------------------------------------------------------------
    # Factory
    # -----------------------------------------------------------------

    @classmethod
    def from_config(cls, config: MemoryConfig) -> "Memory":
        """Build a standard Memory from a config.

        - data_dir set -> SQLite-backed episodic, semantic, quarantine
        - data_dir None -> in-memory everywhere
        - fleet_db_path set -> SQLiteFleetStore wired in
        """
        if config.data_dir:
            from .stores.sqlite import SQLiteEpisodicStore, SQLiteSemanticStore
            from .stores.sqlite_extras import SQLiteQuarantineStore
            Path(config.data_dir).mkdir(parents=True, exist_ok=True)
            episodic = SQLiteEpisodicStore(f"{config.data_dir}/episodic.db")
            semantic = SQLiteSemanticStore(f"{config.data_dir}/semantic.db")
            quarantine = SQLiteQuarantineStore(f"{config.data_dir}/quarantine.db")
        else:
            episodic = InMemoryEpisodicStore()
            semantic = InMemorySemanticStore()
            quarantine = InMemoryQuarantineStore()

        fleet = None
        if config.fleet_db_path:
            from .stores.sqlite_extras import SQLiteFleetStore
            fleet = SQLiteFleetStore(config.fleet_db_path)

        return cls(
            reflex=RingReflexStore(capacity=config.reflex_capacity),
            episodic=episodic,
            quarantine=quarantine,
            semantic=semantic,
            safety=RuleBasedSafetyGate(),
            critic=RuleBasedCritic(),
            fleet=fleet,
            config=config,
        )

    # -----------------------------------------------------------------
    # Hot path: command gate
    # -----------------------------------------------------------------

    def check_command(self, command: Command, context: dict[str, Any] | None = None) -> None:
        """Raises SafetyViolation if the command is blocked.

        Context defaults to reflex.current() so callers don't have to thread it.
        """
        ctx = context if context is not None else self.reflex.current()
        triggered = self.safety.triggered_rule(command, ctx)
        if triggered is not None:
            explanation = self.safety.explain(command, ctx) or "blocked"
            raise SafetyViolation(
                command=command,
                rule=triggered,
                explanation=explanation,
            )

    def command_allowed(self, command: Command, context: dict[str, Any] | None = None) -> bool:
        """Non-raising variant for callers that prefer to branch."""
        ctx = context if context is not None else self.reflex.current()
        return self.safety.allows(command, ctx)

    # -----------------------------------------------------------------
    # Task lifecycle
    # -----------------------------------------------------------------

    def begin_task(self, task_id: str, env_fingerprint: str | None = None) -> Episode:
        return self.episodic.start_episode(task_id, env_fingerprint)

    def record_command(self, episode_id: str, command: Command,
                       t: float | None = None) -> None:
        self.episodic.append_event(episode_id, Event(
            t=t if t is not None else time.monotonic(),
            kind="cmd_issued",
            payload={
                "cmd_name": command.name,
                "cmd_params": command.params,
                "cmd_signature": command.signature(),
            },
        ))

    def record_result(self, episode_id: str, command: Command,
                      outcome: Outcome, detail: dict[str, Any] | None = None,
                      t: float | None = None) -> None:
        self.episodic.append_event(episode_id, Event(
            t=t if t is not None else time.monotonic(),
            kind="cmd_result",
            payload={
                "cmd_name": command.name,
                "outcome": outcome.value,
                "detail": detail or {},
            },
        ))

    def end_task(self, episode_id: str, outcome: Outcome,
                 anomaly_flags: list[str] | None = None,
                 auto_quarantine: bool = True) -> Episode:
        ep = self.episodic.end_episode(episode_id, outcome, anomaly_flags)
        if auto_quarantine:
            candidate = self._bundle_candidate(ep)
            self.quarantine.enqueue(candidate)
        return ep

    # -----------------------------------------------------------------
    # Candidate bundling
    # -----------------------------------------------------------------

    def _bundle_candidate(self, episode: Episode) -> MemoryCandidate:
        """Build a MemoryCandidate from a completed episode.

        Simple heuristic for the proposed skill:
        - Collect all issued commands
        - Compute success rate from result events
        - Propose a skill only if outcome was SUCCESS
        """
        candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        proposed = None

        if episode.outcome == Outcome.SUCCESS and episode.events:
            issued = [
                Command(
                    name=e.payload["cmd_name"],
                    params=e.payload.get("cmd_params", {}),
                )
                for e in episode.events
                if e.kind == "cmd_issued"
            ]
            result_outcomes = [
                e.payload["outcome"]
                for e in episode.events
                if e.kind == "cmd_result"
            ]
            if issued and result_outcomes:
                success_count = sum(
                    1 for o in result_outcomes if o == Outcome.SUCCESS.value
                )
                success_rate = success_count / len(result_outcomes)
                proposed = Skill(
                    skill_id=f"sk_{uuid.uuid4().hex[:12]}",
                    cli_sequence=issued,
                    preconditions=[],  # left for critic/human to enrich
                    environment_class=episode.env_fingerprint or "unknown",
                    success_rate=success_rate,
                    sample_count=1,
                    confidence=success_rate * 0.5,  # starts conservative
                    last_used=datetime.now(timezone.utc),
                    provenance={
                        "source": "local_episode",
                        "episode_id": episode.episode_id,
                        "task_id": episode.task_id,
                    },
                )

        return MemoryCandidate(
            candidate_id=candidate_id,
            episode=episode,
            proposed_skill=proposed,
            proposed_safety_rule=None,
        )

    # -----------------------------------------------------------------
    # Critic loop (typically run on cloud-side, but synchronous here)
    # -----------------------------------------------------------------

    def process_quarantine(self, batch_size: int = 50) -> dict[str, int]:
        """Pull pending candidates, run the critic, apply decisions.

        Returns a counter of decisions for observability.
        """
        pending = self.quarantine.pending(limit=batch_size)
        counts: Counter = Counter()
        for candidate in pending:
            # Provide the full skill set for contradiction/merge checking
            existing = self.semantic.query(limit=1000)
            review = self.critic.review(candidate, existing)
            self._apply_decision(candidate, review)
            counts[review.decision.value] += 1
        return dict(counts)

    def _apply_decision(self, candidate: MemoryCandidate, review) -> None:
        if review.decision == CriticDecision.PROMOTE:
            promoted_skill = None
            if review.revised_skill is not None:
                self.semantic.add_skill(review.revised_skill)
                promoted_skill = review.revised_skill
            elif candidate.proposed_skill is not None:
                self.semantic.add_skill(candidate.proposed_skill)
                promoted_skill = candidate.proposed_skill
            # If fleet is configured and the flag is on, also contribute.
            if (promoted_skill is not None
                    and self.fleet is not None
                    and self.config.fleet_contribute_on_promote):
                self.fleet.contribute(promoted_skill, self.config.agent_id)
        elif review.decision == CriticDecision.MERGE_INTO_EXISTING:
            if review.merged_into:
                existing = self.semantic.get_skill(review.merged_into)
                if existing and candidate.proposed_skill:
                    # Update success rate and sample count via running average
                    new_samples = existing.sample_count + 1
                    merged_rate = (
                        existing.success_rate * existing.sample_count
                        + candidate.proposed_skill.success_rate
                    ) / new_samples
                    existing.success_rate = merged_rate
                    existing.sample_count = new_samples
                    existing.confidence = min(1.0, existing.confidence + 0.05)
                    existing.last_used = datetime.now(timezone.utc)
                    # Contribute the updated (merged) version to fleet too
                    if (self.fleet is not None
                            and self.config.fleet_contribute_on_promote):
                        self.fleet.contribute(existing, self.config.agent_id)
        elif review.decision == CriticDecision.DISCARD:
            pass  # nothing to add
        elif review.decision == CriticDecision.NEEDS_HUMAN_REVIEW:
            # Keep in quarantine for human handling — don't mark reviewed
            return

        self.quarantine.mark_reviewed(candidate.candidate_id, review.decision.value)

    # -----------------------------------------------------------------
    # Fleet-aware retrieval
    # -----------------------------------------------------------------

    def query_skills(self, *, task_type: str | None = None,
                     environment_class: str | None = None,
                     min_confidence: float = 0.0,
                     include_fleet: bool = True,
                     limit: int = 10) -> list[Skill]:
        """Query local semantic memory, optionally merging fleet results.

        Local skills rank above fleet skills with equal confidence — the
        current robot's own evidence is preferred over borrowed evidence.
        """
        local = self.semantic.query(
            task_type=task_type,
            environment_class=environment_class,
            min_confidence=min_confidence,
            limit=limit,
        )
        if not include_fleet or self.fleet is None:
            return local

        fleet_skills = self.fleet.query(
            task_type=task_type,
            environment_fingerprint=environment_class,
            min_validations=self.config.fleet_min_validations,
            limit=limit,
        )
        # Dedupe: a fleet skill that duplicates a local skill's signature
        # should not shadow the local. Local wins.
        local_sigs = {
            "|".join(c.signature() for c in s.cli_sequence)
            for s in local
        }
        fleet_filtered = [
            s for s in fleet_skills
            if "|".join(c.signature() for c in s.cli_sequence) not in local_sigs
        ]
        merged = local + fleet_filtered
        # Prefer local: boost local confidence slightly for ranking stability
        merged.sort(
            key=lambda s: (
                s.confidence + (0.05 if s.provenance.get("source") != "fleet" else 0),
                s.sample_count,
            ),
            reverse=True,
        )
        return merged[:limit]

    # -----------------------------------------------------------------
    # Housekeeping
    # -----------------------------------------------------------------

    def tick_housekeeping(self) -> dict[str, int]:
        """Periodic maintenance — call from a background thread or scheduler."""
        return {
            "episodes_evicted": self.episodic.evict_completed(
                older_than_seconds=self.config.episodic_ttl_seconds,
            ),
            "quarantine_expired": self.quarantine.prune_expired(
                ttl_hours=self.config.quarantine_ttl_hours,
            ),
            "skills_decayed": self.semantic.decay(
                unused_days=self.config.semantic_decay_days,
                rate=self.config.semantic_decay_rate,
            ),
        }
