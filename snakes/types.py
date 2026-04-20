from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Union,
)


ToolExecutionMode = Literal["parallel", "sequential"]


class AgentState(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    ABORTING = "aborting"


EventType = Literal[
    "agent_start",
    "agent_end",
    "turn_start",
    "turn_end",
    "message_start",
    "message_update",
    "message_end",
    "tool_execution_start",
    "tool_execution_end",
]


@dataclass(frozen=True)
class ContentBlock:
    type: Literal["text", "tool_use", "tool_result", "thinking"]
    text: Optional[str] = None
    tool_use_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_result_content: Optional[Any] = None
    is_error: bool = False


@dataclass
class AgentMessage:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant", "system"] = "assistant"
    content: List[ContentBlock] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None

    @property
    def tool_use_blocks(self) -> List[ContentBlock]:
        return [b for b in self.content if b.type == "tool_use"]

    @property
    def has_tool_use(self) -> bool:
        return any(b.type == "tool_use" for b in self.content)

    @property
    def text(self) -> str:
        return "".join(b.text or "" for b in self.content if b.type == "text")


@dataclass(frozen=True)
class AgentEvent:
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    message: Optional[AgentMessage] = None
    delta: Optional[str] = None
    tool_call: Optional[AgentToolCall] = None
    tool_result: Optional[AgentToolResult] = None


@dataclass
class AgentToolCall:
    id: str
    tool_name: str
    tool_input: Dict[str, Any]
    assistant_message_id: str


@dataclass
class AgentToolResult:
    tool_call_id: str
    tool_name: str
    content: Any
    is_error: bool = False
    robot_state_snapshot: Optional[Dict[str, Any]] = None


@dataclass
class AgentTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    execute: Callable[[Dict[str, Any]], Awaitable[Any]]

    # Toolchain execution semantics (minimal, optional)
    timeout_s: Optional[float] = None
    max_retries: int = 0

    # Optional: group name for simple anti-loop safeguards
    group: Optional[str] = None

    is_concurrency_safe: Callable[[Dict[str, Any]], bool] = field(
        default_factory=lambda: lambda _: False
    )
    execution_mode: ToolExecutionMode = "sequential"


@dataclass
class BeforeToolCallContext:
    tool_call: AgentToolCall
    tool: AgentTool
    messages: List[AgentMessage]

    # Set by hook to block execution
    blocked: bool = False
    block_reason: Optional[str] = None
    # Set by hook to substitute a different result
    substitute_result: Optional[Any] = None


@dataclass
class AfterToolCallContext:
    tool_call: AgentToolCall
    tool: AgentTool
    result: AgentToolResult
    messages: List[AgentMessage]

    # Set by hook to override the result sent back to the model
    override_result: Optional[Any] = None
    # Set by hook to inject an observation (e.g. robot state diff)
    observation: Optional[str] = None


@dataclass
class MemorySnapshot:
    reflexes: List[str] = field(default_factory=list)
    semantic: List[str] = field(default_factory=list)
    safety_rules: List[str] = field(default_factory=list)
    episodic: List[str] = field(default_factory=list)


@dataclass
class AgentContext:
    system_prompt: str
    messages: List[AgentMessage] = field(default_factory=list)
    tools: List[AgentTool] = field(default_factory=list)
    memory: MemorySnapshot = field(default_factory=MemorySnapshot)
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    metadata: Dict[str, Any] = field(default_factory=dict)


EmitFn = Callable[[AgentEvent], Awaitable[None]]


@dataclass
class AgentLoopConfig:
    max_turns: int = 100
    max_tool_concurrency: int = 10
    execution_mode: ToolExecutionMode = "parallel"

    before_tool_call: Optional[
        Callable[[BeforeToolCallContext], Awaitable[None]]
    ] = None
    after_tool_call: Optional[
        Callable[[AfterToolCallContext], Awaitable[None]]
    ] = None

    # Robotics: observe robot state after each tool call for verification
    observe_robot_state: Optional[
        Callable[[], Awaitable[Optional[Dict[str, Any]]]]
    ] = None

    # Robotics: write episodic memory during the loop
    write_episodic_memory: Optional[
        Callable[[str], Awaitable[None]]
    ] = None

    # LLM streaming function — decoupled so callers can swap providers.
    # Yields (delta_text, content_block | None) tuples as the response streams.
    stream_fn: Optional[
        Callable[
            [str, List[AgentMessage], List[AgentTool], int],
            AsyncGenerator[tuple[str, Optional[ContentBlock]], None],
        ]
    ] = None


@dataclass
class SteeringMessage:
    content: str
    priority: int = 0


@dataclass
class FollowUpMessage:
    content: str
