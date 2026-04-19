"""Boston Dynamics Spot — 12 leg DOF + 6 arm DOF, gRPC via bosdyn-client."""
from __future__ import annotations
import time
from typing import Any
from robot_cli_core.base_client import JointDef, JointMap, MockClientBase

_JOINTS = [
    # Front Left
    JointDef(0,  "fl.hx", -0.79, 0.79), JointDef(1,  "fl.hy", -0.90, 2.50), JointDef(2,  "fl.kn", -2.79, -0.25),
    # Front Right
    JointDef(3,  "fr.hx", -0.79, 0.79), JointDef(4,  "fr.hy", -0.90, 2.50), JointDef(5,  "fr.kn", -2.79, -0.25),
    # Hind Left
    JointDef(6,  "hl.hx", -0.79, 0.79), JointDef(7,  "hl.hy", -0.90, 2.50), JointDef(8,  "hl.kn", -2.79, -0.25),
    # Hind Right
    JointDef(9,  "hr.hx", -0.79, 0.79), JointDef(10, "hr.hy", -0.90, 2.50), JointDef(11, "hr.kn", -2.79, -0.25),
    # Arm (optional, 6 DOF)
    JointDef(12, "arm0.sh0", -3.14, 1.80), JointDef(13, "arm0.sh1", -3.10, 0.34),
    JointDef(14, "arm0.el0", 0.0, 3.14),    JointDef(15, "arm0.el1", -2.79, 2.79),
    JointDef(16, "arm0.wr0", -1.83, 2.87), JointDef(17, "arm0.wr1", -2.87, 2.87),
]

SPOT_JOINTS = JointMap(_JOINTS)

CAMERAS = ["frontleft_fisheye_image", "frontright_fisheye_image", "left_fisheye_image",
           "right_fisheye_image", "back_fisheye_image", "hand_color_image"]


class SpotMockClient(MockClientBase):
    name = "mock"

    def __init__(self, **kw):
        super().__init__(SPOT_JOINTS, **kw)
        self._powered = False
        self._standing = False
        self._estopped = False
        self._gripper = 1.0
        self._battery_soc = 0.85

    def dispatch(self, cmd: str, args: dict[str, Any]) -> Any:
        ts = self._ts()

        # Power
        if cmd == "power.on":
            self._powered = True; return {"powered": True, **ts}
        if cmd == "power.off":
            self._standing = False; self._powered = False; return {"powered": False, **ts}

        # Estop
        if cmd == "estop.hard":
            self._estopped = True; self._powered = False; return {"estopped": True, "type": "hard", **ts}
        if cmd == "estop.gentle":
            self._standing = False; return {"estopped": True, "type": "gentle", **ts}
        if cmd == "estop.release":
            self._estopped = False; return {"estopped": False, **ts}

        # Locomotion
        if cmd == "stand":
            self._standing = True; return {"standing": True, "height": args.get("height", 0), **ts}
        if cmd == "sit":
            self._standing = False; return {"standing": False, **ts}
        if cmd == "move":
            return {"vx": args.get("vx", 0), "vy": args.get("vy", 0), "vyaw": args.get("vyaw", 0), **ts}
        if cmd == "walk-to":
            return {"action": "walk_to", **args, **ts}
        if cmd == "selfright":
            return {"action": "selfright", **ts}
        if cmd == "euler":
            return {"roll": args.get("roll", 0), "pitch": args.get("pitch", 0), "yaw": args.get("yaw", 0), **ts}

        # Arm
        if cmd == "arm.stow": return {"arm": "stowed", **ts}
        if cmd == "arm.unstow": return {"arm": "ready", **ts}
        if cmd == "arm.move": return {"action": "arm_move", **args, **ts}
        if cmd == "arm.joint-set": return {"action": "arm_joint_set", **args, **ts}
        if cmd == "arm.joint-get":
            return [self.get_joint(i) for i in range(12, 18)]

        # Gripper
        if cmd == "gripper.open": self._gripper = 1.0; return {"gripper": 1.0, **ts}
        if cmd == "gripper.close": self._gripper = 0.0; return {"gripper": 0.0, **ts}
        if cmd == "gripper.set": self._gripper = args.get("fraction", 0.5); return {"gripper": self._gripper, **ts}

        # Sensors
        if cmd == "state":
            return {"powered": self._powered, "standing": self._standing, "estopped": self._estopped,
                    "battery_soc": self._battery_soc, **ts}
        if cmd == "battery":
            return {"soc": self._battery_soc, "voltage": 52.0, "runtime_min": 90, **ts}
        if cmd == "image.list":
            return {"cameras": CAMERAS}
        if cmd == "image.get":
            return {"source": args.get("source", "frontleft"), "bytes": 0, "note": "mock: no image data", **ts}

        # Nav
        if cmd.startswith("nav."):
            return {"action": cmd, **args, **ts}

        # Dock
        if cmd == "dock": return {"action": "dock", "id": args.get("id"), **ts}
        if cmd == "undock": return {"action": "undock", **ts}

        raise ValueError(f"unknown: {cmd!r}")


def get_client(backend="mock", **kw):
    if backend == "mock": return SpotMockClient(**kw)
    raise NotImplementedError("RealClient: pip install bosdyn-client, wrap bosdyn.client.Robot")
