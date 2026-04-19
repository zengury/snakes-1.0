"""Diagnosis CLI — `snakes diag <subsystem> <command>`

Wraps manastone diagnostic servers. In mock mode, returns synthetic data.
In real mode, connects to DDS bridge.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time


def _mock_joint_status(joint_id: str | None) -> dict:
    joints = ["left_hip_pitch", "left_knee", "right_hip_pitch", "right_knee",
              "left_shoulder_pitch", "right_shoulder_pitch", "waist_yaw"]
    if joint_id:
        joints = [joint_id]
    return {
        "ok": True,
        "joints": [
            {
                "name": j,
                "temperature": round(35 + random.uniform(0, 15), 1),
                "torque": round(random.uniform(0.5, 8.0), 2),
                "velocity": round(random.uniform(-0.1, 0.1), 3),
                "status": "normal" if random.random() > 0.1 else "warn",
                "comm_errors": random.randint(0, 3),
            }
            for j in joints
        ],
    }


def _mock_power() -> dict:
    return {
        "ok": True,
        "battery_soc": round(random.uniform(40, 95), 1),
        "voltage": round(random.uniform(44, 50), 1),
        "current_draw": round(random.uniform(1, 8), 2),
        "temperature": round(random.uniform(25, 40), 1),
        "charging": False,
        "estimated_runtime_min": random.randint(30, 120),
    }


def _mock_imu() -> dict:
    return {
        "ok": True,
        "roll": round(random.uniform(-2, 2), 2),
        "pitch": round(random.uniform(-3, 3), 2),
        "yaw": round(random.uniform(-180, 180), 2),
        "accel": [round(random.gauss(0, 0.1), 3) for _ in range(3)],
        "gyro": [round(random.gauss(0, 0.01), 4) for _ in range(3)],
        "fall_risk": "low",
        "posture": "upright",
    }


def _mock_alerts() -> dict:
    alerts = []
    if random.random() > 0.7:
        alerts.append({
            "severity": "warn",
            "subsystem": "joints",
            "message": "left_knee temperature 48.2°C approaching threshold",
            "timestamp": time.time(),
        })
    return {"ok": True, "alerts": alerts, "count": len(alerts)}


def _mock_pid_status() -> dict:
    return {
        "ok": True,
        "tuning_active": False,
        "last_experiment": None,
        "workspace": "apps/diagnosis/storage/pid_workspace/",
    }


def _output(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snakes diag",
        description="Robot maintenance and diagnostics.",
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")
    sub = parser.add_subparsers(dest="subsystem", required=True)

    p_joint = sub.add_parser("joint", help="Joint diagnostics")
    p_joint.add_argument("action", choices=["status", "temp", "torque", "history"])
    p_joint.add_argument("--id", help="Joint name")

    p_power = sub.add_parser("power", help="Power / battery")
    p_power.add_argument("action", choices=["soc", "voltage", "current", "status"])

    p_imu = sub.add_parser("imu", help="IMU / posture")
    p_imu.add_argument("action", choices=["posture", "accel", "gyro", "fall-risk", "status"])

    p_pid = sub.add_parser("pid", help="PID tuning")
    p_pid.add_argument("action", choices=["tune", "status", "rollback"])
    p_pid.add_argument("--joint")

    sub.add_parser("alerts", help="Active alerts")
    sub.add_parser("servers", help="List diagnosis servers")

    args = parser.parse_args(argv)

    if args.subsystem == "servers":
        _output({
            "ok": True,
            "servers": [
                {"name": "joints", "port": 8081, "status": "mock"},
                {"name": "power", "port": 8082, "status": "mock"},
                {"name": "imu", "port": 8083, "status": "mock"},
                {"name": "hand", "port": 8084, "status": "mock"},
                {"name": "vision", "port": 8085, "status": "mock"},
                {"name": "motion", "port": 8086, "status": "mock"},
                {"name": "pid-tuner", "port": 8087, "status": "mock"},
            ],
        })
        return 0

    if args.subsystem == "alerts":
        _output(_mock_alerts())
        return 0

    if args.subsystem == "joint":
        data = _mock_joint_status(getattr(args, "id", None))
        if args.action == "temp":
            data["joints"] = [{"name": j["name"], "temperature": j["temperature"]} for j in data["joints"]]
        elif args.action == "torque":
            data["joints"] = [{"name": j["name"], "torque": j["torque"]} for j in data["joints"]]
        _output(data)
        return 0

    if args.subsystem == "power":
        data = _mock_power()
        if args.action != "status":
            data = {"ok": True, args.action: data.get(args.action, data.get(f"battery_{args.action}"))}
        _output(data)
        return 0

    if args.subsystem == "imu":
        _output(_mock_imu())
        return 0

    if args.subsystem == "pid":
        _output(_mock_pid_status())
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
