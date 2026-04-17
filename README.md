# Snakes 1.0

**Agent Runtime for Robots — Claude Code for Robotics**

Give an LLM a robot shell. Let it explore, learn, remember, and consolidate skills.

## Quick Start

```bash
pip install -e ".[dev]"
pytest
snakes run --robot agibot-x2 --scenario escape-room --level 1
```

## What is this?

Snakes is a harness that lets LLM agents run on robot hardware to complete complex, long-horizon, exploratory tasks. It combines:

- **Pi-style agent loop** — prompt → stream → tool call → verify → loop
- **6-layer memory** (memkit) — reflex, episodic, quarantine, semantic, fleet, safety
- **sdk2cli** — unified robot CLI where `--help` IS the system prompt
- **ROBOT.md** — robot self-model (like CLAUDE.md for Claude Code)

## Hackathon: Escape Room

Three levels for student teams:

| Level | Challenge | Score by |
|-------|-----------|----------|
| 1. Explorer | Walk around, remember room layout | Map accuracy |
| 2. Investigator | Find clues, solve a puzzle | Clues found, time |
| 3. Escapist | Multi-room escape with skill creation | Puzzles, skills, memory use |

```bash
snakes hackathon start --level 1 --team "team-alpha"
snakes hackathon score
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## License

MIT
