from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .loop import run_agent_loop
from .types import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentState,
    AgentTool,
    EmitFn,
    EventType,
    FollowUpMessage,
    MemorySnapshot,
    SteeringMessage,
)


class Agent:
    """Stateful wrapper around the agent loop.

    Manages lifecycle, event subscriptions, tool registration, and
    steering/follow-up queues.  Designed for long-lived robotics
    processes where the agent is prompted repeatedly.
    """

    def __init__(
        self,
        system_prompt: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        config: Optional[AgentLoopConfig] = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._model = model
        self._max_tokens = max_tokens
        self._config = config or AgentLoopConfig()
        self._tools: Dict[str, AgentTool] = {}
        self._subscribers: Dict[Optional[EventType], List[Callable[[AgentEvent], Awaitable[None]]]] = {}
        self._state = AgentState.IDLE
        self._context: Optional[AgentContext] = None
        self._memory = MemorySnapshot()

        self._signal = asyncio.Event()
        self._steering_queue: asyncio.Queue[SteeringMessage] = asyncio.Queue()
        self._follow_up_queue: asyncio.Queue[FollowUpMessage] = asyncio.Queue()

        self._active_task: Optional[asyncio.Task[List[Any]]] = None
        self._idle_event = asyncio.Event()
        self._idle_event.set()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tool(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool

    def unregister_tool(self, name: str) -> None:
        self._tools.pop(name, None)

    @property
    def tools(self) -> List[AgentTool]:
        return list(self._tools.values())

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def on(
        self,
        event_type: Optional[EventType],
        callback: Callable[[AgentEvent], Awaitable[None]],
    ) -> Callable[[], None]:
        """Subscribe to events.  Pass None for event_type to receive all events.

        Returns an unsubscribe function.
        """
        subs = self._subscribers.setdefault(event_type, [])
        subs.append(callback)

        def _unsub() -> None:
            try:
                subs.remove(callback)
            except ValueError:
                pass

        return _unsub

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def prompt(self, message: str) -> List[Any]:
        """Start a new agent run with the given user message."""
        if self._state is not AgentState.IDLE:
            raise RuntimeError(
                f"Cannot prompt while agent is in state {self._state.value}"
            )
        return await self._run([message])

    async def continue_(self) -> List[Any]:
        """Continue the current conversation without adding a new user message."""
        if self._state is not AgentState.IDLE:
            raise RuntimeError(
                f"Cannot continue while agent is in state {self._state.value}"
            )
        return await self._run([])

    def steer(self, message: str, *, priority: int = 0) -> None:
        """Inject a steering message into the current turn.

        Steering messages are picked up between tool calls within a single
        turn, giving the caller a way to redirect the agent mid-flight.
        """
        self._steering_queue.put_nowait(
            SteeringMessage(content=message, priority=priority)
        )

    def follow_up(self, message: str) -> None:
        """Queue a follow-up message for after the current turn completes."""
        self._follow_up_queue.put_nowait(FollowUpMessage(content=message))

    async def abort(self) -> None:
        """Signal the running loop to stop as soon as possible."""
        if self._state is not AgentState.RUNNING:
            return
        self._state = AgentState.ABORTING
        self._signal.set()
        if self._active_task is not None:
            try:
                await self._active_task
            except (asyncio.CancelledError, Exception):
                pass
        self._state = AgentState.IDLE
        self._idle_event.set()

    async def wait_for_idle(self) -> None:
        await self._idle_event.wait()

    def reset(self) -> None:
        """Reset agent state for a fresh conversation.

        Must only be called while the agent is idle.
        """
        if self._state is not AgentState.IDLE:
            raise RuntimeError(
                f"Cannot reset while agent is in state {self._state.value}"
            )
        self._context = None
        self._memory = MemorySnapshot()
        self._signal.clear()
        # Drain queues
        while not self._steering_queue.empty():
            try:
                self._steering_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self._follow_up_queue.empty():
            try:
                self._follow_up_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def context(self) -> Optional[AgentContext]:
        return self._context

    @property
    def memory(self) -> MemorySnapshot:
        return self._memory

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _emit(self, event: AgentEvent) -> None:
        targets: List[Callable[[AgentEvent], Awaitable[None]]] = []
        targets.extend(self._subscribers.get(None, []))
        targets.extend(self._subscribers.get(event.type, []))
        for cb in targets:
            try:
                await cb(event)
            except Exception:
                pass

    async def _run(self, prompts: List[str]) -> List[Any]:
        self._state = AgentState.RUNNING
        self._idle_event.clear()
        self._signal.clear()

        if self._context is None:
            self._context = AgentContext(
                system_prompt=self._system_prompt,
                tools=self.tools,
                memory=self._memory,
                model=self._model,
                max_tokens=self._max_tokens,
            )
        else:
            # Refresh tools in case registrations changed between runs
            self._context.tools = self.tools

        try:
            self._active_task = asyncio.current_task()
            result = await run_agent_loop(
                prompts=prompts,
                context=self._context,
                config=self._config,
                emit=self._emit,
                signal=self._signal,
                steering_queue=self._steering_queue,
                follow_up_queue=self._follow_up_queue,
            )
            return result
        finally:
            self._active_task = None
            self._state = AgentState.IDLE
            self._idle_event.set()
