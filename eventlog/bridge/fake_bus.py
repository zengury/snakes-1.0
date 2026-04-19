"""
FakeDDSBus: in-process pub/sub that satisfies the DDSBus protocol.

Used for tests and local development. Callbacks are dispatched on whatever
thread calls `publish()` — same semantics as real DDS when the middleware
is running on the caller's thread.

For tests that want to simulate real DDS's out-of-process delivery, see
ThreadedFakeDDSBus below.
"""
from __future__ import annotations

import queue
import threading
from collections import defaultdict
from typing import Any

from .bus import DDSBus, SubscriberCallback


class FakeDDSBus:
    """Synchronous in-process bus. Publish delivers to subscribers on the
    calling thread before returning."""

    def __init__(self):
        self._subs: dict[str, list[SubscriberCallback]] = defaultdict(list)
        self._closed = False

    def subscribe(self, topic: str, callback: SubscriberCallback) -> None:
        if self._closed:
            raise RuntimeError("bus is closed")
        self._subs[topic].append(callback)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("bus is closed")
        for cb in list(self._subs.get(topic, [])):
            # Exceptions in one subscriber should not stop delivery to others.
            # Real DDS middlewares generally log and continue — matching that.
            try:
                cb(payload)
            except Exception as e:
                # Stash so tests can inspect. Don't print from library code.
                self._last_error = (topic, e)

    def unsubscribe(self, topic: str) -> None:
        self._subs.pop(topic, None)

    def close(self) -> None:
        self._closed = True
        self._subs.clear()


class ThreadedFakeDDSBus:
    """Like FakeDDSBus, but delivers on a dedicated worker thread — useful
    for tests that want to exercise cross-thread hand-off (the real
    production scenario, where DDS callbacks are NOT on the caller's thread).
    """

    def __init__(self):
        self._subs: dict[str, list[SubscriberCallback]] = defaultdict(list)
        self._q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="fake-dds-dispatcher")
        self._thread.start()
        self._closed = False
        self._lock = threading.Lock()

    def subscribe(self, topic: str, callback: SubscriberCallback) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("bus is closed")
            self._subs[topic].append(callback)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("bus is closed")
        self._q.put((topic, payload))

    def unsubscribe(self, topic: str) -> None:
        with self._lock:
            self._subs.pop(topic, None)

    def close(self) -> None:
        self._closed = True
        self._q.put(None)  # sentinel
        self._thread.join(timeout=2.0)

    def wait_idle(self, timeout: float = 1.0) -> bool:
        """Block until the delivery queue drains. Returns True if drained."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._q.empty():
                # Give the worker a beat to finish the current message
                time.sleep(0.01)
                if self._q.empty():
                    return True
            time.sleep(0.005)
        return False

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            topic, payload = item
            with self._lock:
                callbacks = list(self._subs.get(topic, []))
            for cb in callbacks:
                try:
                    cb(payload)
                except Exception:
                    pass  # swallow, like real DDS


# Protocol checks
_: DDSBus = FakeDDSBus()
_: DDSBus = ThreadedFakeDDSBus()
