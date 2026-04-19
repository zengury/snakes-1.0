"""Fourier GR-1 humanoid — 40 DOF (29 body + 11 hand), WebSocket + HTTP via rocs_client_py."""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

# ── Body joints (motors 0-17) ───────────────────────────────────────
# The GR-1 has 29 body DOF across head, waist, arms, and legs.
# Motor numbers 0-17 cover the primary actuated joints.
_BODY_JOINTS = [
    # Head (3 DOF)
    JointDef(0,  "head_roll",   -0.50,  0.50),
    JointDef(1,  "head_pitch",  -0.60,  0.50),
    JointDef(2,  "head_yaw",    -1.20,  1.20),
    # Waist (3 DOF)
    JointDef(3,  "waist_yaw",   -0.80,  0.80),
    JointDef(4,  "waist_roll",  -0.30,  0.30),
    JointDef(5,  "waist_pitch", -0.50,  0.50),
    # Left arm (6 DOF)
    JointDef(6,  "l_shoulder_pitch", -3.14, 2.09),
    JointDef(7,  "l_shoulder_roll",  -0.50, 2.87),
    JointDef(8,  "l_shoulder_yaw",   -2.87, 2.87),
    JointDef(9,  "l_elbow_pitch",    -2.09, 0.00),
    JointDef(10, "l_wrist_yaw",      -1.57, 1.57),
    JointDef(11, "l_wrist_roll",     -1.57, 1.57),
    # Right arm (6 DOF)
    JointDef(12, "r_shoulder_pitch", -3.14, 2.09),
    JointDef(13, "r_shoulder_roll",  -2.87, 0.50),
    JointDef(14, "r_shoulder_yaw",   -2.87, 2.87),
    JointDef(15, "r_elbow_pitch",     0.00, 2.09),
    JointDef(16, "r_wrist_yaw",      -1.57, 1.57),
    JointDef(17, "r_wrist_roll",     -1.57, 1.57),
]

# ── Leg joints (motors 18-29, 6 per leg) ────────────────────────────
_LEG_JOINTS = [
    # Left leg (6 DOF)
    JointDef(18, "l_hip_yaw",    -0.60,  0.60),
    JointDef(19, "l_hip_roll",   -0.35,  0.70),
    JointDef(20, "l_hip_pitch",  -1.40,  1.40),
    JointDef(21, "l_knee_pitch", -0.10,  2.50),
    JointDef(22, "l_ankle_pitch",-0.80,  0.50),
    JointDef(23, "l_ankle_roll", -0.30,  0.30),
    # Right leg (6 DOF)
    JointDef(24, "r_hip_yaw",    -0.60,  0.60),
    JointDef(25, "r_hip_roll",   -0.70,  0.35),
    JointDef(26, "r_hip_pitch",  -1.40,  1.40),
    JointDef(27, "r_knee_pitch", -0.10,  2.50),
    JointDef(28, "r_ankle_pitch",-0.80,  0.50),
    JointDef(29, "r_ankle_roll", -0.30,  0.30),
]

# ── Hand / finger joints (motors 30-40) ─────────────────────────────
# 11 finger DOF across both hands (6 left, 5 right).
_HAND_JOINTS = [
    JointDef(30, "l_thumb_bend",    0.0, 1.57),
    JointDef(31, "l_thumb_rotate",  0.0, 1.57),
    JointDef(32, "l_index_bend",    0.0, 1.57),
    JointDef(33, "l_middle_bend",   0.0, 1.57),
    JointDef(34, "l_ring_bend",     0.0, 1.57),
    JointDef(35, "l_pinky_bend",    0.0, 1.57),
    JointDef(36, "r_thumb_bend",    0.0, 1.57),
    JointDef(37, "r_thumb_rotate",  0.0, 1.57),
    JointDef(38, "r_index_bend",    0.0, 1.57),
    JointDef(39, "r_middle_bend",   0.0, 1.57),
    JointDef(40, "r_ring_pinky_bend", 0.0, 1.57),
]

GR1_JOINTS = JointMap(_BODY_JOINTS + _LEG_JOINTS + _HAND_JOINTS)

# Predefined upper-body actions from the rocs_client SDK
ARM_ACTIONS = ["LEFT_ARM_WAVE", "TWO_ARMS_WAVE", "ARMS_SWING", "HELLO"]
HAND_ACTIONS = ["TREMBLE", "GRASP", "PINCH", "OPEN"]


class GR1MockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(GR1_JOINTS, **kw)
        self._started = False
        self._standing = False
        self._walking = False
        self._motors_enabled = False

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # ── Lifecycle ────────────────────────────────────────────
        if cmd == "start":
            self._started = True
            return {"started": True, **ts}
        if cmd == "exit":
            self._started = False; self._standing = False; self._walking = False
            return {"started": False, **ts}

        # ── Motor enable / disable ───────────────────────────────
        if cmd == "motor.enable":
            self._motors_enabled = True
            return {"motors_enabled": True, **ts}
        if cmd == "motor.disable":
            self._motors_enabled = False
            return {"motors_enabled": False, **ts}
        if cmd == "motor.move":
            no = args.get("no", 0)
            angle = args.get("angle", 0.0)
            orientation = args.get("orientation", "left")
            return {"motor": no, "angle": angle, "orientation": orientation, **ts}
        if cmd == "motor.get_pvc":
            no = args.get("no", 0)
            orientation = args.get("orientation", "left")
            m = self._motors.get(no)
            return {
                "motor": no, "orientation": orientation,
                "position": round(m.q, 4) if m else 0.0,
                "velocity": round(m.dq, 4) if m else 0.0,
                "current": round(m.tau_est, 3) if m else 0.0,
                **ts,
            }

        # ── Posture ──────────────────────────────────────────────
        if cmd == "stand":
            self._standing = True; self._walking = False
            return {"standing": True, **ts}

        # ── Locomotion ───────────────────────────────────────────
        if cmd == "walk":
            self._walking = True; self._standing = False
            angle = args.get("angle", 0.0)
            speed = args.get("speed", 0.5)
            return {"walking": True, "angle": angle, "speed": speed, **ts}

        # ── Head control ─────────────────────────────────────────
        if cmd == "head":
            return {
                "roll": args.get("roll", 0.0),
                "pitch": args.get("pitch", 0.0),
                "yaw": args.get("yaw", 0.0),
                **ts,
            }

        # ── Upper body actions ───────────────────────────────────
        if cmd == "upper_body":
            arm_action = args.get("arm_action", "NONE")
            hand_action = args.get("hand_action", "NONE")
            return {"arm_action": arm_action, "hand_action": hand_action, **ts}

        # ── State / status ───────────────────────────────────────
        if cmd == "state":
            return {
                "started": self._started,
                "standing": self._standing,
                "walking": self._walking,
                "motors_enabled": self._motors_enabled,
                "dof_total": GR1_JOINTS.count,
                **ts,
            }

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return GR1MockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install rocs_client, wrap rocs_client.Human(host)"
    )
