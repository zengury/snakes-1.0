from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoomObject:
    name: str
    description: str
    interactable: bool = True
    hidden: bool = False
    contains: list[RoomObject] = field(default_factory=list)


@dataclass
class Puzzle:
    description: str
    solution: str
    hints: list[str] = field(default_factory=list)
    solved: bool = False

    def attempt(self, answer: str) -> bool:
        if answer.strip().lower() == self.solution.strip().lower():
            self.solved = True
            return True
        return False

    def get_hint(self, index: int) -> str | None:
        if 0 <= index < len(self.hints):
            return self.hints[index]
        return None


@dataclass
class Room:
    name: str
    description: str
    objects: list[RoomObject] = field(default_factory=list)
    exits: dict[str, str] = field(default_factory=dict)
    discovered: bool = False
    puzzles: list[Puzzle] = field(default_factory=list)

    def visible_objects(self) -> list[RoomObject]:
        return [obj for obj in self.objects if not obj.hidden]

    def all_objects_flat(self) -> list[RoomObject]:
        result: list[RoomObject] = []
        stack = list(self.objects)
        while stack:
            obj = stack.pop()
            result.append(obj)
            stack.extend(obj.contains)
        return result

    def find_object(self, name: str) -> RoomObject | None:
        for obj in self.all_objects_flat():
            if obj.name.lower() == name.lower():
                return obj
        return None

    def obstacle_names(self) -> list[str]:
        return [obj.name for obj in self.objects if not obj.hidden]


@dataclass
class EscapeRoom:
    level: int
    rooms: dict[str, Room] = field(default_factory=dict)
    current_room: str = ""
    inventory: list[RoomObject] = field(default_factory=list)
    hints_used: int = 0
    moves: int = 0
    escaped: bool = False

    def get_current_room(self) -> Room:
        return self.rooms[self.current_room]

    def look(self) -> dict[str, Any]:
        room = self.get_current_room()
        room.discovered = True
        return {
            "room": room.name,
            "description": room.description,
            "objects": [obj.name for obj in room.visible_objects()],
            "exits": list(room.exits.keys()),
        }

    def move(self, direction: str) -> dict[str, Any]:
        room = self.get_current_room()
        if direction not in room.exits:
            return {"ok": False, "error": f"No exit to the {direction}"}
        dest = room.exits[direction]
        if dest not in self.rooms:
            return {"ok": False, "error": f"Unknown room: {dest}"}

        for puzzle in room.puzzles:
            if not puzzle.solved and self._puzzle_blocks_exit(room, direction):
                return {"ok": False, "error": "A puzzle blocks this exit"}

        self.current_room = dest
        self.moves += 1
        self.rooms[dest].discovered = True
        return {"ok": True, "room": dest, **self.look()}

    def _puzzle_blocks_exit(self, room: Room, direction: str) -> bool:
        return any(not p.solved for p in room.puzzles)

    def interact(self, object_name: str) -> dict[str, Any]:
        room = self.get_current_room()
        obj = room.find_object(object_name)
        if obj is None:
            # Allow interacting with items in inventory.
            inv_obj = next((o for o in self.inventory if o.name.lower() == object_name.lower()), None)
            if inv_obj:
                result: dict[str, Any] = {"ok": True, "object": inv_obj.name, "description": inv_obj.description}
                # If the inventory item is a container, reveal and extract its contents.
                if inv_obj.contains:
                    for contained in inv_obj.contains:
                        contained.hidden = False
                    result["found"] = [c.name for c in inv_obj.contains]
                    # Extract to inventory so subsequent actions can reference them.
                    self.inventory.extend(inv_obj.contains)
                    inv_obj.contains = []
                return result
            return {"ok": False, "error": f"No object named '{object_name}' here"}

        if not obj.interactable:
            return {"ok": False, "error": f"Cannot interact with {obj.name}"}

        result: dict[str, Any] = {
            "ok": True,
            "object": obj.name,
            "description": obj.description,
        }

        if obj.contains:
            for contained in obj.contains:
                contained.hidden = False
            result["found"] = [c.name for c in obj.contains]

        return result

    def pickup(self, object_name: str) -> dict[str, Any]:
        room = self.get_current_room()
        obj = room.find_object(object_name)
        if obj is None:
            return {"ok": False, "error": f"No object named '{object_name}' here"}
        if obj.hidden:
            return {"ok": False, "error": f"Cannot see {object_name}"}
        room.objects = [o for o in room.objects if o.name != obj.name]
        for parent in room.objects:
            parent.contains = [c for c in parent.contains if c.name != obj.name]
        self.inventory.append(obj)
        return {"ok": True, "picked_up": obj.name}

    def solve_puzzle(self, puzzle_index: int, answer: str) -> dict[str, Any]:
        room = self.get_current_room()
        if puzzle_index < 0 or puzzle_index >= len(room.puzzles):
            return {"ok": False, "error": "No such puzzle"}
        puzzle = room.puzzles[puzzle_index]
        if puzzle.solved:
            return {"ok": True, "already_solved": True}
        if puzzle.attempt(answer):
            return {"ok": True, "solved": True}
        return {"ok": False, "error": "Wrong answer"}

    def use_hint(self, puzzle_index: int) -> dict[str, Any]:
        room = self.get_current_room()
        if puzzle_index < 0 or puzzle_index >= len(room.puzzles):
            return {"ok": False, "error": "No such puzzle"}
        puzzle = room.puzzles[puzzle_index]
        hint = puzzle.get_hint(self.hints_used)
        if hint is None:
            return {"ok": False, "error": "No more hints"}
        self.hints_used += 1
        return {"ok": True, "hint": hint}

    def get_map_accuracy(self) -> float:
        if not self.rooms:
            return 0.0
        discovered = sum(1 for r in self.rooms.values() if r.discovered)
        return discovered / len(self.rooms)

    def check_escape(self) -> bool:
        if self.level == 1:
            self.escaped = self.get_map_accuracy() == 1.0
        elif self.level == 2:
            room = self.get_current_room()
            self.escaped = all(p.solved for p in room.puzzles)
        else:
            self.escaped = all(
                p.solved
                for room in self.rooms.values()
                for p in room.puzzles
            ) and self.current_room == "exit"
        return self.escaped


def _create_level_1() -> EscapeRoom:
    rooms = {
        "entrance": Room(
            name="Entrance Hall",
            description="A dimly lit hallway with stone walls. Torches flicker on both sides.",
            objects=[
                RoomObject("torch", "A wall-mounted torch casting warm light"),
                RoomObject("stone_bench", "A worn stone bench against the wall"),
            ],
            exits={"north": "library", "east": "storage"},
        ),
        "library": Room(
            name="Library",
            description="Shelves of dusty books line the walls. A reading desk sits in the center.",
            objects=[
                RoomObject("bookshelf", "Tall wooden shelves packed with old books"),
                RoomObject("reading_desk", "A heavy oak desk with an open book"),
                RoomObject("globe", "An antique globe on a brass stand"),
            ],
            exits={"south": "entrance", "east": "study"},
        ),
        "storage": Room(
            name="Storage Room",
            description="Crates and barrels fill this cramped room. It smells of dust.",
            objects=[
                RoomObject("crate", "A wooden crate, lid slightly ajar"),
                RoomObject("barrel", "A sealed barrel"),
                RoomObject("cobweb", "Thick cobwebs in the corner", interactable=False),
            ],
            exits={"west": "entrance", "north": "study"},
        ),
        "study": Room(
            name="Private Study",
            description="A cozy room with a fireplace, armchair, and writing desk.",
            objects=[
                RoomObject("armchair", "A comfortable-looking leather armchair"),
                RoomObject("fireplace", "A stone fireplace with dying embers"),
                RoomObject("writing_desk", "A desk covered in papers and ink"),
            ],
            exits={"west": "library", "south": "storage"},
        ),
    }
    return EscapeRoom(level=1, rooms=rooms, current_room="entrance")


def _create_level_2() -> EscapeRoom:
    key = RoomObject("brass_key", "A small brass key", hidden=True)
    rooms = {
        "chamber": Room(
            name="The Chamber",
            description="A single room with a locked door on the far wall. A table sits in the center.",
            objects=[
                RoomObject("table", "A wooden table with three cups on it", contains=[
                    RoomObject("red_cup", "A red ceramic cup"),
                    RoomObject("blue_cup", "A blue ceramic cup", contains=[key]),
                    RoomObject("green_cup", "A green ceramic cup"),
                ]),
                RoomObject("locked_door", "A heavy door with a brass lock"),
                RoomObject("painting", "A landscape painting slightly askew on the wall"),
                RoomObject("rug", "A frayed rug in the corner", contains=[
                    RoomObject("note", "A crumpled note reading: 'The cold color hides the way out'", hidden=True),
                ]),
            ],
            puzzles=[
                Puzzle(
                    description="The door is locked. Find the key to open it.",
                    solution="brass_key",
                    hints=[
                        "Look under things.",
                        "One of the cups hides something.",
                        "The note mentions a cold color. Blue is cold.",
                    ],
                ),
            ],
            exits={},
        ),
    }
    return EscapeRoom(level=2, rooms=rooms, current_room="chamber")


def _create_level_3() -> EscapeRoom:
    rooms = {
        "cell": Room(
            name="Prison Cell",
            description="A bare stone cell. Moonlight streams through a tiny barred window.",
            objects=[
                RoomObject("bed", "A thin mattress on a metal frame", contains=[
                    RoomObject("rusty_nail", "A rusty nail hidden in the mattress", hidden=True),
                ]),
                RoomObject("window", "A small barred window high on the wall", interactable=False),
                RoomObject("loose_stone", "One stone in the wall looks loose", contains=[
                    RoomObject("torn_map", "A torn piece of paper with a partial map", hidden=True),
                ]),
                RoomObject("bucket", "A dented metal bucket (red herring)"),
            ],
            puzzles=[
                Puzzle(
                    description="The cell door lock can be picked with something thin and metal.",
                    solution="rusty_nail",
                    hints=["Search the bed carefully.", "Feel inside the mattress."],
                ),
            ],
            exits={"north": "corridor"},
        ),
        "corridor": Room(
            name="Dark Corridor",
            description="A long corridor with doors on both sides. Emergency lights flicker.",
            objects=[
                RoomObject("fire_extinguisher", "A wall-mounted fire extinguisher"),
                RoomObject("notice_board", "A board with faded notices and a number sequence: 3-1-4"),
                RoomObject("broken_camera", "A security camera, clearly broken", interactable=False),
                RoomObject("janitor_closet", "A small closet, locked with a combination lock"),
            ],
            puzzles=[],
            exits={"south": "cell", "east": "lab", "west": "control_room"},
        ),
        "lab": Room(
            name="Abandoned Lab",
            description="Equipment and shattered glass cover the tables. A chemical smell lingers.",
            objects=[
                RoomObject("microscope", "A dusty microscope"),
                RoomObject("chemical_cabinet", "A glass cabinet with colorful bottles"),
                RoomObject("computer", "An old terminal, screen still glowing", contains=[
                    RoomObject("access_code", "Screen shows: ACCESS CODE = HELIX", hidden=True),
                ]),
                RoomObject("lab_coat", "A white lab coat hanging on a hook (red herring)"),
                RoomObject("beaker", "A beaker with residue (red herring)"),
            ],
            puzzles=[
                Puzzle(
                    description="The computer asks for a password. The notice board had a clue.",
                    solution="314",
                    hints=["Remember the number sequence from the corridor."],
                ),
            ],
            exits={"west": "corridor"},
        ),
        "control_room": Room(
            name="Control Room",
            description="Banks of monitors and switches. One console is still active.",
            objects=[
                RoomObject("console", "The main control console with a code input"),
                RoomObject("monitors", "Security monitors showing empty rooms", interactable=False),
                RoomObject("keycard_reader", "A reader next to the exit door"),
                RoomObject("toolbox", "A metal toolbox (red herring)"),
            ],
            puzzles=[
                Puzzle(
                    description="Enter the access code to unlock the exit door.",
                    solution="helix",
                    hints=[
                        "The code was displayed somewhere on a screen.",
                        "Check the lab computer.",
                    ],
                ),
            ],
            exits={"east": "corridor", "north": "exit"},
        ),
        "exit": Room(
            name="Exit",
            description="Daylight floods in. You can see the outside world. Freedom!",
            objects=[],
            exits={},
        ),
    }
    return EscapeRoom(level=3, rooms=rooms, current_room="cell")


def create_level(level: int) -> EscapeRoom:
    factories = {
        1: _create_level_1,
        2: _create_level_2,
        3: _create_level_3,
    }
    factory = factories.get(level)
    if factory is None:
        raise ValueError(f"Unknown level: {level}. Choose 1, 2, or 3.")
    return factory()
