from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.hackathon.escape_room import EscapeRoom, RoomObject


@dataclass
class X2HackathonMock:
    escape_room: EscapeRoom
    head_target: str = ""
    left_arm_holding: str = ""
    right_arm_holding: str = ""
    _joint_positions: dict[str, float] = field(default_factory=dict)

    def execute(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        parts = cmd.split(".")
        group = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else ""

        dispatch: dict[str, Any] = {
            "camera": self._handle_camera,
            "lidar": self._handle_lidar,
            "walk": self._handle_walk,
            "arm": self._handle_arm,
            "head": self._handle_head,
            "joint": self._handle_joint,
            "battery": self._handle_battery,
            "status": self._handle_status,
        }

        handler = dispatch.get(group)
        if handler is None:
            return {"ok": False, "error": f"Unknown command group: {group}"}
        return handler(action, args)

    def _handle_camera(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action != "get":
            return {"ok": False, "error": f"Unknown camera action: {action}"}

        room = self.escape_room.get_current_room()
        description = room.description

        if self.head_target:
            obj = room.find_object(self.head_target)
            if obj:
                description = f"Looking at {obj.name}: {obj.description}"
                if obj.contains:
                    visible = [c for c in obj.contains if not c.hidden]
                    if visible:
                        description += f". Contains: {', '.join(c.name for c in visible)}"

        return {
            "ok": True,
            "result": {
                "room": room.name,
                "description": description,
                "visible_objects": [o.name for o in room.visible_objects()],
                "exits": list(room.exits.keys()),
            },
        }

    def _handle_lidar(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action != "get":
            return {"ok": False, "error": f"Unknown lidar action: {action}"}

        room = self.escape_room.get_current_room()
        obstacles = room.obstacle_names()
        walls = list(room.exits.keys())

        return {
            "ok": True,
            "result": {
                "obstacles": obstacles,
                "open_directions": walls,
                "room_bounds": {"width": 5.0, "depth": 5.0},
            },
        }

    def _handle_walk(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "forward":
            direction = args.get("direction", "north")
            return self.escape_room.move(direction)

        if action == "to":
            direction = args.get("direction", "")
            if not direction:
                return {"ok": False, "error": "No direction specified"}
            return self.escape_room.move(direction)

        if action == "stop":
            return {"ok": True, "result": "stopped"}

        return {"ok": False, "error": f"Unknown walk action: {action}"}

    def _handle_arm(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        side = args.get("side", "right")
        target = args.get("target", "")

        if action == "grab":
            if not target:
                return {"ok": False, "error": "No target specified"}
            result = self.escape_room.pickup(target)

            # If the object isn't in the room graph, allow "equipping" it from
            # inventory (common LLM behavior after picking something up).
            if not result.get("ok") and isinstance(result.get("error"), str) and result["error"].startswith("No object named"):
                inv_obj = next(
                    (o for o in self.escape_room.inventory if o.name.lower() == target.lower()),
                    None,
                )
                if inv_obj is not None:
                    result = {"ok": True, "picked_up": inv_obj.name, "equipped": True, "description": inv_obj.description}

            if result.get("ok") is True:
                if side == "left":
                    self.left_arm_holding = target
                else:
                    self.right_arm_holding = target
            return result

        if action == "interact":
            if not target:
                return {"ok": False, "error": "No target specified"}
            return self.escape_room.interact(target)

        if action == "release":
            if side == "left":
                released = self.left_arm_holding
                self.left_arm_holding = ""
            else:
                released = self.right_arm_holding
                self.right_arm_holding = ""
            return {"ok": True, "released": released}

        if action == "use":
            # NOTE: despite the param name, this can be either an inventory item name
            # OR a free-form answer string (e.g., a code like "314").
            item = args.get("item", "") or args.get("answer", "")
            puzzle_index = int(args.get("puzzle_index", 0))
            if not item:
                holding = self.left_arm_holding or self.right_arm_holding
                if holding:
                    item = holding
                else:
                    return {"ok": False, "error": "Not holding anything"}
            return self.escape_room.solve_puzzle(puzzle_index, item)

        return {"ok": False, "error": f"Unknown arm action: {action}"}

    def _handle_head(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "look":
            target = args.get("target", "")
            # Common LLM behavior: target="room" to mean scan.
            if target.lower() in {"room", "the room"}:
                target = ""

            self.head_target = target
            if target:
                room = self.escape_room.get_current_room()
                obj = room.find_object(target)
                if obj is None:
                    # Also allow looking at inventory items (common after pickup).
                    inv_obj = next(
                        (o for o in self.escape_room.inventory if o.name.lower() == target.lower()),
                        None,
                    )
                    if inv_obj is not None:
                        obj = inv_obj
                    else:
                        return {"ok": False, "error": f"Cannot see {target}"}
                result: dict[str, Any] = {
                    "ok": True,
                    "object": obj.name,
                    "description": obj.description,
                }
                if obj.contains:
                    visible = [c for c in obj.contains if not c.hidden]
                    if visible:
                        result["contains"] = [c.name for c in visible]
                return result
            look = self.escape_room.look()
            return {
                "ok": True,
                "result": {
                    "room": look["room"],
                    "description": look["description"],
                    "visible_objects": look["objects"],
                    "exits": look["exits"],
                },
            }

        if action == "scan":
            self.head_target = ""
            look = self.escape_room.look()
            return {
                "ok": True,
                "result": {
                    "room": look["room"],
                    "description": look["description"],
                    "visible_objects": look["objects"],
                    "exits": look["exits"],
                },
            }

        return {"ok": False, "error": f"Unknown head action: {action}"}

    def _handle_joint(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "set":
            joint_name = args.get("joint", "")
            position = float(args.get("position", 0.0))
            self._joint_positions[joint_name] = position
            return {"ok": True, "joint": joint_name, "position": position}

        if action == "get":
            joint_name = args.get("joint", "")
            pos = self._joint_positions.get(joint_name, 0.0)
            return {"ok": True, "joint": joint_name, "position": pos}

        return {"ok": False, "error": f"Unknown joint action: {action}"}

    def _handle_battery(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "battery_percent": 85.0, "charging": False}

    def _handle_status(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        room = self.escape_room.get_current_room()
        return {
            "ok": True,
            "result": {
                "current_room": room.name,
                "inventory": [o.name for o in self.escape_room.inventory],
                "puzzles": [
                    {"index": i, "description": p.description, "solved": p.solved}
                    for i, p in enumerate(room.puzzles)
                ],
                "left_arm": self.left_arm_holding or "empty",
                "right_arm": self.right_arm_holding or "empty",
                "head_target": self.head_target or "none",
                "moves": self.escape_room.moves,
                "hints_used": self.escape_room.hints_used,
                "escaped": self.escape_room.escaped,
                "level": self.escape_room.level,
            },
        }
