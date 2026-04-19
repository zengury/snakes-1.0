"""Inspire Robotics Dexterous Hand — 6 DOF, Modbus RTU over RS485, inspire_hands SDK."""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

# 6 DOF: 6 linear servo actuators driving 12 motor joints.
# Position range: 0-1000 (normalized, maps to servo travel).
# Models: RH56DFX, RH56BFX, RH56DFTP (tactile).

_JOINTS = [
    JointDef(0, "thumb_bend",   0.0, 1000.0),   # Thumb flexion/extension
    JointDef(1, "thumb_rotate", 0.0, 1000.0),   # Thumb rotation
    JointDef(2, "index",        0.0, 1000.0),   # Index finger
    JointDef(3, "middle",       0.0, 1000.0),   # Middle finger
    JointDef(4, "ring",         0.0, 1000.0),   # Ring finger
    JointDef(5, "pinky",        0.0, 1000.0),   # Pinky finger
]

INSPIRE_JOINTS = JointMap(_JOINTS)

FINGER_NAMES = ["thumb_bend", "thumb_rotate", "index", "middle", "ring", "pinky"]

# Gesture presets (6 joint values, 0=open, 1000=closed)
_GESTURES = {
    "pinch": [800, 500, 800, 0, 0, 0],       # Thumb + index pinch
    "point": [0, 0, 0, 1000, 1000, 1000],    # Index extended, others closed
    "thumbs-up": [0, 0, 1000, 1000, 1000, 1000],  # Thumb up, others closed
    "grip": [1000, 500, 1000, 1000, 1000, 1000],  # Full power grasp
}


class InspireHandMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(INSPIRE_JOINTS, **kw)
        self._speed = 500        # 0-1000
        self._force = 500        # 0-1000
        self._per_finger_force = {n: 0.0 for n in FINGER_NAMES}

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Finger open/close/move
        if cmd == "finger.open":
            name = args.get("name", "all")
            if name == "all":
                for jd in self.joint_map.joints:
                    self._motors[jd.index].q = 0.0
                return {"action": "open_all", "position": 0, **ts}
            jd = self.joint_map.resolve(name)
            self._motors[jd.index].q = 0.0
            return {"finger": jd.name, "position": 0, **ts}

        if cmd == "finger.close":
            name = args.get("name", "all")
            if name == "all":
                for jd in self.joint_map.joints:
                    self._motors[jd.index].q = 1000.0
                return {"action": "close_all", "position": 1000, **ts}
            jd = self.joint_map.resolve(name)
            self._motors[jd.index].q = 1000.0
            return {"finger": jd.name, "position": 1000, **ts}

        if cmd == "finger.move":
            name = args.get("name")
            pos = args.get("pos", 500)
            jd = self.joint_map.resolve(name)
            self._motors[jd.index].q = float(pos)
            return {"finger": jd.name, "position": pos, **ts}

        # Gestures
        if cmd == "gesture":
            gesture_name = args.get("gesture")
            force = args.get("force", 500)
            if gesture_name not in _GESTURES:
                raise ValueError(f"unknown gesture: {gesture_name!r}; valid: {list(_GESTURES)}")
            pose = _GESTURES[gesture_name]
            for jd in self.joint_map.joints:
                self._motors[jd.index].q = float(pose[jd.index])
            self._force = force
            return {
                "gesture": gesture_name,
                "force": force,
                "joints": {jd.name: pose[jd.index] for jd in self.joint_map.joints},
                **ts,
            }

        # Speed
        if cmd == "speed.set":
            self._speed = args.get("value", 500)
            return {"speed": self._speed, **ts}

        # Force
        if cmd == "force.set":
            self._force = args.get("value", 500)
            return {"force": self._force, **ts}

        if cmd == "force.get":
            # Simulate per-finger force readings
            return {
                "forces": {
                    jd.name: round(self._rng.uniform(0, self._force * 0.1), 1)
                    for jd in self.joint_map.joints
                },
                **ts,
            }

        # Angles readback
        if cmd == "angles.get":
            return {
                "angles": {
                    jd.name: round(self._motors[jd.index].q, 1)
                    for jd in self.joint_map.joints
                },
                **ts,
            }

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return InspireHandMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install inspire_hands, connect via RS485 (Modbus RTU, 115200 baud)"
    )
