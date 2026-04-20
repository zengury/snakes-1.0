from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class FailureInjectionConfig:
    """Configurable failure injection for mock scenarios.

    Keep it minimal and test-friendly.

    - Probabilities are per-tool-call Bernoulli trials.
    - Optional forced failures support deterministic regression tests.
    """

    seed: int | None = None

    # Perception failures (vision)
    p_vision_fail: float = 0.0
    p_vision_corrupt: float = 0.0

    # Manipulation failures (arm/grasp/interact)
    p_manip_fail: float = 0.0
    p_slip_after_grasp: float = 0.0

    # System failures (timeouts/disconnects)
    p_system_timeout: float = 0.0
    p_system_disconnect: float = 0.0

    # Forced failures for deterministic tests (consume-first semantics)
    force_vision_fail: int = 0
    force_manip_fail: int = 0
    force_system_timeout: int = 0
    force_system_disconnect: int = 0

    def rng(self) -> random.Random:
        return random.Random(self.seed)


class FailureInjector:
    """Pure helper that makes deterministic failure decisions."""

    def __init__(self, cfg: FailureInjectionConfig):
        self.cfg = cfg
        self._rng = cfg.rng()
        self._forced_used = {
            "vision_fail": 0,
            "manip_fail": 0,
            "system_timeout": 0,
            "system_disconnect": 0,
        }

    def coin(self, p: float) -> bool:
        if p <= 0.0:
            return False
        if p >= 1.0:
            return True
        return self._rng.random() < p

    def maybe_system_failure(self) -> dict[str, Any] | None:
        if self._forced_used["system_disconnect"] < self.cfg.force_system_disconnect:
            self._forced_used["system_disconnect"] += 1
            return {
                "outcome": "fail",
                "failure_type": "system",
                "phenomenon": "daemon disconnected (forced)",
                "retryable": True,
            }
        if self._forced_used["system_timeout"] < self.cfg.force_system_timeout:
            self._forced_used["system_timeout"] += 1
            return {
                "outcome": "timeout",
                "failure_type": "system",
                "phenomenon": "tool call timed out (forced)",
                "retryable": True,
            }

        if self.coin(self.cfg.p_system_disconnect):
            return {
                "outcome": "fail",
                "failure_type": "system",
                "phenomenon": "daemon disconnected",
                "retryable": True,
            }
        if self.coin(self.cfg.p_system_timeout):
            return {
                "outcome": "timeout",
                "failure_type": "system",
                "phenomenon": "tool call timed out",
                "retryable": True,
            }
        return None

    def maybe_vision_failure(self) -> dict[str, Any] | None:
        if self._forced_used["vision_fail"] < self.cfg.force_vision_fail:
            self._forced_used["vision_fail"] += 1
            return {
                "outcome": "fail",
                "failure_type": "perception",
                "phenomenon": "image blurred / exposure failure (forced)",
                "retryable": True,
            }

        if self.coin(self.cfg.p_vision_fail):
            return {
                "outcome": "fail",
                "failure_type": "perception",
                "phenomenon": "image blurred / exposure failure",
                "retryable": True,
            }
        return None

    def maybe_manip_failure(self) -> dict[str, Any] | None:
        if self._forced_used["manip_fail"] < self.cfg.force_manip_fail:
            self._forced_used["manip_fail"] += 1
            return {
                "outcome": "fail",
                "failure_type": "manipulation",
                "phenomenon": "grasp failed: object slipped during closure (forced)",
                "retryable": True,
            }

        if self.coin(self.cfg.p_manip_fail):
            return {
                "outcome": "fail",
                "failure_type": "manipulation",
                "phenomenon": "grasp failed: object slipped during closure",
                "retryable": True,
            }
        return None
