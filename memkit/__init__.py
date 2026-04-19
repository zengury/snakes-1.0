"""memkit — a reusable memory architecture for agent runtimes."""

from .async_memory import AsyncMemory
from .memory import Memory, MemoryConfig
from .protocols import (
    Command,
    Critic,
    CriticDecision,
    CriticReview,
    Episode,
    EpisodicStore,
    Event,
    FleetStore,
    MemoryCandidate,
    Outcome,
    QuarantineStore,
    ReflexStore,
    SafetyGate,
    SafetyRule,
    SafetyViolation,
    SemanticStore,
    Severity,
    Skill,
)

__version__ = "0.2.0"

__all__ = [
    # Facade
    "AsyncMemory",
    "Memory",
    "MemoryConfig",
    # Data types
    "Command",
    "Episode",
    "Event",
    "MemoryCandidate",
    "Outcome",
    "SafetyRule",
    "Severity",
    "Skill",
    # Protocols
    "Critic",
    "CriticDecision",
    "CriticReview",
    "EpisodicStore",
    "FleetStore",
    "QuarantineStore",
    "ReflexStore",
    "SafetyGate",
    "SemanticStore",
    # Errors
    "SafetyViolation",
]
