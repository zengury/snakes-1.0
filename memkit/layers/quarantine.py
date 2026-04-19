"""
Quarantine: holding pen between episode-end and semantic promotion.

The fast loop never reads from quarantine. The critic loop pulls pending
candidates in batches.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from ..protocols import MemoryCandidate, QuarantineStore


class InMemoryQuarantineStore:
    """Implements QuarantineStore in-memory."""

    def __init__(self):
        self._pending: dict[str, MemoryCandidate] = {}
        self._reviewed: dict[str, str] = {}  # candidate_id -> decision
        self._enqueued_at: dict[str, float] = {}

    def enqueue(self, candidate: MemoryCandidate) -> None:
        if not candidate.candidate_id:
            candidate.candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        if not candidate.created_at:
            candidate.created_at = datetime.now(timezone.utc)
        self._pending[candidate.candidate_id] = candidate
        self._enqueued_at[candidate.candidate_id] = time.time()

    def pending(self, limit: int = 100) -> list[MemoryCandidate]:
        # Oldest first — FIFO review order
        sorted_ids = sorted(
            self._pending.keys(),
            key=lambda cid: self._enqueued_at.get(cid, 0),
        )
        return [self._pending[cid] for cid in sorted_ids[:limit]]

    def mark_reviewed(self, candidate_id: str, decision: str) -> None:
        if candidate_id not in self._pending:
            raise KeyError(f"no pending candidate {candidate_id}")
        self._reviewed[candidate_id] = decision
        self._pending.pop(candidate_id, None)
        self._enqueued_at.pop(candidate_id, None)

    def prune_expired(self, ttl_hours: float = 24) -> int:
        now = time.time()
        cutoff = ttl_hours * 3600
        expired = [
            cid for cid, ts in self._enqueued_at.items()
            if now - ts > cutoff
        ]
        for cid in expired:
            self._pending.pop(cid, None)
            self._enqueued_at.pop(cid, None)
        return len(expired)


# Protocol check
_: QuarantineStore = InMemoryQuarantineStore()
