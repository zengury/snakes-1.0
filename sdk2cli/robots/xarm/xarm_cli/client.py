"""UFACTORY xArm — 5/6/7 DOF robotic arm, TCP/IP via xArm-Python-SDK."""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

# xArm7 joint definitions (radians, converted from degree limits)
_JOINTS_XARM7 = [
    # J1: +/-360 deg
    JointDef(0, "J1", -6.2832, 6.2832),
    # J2: -118 ~ +120 deg
    JointDef(1, "J2", -2.0595, 2.0944),
    # J3: +/-360 deg
    JointDef(2, "J3", -6.2832, 6.2832),
    # J4: -11 ~ +225 deg
    JointDef(3, "J4", -0.1920, 3.9270),
    # J5: +/-360 deg
    JointDef(4, "J5", -6.2832, 6.2832),
    # J6: -97 ~ +180 deg
    JointDef(5, "J6", -1.6930, 3.1416),
    # J7: +/-360 deg
    JointDef(6, "J7", -6.2832, 6.2832),
]

XARM7_JOINTS = JointMap(_JOINTS_XARM7)


class XArmMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(XARM7_JOINTS, **kw)
        self._state = 4          # 0=enabled, 3=paused, 4=stopped
        self._mode = 0           # 0=position, 1=servo, 2=joint_vel, 4=cart_vel
        self._error_code = 0
        self._warn_code = 0
        self._gripper_enabled = False
        self._gripper_pos = 850.0
        self._gripper_speed = 5000.0
        self._tcp_load = {"weight": 0.0, "center": [0.0, 0.0, 0.0]}
        self._tcp_offset = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self._collision_sensitivity = 3
        self._position = [206.0, 0.0, 120.5, 3.1416, 0.0, 0.0]  # x,y,z,roll,pitch,yaw

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # ── State / Enable / Disable ────────────────────────────────
        if cmd == "get_state":
            return {"state": self._state, "mode": self._mode,
                    "error_code": self._error_code, "warn_code": self._warn_code, **ts}
        if cmd == "set_state":
            self._state = int(args.get("state", 0))
            return {"state": self._state, **ts}
        if cmd == "set_mode":
            self._mode = int(args.get("mode", 0))
            return {"mode": self._mode, **ts}
        if cmd == "enable":
            self._state = 0
            return {"state": 0, "enabled": True, **ts}

        # ── Safety ──────────────────────────────────────────────────
        if cmd == "emergency_stop":
            self._state = 4
            return {"state": 4, "action": "emergency_stop", **ts}
        if cmd == "clean_error":
            self._error_code = 0; return {"error_code": 0, **ts}
        if cmd == "clean_warn":
            self._warn_code = 0; return {"warn_code": 0, **ts}

        # ── Motion ──────────────────────────────────────────────────
        if cmd == "move_joint":
            angles = args.get("angles", [])
            return {"action": "move_joint", "angles": angles, **ts}
        if cmd == "move_line":
            pose = args.get("pose", [])
            return {"action": "move_line", "pose": pose, **ts}
        if cmd == "move_arc_line":
            pose = args.get("pose", [])
            return {"action": "move_arc_line", "pose": pose, **ts}
        if cmd == "move_circle":
            return {"action": "move_circle", **args, **ts}
        if cmd == "move_gohome":
            return {"action": "move_gohome", **ts}

        # ── Servo control ───────────────────────────────────────────
        if cmd == "set_servo_angle":
            sid = args.get("servo_id"); angle = args.get("angle")
            return {"action": "set_servo_angle", "servo_id": sid, "angle": angle, **ts}
        if cmd == "set_servo_cartesian":
            pose = args.get("pose", [])
            return {"action": "set_servo_cartesian", "pose": pose, **ts}

        # ── Velocity control ────────────────────────────────────────
        if cmd == "vc_set_joint_velocity":
            speeds = args.get("speeds", [])
            return {"action": "vc_set_joint_velocity", "speeds": speeds, **ts}
        if cmd == "vc_set_cartesian_velocity":
            speeds = args.get("speeds", [])
            return {"action": "vc_set_cartesian_velocity", "speeds": speeds, **ts}

        # ── Position queries ────────────────────────────────────────
        if cmd == "get_position":
            return {"position": self._position, **ts}
        if cmd == "get_servo_angle":
            return {"angles": [round(self._motors[i].q, 4) for i in range(self.joint_map.count)], **ts}

        # ── TCP config ──────────────────────────────────────────────
        if cmd == "set_tcp_load":
            self._tcp_load = {"weight": args.get("weight", 0), "center": args.get("center", [0, 0, 0])}
            return {"tcp_load": self._tcp_load, **ts}
        if cmd == "set_tcp_offset":
            self._tcp_offset = args.get("offset", [0]*6)
            return {"tcp_offset": self._tcp_offset, **ts}
        if cmd == "set_collision_sensitivity":
            self._collision_sensitivity = int(args.get("level", 3))
            return {"collision_sensitivity": self._collision_sensitivity, **ts}

        # ── Gripper ─────────────────────────────────────────────────
        if cmd == "gripper.enable":
            self._gripper_enabled = bool(args.get("on", True))
            return {"gripper_enabled": self._gripper_enabled, **ts}
        if cmd == "gripper.position":
            self._gripper_pos = float(args.get("pos", 850))
            return {"gripper_position": self._gripper_pos, **ts}
        if cmd == "gripper.speed":
            self._gripper_speed = float(args.get("speed", 5000))
            return {"gripper_speed": self._gripper_speed, **ts}
        if cmd == "gripper.get":
            return {"gripper_enabled": self._gripper_enabled,
                    "gripper_position": self._gripper_pos,
                    "gripper_speed": self._gripper_speed, **ts}

        # ── I/O ─────────────────────────────────────────────────────
        if cmd == "tgpio.set_digital":
            return {"ionum": args.get("ionum"), "value": args.get("value"), **ts}
        if cmd == "tgpio.get_digital":
            return {"io0": 0, "io1": 0, **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return XArmMockClient(**kw)
    raise NotImplementedError("RealClient: pip install xArm-Python-SDK, wrap xarm.wrapper.XArmAPI")
