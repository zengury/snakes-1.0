"""
Core protocol definitions for memkit.

These are the interfaces. Stores, layers, and critics all implement these.
Keeping them in one file makes the contract surface explicit and easy to audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    HARD_STOP = "hard_stop"
    SOFT_STOP = "soft_stop"
    WARN = "warn"


@dataclass
class Command:
    """A single action the agent issues. Project-agnostic: robotics calls this
    a CLI command, but it could equally be an API call or a tool invocation."""
    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        """Structural identity: name + sorted param keys. Used for indexing
        skills by pattern rather than by exact parameter values."""
        keys = sorted(self.params.keys())
        return f"{self.name}({','.join(keys)})"


@dataclass
class Event:
    """Something that happened during an episode."""
    t: float  # seconds since episode start
    kind: str  # 'cmd_issued', 'cmd_result', 'perception', 'anomaly', ...
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Episode:
    """A bounded trace of agent activity — typically a task attempt."""
    episode_id: str
    task_id: str
    started_at: datetime
    events: list[Event] = field(default_factory=list)
    outcome: Outcome = Outcome.UNKNOWN
    anomaly_flags: list[str] = field(default_factory=list)
    env_fingerprint: str | None = None
    human_feedback: dict[str, Any] | None = None

    def command_sequence(self) -> list[str]:
        """Extract the ordered CLI signatures from this episode."""
        return [
            e.payload.get("cmd_signature", "")
            for e in self.events
            if e.kind == "cmd_issued"
        ]


@dataclass
class Skill:
    """A learned action pattern stored in semantic memory."""
    skill_id: str
    cli_sequence: list[Command]
    preconditions: list[dict[str, Any]]
    environment_class: str
    success_rate: float
    sample_count: int
    confidence: float
    last_used: datetime
    provenance: dict[str, Any]
    supersedes: list[str] = field(default_factory=list)


@dataclass
class SafetyRule:
    """A gate condition checked synchronously before every command."""
    rule_id: str
    severity: Severity
    context_predicate: dict[str, Any]  # DSL — see evaluator below
    forbidden_command_pattern: str  # glob-style, matched against Command.name
    unless_params: dict[str, Any] | None = None
    source: str = "human_review"
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    supersedes: str | None = None


@dataclass
class MemoryCandidate:
    """Output of an episode, awaiting critic review before promotion."""
    candidate_id: str
    episode: Episode
    proposed_skill: Skill | None  # critic may revise
    proposed_safety_rule: SafetyRule | None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Store protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ReflexStore(Protocol):
    """The fastest layer. Pre-allocated, zero-IO, ring-buffer semantics.

    Implementations MUST NOT block. No network, no disk.
    """

    def snapshot(self, state: dict[str, Any]) -> None: ...
    def current(self) -> dict[str, Any]: ...
    def recent(self, n: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class EpisodicStore(Protocol):
    """Working memory for the current task(s). Fast but not real-time."""

    def start_episode(self, task_id: str, env_fingerprint: str | None = None) -> Episode: ...
    def append_event(self, episode_id: str, event: Event) -> None: ...
    def end_episode(self, episode_id: str, outcome: Outcome,
                    anomaly_flags: list[str] | None = None) -> Episode: ...
    def get_episode(self, episode_id: str) -> Episode | None: ...
    def active_episodes(self) -> list[Episode]: ...
    def evict_completed(self, older_than_seconds: float = 3600) -> int: ...


@runtime_checkable
class QuarantineStore(Protocol):
    """Holds candidate memories awaiting critic review."""

    def enqueue(self, candidate: MemoryCandidate) -> None: ...
    def pending(self, limit: int = 100) -> list[MemoryCandidate]: ...
    def mark_reviewed(self, candidate_id: str, decision: str) -> None: ...
    def prune_expired(self, ttl_hours: float = 24) -> int: ...


@runtime_checkable
class SemanticStore(Protocol):
    """Durable learned knowledge for this agent/robot."""

    def add_skill(self, skill: Skill) -> None: ...
    def get_skill(self, skill_id: str) -> Skill | None: ...
    def query(self, *, task_type: str | None = None,
              environment_class: str | None = None,
              min_confidence: float = 0.0,
              limit: int = 10) -> list[Skill]: ...
    def update_confidence(self, skill_id: str, new_confidence: float) -> None: ...
    def supersede(self, old_id: str, new_skill: Skill) -> None: ...
    def decay(self, unused_days: float = 30, rate: float = 0.9) -> int: ...


@runtime_checkable
class FleetStore(Protocol):
    """Cross-agent shared memory. Same shape as SemanticStore, plus validation."""

    def contribute(self, skill: Skill, source_agent_id: str) -> None: ...
    def query(self, *, task_type: str | None = None,
              environment_fingerprint: str | None = None,
              min_validations: int = 2,
              limit: int = 10) -> list[Skill]: ...


@runtime_checkable
class SafetyGate(Protocol):
    """Synchronous command gate. Called on EVERY command."""

    def allows(self, command: Command, context: dict[str, Any]) -> bool: ...
    def explain(self, command: Command, context: dict[str, Any]) -> str | None: ...
    def triggered_rule(self, command: Command, context: dict[str, Any]) -> SafetyRule | None: ...
    def add_rule(self, rule: SafetyRule) -> None: ...
    def rules(self) -> list[SafetyRule]: ...


# ---------------------------------------------------------------------------
# Critic protocol
# ---------------------------------------------------------------------------


class CriticDecision(str, Enum):
    PROMOTE = "promote"
    DISCARD = "discard"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    MERGE_INTO_EXISTING = "merge_into_existing"


@dataclass
class CriticReview:
    candidate_id: str
    decision: CriticDecision
    reason: str
    merged_into: str | None = None  # skill_id if MERGE_INTO_EXISTING
    revised_skill: Skill | None = None  # critic may rewrite the proposal


@runtime_checkable
class Critic(Protocol):
    """Reviews candidates and decides promotion. Typically LLM-backed in
    production; rule-based or mock for testing."""

    def review(self, candidate: MemoryCandidate,
               existing_skills: list[Skill]) -> CriticReview: ...


# ---------------------------------------------------------------------------
# Safety violation
# ---------------------------------------------------------------------------


class SafetyViolation(Exception):
    """Raised (or returned) when the safety gate blocks a command."""

    def __init__(self, command: Command, rule: SafetyRule, explanation: str):
        super().__init__(f"Safety rule {rule.rule_id} blocked {command.name}: {explanation}")
        self.command = command
        self.rule = rule
        self.explanation = explanation
