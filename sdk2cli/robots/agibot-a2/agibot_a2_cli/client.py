"""AGIBOT Expedition A2 — AimDK SDK client.

Real backend uses HTTP/JSON RPC to 192.168.100.100:56322 and ROS2 pub/sub.
Joint data from https://github.com/zengury/sdks analysis.
"""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase, SafetyError

# ── A2 Joint Map ──────────────────────────────────────────────────────

_ARM_JOINTS = [
    JointDef(0,  "left_arm_joint1",  -3.14, 3.14, 80, 2),   # L shoulder pitch
    JointDef(1,  "left_arm_joint2",  -1.57, 2.62, 80, 2),   # L shoulder roll
    JointDef(2,  "left_arm_joint3",  -3.14, 3.14, 60, 1),   # L shoulder yaw
    JointDef(3,  "left_arm_joint4",  -2.09, 0.17, 60, 1),   # L elbow pitch
    JointDef(4,  "left_arm_joint5",  -3.14, 3.14, 40, 1),   # L wrist roll
    JointDef(5,  "left_arm_joint6",  -1.57, 1.57, 40, 1),   # L wrist pitch
    JointDef(6,  "left_arm_joint7",  -1.57, 1.57, 40, 1),   # L wrist yaw
    JointDef(7,  "right_arm_joint1", -3.14, 3.14, 80, 2),   # R shoulder pitch
    JointDef(8,  "right_arm_joint2", -2.62, 1.57, 80, 2),   # R shoulder roll
    JointDef(9,  "right_arm_joint3", -3.14, 3.14, 60, 1),   # R shoulder yaw
    JointDef(10, "right_arm_joint4", -2.09, 0.17, 60, 1),   # R elbow pitch
    JointDef(11, "right_arm_joint5", -3.14, 3.14, 40, 1),   # R wrist roll
    JointDef(12, "right_arm_joint6", -1.57, 1.57, 40, 1),   # R wrist pitch
    JointDef(13, "right_arm_joint7", -1.57, 1.57, 40, 1),   # R wrist yaw
    # Head (2 DOF)
    JointDef(14, "head_yaw",   -0.785, 0.785, 20, 0.5),     # ±45°
    JointDef(15, "head_pitch", -0.401, 0.401, 20, 0.5),     # ±23°
]

A2_JOINTS = JointMap(_ARM_JOINTS)

# Hand finger names (not in JointMap — separate position units 0-2000)
HAND_FINGERS = ["thumb_swing", "thumb_curl", "index", "middle", "ring", "pinky"]

ARM_HOME_L = [0.0, 1.2, 0.0, -0.5, 1.5, 0.0, 0.0]
ARM_HOME_R = [0.0, -1.2, 0.0, 0.5, 1.5, 0.0, 0.0]

ACTION_MODES = {
    "locomotion":    "McAction_RL_LOCOMOTION_DEFAULT",
    "arm-servo":     "McAction_RL_LOCOMOTION_ARM_EXT_JOINT_SERVO",
    "arm-planning":  "McAction_RL_LOCOMOTION_ARM_EXT_PLANNING_MOVE",
    "whole-body":    "McAction_RL_WHOLE_BODY_EXT_JOINT_SERVO",
}

GAITS = ["stance", "walk", "smart-walk", "terrain", "run", "jump", "hop"]
GESTURES = ["pinch", "grip", "point", "thumbs-up", "fist", "open"]
CAMERAS = ["head-rgb", "head-depth", "hip-rgb", "hip-depth",
           "chest-left", "chest-right", "interactive"]

GESTURE_POSITIONS = {
    "open":      [0, 0, 0, 0, 0, 0],
    "fist":      [2000, 2000, 2000, 2000, 2000, 2000],
    "grip":      [1500, 1800, 1800, 1800, 1800, 1800],
    "pinch":     [1200, 1500, 1500, 0, 0, 0],
    "point":     [0, 0, 0, 2000, 2000, 2000],
    "thumbs-up": [0, 0, 2000, 2000, 2000, 2000],
}


class A2MockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(A2_JOINTS, **kw)
        self._action = "locomotion"
        self._gait = "stance"
        self._hand_l = [0] * 6
        self._hand_r = [0] * 6
        self._waist = {"z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self._walking = False

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Action
        if cmd == "action.set":
            mode = args["mode"]
            if mode not in ACTION_MODES:
                raise SafetyError(f"unknown action mode: {mode}. Valid: {list(ACTION_MODES)}")
            self._action = mode
            return {"action": ACTION_MODES[mode], "mode": mode, **ts}
        if cmd == "action.get":
            return {"mode": self._action, "action": ACTION_MODES.get(self._action, self._action), **ts}
        if cmd == "action.list":
            return {"modes": ACTION_MODES, **ts}

        # Walk
        if cmd == "walk":
            self._walking = True
            return {"forward": args.get("forward", 0), "lateral": args.get("lateral", 0),
                    "angular": args.get("angular", 0), "mode": args.get("mode", "default"), **ts}
        if cmd == "walk.stop":
            self._walking = False
            return {"forward": 0, "lateral": 0, "angular": 0, **ts}
        if cmd == "gait.set":
            t = args["type"]
            if t not in GAITS:
                raise SafetyError(f"unknown gait: {t}. Valid: {GAITS}")
            self._gait = t
            return {"gait": t, **ts}
        if cmd == "gait.get":
            return {"gait": self._gait, **ts}
        if cmd == "stand":
            self._walking = False
            return {"action": "stand", **ts}

        # Arm
        if cmd == "arm.joint-set":
            positions = args.get("positions", ARM_HOME_L + ARM_HOME_R)
            for i, q in enumerate(positions[:14]):
                self.set_joint(i, q)
            return {"joints": 14, "positions": positions[:14], **ts}
        if cmd == "arm.joint-get":
            return [self.get_joint(i) for i in range(14)]
        if cmd == "arm.home":
            for i, q in enumerate(ARM_HOME_L + ARM_HOME_R):
                self._motors[i].q = q
            return {"action": "home", "left": ARM_HOME_L, "right": ARM_HOME_R, **ts}
        if cmd == "arm.move-joint":
            return {"action": "joint_move", "group": args.get("group", "both"), **ts}
        if cmd == "arm.move-linear":
            return {"action": "linear_move", **args, **ts}
        if cmd == "arm.plan":
            return {"action": "planning_move", "feasible": True, **args, **ts}
        if cmd == "arm.interact":
            return {"action": "interact", "type": args.get("type", "handshake"), **ts}
        if cmd == "arm.tcp-get":
            return {"left": {"x": 0.35, "y": 0.2, "z": 0.9, "qw": 1, "qx": 0, "qy": 0, "qz": 0},
                    "right": {"x": 0.35, "y": -0.2, "z": 0.9, "qw": 1, "qx": 0, "qy": 0, "qz": 0}, **ts}
        if cmd == "arm.fk":
            return {"pose": {"x": 0.4, "y": 0.2, "z": 0.8, "qw": 1, "qx": 0, "qy": 0, "qz": 0}, **ts}
        if cmd == "arm.ik":
            return {"angles": [0.0] * 7, "feasible": True, **ts}

        # Hand
        if cmd == "hand.set":
            side = args.get("side", "left")
            positions = [args.get(f, 0) for f in ["thumb0", "thumb1", "index", "middle", "ring", "pinky"]]
            if side in ("left", "both"):
                self._hand_l = positions
            if side in ("right", "both"):
                self._hand_r = positions
            return {"side": side, "positions": positions, **ts}
        if cmd == "hand.get":
            side = args.get("side", "both")
            r = {}
            if side in ("left", "both"):
                r["left"] = dict(zip(HAND_FINGERS, self._hand_l))
            if side in ("right", "both"):
                r["right"] = dict(zip(HAND_FINGERS, self._hand_r))
            return {**r, **ts}
        if cmd == "hand.open":
            side = args.get("side", "both")
            if side in ("left", "both"): self._hand_l = [0] * 6
            if side in ("right", "both"): self._hand_r = [0] * 6
            return {"side": side, "positions": [0] * 6, **ts}
        if cmd == "hand.close":
            side = args.get("side", "both")
            f = args.get("force", 2000)
            pos = [f] * 6
            if side in ("left", "both"): self._hand_l = pos
            if side in ("right", "both"): self._hand_r = pos
            return {"side": side, "positions": pos, **ts}
        if cmd == "hand.gesture":
            name = args.get("name", "open")
            if name not in GESTURE_POSITIONS:
                raise SafetyError(f"unknown gesture: {name}. Valid: {list(GESTURE_POSITIONS)}")
            pos = GESTURE_POSITIONS[name]
            side = args.get("side", "both")
            if side in ("left", "both"): self._hand_l = list(pos)
            if side in ("right", "both"): self._hand_r = list(pos)
            return {"gesture": name, "side": side, "positions": pos, **ts}

        # Head
        if cmd == "head.set":
            yaw = args.get("yaw", 0.0)
            pitch = args.get("pitch", 0.0)
            if not (-0.785 <= yaw <= 0.785):
                raise SafetyError(f"head yaw {yaw} out of range [-0.785, 0.785]")
            if not (-0.401 <= pitch <= 0.401):
                raise SafetyError(f"head pitch {pitch} out of range [-0.401, 0.401]")
            self._motors[14].q = yaw
            self._motors[15].q = pitch
            return {"yaw": yaw, "pitch": pitch, **ts}
        if cmd == "head.get":
            return {"yaw": self._motors[14].q, "pitch": self._motors[15].q, **ts}
        if cmd == "head.shake":
            return {"action": "shake", **ts}
        if cmd == "head.nod":
            return {"action": "nod", **ts}

        # Waist
        if cmd == "waist.set":
            for k in ("z", "roll", "pitch", "yaw"):
                if k in args:
                    v = float(args[k])
                    if k == "z" and not (-0.15 <= v <= 0.04):
                        raise SafetyError(f"waist z={v} out of range [-0.15, 0.04]")
                    if k in ("roll", "pitch", "yaw") and not (-0.5236 <= v <= 0.5236):
                        raise SafetyError(f"waist {k}={v} out of range [-0.5236, 0.5236]")
                    self._waist[k] = v
            return {**self._waist, **ts}
        if cmd == "waist.get":
            return {**self._waist, **ts}
        if cmd == "waist.lift":
            z = float(args["z"])
            if not (-0.15 <= z <= 0.04):
                raise SafetyError(f"waist z={z} out of range [-0.15, 0.04]")
            self._waist["z"] = z
            return {"z": z, **ts}

        # Sensors
        if cmd == "imu.get":
            r = self._rng
            return {"orientation": {"w": 1, "x": 0, "y": 0, "z": 0},
                    "gyro": [round(r.gauss(0, 0.005), 4) for _ in range(3)],
                    "accel": [round(r.gauss(0, 0.02), 4), round(r.gauss(0, 0.02), 4),
                              round(9.81 + r.gauss(0, 0.02), 4)], **ts}
        if cmd == "camera.list":
            return {"cameras": CAMERAS}
        if cmd == "camera.get":
            return {"source": args.get("source"), "bytes": 0, "note": "mock: no image data", **ts}
        if cmd == "lidar.get":
            return {"points": 0, "note": "mock: no lidar data", **ts}

        # Dance
        if cmd == "dance.list":
            return {"dances": ["wave_dance", "tai_chi", "robot_dance", "greeting"], **ts}
        if cmd == "dance.play":
            return {"action": "dance", "name": args.get("name"), **ts}
        if cmd == "dance.stop":
            return {"action": "dance_stop", **ts}

        # Safety
        if cmd == "safe-stop":
            self._walking = False
            return {"action": "safe_stop", "emergency": True, **ts}
        if cmd == "collision.detect":
            return {"collision": False, **ts}
        if cmd == "collision.predict":
            return {"collision": False, "feasible": True, **args, **ts}

        # Joint params
        if cmd == "joint.params":
            return [{"name": j.name, "lo": j.lo, "hi": j.hi} for j in A2_JOINTS.joints]

        raise ValueError(f"unknown command: {cmd!r}")


def get_client(backend: str = "mock", **kw):
    if backend == "mock":
        return A2MockClient(**kw)
    raise NotImplementedError(
        "RealClient: install a2_aimdk (pip install -e protocol/protobuf/), "
        "then use HTTP RPC to http://192.168.100.100:56322/rpc/ "
        "and ROS2 pub/sub on /motion/control/ topics. "
        "See https://github.com/zengury/sdks/tree/main/examples/mc/"
    )
