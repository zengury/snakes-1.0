"""AGIBOT Genie G2 — 47 joints, gRPC control via genie_sim.

Joint data sourced from genie_sim/source/geniesim/utils/name_utils.py
and genie_sim/source/data_collection/config/robot_cfg/robot_joint_names.json
"""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase, SafetyError

# ── G2 Joint Map (47 joints from genie_sim) ──────────────────────────

_JOINTS = [
    # Body/Waist (5)
    JointDef(0, "body_joint1", -1.57, 1.57), JointDef(1, "body_joint2", -0.79, 0.79),
    JointDef(2, "body_joint3", -0.79, 0.79), JointDef(3, "body_joint4", -1.57, 1.57),
    JointDef(4, "body_joint5", -0.79, 0.79),
    # Head (3)
    JointDef(5, "head_joint1", -1.57, 1.57), JointDef(6, "head_joint2", -0.79, 0.79),
    JointDef(7, "head_joint3", -0.52, 0.52),
    # Left Arm (7)
    JointDef(8, "arm_l_joint1", -3.14, 3.14), JointDef(9, "arm_l_joint2", -2.09, 2.09),
    JointDef(10, "arm_l_joint3", -3.14, 3.14), JointDef(11, "arm_l_joint4", -2.44, 0.17),
    JointDef(12, "arm_l_joint5", -3.14, 3.14), JointDef(13, "arm_l_joint6", -1.57, 1.57),
    JointDef(14, "arm_l_joint7", -3.14, 3.14),
    # Right Arm (7)
    JointDef(15, "arm_r_joint1", -3.14, 3.14), JointDef(16, "arm_r_joint2", -2.09, 2.09),
    JointDef(17, "arm_r_joint3", -3.14, 3.14), JointDef(18, "arm_r_joint4", -2.44, 0.17),
    JointDef(19, "arm_r_joint5", -3.14, 3.14), JointDef(20, "arm_r_joint6", -1.57, 1.57),
    JointDef(21, "arm_r_joint7", -3.14, 3.14),
    # Left Gripper inner (4)
    JointDef(22, "gripper_l_inner1", -0.1, 1.2), JointDef(23, "gripper_l_inner3", -0.1, 1.2),
    JointDef(24, "gripper_l_inner4", -0.1, 1.2), JointDef(25, "gripper_l_inner0", -0.1, 1.2),
    # Left Gripper outer (4)
    JointDef(26, "gripper_l_outer1", -0.1, 1.2), JointDef(27, "gripper_l_outer3", -0.1, 1.2),
    JointDef(28, "gripper_l_outer4", -0.1, 1.2), JointDef(29, "gripper_l_outer0", -0.1, 1.2),
    # Right Gripper inner (4)
    JointDef(30, "gripper_r_inner1", -0.1, 1.2), JointDef(31, "gripper_r_inner3", -0.1, 1.2),
    JointDef(32, "gripper_r_inner4", -0.1, 1.2), JointDef(33, "gripper_r_inner0", -0.1, 1.2),
    # Right Gripper outer (4)
    JointDef(34, "gripper_r_outer1", -0.1, 1.2), JointDef(35, "gripper_r_outer3", -0.1, 1.2),
    JointDef(36, "gripper_r_outer4", -0.1, 1.2), JointDef(37, "gripper_r_outer0", -0.1, 1.2),
    # Wheels (8)
    JointDef(38, "lwheel_front1", -999, 999), JointDef(39, "lwheel_front2", -999, 999),
    JointDef(40, "lwheel_rear1", -999, 999), JointDef(41, "lwheel_rear2", -999, 999),
    JointDef(42, "rwheel_front1", -999, 999), JointDef(43, "rwheel_front2", -999, 999),
    JointDef(44, "rwheel_rear1", -999, 999), JointDef(45, "rwheel_rear2", -999, 999),
]

G2_JOINTS = JointMap(_JOINTS)

ARM_HOME = [0.0, -0.66, 0.0, -1.6, 0.0, -0.8, 0.0]  # rad

# Arm joint index ranges
ARM_L_RANGE = range(8, 15)   # indices 8-14
ARM_R_RANGE = range(15, 22)  # indices 15-21


class G2MockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(G2_JOINTS, **kw)
        self._gripper_l = 1.0  # open
        self._gripper_r = 1.0
        self._chassis_vx = 0.0
        self._chassis_vy = 0.0
        self._chassis_vyaw = 0.0
        self._recording = False

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        # Arm
        if cmd == "arm.joint-get":
            side = args.get("side", "both")
            r = ARM_L_RANGE if side == "left" else ARM_R_RANGE if side == "right" else list(ARM_L_RANGE) + list(ARM_R_RANGE)
            return [self.get_joint(i) for i in r]
        if cmd == "arm.joint-set":
            side = args["side"]
            positions = args["positions"]
            r = ARM_L_RANGE if side == "left" else ARM_R_RANGE
            results = []
            for i, q in zip(r, positions):
                results.append(self.set_joint(i, q))
            return results
        if cmd == "arm.ee-pose":
            return {"side": args.get("side", "left"), "x": 0.4, "y": 0.2, "z": 0.8,
                    "qw": 1, "qx": 0, "qy": 0, "qz": 0, **self._ts()}
        if cmd == "arm.moveto":
            return {"action": "moveto", **args, **self._ts()}
        if cmd == "arm.ik-check":
            return {"feasible": True, **args, **self._ts()}
        if cmd == "arm.trajectory":
            return {"action": "trajectory", "file": args.get("file"), **self._ts()}

        # Gripper
        if cmd == "gripper.open":
            side = args.get("side", "left")
            w = args.get("width", 1.0)
            if side == "left": self._gripper_l = w
            else: self._gripper_r = w
            return {"side": side, "width": w, **self._ts()}
        if cmd == "gripper.close":
            side = args.get("side", "left")
            f = args.get("force", 0.5)
            if side == "left": self._gripper_l = 0.0
            else: self._gripper_r = 0.0
            return {"side": side, "force": f, **self._ts()}
        if cmd == "gripper.get":
            side = args.get("side", "left")
            w = self._gripper_l if side == "left" else self._gripper_r
            return {"side": side, "width": w, **self._ts()}

        # Waist
        if cmd == "waist.set":
            for k, v in args.items():
                if k.startswith("j"):
                    idx = int(k[1]) - 1  # j1 → index 0
                    self.set_joint(idx, float(v))
            return {"action": "waist_set", **self._ts()}
        if cmd == "waist.get":
            return [self.get_joint(i) for i in range(5)]

        # Head
        if cmd == "head.set":
            for k, v in args.items():
                if k.startswith("j"):
                    idx = 5 + int(k[1]) - 1
                    self.set_joint(idx, float(v))
            return {"action": "head_set", **self._ts()}
        if cmd == "head.get":
            return [self.get_joint(i) for i in range(5, 8)]

        # Chassis
        if cmd == "chassis.move":
            self._chassis_vx = args.get("vx", 0)
            self._chassis_vy = args.get("vy", 0)
            self._chassis_vyaw = args.get("vyaw", 0)
            return {"vx": self._chassis_vx, "vy": self._chassis_vy,
                    "vyaw": self._chassis_vyaw, **self._ts()}
        if cmd == "chassis.stop":
            self._chassis_vx = self._chassis_vy = self._chassis_vyaw = 0
            return {"action": "stop", **self._ts()}

        # Recording
        if cmd == "record.start":
            self._recording = True
            return {"recording": True, **self._ts()}
        if cmd == "record.stop":
            self._recording = False
            return {"recording": False, **self._ts()}

        raise ValueError(f"unknown command: {cmd!r}")


def get_client(backend: str = "mock", **kw) -> G2MockClient:
    if backend == "mock":
        return G2MockClient(**kw)
    raise NotImplementedError(
        "RealClient: pip install genie_sim, then wrap RpcClient from "
        "genie_sim/source/data_collection/client/robot/client.py"
    )
