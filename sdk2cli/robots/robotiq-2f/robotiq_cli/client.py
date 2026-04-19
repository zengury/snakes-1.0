"""Robotiq 2F Gripper — 1 DOF adaptive gripper, Modbus RTU over RS485/TCP."""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase, SafetyError

_JOINTS = [
    JointDef(0, "finger", 0.0, 1.0),   # normalized: 0=open, 1=closed
]

ROBOTIQ_JOINTS = JointMap(_JOINTS)

MODELS = ("2F-85", "2F-140")

# Position mapping: raw 0-255 = fully open to fully closed
# 2F-85:  0mm (closed) to 85mm (open)
# 2F-140: 0mm (closed) to 140mm (open)
_MAX_MM = {"2F-85": 85.0, "2F-140": 140.0}


class RobotiqMockClient(MockClientBase):
    name = "mock"

    def __init__(self, model: str = "2F-85", **kw):
        super().__init__(ROBOTIQ_JOINTS, **kw)
        self._model = model
        self._max_mm = _MAX_MM.get(model, 85.0)
        self._position = 0       # 0-255 (0=open, 255=closed)
        self._speed = 255        # 0-255
        self._force = 0          # 0-255
        self._activated = False
        self._object_detected = False
        self._fault = 0

    def _pos_to_mm(self, pos: int) -> float:
        return round(self._max_mm * (1.0 - pos / 255.0), 2)

    def _mm_to_pos(self, mm: float) -> int:
        return max(0, min(255, int(round(255.0 * (1.0 - mm / self._max_mm)))))

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        if cmd == "activate":
            self._activated = True
            self._fault = 0
            return {"activated": True, "model": self._model, **ts}

        if not self._activated and cmd not in ("status",):
            raise SafetyError("gripper not activated; run 'activate' first")

        if cmd == "open":
            self._position = 0
            self._motors[0].q = 0.0
            return {"position": 0, "position_mm": self._pos_to_mm(0), "action": "open", **ts}

        if cmd == "close":
            self._position = 255
            self._motors[0].q = 1.0
            return {"position": 255, "position_mm": self._pos_to_mm(255), "action": "close", **ts}

        if cmd == "move":
            pos = int(args.get("position", 128))
            if not (0 <= pos <= 255):
                raise SafetyError(f"position {pos} out of range [0, 255]")
            speed = int(args.get("speed", self._speed))
            force = int(args.get("force", self._force))
            self._position = pos
            self._speed = speed
            self._force = force
            self._motors[0].q = pos / 255.0
            return {"position": pos, "position_mm": self._pos_to_mm(pos),
                    "speed": speed, "force": force, **ts}

        if cmd == "move-mm":
            distance = float(args.get("distance", self._max_mm / 2))
            if not (0.0 <= distance <= self._max_mm):
                raise SafetyError(f"distance {distance:.1f}mm out of range [0, {self._max_mm}]")
            pos = self._mm_to_pos(distance)
            self._position = pos
            self._motors[0].q = pos / 255.0
            return {"position": pos, "position_mm": self._pos_to_mm(pos),
                    "requested_mm": distance, **ts}

        if cmd == "status":
            return {
                "activated": self._activated,
                "model": self._model,
                "position": self._position,
                "position_mm": self._pos_to_mm(self._position),
                "speed": self._speed,
                "force": self._force,
                "object_detected": self._object_detected,
                "fault": self._fault,
                **ts,
            }

        if cmd == "calibrate":
            self._position = 0
            self._motors[0].q = 0.0
            return {"calibrated": True, "model": self._model, "max_mm": self._max_mm, **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return RobotiqMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install pyRobotiqGripper, connect via Modbus RTU (RS485 or TCP)"
    )
