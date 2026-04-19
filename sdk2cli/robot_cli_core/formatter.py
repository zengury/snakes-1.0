"""Dual output: --format json (agent) or --format text (human). Shared by all robots."""
from __future__ import annotations
import json, os, sys
from typing import Any

class Formatter:
    def __init__(self, mode: str | None = None, file=None) -> None:
        self.mode = mode or os.environ.get("ROBOT_FORMAT", "json")
        self.file = file or sys.stdout

    def emit(self, value: Any) -> None:
        if self.mode == "text":
            self._text(value)
        else:
            self.file.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.file.flush()

    def _text(self, value: Any) -> None:
        if isinstance(value, dict):
            skip = {"timestamp", "backend"}
            items = [(k, v) for k, v in value.items() if k not in skip]
            if len(items) <= 6:
                self.file.write("  ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in items) + "\n")
            else:
                mx = max(len(k) for k, _ in items)
                for k, v in items:
                    self.file.write(f"  {k:<{mx}}  {v:.4f}\n" if isinstance(v, float) else f"  {k:<{mx}}  {v}\n")
        elif isinstance(value, list):
            for item in value:
                self._text(item)
        else:
            self.file.write(f"{value}\n")
