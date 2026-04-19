"""vla2cli — Extract Snakes-usable datasets from VLA training corpora.

Purpose:
- Convert VLA training data (LeRobot, Open X-Embodiment, DROID, Octo)
  into Snakes' EventLog format with derived reasoning chains.
- Export CLI command templates from successful trajectories (each
  successful demo → a reusable skill + CLI wrapper).
- Prepare data for local LLM fine-tuning so smaller models output
  correct sdk2cli parameters with high accuracy.

Three outputs:
1. CLI commands (trajectory replay skills)
2. EventLog-format training data (for Snakes' own learning loop)
3. LLM fine-tune data (prompt → CLI command pairs)
"""
from __future__ import annotations

__version__ = "0.1.0"
