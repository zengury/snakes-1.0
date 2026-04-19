"""Dual output formatter: JSON (for agents) and text (for humans).

Usage:
    fmt = Formatter(mode="json")   # or "text"
    fmt.emit({"joint": "LeftKnee", "q": 1.5, "temperature": 28.1})

JSON mode: one JSON object per line (default, agent-friendly).
Text mode: aligned key=value pairs (human-friendly).

Set via --format flag or UNITREE_FORMAT env var.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any


class Formatter:
    def __init__(self, mode: str | None = None, file=None) -> None:
        self.mode = mode or os.environ.get("UNITREE_FORMAT", "json")
        self.file = file or sys.stdout

    def emit(self, value: Any) -> None:
        if self.mode == "text":
            self._emit_text(value)
        else:
            self.file.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.file.flush()

    def _emit_text(self, value: Any) -> None:
        if isinstance(value, dict):
            # Skip internal fields
            skip = {"timestamp", "backend"}
            items = [(k, v) for k, v in value.items() if k not in skip]
            if not items:
                return
            # Single-line for small dicts, table for large
            if len(items) <= 6:
                parts = []
                for k, v in items:
                    if isinstance(v, float):
                        parts.append(f"{k}={v:.4f}")
                    else:
                        parts.append(f"{k}={v}")
                self.file.write("  ".join(parts) + "\n")
            else:
                max_k = max(len(k) for k, _ in items)
                for k, v in items:
                    if isinstance(v, float):
                        self.file.write(f"  {k:<{max_k}}  {v:.4f}\n")
                    else:
                        self.file.write(f"  {k:<{max_k}}  {v}\n")
        elif isinstance(value, list):
            for item in value:
                self._emit_text(item)
                if isinstance(item, dict) and len(item) > 6:
                    self.file.write("\n")  # separator between large records
        else:
            self.file.write(f"{value}\n")
