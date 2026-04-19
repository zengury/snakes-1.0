# Snakes 1.0 — Agent Runtime for Robots

## What is this

"Claude Code for Robotics" — a runtime that lets LLM agents run on robot hardware. Turns a skilled robot into a cognitive robot that knows who it is, learns by doing, consolidates skills, and has memory.

**Terminal goal**: accumulate the world's largest cognitive-physical aligned dataset through deployed robots, then train the best VLA on it.

## Architecture (3-layer monorepo)

### Skeleton (Agent Runtime Core, scenario-agnostic)
```
snakes/    — Agent loop (Python port of Pi's agent-loop.ts)
sdk2cli/   — CLI + daemon + manifest for 37 robots (to be merged)
memkit/    — 6-layer memory + critic pipeline (to be merged from zengury/memory)
eventlog/  — Unified event log (physical + cognitive + command)
roles/     — Role overlays (hackathon.md, barista.md, ...)
```

### Training Method (vla2cli)
```
vla2cli/   — Extract from VLA datasets → CLI commands / LLM fine-tune data
```

### Applications
```
apps/diagnosis/ — Robot maintenance CLI (to be merged from zengury/mcp-ros-diagnosis)
apps/hackathon/ — Escape room scenarios (3 levels + scoring)
```

## Key Design Decisions (DO NOT VIOLATE)

1. **CLI `--help` IS the LLM system prompt** — 200 tokens vs MCP's 5000. Never switch to MCP.
2. **ROBOT.md = robot's CLAUDE.md** — loaded into system prompt at every run.
3. **EventLog is the single source of truth** — replaces both old EventLog (mcp) and Episodic (memkit). One JSONL stream, physical+cognitive aligned by task_id.
4. **memkit only does learning, not storage** — reads from EventLog, promotes to Semantic/Fleet/Safety via Critic pipeline.
5. **VLA is a callable skill, not a competitor** — sits inside Skill Engine alongside trajectory replay and RL policies.
6. **Failures are assets** — every failure is annotated (phenomenon + reason) and retained as VLA training data. Only "harm humans" is an absolute red line.
7. **Writes are earned** — nothing enters Semantic memory without passing Quarantine → Critic review.
8. **Fleet memory is validation-gated** — K robots must confirm before knowledge goes fleet-wide.

## Data Flywheel (the real strategy)

```
Robots run tasks → EventLog captures physical trajectories + reasoning chains
→ memkit Critic: success → Semantic skill / failure → annotated training data
→ scripts/export_dataset.py → LeRobot/RLDS format
→ Train VLA → deploy as skill → robots perform better → more data → better VLA
```

This dataset is unique because it aligns physical trajectories with reasoning chains at ms resolution. Google has trajectories but no reasoning. OpenAI has reasoning but no trajectories. Only Snakes has both.

## Related Repos (all by zengury)

| Repo | Role | Merge status |
|------|------|-------------|
| `zengury/memory` | memkit 6-layer memory | To merge (Week 1-2 of MERGE_PLAN) |
| `zengury/mcp-ros-diagnosis` | MCP diagnostic servers + EventLog | To merge (Week 1) |
| `zengury/sdk2cli` | CLI for 37 robots | To merge (Week 1) |
| `zengury/cli-enhanced` | Hackathon escape room | Already ported to scenarios/ |
| `zengury/snakes-pi-platform` | Pi agent loop reference | Architecture ported to snakes/loop.py |

## Target Robot

**AGIBOT X2** (30 DOF humanoid, Pure ROS2, aimdk_msgs). All Python. Mock backend for development.

## Target Scenario

**Escape room hackathon for students** with 3 levels:
- L1 Explorer: navigate + remember layout
- L2 Investigator: find clues + solve puzzle
- L3 Escapist: multi-room escape with skill creation

## Current Status

- [x] Agent loop (Pi port) — 20 tests passing
- [x] EventLog unified schema + writer/reader — 8 tests passing
- [x] Escape room scenarios + scoring
- [x] ARCHITECTURE.md + MERGE_PLAN.md
- [ ] Merge sdk2cli, memkit, mcp into monorepo
- [ ] First end-to-end run with real LLM
- [ ] First learned skill (fail → succeed → consolidate)

## Tests

```bash
pip install -e ".[dev]"
pytest  # 28 passed
```

## Convention

- All Python, >=3.9, `from __future__ import annotations`
- Use dataclasses, asyncio, typing
- No comments unless the WHY is non-obvious
- ROBOT.md per robot, EventLog per deployment
