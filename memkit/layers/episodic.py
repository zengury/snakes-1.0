"""
Episodic memory: working memory for active tasks.

Two implementations:
- InMemoryEpisodicStore: for tests and short-lived agents
- SQLiteEpisodicStore: for durable local storage (see stores/sqlite.py)
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from ..protocols import Episode, EpisodicStore, Event, Outcome


class InMemoryEpisodicStore:
    """Implements EpisodicStore with a plain dict. Not durable."""

    def __init__(self):
        self._episodes: dict[str, Episode] = {}
        self._active: set[str] = set()
        self._completed_at: dict[str, float] = {}  # episode_id -> unix ts

    def start_episode(self, task_id: str, env_fingerprint: str | None = None) -> Episode:
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        ep = Episode(
            episode_id=episode_id,
            task_id=task_id,
            started_at=datetime.now(timezone.utc),
            env_fingerprint=env_fingerprint,
        )
        self._episodes[episode_id] = ep
        self._active.add(episode_id)
        return ep

    def append_event(self, episode_id: str, event: Event) -> None:
        ep = self._episodes.get(episode_id)
        if ep is None:
            raise KeyError(f"unknown episode {episode_id}")
        if episode_id not in self._active:
            raise RuntimeError(f"episode {episode_id} already ended")
        ep.events.append(event)

    def end_episode(self, episode_id: str, outcome: Outcome,
                    anomaly_flags: list[str] | None = None) -> Episode:
        ep = self._episodes.get(episode_id)
        if ep is None:
            raise KeyError(f"unknown episode {episode_id}")
        ep.outcome = outcome
        if anomaly_flags:
            ep.anomaly_flags = list(anomaly_flags)
        self._active.discard(episode_id)
        self._completed_at[episode_id] = time.time()
        return ep

    def get_episode(self, episode_id: str) -> Episode | None:
        return self._episodes.get(episode_id)

    def active_episodes(self) -> list[Episode]:
        return [self._episodes[eid] for eid in self._active]

    def evict_completed(self, older_than_seconds: float = 3600) -> int:
        now = time.time()
        to_evict = [
            eid for eid, ts in self._completed_at.items()
            if now - ts > older_than_seconds
        ]
        for eid in to_evict:
            self._episodes.pop(eid, None)
            self._completed_at.pop(eid, None)
        return len(to_evict)


# Protocol check
_: EpisodicStore = InMemoryEpisodicStore()
