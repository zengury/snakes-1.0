"""Elephant Robotics myCobot 280 — 6 DOF desktop cobot, serial USB via pymycobot."""
from __future__ import annotations
import math
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase, SafetyError

# ±165 degrees = ±2.88 radians for all joints
_LIMIT = round(165.0 * math.pi / 180.0, 4)  # 2.8798

_JOINTS = [
    JointDef(0, "J1", -_LIMIT, _LIMIT),
    JointDef(1, "J2", -_LIMIT, _LIMIT),
    JointDef(2, "J3", -_LIMIT, _LIMIT),
    JointDef(3, "J4", -_LIMIT, _LIMIT),
    JointDef(4, "J5", -_LIMIT, _LIMIT),
    JointDef(5, "J6", -_LIMIT, _LIMIT),
]

MYCOBOT_JOINTS = JointMap(_JOINTS)


class MyCobotMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(MYCOBOT_JOINTS, **kw)
        self._powered = True
        self._coords = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # x,y,z,rx,ry,rz
        self._gripper_open = True
        self._gripper_value = 0      # 0-100
        self._moving = False
        self._drag_recording = False
        self._drag_trajectory = []   # list of angle snapshots

    def _angles_deg(self) -> list[float]:
        """Return current joint angles in degrees."""
        return [round(math.degrees(self._motors[i].q), 2) for i in range(6)]

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Power
        if cmd == "power-on":
            self._powered = True
            return {"powered": True, **ts}

        if cmd == "power-off":
            self._powered = False
            return {"powered": False, **ts}

        if not self._powered and cmd not in ("power-on",):
            raise SafetyError("robot powered off; run 'power on' first")

        # Move by angles (degrees input, stored as radians internally)
        if cmd == "move-angles":
            angles_deg = args.get("angles", [0.0] * 6)
            speed = args.get("speed", 50)
            for i, deg in enumerate(angles_deg):
                rad = math.radians(deg)
                jd = self.joint_map.by_index[i]
                self.joint_map.validate_position(jd, rad)
                self._motors[i].q = rad
            return {"action": "send_angles", "angles": angles_deg, "speed": speed, **ts}

        # Move by coords
        if cmd == "move-coords":
            coords = args.get("coords", [0.0] * 6)
            speed = args.get("speed", 50)
            self._coords = list(coords)
            return {"action": "send_coords", "coords": coords, "speed": speed, **ts}

        # Get angles
        if cmd == "get-angles":
            return {"angles": self._angles_deg(),
                    "joint_names": MYCOBOT_JOINTS.all_names(), **ts}

        # Get coords
        if cmd == "get-coords":
            return {"coords": self._coords,
                    "labels": ["x", "y", "z", "rx", "ry", "rz"], **ts}

        # Gripper
        if cmd == "gripper-open":
            self._gripper_open = True
            self._gripper_value = 0
            return {"gripper": "open", "value": 0, **ts}

        if cmd == "gripper-close":
            self._gripper_open = False
            self._gripper_value = 100
            return {"gripper": "closed", "value": 100, **ts}

        if cmd == "gripper-set":
            value = int(args.get("value", 50))
            speed = int(args.get("speed", 50))
            if not (0 <= value <= 100):
                raise SafetyError(f"gripper value {value} out of range [0, 100]")
            self._gripper_value = value
            self._gripper_open = (value == 0)
            return {"gripper_value": value, "speed": speed, **ts}

        # Release all servos (freedrive)
        if cmd == "release":
            return {"action": "release_all_servos", "released": True, **ts}

        # Is moving
        if cmd == "is-moving":
            return {"moving": self._moving, **ts}

        # Drag teach
        if cmd == "drag-start":
            self._drag_recording = True
            self._drag_trajectory = []
            return {"recording": True, "action": "drag_start", **ts}

        if cmd == "drag-stop":
            self._drag_recording = False
            return {"recording": False, "points": len(self._drag_trajectory),
                    "action": "drag_stop", **ts}

        if cmd == "drag-play":
            speed = args.get("speed", 50)
            return {"action": "drag_play", "points": len(self._drag_trajectory),
                    "speed": speed, **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return MyCobotMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install pymycobot, wrap MyCobot280 via serial USB"
    )
