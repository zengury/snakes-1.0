"""Diagnosis CLI — `snakes diag <subsystem> <command>`

Stub. Full implementation when mcp-ros-diagnosis source is merged.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snakes diag",
        description="Robot maintenance and diagnostics.",
    )
    sub = parser.add_subparsers(dest="subsystem", required=True)

    p_joint = sub.add_parser("joint", help="Joint diagnostics")
    p_joint.add_argument("action", choices=["status", "temp", "torque", "history"])
    p_joint.add_argument("--id", help="Joint name")

    p_power = sub.add_parser("power", help="Power / battery")
    p_power.add_argument("action", choices=["soc", "voltage", "current", "history"])

    p_imu = sub.add_parser("imu", help="IMU / posture")
    p_imu.add_argument("action", choices=["posture", "accel", "gyro", "fall-risk"])

    p_pid = sub.add_parser("pid", help="PID tuning")
    p_pid.add_argument("action", choices=["tune", "status", "rollback"])
    p_pid.add_argument("--joint")

    sub.add_parser("alerts", help="Active alerts")
    sub.add_parser("servers", help="List diagnosis servers")

    args = parser.parse_args(argv)

    if args.subsystem == "servers":
        print("Diagnosis servers (when merged from mcp-ros-diagnosis):")
        print("  joints  — manastone-joints (8081)")
        print("  power   — manastone-power (8082)")
        print("  imu     — manastone-imu (8083)")
        print("  hand    — manastone-hand (8084)")
        print("  vision  — manastone-vision (8085)")
        print("  motion  — manastone-motion (8086)")
        print("  pid     — manastone-pid-tuner (8087)")
        return 0

    print(f"snakes diag {args.subsystem} {getattr(args, 'action', '')}: not yet implemented")
    print("Source merge from zengury/mcp-ros-diagnosis pending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
