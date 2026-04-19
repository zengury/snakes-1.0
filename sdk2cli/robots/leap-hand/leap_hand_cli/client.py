"""LEAP Hand — 16 DOF dexterous hand, 4 fingers x 4 joints, Dynamixel servos."""
from __future__ import annotations
import math
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

# Joint range: 0-3.14 rad (approx 0-180 degrees usable range for each joint).
# Dynamixel raw range is 0-4095 (0-360 deg) but effective ROM is smaller.
# Using radian limits representative of the LEAP Hand mechanical stops.

_JOINTS = [
    # Index finger (joints 0-3)
    JointDef(0,  "index_mcp_abd",  -0.35, 0.35),   # MCP abduction/adduction
    JointDef(1,  "index_mcp_flex", 0.0,   2.09),    # MCP flexion (~0-120 deg)
    JointDef(2,  "index_pip",      0.0,   1.92),    # PIP flexion (~0-110 deg)
    JointDef(3,  "index_dip",      0.0,   1.75),    # DIP flexion (~0-100 deg)
    # Middle finger (joints 4-7)
    JointDef(4,  "middle_mcp_abd",  -0.35, 0.35),
    JointDef(5,  "middle_mcp_flex", 0.0,   2.09),
    JointDef(6,  "middle_pip",      0.0,   1.92),
    JointDef(7,  "middle_dip",      0.0,   1.75),
    # Ring finger (joints 8-11)
    JointDef(8,  "ring_mcp_abd",  -0.35, 0.35),
    JointDef(9,  "ring_mcp_flex", 0.0,   2.09),
    JointDef(10, "ring_pip",      0.0,   1.92),
    JointDef(11, "ring_dip",      0.0,   1.75),
    # Thumb (joints 12-15)
    JointDef(12, "thumb_mcp_abd",  -0.79, 0.79),    # Thumb has wider abduction
    JointDef(13, "thumb_mcp_flex", 0.0,   1.57),    # MCP flexion (~0-90 deg)
    JointDef(14, "thumb_pip",      0.0,   1.75),    # PIP flexion
    JointDef(15, "thumb_dip",      0.0,   1.75),    # DIP flexion
]

LEAP_JOINTS = JointMap(_JOINTS)

# Predefined grasp poses (16 joint values in radians)
_GRASPS = {
    "open": [
        0.0, 0.0, 0.0, 0.0,    # index: all extended
        0.0, 0.0, 0.0, 0.0,    # middle
        0.0, 0.0, 0.0, 0.0,    # ring
        0.0, 0.0, 0.0, 0.0,    # thumb
    ],
    "close": [
        0.0, 1.57, 1.57, 1.40,   # index: fully flexed
        0.0, 1.57, 1.57, 1.40,   # middle
        0.0, 1.57, 1.57, 1.40,   # ring
        0.0, 1.22, 1.40, 1.40,   # thumb
    ],
    "pinch": [
        0.0, 1.40, 1.22, 1.05,   # index: curled for pinch
        0.0, 0.0, 0.0, 0.0,      # middle: open
        0.0, 0.0, 0.0, 0.0,      # ring: open
        0.35, 1.05, 1.05, 0.87,  # thumb: opposing index
    ],
    "point": [
        0.0, 0.0, 0.0, 0.0,      # index: extended (pointing)
        0.0, 1.57, 1.57, 1.40,   # middle: closed
        0.0, 1.57, 1.57, 1.40,   # ring: closed
        0.0, 1.22, 1.40, 1.40,   # thumb: closed
    ],
    "thumbs-up": [
        0.0, 1.57, 1.57, 1.40,   # index: closed
        0.0, 1.57, 1.57, 1.40,   # middle: closed
        0.0, 1.57, 1.57, 1.40,   # ring: closed
        0.0, 0.0, 0.0, 0.0,      # thumb: extended upward
    ],
}

CONTROL_MODES = ("position", "velocity", "current")


class LeapHandMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(LEAP_JOINTS, **kw)
        self._control_mode = "position"
        self._grasp = "open"

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Grasp commands
        if cmd == "grasp":
            pose_name = args.get("pose", "open")
            if pose_name not in _GRASPS:
                raise ValueError(f"unknown grasp pose: {pose_name!r}; valid: {list(_GRASPS)}")
            pose = _GRASPS[pose_name]
            for jd in self.joint_map.joints:
                self._motors[jd.index].q = pose[jd.index]
            self._grasp = pose_name
            return {
                "grasp": pose_name,
                "joints": {jd.name: round(pose[jd.index], 4) for jd in self.joint_map.joints},
                **ts,
            }

        # Control mode switching
        if cmd == "control.set":
            mode = args.get("mode", "position")
            if mode not in CONTROL_MODES:
                raise ValueError(f"unknown control mode: {mode!r}; valid: {list(CONTROL_MODES)}")
            self._control_mode = mode
            return {"control_mode": mode, **ts}

        if cmd == "control.get":
            return {"control_mode": self._control_mode, **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return LeapHandMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install dynamixel-sdk, connect via USB serial (Dynamixel protocol)"
    )
