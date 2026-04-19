"""DexRobot Dexterous Hand — 19 DOF (DexHand021), USB-CAN, dexrobot_ecosystem SDK."""
from __future__ import annotations
import math
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

# DexHand021: 19 DOF (4+4+4+4+3)
# Joint range: 0-3.14 rad (model-specific, reasonable defaults)

_JOINTS = [
    # Thumb (4 DOF)
    JointDef(0,  "thumb_cmc_abd",   -0.52, 0.52),   # CMC abduction/adduction
    JointDef(1,  "thumb_cmc_flex",   0.0,  1.57),   # CMC flexion (~0-90 deg)
    JointDef(2,  "thumb_mcp",        0.0,  1.57),   # MCP flexion
    JointDef(3,  "thumb_ip",         0.0,  1.40),   # IP flexion (~0-80 deg)
    # Index finger (4 DOF)
    JointDef(4,  "index_mcp_abd",   -0.35, 0.35),   # MCP abduction
    JointDef(5,  "index_mcp_flex",   0.0,  1.92),   # MCP flexion (~0-110 deg)
    JointDef(6,  "index_pip",        0.0,  1.92),   # PIP flexion
    JointDef(7,  "index_dip",        0.0,  1.57),   # DIP flexion
    # Middle finger (4 DOF)
    JointDef(8,  "middle_mcp_abd",  -0.35, 0.35),
    JointDef(9,  "middle_mcp_flex",  0.0,  1.92),
    JointDef(10, "middle_pip",       0.0,  1.92),
    JointDef(11, "middle_dip",       0.0,  1.57),
    # Ring finger (4 DOF)
    JointDef(12, "ring_mcp_abd",    -0.35, 0.35),
    JointDef(13, "ring_mcp_flex",    0.0,  1.92),
    JointDef(14, "ring_pip",         0.0,  1.92),
    JointDef(15, "ring_dip",         0.0,  1.57),
    # Pinky finger (3 DOF — no abduction)
    JointDef(16, "pinky_mcp_flex",   0.0,  1.92),
    JointDef(17, "pinky_pip",        0.0,  1.92),
    JointDef(18, "pinky_dip",        0.0,  1.57),
]

DEXROBOT_JOINTS = JointMap(_JOINTS)

FINGER_GROUPS = {
    "thumb": [0, 1, 2, 3],
    "index": [4, 5, 6, 7],
    "middle": [8, 9, 10, 11],
    "ring": [12, 13, 14, 15],
    "pinky": [16, 17, 18],
}

# Grasp presets (19 joint values in radians)
_GRASPS = {
    "open": [0.0] * 19,
    "close": [
        0.0, 1.40, 1.40, 1.22,        # thumb
        0.0, 1.57, 1.57, 1.40,        # index
        0.0, 1.57, 1.57, 1.40,        # middle
        0.0, 1.57, 1.57, 1.40,        # ring
        1.57, 1.57, 1.40,             # pinky
    ],
}

# Tactile sensor counts per finger (Pro model)
_TACTILE_COUNTS = {"thumb": 80, "index": 80, "middle": 80, "ring": 80, "pinky": 80, "palm": 40}


class DexRobotMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(DEXROBOT_JOINTS, **kw)
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

        # Tactile sensing
        if cmd == "tactile.get":
            finger = args.get("finger")
            if finger and finger not in _TACTILE_COUNTS:
                raise ValueError(f"unknown finger: {finger!r}; valid: {list(_TACTILE_COUNTS)}")
            if finger:
                count = _TACTILE_COUNTS[finger]
                return {
                    "finger": finger,
                    "sensors": count,
                    "values": [round(self._rng.uniform(0, 100), 1) for _ in range(count)],
                    **ts,
                }
            return {
                "fingers": {
                    f: {
                        "sensors": c,
                        "mean_pressure": round(self._rng.uniform(0, 50), 1),
                    }
                    for f, c in _TACTILE_COUNTS.items()
                },
                **ts,
            }

        # Forward kinematics
        if cmd == "fk":
            # Mock: return simulated fingertip poses based on current joint positions
            tips = {}
            for fname, indices in FINGER_GROUPS.items():
                # Simple mock: sum joint angles to estimate extension
                total_flex = sum(self._motors[i].q for i in indices)
                tips[fname] = {
                    "x": round(0.05 * math.cos(total_flex * 0.3), 4),
                    "y": round(0.02 * math.sin(total_flex * 0.2), 4),
                    "z": round(0.10 - 0.03 * total_flex / 3.14, 4),
                }
            return {"fingertips": tips, **ts}

        # Inverse kinematics
        if cmd == "ik":
            finger = args.get("finger", "index")
            x = args.get("x", 0.0)
            y = args.get("y", 0.0)
            z = args.get("z", 0.0)
            if finger not in FINGER_GROUPS:
                raise ValueError(f"unknown finger: {finger!r}; valid: {list(FINGER_GROUPS)}")
            indices = FINGER_GROUPS[finger]
            # Mock IK: generate plausible joint angles
            dist = math.sqrt(x*x + y*y + z*z)
            base_angle = min(1.57, max(0.0, dist * 10.0))
            joint_names = [self.joint_map.by_index[i].name for i in indices]
            angles = {
                joint_names[0]: round(math.atan2(y, x) * 0.3 if len(indices) == 4 else 0.0, 4),
            }
            for i, jn in enumerate(joint_names[1:] if len(indices) == 4 else joint_names):
                angles[jn] = round(base_angle * (0.8 ** i), 4)
            return {"finger": finger, "target": {"x": x, "y": y, "z": z}, "joints": angles, **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return DexRobotMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install pyzlg_dexhand dexrobot_kinematics, connect via USB-CAN"
    )
