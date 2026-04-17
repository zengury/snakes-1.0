from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import pytest

from snakes.types import AgentMessage, AgentTool, ContentBlock, MemorySnapshot


class MockLLMResponse:
    def __init__(self, text: str = "", tool_calls: Optional[List[Dict[str, Any]]] = None):
        self.text = text
        self.tool_calls = tool_calls or []


class MockLLM:
    def __init__(self, responses: Optional[List[MockLLMResponse]] = None):
        self.responses = responses or [MockLLMResponse(text="Hello, I am the robot assistant.")]
        self._call_index = 0
        self.calls: List[Dict[str, Any]] = []

    async def stream(
        self,
        system_prompt: str,
        messages: List[AgentMessage],
        tools: List[AgentTool],
        max_tokens: int,
    ) -> AsyncGenerator[Tuple[str, Optional[ContentBlock]], None]:
        self.calls.append({
            "system_prompt": system_prompt,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        })

        if self._call_index >= len(self.responses):
            resp = MockLLMResponse(text="No more responses configured.")
        else:
            resp = self.responses[self._call_index]
        self._call_index += 1

        if resp.text:
            yield resp.text, ContentBlock(type="text", text=resp.text)

        for tc in resp.tool_calls:
            yield "", ContentBlock(
                type="tool_use",
                tool_use_id=tc.get("id", f"call_{self._call_index}_{tc['name']}"),
                tool_name=tc["name"],
                tool_input=tc.get("input", {}),
            )


@pytest.fixture
def mock_llm():
    return MockLLM()


class MockExecutor:
    def __init__(self) -> None:
        self.results: Dict[str, Any] = {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.safety_errors: set[str] = set()

    async def execute(self, cmd: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((cmd, args))
        if cmd in self.safety_errors:
            from snakes.tools import SafetyError
            raise SafetyError(f"Safety limit triggered for {cmd}", cmd, args)
        if cmd in self.results:
            return self.results[cmd]
        return {"ok": True, "result": f"executed {cmd}"}


@pytest.fixture
def mock_executor():
    return MockExecutor()


@pytest.fixture
def sample_manifest():
    return (
        "cmd: arm.move_joint\n"
        "desc: Move a single joint to target angle\n"
        "param: joint_id (int) - Joint index 0-5\n"
        "param: angle (float) - Target angle in degrees\n"
        "param: speed (float) [optional] - Speed multiplier\n"
        "\n"
        "cmd: arm.gripper\n"
        "desc: Open or close the gripper\n"
        "param: action (str) - open or close\n"
        "param: force (float) [optional] - Grip force in newtons\n"
        "\n"
        "cmd: base.move\n"
        "desc: Move the mobile base\n"
        "param: x (float) - X displacement in meters\n"
        "param: y (float) - Y displacement in meters\n"
        "param: theta (float) [optional] - Rotation in radians\n"
        "\n"
        "cmd: sensors.camera\n"
        "desc: Capture image from camera\n"
        "param: camera_id (str) - Camera identifier\n"
    )


@pytest.fixture
def sample_robot_md(tmp_path: Any) -> Any:
    content = (
        "# ROBOT.md\n"
        "\n"
        "**Name**: X2-Alpha\n"
        "**Type**: humanoid\n"
        "**DOF**: 36\n"
        "**Sensors**: lidar, depth_camera, imu, force_torque\n"
        "**Capabilities**: walk, grasp, lift, navigate\n"
        "**Learned Skills**: none\n"
        "**Location**: lab-a\n"
        "**Battery**: 85%\n"
        "**Current Task**: idle\n"
        "**Owner**: team-alpha\n"
    )
    p = tmp_path / "ROBOT.md"
    p.write_text(content)
    return p


@pytest.fixture
def memory_snapshot():
    return MemorySnapshot(
        safety_rules=["Never move joints beyond limits", "Stop if battery < 10%"],
        semantic=["The red cup is usually on the desk"],
        episodic=[],
        reflexes=[],
    )


@dataclass
class Room:
    name: str
    description: str
    items: list[str] = field(default_factory=list)
    exits: dict[str, str] = field(default_factory=dict)
    locked_exits: dict[str, str] = field(default_factory=dict)
    clues: list[str] = field(default_factory=list)
    is_exit: bool = False


@dataclass
class EscapeRoom:
    rooms: dict[str, Room] = field(default_factory=dict)
    current_room: str = "start"
    inventory: list[str] = field(default_factory=list)
    score: int = 0
    escaped: bool = False
    discovered_rooms: set[str] = field(default_factory=set)

    def look(self) -> dict[str, Any]:
        room = self.rooms[self.current_room]
        self.discovered_rooms.add(self.current_room)
        return {
            "room": room.name,
            "description": room.description,
            "items": list(room.items),
            "exits": list(room.exits.keys()),
            "locked_exits": list(room.locked_exits.keys()),
        }

    def move(self, direction: str) -> dict[str, Any]:
        room = self.rooms[self.current_room]
        if direction in room.locked_exits:
            return {"ok": False, "error": f"Exit '{direction}' is locked. Need: {room.locked_exits[direction]}"}
        if direction not in room.exits:
            return {"ok": False, "error": f"No exit '{direction}' from {room.name}"}
        dest = room.exits[direction]
        self.current_room = dest
        self.score += 10
        self.discovered_rooms.add(dest)
        dest_room = self.rooms[dest]
        if dest_room.is_exit:
            self.escaped = True
            self.score += 100
        return {"ok": True, "room": dest, "score": self.score, "escaped": self.escaped}

    def pickup(self, item: str) -> dict[str, Any]:
        room = self.rooms[self.current_room]
        if item not in room.items:
            return {"ok": False, "error": f"No '{item}' here"}
        room.items.remove(item)
        self.inventory.append(item)
        self.score += 5
        return {"ok": True, "item": item, "inventory": list(self.inventory), "score": self.score}

    def use_item(self, item: str, target: str) -> dict[str, Any]:
        if item not in self.inventory:
            return {"ok": False, "error": f"You don't have '{item}'"}
        room = self.rooms[self.current_room]
        if target in room.locked_exits and room.locked_exits[target] == item:
            del room.locked_exits[target]
            room.exits[target] = target.replace("_door", "").replace("locked_", "")
            self.inventory.remove(item)
            self.score += 25
            return {"ok": True, "unlocked": target, "score": self.score}
        return {"ok": False, "error": f"Can't use '{item}' on '{target}'"}

    def examine(self, target: str) -> dict[str, Any]:
        room = self.rooms[self.current_room]
        if target in room.items:
            self.score += 2
            return {"ok": True, "description": f"A closer look at {target}.", "clues": list(room.clues)}
        return {"ok": False, "error": f"Nothing called '{target}' to examine"}


def _build_l1() -> EscapeRoom:
    return EscapeRoom(
        rooms={
            "start": Room(
                name="Entry Hall",
                description="A dimly lit hallway with stone walls.",
                items=["torch"],
                exits={"north": "library"},
            ),
            "library": Room(
                name="Library",
                description="Shelves of dusty books line the walls.",
                items=["key"],
                exits={"south": "start", "east": "exit_hall"},
            ),
            "exit_hall": Room(
                name="Exit Hall",
                description="A door with daylight behind it.",
                exits={},
                is_exit=True,
            ),
        },
        current_room="start",
    )


def _build_l2() -> EscapeRoom:
    return EscapeRoom(
        rooms={
            "start": Room(
                name="Foyer",
                description="An ornate foyer with a chandelier.",
                items=["notebook"],
                exits={"north": "gallery"},
                clues=["The painting hides a secret."],
            ),
            "gallery": Room(
                name="Gallery",
                description="Paintings hang on every wall.",
                items=["painting_fragment"],
                exits={"south": "start"},
                locked_exits={"east_door": "gallery_key"},
                clues=["Look behind the largest frame."],
            ),
            "hidden": Room(
                name="Hidden Study",
                description="A secret study with maps and scrolls.",
                items=["gallery_key", "cipher_wheel"],
                exits={"west": "gallery"},
            ),
            "vault": Room(
                name="Vault",
                description="A cold room with a heavy iron door ahead.",
                items=["treasure"],
                exits={"north": "exit_corridor"},
                clues=["The cipher reveals the final code."],
            ),
            "exit_corridor": Room(
                name="Exit Corridor",
                description="Freedom is just steps away.",
                exits={},
                is_exit=True,
            ),
        },
        current_room="start",
    )


def _build_l3() -> EscapeRoom:
    return EscapeRoom(
        rooms={
            "start": Room(
                name="Dungeon Cell",
                description="A damp cell with rusty bars.",
                items=["loose_brick"],
                exits={},
                locked_exits={"cell_door": "lockpick"},
                clues=["The bricks are not all solid."],
            ),
            "corridor": Room(
                name="Corridor",
                description="A winding corridor with flickering torches.",
                items=["lockpick", "map"],
                exits={"south": "start", "north": "guard_room"},
            ),
            "guard_room": Room(
                name="Guard Room",
                description="An empty guard post with a weapons rack.",
                items=["guard_key"],
                exits={"south": "corridor"},
                locked_exits={"gate": "guard_key"},
            ),
            "courtyard": Room(
                name="Courtyard",
                description="An open courtyard under the night sky.",
                items=["rope"],
                exits={"south": "guard_room"},
                locked_exits={"outer_wall": "rope"},
            ),
            "freedom": Room(
                name="Outside",
                description="The open road stretches before you.",
                exits={},
                is_exit=True,
            ),
        },
        current_room="start",
    )


@pytest.fixture
def escape_room_l1() -> EscapeRoom:
    return _build_l1()


@pytest.fixture
def escape_room_l2() -> EscapeRoom:
    return _build_l2()


@pytest.fixture
def escape_room_l3() -> EscapeRoom:
    return _build_l3()
