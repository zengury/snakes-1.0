"""AGIBOT Lingxi X2 — Pure ROS2 SDK client.

31 joints with exact limits from SDK source. Real backend uses rclpy
to pub/sub on /aima/hal/joint/ topics and call aimdk_msgs services.
"""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase, SafetyError

# ── X2 Joint Map (31 DOF from motocontrol.py) ────────────────────────

_JOINTS = [
    # Legs (12)
    JointDef(0,  "left_hip_pitch",    -2.704, 2.556, 40, 4),
    JointDef(1,  "left_hip_roll",     -0.235, 2.906, 40, 4),
    JointDef(2,  "left_hip_yaw",      -1.684, 3.430, 30, 3),
    JointDef(3,  "left_knee",          0.000, 2.407, 80, 8),
    JointDef(4,  "left_ankle_pitch",  -0.803, 0.453, 40, 4),
    JointDef(5,  "left_ankle_roll",   -0.263, 0.263, 20, 2),
    JointDef(6,  "right_hip_pitch",   -2.704, 2.556, 40, 4),
    JointDef(7,  "right_hip_roll",    -2.906, 0.235, 40, 4),
    JointDef(8,  "right_hip_yaw",     -3.430, 1.684, 30, 3),
    JointDef(9,  "right_knee",         0.000, 2.407, 80, 8),
    JointDef(10, "right_ankle_pitch", -0.803, 0.453, 40, 4),
    JointDef(11, "right_ankle_roll",  -0.263, 0.263, 20, 2),
    # Waist (3)
    JointDef(12, "waist_yaw",         -3.430, 2.382, 20, 4),
    JointDef(13, "waist_pitch",       -0.314, 0.314, 20, 4),
    JointDef(14, "waist_roll",        -0.488, 0.488, 20, 4),
    # Left Arm (7)
    JointDef(15, "left_shoulder_pitch",  -3.080, 2.040, 20, 2),
    JointDef(16, "left_shoulder_roll",   -0.061, 2.993, 20, 2),
    JointDef(17, "left_shoulder_yaw",    -2.556, 2.556, 20, 2),
    JointDef(18, "left_elbow",           -2.356, 0.000, 20, 2),
    JointDef(19, "left_wrist_yaw",       -2.556, 2.556, 20, 2),
    JointDef(20, "left_wrist_pitch",     -0.558, 0.558, 20, 2),
    JointDef(21, "left_wrist_roll",      -1.571, 0.724, 20, 2),
    # Right Arm (7)
    JointDef(22, "right_shoulder_pitch", -3.080, 2.040, 20, 2),
    JointDef(23, "right_shoulder_roll",  -2.993, 0.061, 20, 2),
    JointDef(24, "right_shoulder_yaw",   -2.556, 2.556, 20, 2),
    JointDef(25, "right_elbow",          -2.356, 0.000, 20, 2),
    JointDef(26, "right_wrist_yaw",      -2.556, 2.556, 20, 2),
    JointDef(27, "right_wrist_pitch",    -0.558, 0.558, 20, 2),
    JointDef(28, "right_wrist_roll",     -0.724, 1.571, 20, 2),
    # Head (2)
    JointDef(29, "head_yaw",            -0.366, 0.366, 20, 2),
    JointDef(30, "head_pitch",          -0.384, 0.384, 20, 2),
]

X2_JOINTS = JointMap(_JOINTS)

ACTION_MODES = {
    "PASSIVE_DEFAULT": 1, "SOFT_EMERGENCY_STOP": 2, "DAMPING_DEFAULT": 3,
    "ZERO_TORQUE_DEFAULT": 4, "JOINT_DEFAULT": 100, "JOINT_FREEZE": 101,
    "STAND_DEFAULT": 200, "STAND_BODY_CONTROL": 201,
    "LOCOMOTION_DEFAULT": 300, "RUN_DEFAULT": 301, "LOCOMOTION_STEP": 302,
    "VR_REMOTE_CONTROLLER": 400,
    "SIT_DOWN_DEFAULT": 2000, "CROUCH_DOWN_DEFAULT": 2002,
    "LIE_DOWN_DEFAULT": 2004, "STAND_UP_DEFAULT": 2005,
    "ASCEND_STAIRS": 2006, "DESCEND_STAIRS": 2008,
}

PRESET_MOTIONS = {
    1001: "raise-hand", 1002: "wave", 1003: "handshake", 1004: "blow-kiss",
    1007: "heart", 1008: "high-five", 1010: "raise-both", 1013: "salute",
    3001: "bow", 3002: "thumbs-up", 3003: "peace", 3007: "light-wave",
    3008: "hug", 3009: "cross-arms", 3011: "cheer", 3017: "clap",
    3024: "scratch-head", 3031: "wave-goodbye",
    4001: "nod-head", 4002: "shake-head",
}

CAMERAS = ["head-rgb", "head-depth", "head-rear", "stereo-left", "stereo-right"]


class X2MockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(X2_JOINTS, **kw)
        self._action = "JOINT_DEFAULT"
        self._input_sources: dict[str, dict] = {}
        self._active_source: str | None = None
        self._hand_type = "omnihand"
        self._hand_l = [0.0] * 10
        self._hand_r = [0.0] * 10
        self._walking = False
        self._battery_soc = 0.85

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Action
        if cmd == "action.set":
            mode = args["mode"]
            if mode not in ACTION_MODES:
                raise SafetyError(f"unknown action: {mode}. Valid: {list(ACTION_MODES)}")
            self._action = mode
            return {"action": mode, "value": ACTION_MODES[mode], **ts}
        if cmd == "action.get":
            return {"action": self._action, "value": ACTION_MODES.get(self._action), **ts}
        if cmd == "action.list":
            return {"modes": ACTION_MODES, **ts}

        # Input source
        if cmd == "input.add":
            name = args["name"]
            self._input_sources[name] = {"priority": args.get("priority", 40), "timeout": args.get("timeout", 1000), "enabled": True}
            self._active_source = name
            return {"added": name, **self._input_sources[name], **ts}
        if cmd == "input.enable":
            name = args["name"]
            if name in self._input_sources:
                self._input_sources[name]["enabled"] = True
                self._active_source = name
            return {"enabled": name, **ts}
        if cmd == "input.disable":
            name = args["name"]
            if name in self._input_sources:
                self._input_sources[name]["enabled"] = False
            return {"disabled": name, **ts}
        if cmd == "input.delete":
            self._input_sources.pop(args["name"], None)
            return {"deleted": args["name"], **ts}
        if cmd == "input.get":
            return {"active": self._active_source, "sources": self._input_sources, **ts}

        # Walk
        if cmd == "walk":
            self._walking = True
            return {"forward": args.get("forward", 0), "lateral": args.get("lateral", 0),
                    "angular": args.get("angular", 0), **ts}
        if cmd == "walk.stop":
            self._walking = False
            return {"forward": 0, "lateral": 0, "angular": 0, **ts}

        # Arm (14 joints, indices 15-28)
        if cmd == "arm.set":
            positions = args.get("positions", [0.0]*14)
            if isinstance(positions, str):
                positions = [float(x) for x in positions.split(",")]
            for i, q in enumerate(positions[:14]):
                self.set_joint(15 + i, q)
            return {"joints": 14, "positions": positions[:14], **ts}
        if cmd == "arm.get":
            return [self.get_joint(i) for i in range(15, 29)]
        if cmd == "arm.home":
            home = [0, 1.0, 0, -1.2, 0, 0, 0, 0, -1.0, 0, 1.2, 0, 0, 0]
            for i, q in enumerate(home):
                self._motors[15 + i].q = q
            return {"action": "home", **ts}

        # Waist (3 joints, indices 12-14)
        if cmd == "waist.set":
            for k, idx in [("yaw", 12), ("pitch", 13), ("roll", 14)]:
                if k in args and args[k] is not None:
                    self.set_joint(idx, float(args[k]))
            return {k: self._motors[12+i].q for i, k in enumerate(["yaw","pitch","roll"])} | ts
        if cmd == "waist.get":
            return {k: round(self._motors[12+i].q, 4) for i, k in enumerate(["yaw","pitch","roll"])} | ts

        # Head (2 joints, indices 29-30)
        if cmd == "head.set":
            if "yaw" in args and args["yaw"] is not None:
                self.set_joint(29, float(args["yaw"]))
            if "pitch" in args and args["pitch"] is not None:
                self.set_joint(30, float(args["pitch"]))
            return {"yaw": self._motors[29].q, "pitch": self._motors[30].q, **ts}
        if cmd == "head.get":
            return {"yaw": round(self._motors[29].q, 4), "pitch": round(self._motors[30].q, 4), **ts}

        # Leg (12 joints, indices 0-11)
        if cmd == "leg.set":
            positions = args.get("positions", [0.0]*12)
            if isinstance(positions, str):
                positions = [float(x) for x in positions.split(",")]
            for i, q in enumerate(positions[:12]):
                self.set_joint(i, q)
            return {"joints": 12, **ts}
        if cmd == "leg.get":
            return [self.get_joint(i) for i in range(12)]

        # Hand
        if cmd == "hand.type":
            return {"type": self._hand_type, "dof_per_hand": 10 if self._hand_type == "omnihand" else 1, **ts}
        if cmd == "hand.set":
            side = args.get("side", "left")
            pos = args.get("positions", [0.0]*10)
            if isinstance(pos, str):
                pos = [float(x) for x in pos.split(",")]
            if side in ("left", "both"): self._hand_l = pos[:10]
            if side in ("right", "both"): self._hand_r = pos[:10]
            return {"side": side, "positions": pos[:10], **ts}
        if cmd == "hand.get":
            side = args.get("side", "both")
            r = {}
            if side in ("left", "both"): r["left"] = self._hand_l
            if side in ("right", "both"): r["right"] = self._hand_r
            return {**r, **ts}
        if cmd == "hand.open":
            side = args.get("side", "both")
            if side in ("left", "both"): self._hand_l = [0.0]*10
            if side in ("right", "both"): self._hand_r = [0.0]*10
            return {"side": side, "action": "open", **ts}
        if cmd == "hand.close":
            side = args.get("side", "both")
            if side in ("left", "both"): self._hand_l = [1.0]*10
            if side in ("right", "both"): self._hand_r = [1.0]*10
            return {"side": side, "action": "close", **ts}

        # Preset motions
        if cmd == "motion.play":
            mid = int(args["id"])
            name = PRESET_MOTIONS.get(mid, f"motion_{mid}")
            return {"motion_id": mid, "name": name, "area": args.get("area", "full"), **ts}
        if cmd == "motion.list":
            return {"motions": PRESET_MOTIONS, **ts}

        # Sensors
        if cmd == "imu.get":
            r = self._rng
            return {"source": args.get("source", "chest"),
                    "orientation": {"w": 1, "x": 0, "y": 0, "z": 0},
                    "gyro": [round(r.gauss(0, 0.005), 4) for _ in range(3)],
                    "accel": [round(r.gauss(0, 0.02), 4), round(r.gauss(0, 0.02), 4),
                              round(9.81 + r.gauss(0, 0.02), 4)], **ts}
        if cmd == "camera.list":
            return {"cameras": CAMERAS}
        if cmd == "camera.get":
            return {"source": args.get("source"), "bytes": 0, "note": "mock", **ts}
        if cmd == "lidar.get":
            return {"points": 0, "sensor": "RoboSense_E1R", **ts}
        if cmd == "touch.get":
            return {"channels": 8, "events": [], **ts}
        if cmd == "battery.status":
            return {"soc": self._battery_soc, "capacity_wh": 421, "runtime_est_min": 120, **ts}

        # Interaction
        if cmd == "tts.play":
            return {"text": args.get("text"), "priority": args.get("priority", "mid"), **ts}
        if cmd == "audio.volume.get":
            return {"volume": 50, **ts}
        if cmd == "audio.volume.set":
            return {"volume": args.get("level", 50), **ts}
        if cmd == "audio.mute.get":
            return {"muted": False, **ts}
        if cmd == "audio.mute.set":
            return {"muted": args.get("on", False), **ts}
        if cmd == "face.emoji":
            return {"emoji": args.get("name"), **ts}
        if cmd == "face.video":
            return {"video": args.get("path"), **ts}
        if cmd == "led.set":
            return {"r": args.get("r", 0), "g": args.get("g", 0), "b": args.get("b", 0),
                    "mode": args.get("mode", "static"), **ts}

        # Joint all-state
        if cmd == "joint.all-state":
            return self.list_joints()

        raise ValueError(f"unknown command: {cmd!r}")


def get_client(backend: str = "mock", **kw):
    if backend == "mock":
        return X2MockClient(**kw)
    raise NotImplementedError(
        "RealClient: requires ROS2 Humble + aimdk_msgs. "
        "Build with colcon in SDK-X2 workspace. "
        "Robot IP: 10.0.1.41 (wired) or 192.168.88.88 (WiFi). "
        "See https://x2-aimdk.agibot.com"
    )
