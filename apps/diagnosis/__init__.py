"""apps.diagnosis — Robot maintenance and diagnostics via CLI.

Merged from zengury/mcp-ros-diagnosis (manastone). Wraps per-subsystem
MCP servers (joints, power, imu, hand, vision, motion, pid-tuner) with
a unified CLI interface.

Usage (planned):
    snakes diag joint status              # all joint health
    snakes diag joint temp --id left_knee
    snakes diag power soc
    snakes diag imu posture
    snakes diag pid tune --joint left_knee --trial 1
    snakes diag alerts
"""
from __future__ import annotations
