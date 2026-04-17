from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .types import AgentTool, MemorySnapshot


@dataclass
class CLICommand:
    """A single command from the sdk2cli daemon manifest."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    is_read_only: bool = False


@dataclass
class Sdk2CliManifest:
    """Parsed manifest from the sdk2cli daemon describing available robot commands."""

    commands: List[CLICommand] = field(default_factory=list)
    version: str = ""
    robot_name: str = ""


class ContextAssembler:
    """Builds the full LLM context for a robotics agent turn.

    Combines the robot identity document (ROBOT.md), the tool manifest
    from sdk2cli, memory snapshots, and current task state into the
    system prompt and tool list that get sent to the model.
    """

    def __init__(
        self,
        robot_md: str,
        manifest: Sdk2CliManifest,
        *,
        memory: Optional[MemorySnapshot] = None,
        task_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._robot_md = robot_md
        self._manifest = manifest
        self._memory = memory or MemorySnapshot()
        self._task_state = task_state or {}

    @property
    def memory(self) -> MemorySnapshot:
        return self._memory

    @memory.setter
    def memory(self, value: MemorySnapshot) -> None:
        self._memory = value

    @property
    def task_state(self) -> Dict[str, Any]:
        return self._task_state

    @task_state.setter
    def task_state(self, value: Dict[str, Any]) -> None:
        self._task_state = value

    def build_system_prompt(self) -> str:
        return assemble_system_prompt(
            self._robot_md, self._manifest, self._memory, self._task_state
        )

    def build_tools(
        self,
        execute_fn: Callable[..., Any],
    ) -> List[AgentTool]:
        return assemble_tools(self._manifest, self._memory, execute_fn)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def assemble_system_prompt(
    robot_md: str,
    manifest: Sdk2CliManifest,
    memory: MemorySnapshot,
    task_state: Optional[Dict[str, Any]] = None,
) -> str:
    sections: List[str] = []

    # Identity
    sections.append(robot_md.strip())

    # Available capabilities summary (the full tool schemas go via the
    # tools API parameter; this is a natural-language overview so the
    # model can reason about what it can do).
    if manifest.commands:
        cmd_lines = [f"- {c.name}: {c.description}" for c in manifest.commands]
        sections.append(
            "# Available Robot Commands\n" + "\n".join(cmd_lines)
        )

    # Safety rules -- always placed early so the model sees them before
    # deciding on actions.
    if memory.safety_rules:
        rules_text = "\n".join(f"- {r}" for r in memory.safety_rules)
        sections.append(f"# Safety Rules\n{rules_text}")

    # Reflex memories (fast reactive patterns)
    if memory.reflexes:
        reflex_text = "\n".join(f"- {r}" for r in memory.reflexes)
        sections.append(f"# Reflexes\n{reflex_text}")

    # Relevant semantic memories
    if memory.semantic:
        sem_text = "\n".join(f"- {s}" for s in memory.semantic)
        sections.append(f"# Relevant Memories\n{sem_text}")

    # Recent episodic memories
    if memory.episodic:
        ep_text = "\n".join(f"- {e}" for e in memory.episodic[-20:])
        sections.append(f"# Recent Episodes\n{ep_text}")

    # Current task state
    if task_state:
        state_lines = [f"- {k}: {v}" for k, v in task_state.items()]
        sections.append(
            "# Current Task State\n" + "\n".join(state_lines)
        )

    return "\n\n".join(sections)


def assemble_tools(
    manifest: Sdk2CliManifest,
    memory: MemorySnapshot,
    execute_fn: Callable[..., Any],
) -> List[AgentTool]:
    """Convert sdk2cli CLI commands into AgentTool objects.

    ``execute_fn`` must be an async callable with signature
    ``async def execute(command_name: str, params: dict) -> str``.
    Each generated tool delegates to ``execute_fn`` with its own
    command name bound.
    """
    tools: List[AgentTool] = []

    for cmd in manifest.commands:
        tool = _cli_command_to_tool(cmd, execute_fn)
        tools.append(tool)

    return tools


def _cli_command_to_tool(
    cmd: CLICommand,
    execute_fn: Callable[..., Any],
) -> AgentTool:
    input_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    for param_name, param_def in cmd.parameters.items():
        if isinstance(param_def, dict):
            input_schema["properties"][param_name] = param_def
            if param_def.get("required", False):
                input_schema["required"].append(param_name)
        else:
            input_schema["properties"][param_name] = {
                "type": "string",
                "description": str(param_def),
            }

    bound_name = cmd.name

    async def _execute(params: Dict[str, Any]) -> str:
        return await execute_fn(bound_name, params)

    return AgentTool(
        name=cmd.name,
        description=cmd.description,
        input_schema=input_schema,
        execute=_execute,
        is_concurrency_safe=lambda _input, _ro=cmd.is_read_only: _ro,
    )
