"""
Reflex layer: zero-allocation ring buffer for the hot path.

No locks on the read side by design — the fast loop reads `current()` which
returns the most recent snapshot. Multiple writers are NOT supported; this is
expected to be owned by the runtime tick thread.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from ..protocols import ReflexStore


class RingReflexStore:
    """In-memory ring buffer. Implements ReflexStore."""

    def __init__(self, capacity: int = 256):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._buf: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._capacity = capacity

    def snapshot(self, state: dict[str, Any]) -> None:
        # Shallow copy so callers can mutate their own dict without affecting
        # the ring. We deliberately don't deepcopy — the caller owns nested
        # object semantics.
        self._buf.append(dict(state))

    def current(self) -> dict[str, Any]:
        if not self._buf:
            return {}
        return self._buf[-1]

    def recent(self, n: int) -> list[dict[str, Any]]:
        if n <= 0:
            return []
        # deque slicing: take the last n
        buf_len = len(self._buf)
        start = max(0, buf_len - n)
        return [self._buf[i] for i in range(start, buf_len)]

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._buf)


# Compile-time protocol check
_: ReflexStore = RingReflexStore(capacity=1)
