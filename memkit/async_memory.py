"""
Async wrapper for Memory.

Design: the fast path (reflex + safety) stays synchronous because it's already
non-blocking (in-memory, deterministic). Everything that touches disk or calls
out to a critic becomes async via run_in_executor.

This lets the runtime's asyncio event loop coexist with memkit's blocking
SQLite without starving other tasks.

Usage:
    async_mem = AsyncMemory.from_config(config)
    await async_mem.begin_task(...)
    # Fast path unchanged:
    async_mem.reflex.snapshot(...)
    async_mem.safety.allows(cmd, ctx)   # sync is fine
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .memory import Memory, MemoryConfig
from .protocols import (
    Command,
    Episode,
    MemoryCandidate,
    Outcome,
    SafetyViolation,
    Skill,
)


class AsyncMemory:
    """Asyncio-friendly facade around Memory. Thin wrapper — keeps the sync
    Memory as the source of truth, offloads blocking ops to a thread pool.

    Access `.sync` for the underlying synchronous Memory when you need it
    (e.g., from a non-async callback).
    """

    def __init__(self, memory: Memory, executor: ThreadPoolExecutor | None = None):
        self.sync = memory
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="memkit"
        )
        self._owns_executor = executor is None

    @classmethod
    def from_config(cls, config: MemoryConfig,
                    executor: ThreadPoolExecutor | None = None) -> "AsyncMemory":
        return cls(Memory.from_config(config), executor=executor)

    # -----------------------------------------------------------------
    # Fast path — sync access preserved for hot loops
    # -----------------------------------------------------------------

    @property
    def reflex(self):
        return self.sync.reflex

    @property
    def safety(self):
        return self.sync.safety

    @property
    def config(self):
        return self.sync.config

    def check_command(self, command: Command,
                      context: dict[str, Any] | None = None) -> None:
        """Synchronous — safety gate is in-memory rule evaluation.

        Raising SafetyViolation from inside an async coroutine is fine.
        """
        self.sync.check_command(command, context)

    def command_allowed(self, command: Command,
                        context: dict[str, Any] | None = None) -> bool:
        return self.sync.command_allowed(command, context)

    # -----------------------------------------------------------------
    # Slow path — async wrappers around blocking IO
    # -----------------------------------------------------------------

    async def begin_task(self, task_id: str,
                         env_fingerprint: str | None = None) -> Episode:
        return await self._run(self.sync.begin_task, task_id, env_fingerprint)

    async def record_command(self, episode_id: str, command: Command,
                             t: float | None = None) -> None:
        await self._run(self.sync.record_command, episode_id, command, t)

    async def record_result(self, episode_id: str, command: Command,
                            outcome: Outcome, detail: dict[str, Any] | None = None,
                            t: float | None = None) -> None:
        await self._run(self.sync.record_result, episode_id, command,
                        outcome, detail, t)

    async def end_task(self, episode_id: str, outcome: Outcome,
                       anomaly_flags: list[str] | None = None,
                       auto_quarantine: bool = True) -> Episode:
        return await self._run(
            self.sync.end_task, episode_id, outcome, anomaly_flags, auto_quarantine,
        )

    async def process_quarantine(self, batch_size: int = 50) -> dict[str, int]:
        return await self._run(self.sync.process_quarantine, batch_size)

    async def query_skills(self, *, task_type: str | None = None,
                           environment_class: str | None = None,
                           min_confidence: float = 0.0,
                           include_fleet: bool = True,
                           limit: int = 10) -> list[Skill]:
        return await self._run(
            lambda: self.sync.query_skills(
                task_type=task_type,
                environment_class=environment_class,
                min_confidence=min_confidence,
                include_fleet=include_fleet,
                limit=limit,
            )
        )

    async def tick_housekeeping(self) -> dict[str, int]:
        return await self._run(self.sync.tick_housekeeping)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        if args:
            return await loop.run_in_executor(
                self._executor, lambda: fn(*args),
            )
        return await loop.run_in_executor(self._executor, fn)

    async def aclose(self) -> None:
        """Shut down the thread pool if we own it."""
        if self._owns_executor:
            await asyncio.get_running_loop().run_in_executor(
                None, self._executor.shutdown, True,
            )
