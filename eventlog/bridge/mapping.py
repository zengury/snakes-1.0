"""
Topic mapping: declare how DDS message fields become reflex state keys.

Design decisions:

1. **Declarative over imperative.** You describe what to extract, not how.
   This makes the G1 configuration a static YAML/dict rather than code,
   which matters because topic schemas change between robot firmware
   versions.

2. **Field extraction uses dotted paths.** `"imu.quaternion.w"` rather than
   `lambda m: m["imu"]["quaternion"]["w"]`. Readable, serializable,
   debuggable.

3. **Rate limiting is per-topic, not per-message.** Reflex can take 1 kHz;
   any downstream work beyond reflex must be sampled down. The adapter
   handles this at the mapping layer so the application code never has to.

4. **Missing fields are silently dropped.** Robots ship broken firmware
   that occasionally omits fields. The reflex store should get what it can
   and move on — raising would kill the DDS thread.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class FieldMapping:
    """Extract one value from a DDS message into a reflex state key.

    Attributes:
        reflex_key: The key under which the value is stored in reflex state.
        source_path: Dotted path into the message (e.g., "imu.quaternion.w").
        transform: Optional callable to transform the extracted value.
        required: If True, a missing field drops the entire snapshot.
                  If False (default), the field is simply omitted.
        safety_critical: If True, this field bypasses the topic's rate limit.
                         Use for any field referenced by safety rules or
                         anomaly detection — stale safety state is worse
                         than bandwidth cost. Fields without this flag
                         obey the topic's min_interval_s.
    """
    reflex_key: str
    source_path: str
    transform: Callable[[Any], Any] | None = None
    required: bool = False
    safety_critical: bool = False


@dataclass
class TopicMapping:
    """How to convert messages on one DDS topic into reflex snapshots.

    Attributes:
        topic: DDS topic name.
        fields: List of FieldMapping — each extracts one value.
        min_interval_s: Minimum seconds between snapshots from this topic.
                        Zero means no rate limiting.
        merge: If True, merge extracted fields into existing reflex state.
               If False, replace the reflex state entirely each snapshot.
               Default True — typically multiple topics contribute to one
               unified reflex view.
    """
    topic: str
    fields: list[FieldMapping]
    min_interval_s: float = 0.0
    merge: bool = True

    # Internal — last-snapshot timestamp, mutated in the hot path.
    _last_snapshot_ts: float = field(default=0.0, init=False, repr=False)

    def should_sample(self, now: float | None = None) -> bool:
        """Returns True if enough time has passed since the last snapshot."""
        if self.min_interval_s <= 0:
            return True
        ts = now if now is not None else time.monotonic()
        if ts - self._last_snapshot_ts >= self.min_interval_s:
            return True
        return False

    def mark_sampled(self, now: float | None = None) -> None:
        self._last_snapshot_ts = now if now is not None else time.monotonic()

    def has_safety_critical(self) -> bool:
        """True if any field is safety_critical — skips rate-limit short-circuit."""
        return any(fm.safety_critical for fm in self.fields)

    def extract(self, message: dict[str, Any],
                *, only_safety_critical: bool = False) -> dict[str, Any] | None:
        """Extract mapped fields from a message.

        Args:
            message: The incoming DDS message.
            only_safety_critical: If True, extract ONLY fields flagged
                safety_critical. Used when the topic is rate-limited but
                we still want to apply safety-critical updates.

        Returns a dict of reflex_key -> value, or None if a required field
        was missing. Returns an empty dict if no fields matched the filter.
        """
        out: dict[str, Any] = {}
        for fm in self.fields:
            if only_safety_critical and not fm.safety_critical:
                continue
            value = _walk_path(message, fm.source_path)
            if value is _MISSING:
                if fm.required:
                    return None
                continue
            if fm.transform is not None:
                try:
                    value = fm.transform(value)
                except Exception:
                    # Transform errors drop the field silently — we don't
                    # want one bad IMU reading to kill the whole topic.
                    if fm.required:
                        return None
                    continue
            out[fm.reflex_key] = value
        return out


# Sentinel for missing fields — None is a valid field value in some schemas
class _MissingType:
    def __repr__(self):
        return "<MISSING>"


_MISSING: Any = _MissingType()


def _walk_path(obj: Any, path: str) -> Any:
    """Walk a dotted path into a nested dict/object. Returns _MISSING if
    any step can't be resolved."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            # Support object attribute access too — useful for IDL-generated
            # classes that expose fields as attributes instead of dict keys.
            if not hasattr(current, part):
                return _MISSING
            current = getattr(current, part)
    return current
