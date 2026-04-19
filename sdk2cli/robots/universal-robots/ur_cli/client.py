"""Universal Robots UR — 6 DOF cobot, RTDE protocol via ur_rtde SDK at 500Hz."""
from __future__ import annotations
import math
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

_JOINTS = [
    JointDef(0, "base",    -6.28, 6.28),
    JointDef(1, "shoulder", -6.28, 6.28),
    JointDef(2, "elbow",   -3.14, 3.14),
    JointDef(3, "wrist1",  -6.28, 6.28),
    JointDef(4, "wrist2",  -6.28, 6.28),
    JointDef(5, "wrist3",  -6.28, 6.28),
]

UR_JOINTS = JointMap(_JOINTS)

# Robot mode constants (matching UR controller)
ROBOT_MODES = {
    -1: "NO_CONTROLLER",
    0: "DISCONNECTED",
    1: "CONFIRM_SAFETY",
    2: "BOOTING",
    3: "POWER_OFF",
    4: "POWER_ON",
    5: "IDLE",
    6: "BACKDRIVE",
    7: "RUNNING",
}

UR_MODELS = ("UR3", "UR3e", "UR5", "UR5e", "UR10", "UR10e", "UR16e", "UR20", "UR30")


class URMockClient(MockClientBase):
    name = "mock"

    def __init__(self, model: str = "UR5e", **kw):
        super().__init__(UR_JOINTS, **kw)
        self._model = model
        self._robot_mode = 7  # RUNNING
        self._tcp_pose = [0.0, 0.0, 0.5, 0.0, 0.0, 0.0]  # x,y,z,rx,ry,rz
        self._tcp_force = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self._teach_mode = False
        self._freedrive = False
        self._joint_temps = [25.0] * 6

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Move commands
        if cmd == "move-joint":
            joints = args.get("joints", [0.0] * 6)
            speed = args.get("speed", 1.05)
            accel = args.get("accel", 1.4)
            for i, q in enumerate(joints):
                jd = self.joint_map.by_index[i]
                self.joint_map.validate_position(jd, q)
                self._motors[i].q = q
            return {"action": "moveJ", "joints": joints, "speed": speed, "accel": accel, **ts}

        if cmd == "move-line":
            pose = args.get("pose", [0.0] * 6)
            speed = args.get("speed", 0.25)
            accel = args.get("accel", 1.2)
            self._tcp_pose = list(pose)
            return {"action": "moveL", "pose": pose, "speed": speed, "accel": accel, **ts}

        if cmd == "servo-joint":
            joints = args.get("joints", [0.0] * 6)
            for i, q in enumerate(joints):
                jd = self.joint_map.by_index[i]
                self.joint_map.validate_position(jd, q)
                self._motors[i].q = q
            return {"action": "servoJ", "joints": joints, **ts}

        if cmd == "speed-joint":
            speeds = args.get("speeds", [0.0] * 6)
            accel = args.get("accel", 0.5)
            return {"action": "speedJ", "speeds": speeds, "accel": accel, **ts}

        if cmd == "force-mode":
            task_frame = args.get("task_frame", [0.0] * 6)
            selection = args.get("selection", [0, 0, 1, 0, 0, 0])
            wrench = args.get("wrench", [0.0, 0.0, 20.0, 0.0, 0.0, 0.0])
            f_type = args.get("type", 2)
            limits = args.get("limits", [2.0, 2.0, 1.5, 1.0, 1.0, 1.0])
            return {"action": "forceMode", "task_frame": task_frame,
                    "selection": selection, "wrench": wrench,
                    "type": f_type, "limits": limits, **ts}

        if cmd == "teach-mode":
            state = args.get("state", "on")
            self._teach_mode = (state == "on")
            return {"teach_mode": self._teach_mode, **ts}

        if cmd == "freedrive":
            state = args.get("state", "on")
            self._freedrive = (state == "on")
            return {"freedrive": self._freedrive, **ts}

        # Query commands
        if cmd == "get-pose":
            return {"tcp_pose": self._tcp_pose, "labels": ["x", "y", "z", "rx", "ry", "rz"], **ts}

        if cmd == "get-force":
            return {"tcp_force": self._tcp_force, "labels": ["fx", "fy", "fz", "tx", "ty", "tz"], **ts}

        if cmd == "get-mode":
            mode_id = self._robot_mode
            return {"mode_id": mode_id, "mode": ROBOT_MODES.get(mode_id, "UNKNOWN"),
                    "model": self._model, "teach_mode": self._teach_mode,
                    "freedrive": self._freedrive, **ts}

        if cmd == "get-temps":
            temps = [t + self._rng.uniform(-0.5, 0.5) for t in self._joint_temps]
            return {"temperatures": [round(t, 1) for t in temps],
                    "joint_names": UR_JOINTS.all_names(), **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock":
        return URMockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install ur_rtde, wrap RTDEControlInterface + RTDEReceiveInterface"
    )
