"""Abstract base client, safety primitives, and joint map helpers.

Each robot defines its own subclass of RobotClient + JointMap.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


class SafetyError(ValueError):
    """Raised when a command violates a safety invariant."""


@dataclass
class JointDef:
    index: int
    name: str
    lo: float           # lower limit (rad or normalized)
    hi: float           # upper limit
    default_kp: float = 40.0
    default_kd: float = 1.0


class JointMap:
    """Defines a robot's joint set. Three ways to construct:

    1. JointMap([JointDef(...)]) — from code (current approach)
    2. JointMap.from_yaml("joint_limits.yaml") — from our structured data
    3. JointMap.from_urdf("robot.urdf") — from URDF model file

    Auto-load priority: URDF > YAML > code hardcoded.
    """

    def __init__(self, joints: list[JointDef]) -> None:
        self.joints = joints
        self.by_index = {j.index: j for j in joints}
        self.by_name = {j.name: j for j in joints}
        self._by_name_lower = {j.name.lower(): j for j in joints}
        self.count = len(joints)

    def resolve(self, id_or_name: int | str) -> JointDef:
        if isinstance(id_or_name, int):
            if id_or_name not in self.by_index:
                raise SafetyError(f"joint index {id_or_name} out of range [0, {self.count})")
            return self.by_index[id_or_name]
        name = str(id_or_name).strip()
        if name in self.by_name:
            return self.by_name[name]
        lower = name.lower()
        if lower in self._by_name_lower:
            return self._by_name_lower[lower]
        raise SafetyError(f"unknown joint: {name!r}")

    def validate_position(self, joint: JointDef, q: float) -> None:
        if not (joint.lo <= q <= joint.hi):
            raise SafetyError(
                f"{joint.name}(#{joint.index}): q={q:.3f} out of range [{joint.lo:.2f}, {joint.hi:.2f}]"
            )

    def all_names(self) -> list[str]:
        return [j.name for j in self.joints]

    # ── Loaders ───────────────────────────────────────────

    @classmethod
    def from_urdf(cls, urdf_path: str) -> "JointMap":
        """Load from URDF <joint><limit lower='' upper=''/></joint>.

        This is the most authoritative source — limits come directly
        from the manufacturer's robot model.
        """
        import xml.etree.ElementTree as ET
        tree = ET.parse(urdf_path)
        joints: list[JointDef] = []
        for j in tree.findall(".//joint"):
            jtype = j.get("type", "fixed")
            if jtype in ("fixed", "floating"):
                continue
            limit = j.find("limit")
            lo = float(limit.get("lower", "-3.14")) if limit is not None else -3.14
            hi = float(limit.get("upper", "3.14")) if limit is not None else 3.14
            joints.append(JointDef(
                index=len(joints),
                name=j.get("name", f"joint_{len(joints)}"),
                lo=lo, hi=hi,
            ))
        return cls(joints)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "JointMap":
        """Load from our joint_limits.yaml format.

        Equivalent to ROS joint_limits.yaml but with index, kp/kd, group.
        """
        import yaml  # type: ignore
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        joints: list[JointDef] = []
        for j in data.get("joints", []):
            if not isinstance(j, dict) or "name" not in j:
                continue
            joints.append(JointDef(
                index=j.get("index", len(joints)),
                name=j["name"],
                lo=float(j.get("lower", -3.14)),
                hi=float(j.get("upper", 3.14)),
                default_kp=float(j.get("kp", j.get("default_kp", 40))),
                default_kd=float(j.get("kd", j.get("default_kd", 1))),
            ))
        return cls(joints)

    @classmethod
    def auto_load(cls, robot_dir: str, fallback: "JointMap | None" = None) -> "JointMap":
        """Auto-load with priority: URDF > joint_limits.yaml > fallback.

        Args:
            robot_dir: path to the robot's directory (e.g. robots/agibot-x2/)
            fallback: JointMap from code (client.py hardcoded) if no file found
        """
        from pathlib import Path
        d = Path(robot_dir)

        # Priority 1: URDF
        for urdf_candidate in [d / "urdf" / "robot.urdf", d / "urdf" / "*.urdf"]:
            if urdf_candidate.exists():
                return cls.from_urdf(str(urdf_candidate))
        # Check glob
        urdf_dir = d / "urdf"
        if urdf_dir.is_dir():
            urdfs = list(urdf_dir.glob("*.urdf"))
            if urdfs:
                return cls.from_urdf(str(urdfs[0]))

        # Priority 2: joint_limits.yaml
        yaml_file = d / "joint_limits.yaml"
        if yaml_file.exists():
            try:
                return cls.from_yaml(str(yaml_file))
            except Exception:
                pass  # YAML parse failed, fall through

        # Priority 3: code hardcoded
        if fallback is not None:
            return fallback

        raise FileNotFoundError(
            f"No joint data found in {d}. Provide urdf/robot.urdf, "
            f"joint_limits.yaml, or pass a JointMap from code."
        )


@dataclass
class MotorSnapshot:
    q: float = 0.0
    dq: float = 0.0
    tau_est: float = 0.0
    temperature: float = 25.0


class RobotClient:
    """Abstract base. Each robot implements a subclass."""

    name: str = "abstract"
    joint_map: JointMap | None = None

    def get_joint(self, idx: int) -> dict:
        raise NotImplementedError

    def set_joint(self, idx: int, q: float, **kwargs) -> dict:
        raise NotImplementedError

    def list_joints(self) -> list[dict]:
        raise NotImplementedError

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        """Override to handle robot-specific commands beyond joint control."""
        raise ValueError(f"unknown command: {cmd!r}")


class MockClientBase(RobotClient):
    """Base mock with in-memory joint state. Subclass and add robot-specific commands."""

    name = "mock"

    def __init__(self, joint_map: JointMap, seed: int | None = None) -> None:
        import random
        self.joint_map = joint_map
        self._rng = random.Random(seed)
        self._motors = {j.index: MotorSnapshot() for j in joint_map.joints}
        self._state: dict[str, Any] = {}

    def _ts(self) -> dict:
        return {"timestamp": time.time(), "backend": self.name}

    def get_joint(self, idx: int) -> dict:
        jd = self.joint_map.by_index[idx]
        m = self._motors[idx]
        return {
            "index": idx, "name": jd.name,
            "q": round(m.q, 4), "dq": round(m.dq, 4),
            "tau_est": round(m.tau_est, 3),
            "temperature": round(m.temperature + self._rng.uniform(-0.5, 0.5), 1),
        }

    def set_joint(self, idx: int, q: float, **kwargs) -> dict:
        jd = self.joint_map.by_index[idx]
        self.joint_map.validate_position(jd, q)
        m = self._motors[idx]
        m.q = q
        m.dq = kwargs.get("dq", 0.0)
        return {"index": idx, "name": jd.name, "q": q, **kwargs, **self._ts()}

    def list_joints(self) -> list[dict]:
        return [self.get_joint(j.index) for j in self.joint_map.joints]
