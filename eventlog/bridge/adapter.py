"""
DDSAdapter: the bridge between a DDS bus and a memkit Memory.

Responsibilities:
1. Subscribe to state topics, route extracted fields into reflex.
2. Gate outbound commands through mem.check_command() before publishing.
3. Record commands into the active episodic trace.
4. Optionally flag anomalies from state topics (e.g., low battery).

What this adapter does NOT do:
- Start or end tasks. That's runtime policy — the application decides when
  a task begins, based on external triggers.
- Planning or replanning. Those are slow-loop concerns.
- Touch episodic/semantic/quarantine from the DDS callback thread. Ever.

Design invariants:
- DDS callbacks only touch reflex and (optionally) append to episodic
  through the "record_command"/"record_result" paths which are already
  fast (SQLite WAL append or in-memory list append). No critic calls,
  no semantic queries, no sync I/O beyond that.
- emit_command() is the ONLY outbound path. Anything else is a bug.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from memkit import Command, Memory, Outcome, SafetyViolation

from .bus import DDSBus
from .mapping import TopicMapping


@dataclass
class AdapterConfig:
    """Tunable knobs for the adapter."""
    # If True, commands that fail the safety gate raise SafetyViolation to
    # the caller. If False, they are silently dropped (logged) — useful when
    # you have a higher-level planner that expects silent failure semantics.
    raise_on_safety_block: bool = True

    # If True, every outbound command is recorded into the active episode.
    # Set False for cases where the caller manages episode recording manually.
    auto_record_commands: bool = True

    # Anomaly rules: evaluated on every reflex snapshot. If an anomaly
    # condition fires, the adapter appends an "anomaly" flag to the active
    # episode. Lightweight — no LLM, no critic, just structured checks.
    anomaly_rules: list["AnomalyRule"] = field(default_factory=list)


@dataclass
class AnomalyRule:
    """Structural rule for flagging anomalies from reflex state.

    Example — low battery:
        AnomalyRule(
            name="battery_critical",
            reflex_key="battery_pct",
            check=lambda v: v is not None and v < 5,
        )
    """
    name: str
    reflex_key: str
    check: Any  # Callable[[Any], bool] — loose typing to keep dataclass simple


class DDSAdapter:
    """Routes DDS state topics into memkit reflex; routes outbound commands
    through memkit's safety gate and episode recorder."""

    def __init__(
        self,
        memory: Memory,
        bus: DDSBus,
        mappings: list[TopicMapping],
        *,
        command_topic: str = "cli_command",
        result_topic: str | None = "cli_result",
        config: AdapterConfig | None = None,
    ):
        self.memory = memory
        self.bus = bus
        # Multiple mappings may declare the same topic (e.g., separating
        # IMU fields from battery fields on rt/lowstate). Merge them into
        # a single mapping per topic. The merged mapping uses the MINIMUM
        # of the min_interval_s values — always pick the faster rate when
        # in doubt. merge flag is OR'd (True wins).
        self.mappings = _merge_mappings_by_topic(mappings)
        self.command_topic = command_topic
        self.result_topic = result_topic
        self.config = config or AdapterConfig()

        # Active episode — None when no task is in progress. The adapter
        # does NOT set this; the runtime does, via set_active_episode().
        # This keeps task lifecycle out of the adapter.
        self._active_episode_id: str | None = None
        self._episode_lock = threading.Lock()

        # Stats for observability
        self._stats = {
            "messages_received": 0,
            "messages_dropped_rate": 0,
            "snapshots_applied": 0,
            "safety_critical_applied": 0,
            "commands_emitted": 0,
            "commands_blocked": 0,
            "anomalies_flagged": 0,
        }
        self._stats_lock = threading.Lock()

        self._subscribed = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to all configured topics. Idempotent."""
        if self._subscribed:
            return
        for topic in self.mappings:
            self.bus.subscribe(topic, self._make_handler(topic))
        # Also subscribe to results if configured
        if self.result_topic:
            self.bus.subscribe(self.result_topic, self._handle_result)
        self._subscribed = True

    def stop(self) -> None:
        """Unsubscribe all. Idempotent."""
        if not self._subscribed:
            return
        for topic in self.mappings:
            self.bus.unsubscribe(topic)
        if self.result_topic:
            self.bus.unsubscribe(self.result_topic)
        self._subscribed = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # -----------------------------------------------------------------
    # Task lifecycle hook — set by runtime, not by adapter
    # -----------------------------------------------------------------

    def set_active_episode(self, episode_id: str | None) -> None:
        """Called by the runtime when a task begins or ends.

        When None, inbound commands are NOT recorded (but safety still
        gates them). When set, commands are appended to the episode.
        """
        with self._episode_lock:
            self._active_episode_id = episode_id

    # -----------------------------------------------------------------
    # Outbound — the only path from app to robot
    # -----------------------------------------------------------------

    def emit_command(self, command: Command,
                     context: dict[str, Any] | None = None) -> bool:
        """Gate a command through safety, publish it, record it.

        Returns True if the command was emitted, False if blocked.
        Raises SafetyViolation if configured to.
        """
        # 1. Safety gate — synchronous, must be fast
        try:
            self.memory.check_command(command, context=context)
        except SafetyViolation:
            with self._stats_lock:
                self._stats["commands_blocked"] += 1
            if self.config.raise_on_safety_block:
                raise
            return False

        # 2. Record into the active episode (if any)
        if self.config.auto_record_commands:
            episode_id = self._current_episode_id()
            if episode_id is not None:
                # This touches episodic storage. For SQLite-backed episodic,
                # it's a single WAL append — sub-ms. For in-memory, it's a
                # list append.
                try:
                    self.memory.record_command(episode_id, command)
                except Exception:
                    # Don't let episodic failures block command emission.
                    # The robot's motion is more important than the trace.
                    pass

        # 3. Publish
        self.bus.publish(self.command_topic, {
            "name": command.name,
            "params": command.params,
        })
        with self._stats_lock:
            self._stats["commands_emitted"] += 1
        return True

    # -----------------------------------------------------------------
    # Inbound — DDS callbacks
    # -----------------------------------------------------------------

    def _make_handler(self, topic: str):
        """Build a closure that handles one topic's messages."""
        mapping = self.mappings[topic]

        def handler(message: dict[str, Any]) -> None:
            with self._stats_lock:
                self._stats["messages_received"] += 1

            # Rate limit check
            allow_full = mapping.should_sample()

            if allow_full:
                # Full extract — all fields
                extracted = mapping.extract(message)
                if extracted is None:
                    return  # required field missing
                mapping.mark_sampled()
                with self._stats_lock:
                    self._stats["snapshots_applied"] += 1
            else:
                # Rate-limited: extract only safety-critical fields, if any
                if not mapping.has_safety_critical():
                    with self._stats_lock:
                        self._stats["messages_dropped_rate"] += 1
                    return
                extracted = mapping.extract(message, only_safety_critical=True)
                if not extracted:
                    with self._stats_lock:
                        self._stats["messages_dropped_rate"] += 1
                    return
                with self._stats_lock:
                    self._stats["safety_critical_applied"] += 1

            # Apply to reflex — merge or replace
            if mapping.merge:
                combined = dict(self.memory.reflex.current())
                combined.update(extracted)
                self.memory.reflex.snapshot(combined)
            else:
                self.memory.reflex.snapshot(extracted)

            # Anomaly detection — runs on every apply, full or partial
            self._check_anomalies(extracted)

        return handler

    def _handle_result(self, message: dict[str, Any]) -> None:
        """Handler for the result topic. Records outcome back into episode."""
        episode_id = self._current_episode_id()
        if episode_id is None:
            return
        name = message.get("name", "unknown")
        outcome_raw = message.get("outcome", "unknown")
        try:
            outcome = Outcome(outcome_raw)
        except ValueError:
            outcome = Outcome.UNKNOWN
        detail = message.get("detail")
        try:
            self.memory.record_result(
                episode_id,
                Command(name=name, params=message.get("params", {})),
                outcome,
                detail=detail,
            )
        except Exception:
            pass  # Same philosophy as record_command — don't cascade

    def _check_anomalies(self, extracted: dict[str, Any]) -> None:
        """Evaluate anomaly rules against freshly extracted state."""
        if not self.config.anomaly_rules:
            return
        episode_id = self._current_episode_id()
        if episode_id is None:
            return
        current = self.memory.reflex.current()
        for rule in self.config.anomaly_rules:
            if rule.reflex_key not in current:
                continue
            try:
                if rule.check(current[rule.reflex_key]):
                    self._flag_anomaly(episode_id, rule.name)
            except Exception:
                continue

    def _flag_anomaly(self, episode_id: str, anomaly_name: str) -> None:
        """Append an anomaly event to the episode. Idempotent-ish:
        we don't de-dup here, but anomaly rules should self-debounce if
        they want that behavior."""
        try:
            from memkit import Event
            self.memory.episodic.append_event(
                episode_id,
                Event(
                    t=time.monotonic(),
                    kind="anomaly",
                    payload={"name": anomaly_name},
                ),
            )
            with self._stats_lock:
                self._stats["anomalies_flagged"] += 1
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Observability
    # -----------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def _current_episode_id(self) -> str | None:
        with self._episode_lock:
            return self._active_episode_id


def _merge_mappings_by_topic(mappings: list[TopicMapping]) -> dict[str, TopicMapping]:
    """Merge mappings that share a topic into a single mapping per topic.

    - Fields are concatenated (preserving declaration order).
    - min_interval_s becomes the MINIMUM across merged mappings (fastest wins).
    - merge flag is OR'd: if any contributor wants merge semantics, the
      combined mapping uses merge semantics.

    Duplicate reflex_keys across merged mappings are left to the user —
    the later declaration will overwrite the earlier one at extract time.
    """
    result: dict[str, TopicMapping] = {}
    for m in mappings:
        if m.topic not in result:
            # Copy fields list to avoid mutating the caller's TopicMapping
            result[m.topic] = TopicMapping(
                topic=m.topic,
                fields=list(m.fields),
                min_interval_s=m.min_interval_s,
                merge=m.merge,
            )
            continue
        existing = result[m.topic]
        existing.fields.extend(m.fields)
        # Choose the faster rate limit
        if m.min_interval_s > 0 and existing.min_interval_s > 0:
            existing.min_interval_s = min(existing.min_interval_s, m.min_interval_s)
        else:
            # Either is 0 (no limit) → the combined is 0
            existing.min_interval_s = 0.0
        existing.merge = existing.merge or m.merge
    return result
