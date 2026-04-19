"""Undo stack for actuator commands.

Before every SET operation (joint set, loco move, arm do, etc.), the daemon
snapshots the relevant state. `unitree undo` pops the stack and restores
the previous joint positions.

The stack is bounded (default 50 entries) and lives in the daemon process.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from unitree_cli.client import G1_IDX_TO_NAME, G1_NUM_MOTOR, UnitreeClient, resolve_joint


@dataclass
class UndoEntry:
    """One undoable action."""
    cmd: str                      # e.g. "joint.set"
    args: dict[str, Any]          # original command args
    snapshot: dict[str, Any]      # state before the command
    timestamp: float = field(default_factory=time.time)


class UndoStack:
    def __init__(self, client: UnitreeClient, max_size: int = 50) -> None:
        self.client = client
        self.max_size = max_size
        self._stack: list[UndoEntry] = []

    def save(self, cmd: str, args: dict[str, Any]) -> None:
        """Snapshot relevant state before a mutating command."""
        if cmd == "joint.set":
            id_or_name = args.get("id_or_name", args.get("idx", 0))
            idx = resolve_joint(id_or_name)
            snap = self.client.joint_get(idx)
        elif cmd.startswith("loco."):
            state = self.client.get_state()
            snap = {"fsm_id": state.fsm_id, "motors": [
                {"q": m.q, "dq": m.dq} for m in state.motors
            ]}
        else:
            snap = {}

        self._stack.append(UndoEntry(cmd=cmd, args=args, snapshot=snap))
        if len(self._stack) > self.max_size:
            self._stack.pop(0)

    def undo(self, steps: int = 1) -> list[dict[str, Any]]:
        """Pop and restore the last N entries. Returns list of restored states."""
        results = []
        for _ in range(min(steps, len(self._stack))):
            entry = self._stack.pop()
            restored = self._restore(entry)
            results.append(restored)
        return results

    def _restore(self, entry: UndoEntry) -> dict[str, Any]:
        if entry.cmd == "joint.set" and "q" in entry.snapshot:
            id_or_name = entry.args.get("id_or_name", entry.args.get("idx", 0))
            idx = resolve_joint(id_or_name)
            old_q = entry.snapshot["q"]
            self.client.joint_set(idx, old_q)
            name = G1_IDX_TO_NAME.get(idx, str(idx))
            return {
                "undone": entry.cmd,
                "joint": name,
                "restored_q": old_q,
                "timestamp": time.time(),
            }
        return {
            "undone": entry.cmd,
            "snapshot": entry.snapshot,
            "note": "state recorded but automatic restore not implemented for this command type",
            "timestamp": time.time(),
        }

    @property
    def depth(self) -> int:
        return len(self._stack)

    def info(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "max_size": self.max_size,
            "entries": [
                {"cmd": e.cmd, "timestamp": e.timestamp}
                for e in reversed(self._stack[-5:])  # last 5
            ],
        }
