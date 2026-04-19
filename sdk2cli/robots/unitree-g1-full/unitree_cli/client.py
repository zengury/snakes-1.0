"""Backend abstractions for Unitree robots.

Supports G1 (29-DOF humanoid) as primary target, with architecture ready
for Go2/B2/H1/R1. Joint indices, ranges, and PD gains are taken directly
from unitree_sdk2 / unitree_sdk2py source.

Two backends:
- MockClient: in-memory simulation, no hardware. Default.
- RealClient: wraps unitree_sdk2py LocoClient + DDS channels. Scaffold.

Safety validators run BEFORE any backend call regardless of transport.
"""
from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# G1 29-DOF joint definitions — from unitree_sdk2py G1JointIndex
# ---------------------------------------------------------------------------

class G1Joint(IntEnum):
    LeftHipPitch     = 0
    LeftHipRoll      = 1
    LeftHipYaw       = 2
    LeftKnee         = 3
    LeftAnklePitch   = 4
    LeftAnkleRoll    = 5
    RightHipPitch    = 6
    RightHipRoll     = 7
    RightHipYaw      = 8
    RightKnee        = 9
    RightAnklePitch  = 10
    RightAnkleRoll   = 11
    WaistYaw         = 12
    WaistRoll        = 13
    WaistPitch       = 14
    LeftShoulderPitch  = 15
    LeftShoulderRoll   = 16
    LeftShoulderYaw    = 17
    LeftElbow          = 18
    LeftWristRoll      = 19
    LeftWristPitch     = 20
    LeftWristYaw       = 21
    RightShoulderPitch = 22
    RightShoulderRoll  = 23
    RightShoulderYaw   = 24
    RightElbow         = 25
    RightWristRoll     = 26
    RightWristPitch    = 27
    RightWristYaw      = 28


G1_NUM_MOTOR = 29

# name → index lookup (case-insensitive)
G1_NAME_TO_IDX: dict[str, int] = {j.name: j.value for j in G1Joint}
G1_IDX_TO_NAME: dict[int, str] = {j.value: j.name for j in G1Joint}

# Joint position limits (rad). Source: URDF + SDK examples.
# Conservative defaults — tighten from your robot's actual URDF.
G1_JOINT_LIMITS: dict[int, tuple[float, float]] = {
    # Left leg
    0: (-1.54, 1.54),   1: (-0.79, 0.79),   2: (-1.54, 1.54),
    3: (-0.17, 2.44),   4: (-0.79, 0.79),   5: (-0.52, 0.52),
    # Right leg (mirror)
    6: (-1.54, 1.54),   7: (-0.79, 0.79),   8: (-1.54, 1.54),
    9: (-0.17, 2.44),  10: (-0.79, 0.79),  11: (-0.52, 0.52),
    # Waist
    12: (-1.54, 1.54), 13: (-0.79, 0.79),  14: (-0.79, 0.79),
    # Left arm
    15: (-3.14, 3.14), 16: (-1.57, 2.97),  17: (-3.14, 3.14),
    18: (-0.17, 2.70), 19: (-3.14, 3.14),  20: (-1.57, 1.57),
    21: (-3.14, 3.14),
    # Right arm (mirror roll signs)
    22: (-3.14, 3.14), 23: (-2.97, 1.57),  24: (-3.14, 3.14),
    25: (-0.17, 2.70), 26: (-3.14, 3.14),  27: (-1.57, 1.57),
    28: (-3.14, 3.14),
}

# Default PD gains per joint — from unitree_sdk2py examples
G1_DEFAULT_KP = [
    60, 60, 60, 100, 40, 40,   # left leg
    60, 60, 60, 100, 40, 40,   # right leg
    60, 40, 40,                 # waist
    40, 40, 40, 40, 40, 40, 40, # left arm
    40, 40, 40, 40, 40, 40, 40, # right arm
]
G1_DEFAULT_KD = [
    1, 1, 1, 2, 1, 1,
    1, 1, 1, 2, 1, 1,
    1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1,
]

# G1 arm action presets — from g1_arm_action_client.py
G1_ARM_ACTIONS: dict[str, int] = {
    "release": 99, "two-hand-kiss": 11, "left-kiss": 12, "right-kiss": 13,
    "hands-up": 15, "clap": 17, "high-five": 18, "hug": 19,
    "heart": 20, "right-heart": 21, "reject": 22, "right-hand-up": 23,
    "x-ray": 24, "face-wave": 25, "wave": 26, "shake-hand": 27,
}


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

class SafetyError(ValueError):
    """Raised when a command violates a safety invariant."""


def resolve_joint(id_or_name: int | str) -> int:
    """Resolve a joint index or name to an integer index."""
    if isinstance(id_or_name, int):
        if id_or_name < 0 or id_or_name >= G1_NUM_MOTOR:
            raise SafetyError(f"joint index {id_or_name} out of range [0, {G1_NUM_MOTOR})")
        return id_or_name
    name = id_or_name.strip()
    # Try exact match first, then case-insensitive
    if name in G1_NAME_TO_IDX:
        return G1_NAME_TO_IDX[name]
    name_lower = name.lower()
    for k, v in G1_NAME_TO_IDX.items():
        if k.lower() == name_lower:
            return v
    raise SafetyError(f"unknown joint name: {name!r}")


def validate_joint_q(idx: int, q: float) -> None:
    lo, hi = G1_JOINT_LIMITS.get(idx, (-3.14, 3.14))
    if not (lo <= q <= hi):
        name = G1_IDX_TO_NAME.get(idx, str(idx))
        raise SafetyError(f"{name}(#{idx}): q={q:.3f} out of range [{lo:.2f}, {hi:.2f}] rad")


def validate_kp(kp: float) -> None:
    if not (0 <= kp <= 500):
        raise SafetyError(f"kp={kp} out of range [0, 500]")


def validate_kd(kd: float) -> None:
    if not (0 <= kd <= 50):
        raise SafetyError(f"kd={kd} out of range [0, 50]")


def validate_arm_action(action: str) -> int:
    action_lower = action.lower().strip()
    for k, v in G1_ARM_ACTIONS.items():
        if k == action_lower:
            return v
    # Try as integer
    try:
        return int(action)
    except ValueError:
        valid = ", ".join(G1_ARM_ACTIONS.keys())
        raise SafetyError(f"unknown arm action: {action!r}. Valid: {valid}")


# ---------------------------------------------------------------------------
# Motor state snapshot — used by undo system
# ---------------------------------------------------------------------------

@dataclass
class MotorSnapshot:
    q: float = 0.0
    dq: float = 0.0
    tau_est: float = 0.0
    temperature: float = 25.0


@dataclass
class RobotState:
    motors: list[MotorSnapshot] = field(default_factory=lambda: [MotorSnapshot() for _ in range(G1_NUM_MOTOR)])
    imu_rpy: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    imu_gyro: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    imu_accel: list[float] = field(default_factory=lambda: [0.0, 0.0, 9.81])
    fsm_id: int = 0
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Abstract client
# ---------------------------------------------------------------------------

class UnitreeClient:
    name: str = "abstract"

    def get_state(self) -> RobotState:
        raise NotImplementedError

    # --- Locomotion (LocoClient RPC) ---
    def loco_damp(self) -> dict: raise NotImplementedError
    def loco_start(self) -> dict: raise NotImplementedError
    def loco_stand_up(self) -> dict: raise NotImplementedError
    def loco_sit(self) -> dict: raise NotImplementedError
    def loco_squat(self) -> dict: raise NotImplementedError
    def loco_zero_torque(self) -> dict: raise NotImplementedError
    def loco_stop(self) -> dict: raise NotImplementedError
    def loco_high_stand(self) -> dict: raise NotImplementedError
    def loco_low_stand(self) -> dict: raise NotImplementedError
    def loco_balance(self, mode: int = 0) -> dict: raise NotImplementedError
    def loco_move(self, vx: float, vy: float, vyaw: float, continuous: bool = False) -> dict: raise NotImplementedError
    def loco_velocity(self, vx: float, vy: float, omega: float, duration: float = 1.0) -> dict: raise NotImplementedError
    def loco_wave_hand(self, turn: bool = False) -> dict: raise NotImplementedError
    def loco_shake_hand(self, stage: int = -1) -> dict: raise NotImplementedError
    def loco_get_fsm_id(self) -> dict: raise NotImplementedError
    def loco_set_fsm_id(self, fsm_id: int) -> dict: raise NotImplementedError
    def loco_get_stand_height(self) -> dict: raise NotImplementedError
    def loco_set_stand_height(self, height: float) -> dict: raise NotImplementedError
    def loco_get_swing_height(self) -> dict: raise NotImplementedError
    def loco_set_swing_height(self, height: float) -> dict: raise NotImplementedError
    def loco_get_balance_mode(self) -> dict: raise NotImplementedError
    def loco_set_balance_mode(self, mode: int) -> dict: raise NotImplementedError

    # --- Arm actions ---
    def arm_do(self, action_id: int) -> dict: raise NotImplementedError
    def arm_list(self) -> dict: raise NotImplementedError

    # --- Audio ---
    def audio_tts(self, text: str, speaker: int = 0) -> dict: raise NotImplementedError
    def audio_volume_get(self) -> dict: raise NotImplementedError
    def audio_volume_set(self, level: int) -> dict: raise NotImplementedError
    def audio_led(self, r: int, g: int, b: int) -> dict: raise NotImplementedError

    # --- Joint-level ---
    def joint_get(self, idx: int) -> dict: raise NotImplementedError
    def joint_set(self, idx: int, q: float, dq: float = 0.0,
                  kp: float | None = None, kd: float | None = None,
                  tau: float = 0.0) -> dict: raise NotImplementedError
    def joint_list(self) -> list[dict]: raise NotImplementedError

    # --- IMU ---
    def imu_get(self) -> dict: raise NotImplementedError

    # --- Mode switcher ---
    def mode_check(self) -> dict: raise NotImplementedError
    def mode_select(self, name: str) -> dict: raise NotImplementedError
    def mode_release(self) -> dict: raise NotImplementedError


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------

class MockClient(UnitreeClient):
    name = "mock"

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._state = RobotState()
        self._fsm_id = 0
        self._stand_height = 0.75
        self._swing_height = 0.1
        self._balance_mode = 0
        self._mode = "normal"
        self._estopped = False

    def get_state(self) -> RobotState:
        return RobotState(
            motors=[MotorSnapshot(q=m.q, dq=m.dq, tau_est=m.tau_est, temperature=m.temperature)
                    for m in self._state.motors],
            imu_rpy=list(self._state.imu_rpy),
            fsm_id=self._fsm_id,
            timestamp=time.time(),
        )

    def _ts(self) -> dict:
        return {"timestamp": time.time(), "backend": self.name}

    # Locomotion
    def loco_damp(self):
        self._fsm_id = 1
        return {"action": "damp", "fsm_id": 1, **self._ts()}

    def loco_start(self):
        self._fsm_id = 200
        return {"action": "start", "fsm_id": 200, **self._ts()}

    def loco_stand_up(self):
        self._fsm_id = 706
        return {"action": "stand_up", "fsm_id": 706, **self._ts()}

    def loco_sit(self):
        self._fsm_id = 3
        return {"action": "sit", "fsm_id": 3, **self._ts()}

    def loco_squat(self):
        self._fsm_id = 706
        return {"action": "squat", "fsm_id": 706, **self._ts()}

    def loco_zero_torque(self):
        self._fsm_id = 0
        return {"action": "zero_torque", "fsm_id": 0, **self._ts()}

    def loco_stop(self):
        return {"action": "stop_move", **self._ts()}

    def loco_high_stand(self):
        self._stand_height = 1.0
        return {"action": "high_stand", "height": 1.0, **self._ts()}

    def loco_low_stand(self):
        self._stand_height = 0.5
        return {"action": "low_stand", "height": 0.5, **self._ts()}

    def loco_balance(self, mode=0):
        self._balance_mode = mode
        return {"action": "balance_stand", "mode": mode, **self._ts()}

    def loco_move(self, vx, vy, vyaw, continuous=False):
        return {"action": "move", "vx": vx, "vy": vy, "vyaw": vyaw, "continuous": continuous, **self._ts()}

    def loco_velocity(self, vx, vy, omega, duration=1.0):
        return {"action": "set_velocity", "vx": vx, "vy": vy, "omega": omega, "duration": duration, **self._ts()}

    def loco_wave_hand(self, turn=False):
        return {"action": "wave_hand", "turn": turn, **self._ts()}

    def loco_shake_hand(self, stage=-1):
        return {"action": "shake_hand", "stage": stage, **self._ts()}

    def loco_get_fsm_id(self):
        return {"fsm_id": self._fsm_id, **self._ts()}

    def loco_set_fsm_id(self, fsm_id):
        self._fsm_id = fsm_id
        return {"fsm_id": fsm_id, **self._ts()}

    def loco_get_stand_height(self):
        return {"stand_height": self._stand_height, **self._ts()}

    def loco_set_stand_height(self, height):
        self._stand_height = height
        return {"stand_height": height, **self._ts()}

    def loco_get_swing_height(self):
        return {"swing_height": self._swing_height, **self._ts()}

    def loco_set_swing_height(self, height):
        self._swing_height = height
        return {"swing_height": height, **self._ts()}

    def loco_get_balance_mode(self):
        return {"balance_mode": self._balance_mode, **self._ts()}

    def loco_set_balance_mode(self, mode):
        self._balance_mode = mode
        return {"balance_mode": mode, **self._ts()}

    # Arm
    def arm_do(self, action_id):
        name = next((k for k, v in G1_ARM_ACTIONS.items() if v == action_id), str(action_id))
        return {"action": "arm", "action_id": action_id, "name": name, **self._ts()}

    def arm_list(self):
        return {"actions": G1_ARM_ACTIONS, **self._ts()}

    # Audio
    def audio_tts(self, text, speaker=0):
        return {"action": "tts", "text": text, "speaker": speaker, **self._ts()}

    def audio_volume_get(self):
        return {"volume": 50, **self._ts()}

    def audio_volume_set(self, level):
        return {"volume": level, **self._ts()}

    def audio_led(self, r, g, b):
        return {"led": [r, g, b], **self._ts()}

    # Joints
    def joint_get(self, idx):
        m = self._state.motors[idx]
        return {
            "index": idx, "name": G1_IDX_TO_NAME[idx],
            "q": round(m.q, 4), "dq": round(m.dq, 4),
            "tau_est": round(m.tau_est, 3),
            "temperature": round(m.temperature + self._rng.uniform(-0.5, 0.5), 1),
        }

    def joint_set(self, idx, q, dq=0.0, kp=None, kd=None, tau=0.0):
        validate_joint_q(idx, q)
        if kp is not None:
            validate_kp(kp)
        if kd is not None:
            validate_kd(kd)
        kp = kp if kp is not None else G1_DEFAULT_KP[idx]
        kd = kd if kd is not None else G1_DEFAULT_KD[idx]
        m = self._state.motors[idx]
        m.q = q
        m.dq = dq
        m.tau_est = tau
        return {
            "index": idx, "name": G1_IDX_TO_NAME[idx],
            "q": q, "dq": dq, "kp": kp, "kd": kd, "tau": tau,
            **self._ts(),
        }

    def joint_list(self):
        return [self.joint_get(i) for i in range(G1_NUM_MOTOR)]

    # IMU
    def imu_get(self):
        r = self._rng
        return {
            "rpy": [round(r.gauss(0, 0.01), 4) for _ in range(3)],
            "gyro": [round(r.gauss(0, 0.005), 4) for _ in range(3)],
            "accel": [round(r.gauss(0, 0.02), 4), round(r.gauss(0, 0.02), 4), round(9.81 + r.gauss(0, 0.02), 4)],
            "quaternion": [1.0, 0.0, 0.0, 0.0],
            **self._ts(),
        }

    # Mode
    def mode_check(self):
        return {"mode": self._mode, **self._ts()}

    def mode_select(self, name):
        self._mode = name
        return {"mode": name, **self._ts()}

    def mode_release(self):
        prev = self._mode
        self._mode = "released"
        return {"previous": prev, "mode": "released", **self._ts()}


# ---------------------------------------------------------------------------
# Real backend — scaffold for unitree_sdk2py
# ---------------------------------------------------------------------------

class RealClient(UnitreeClient):
    """Wraps unitree_sdk2py. Fill in method bodies on real hardware.

    Import paths (from unitree_sdk2py source):
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber
        from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
        from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
        from unitree_sdk2py.utils.crc import CRC
    """

    name = "real"

    def __init__(self, interface: str = "eth0", domain_id: int = 0) -> None:
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        except ImportError as exc:
            raise RuntimeError(
                "unitree_sdk2py not installed. Run: pip install unitree_sdk2py\n"
                "Also requires CycloneDDS: export CYCLONEDDS_HOME=~/cyclonedds/install"
            ) from exc

        ChannelFactoryInitialize(domain_id, interface)
        self._loco = LocoClient()
        self._loco.SetTimeout(10.0)
        self._loco.Init()

        # TODO: Initialize these on real hardware:
        # self._arm = G1ArmActionClient(); self._arm.Init()
        # self._audio = AudioClient(); self._audio.Init()
        # self._switcher = MotionSwitcherClient(); self._switcher.Init()
        # self._low_sub = ChannelSubscriber("rt/lowstate", HGLowState_)
        # self._low_pub = ChannelPublisher("rt/lowcmd", HGLowCmd_)
        # self._crc = CRC()

        raise NotImplementedError(
            "RealClient initialized LocoClient successfully. "
            "Fill in remaining method bodies against unitree_sdk2py. "
            "See docstring for import paths."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_client(backend: str | None = None, **kwargs: Any) -> UnitreeClient:
    backend = backend or os.environ.get("UNITREE_BACKEND", "mock")
    if backend == "mock":
        kwargs.pop("interface", None)  # MockClient doesn't need interface
        return MockClient(**kwargs)
    if backend == "real":
        interface = kwargs.pop("interface", os.environ.get("UNITREE_INTERFACE", "eth0"))
        return RealClient(interface=interface, **kwargs)
    raise ValueError(f"unknown backend: {backend!r}")
