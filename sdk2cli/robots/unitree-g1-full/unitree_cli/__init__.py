"""unitree-cli — Agent-native CLI for the Unitree G1 humanoid robot.

The CLI is a thin client. A long-running daemon (`unitree daemon start`)
holds the DDS connection to the robot. If the daemon is not running the
CLI falls back to a short-lived in-process client (slower, useful for
single commands).

The manifest (see `manifest.txt`) is both the `unitree --help` output and
the system-prompt fragment injected into an LLM-driven agent. Human
debugging and agent execution use the exact same command surface.
"""
__version__ = "0.1.0"
