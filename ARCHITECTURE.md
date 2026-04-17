# Snakes Architecture

**Agent Runtime for Robots — Claude Code for Robotics**

## Vision

Snakes turns a "skilled robot" (can walk, can grasp) into a "cognitive robot" (knows who it is, what it can do, learns by doing, remembers, consolidates skills).

Like Claude Code gave LLMs a coding harness (shell + memory + tools + safety), Snakes gives LLMs a robotics harness (CLI + memory + sensors + safety).

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Snakes Runtime                         │
│                                                             │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐│
│  │  Gateway    │  │  Agent Loop  │  │     Memory           ││
│  │            │  │  (Pi-style)  │  │    (memkit)          ││
│  │ LLM conn   │  │             │  │                      ││
│  │ Auth       │  │ Prompt      │  │ Reflex    <10ms      ││
│  │ Human-in-  │  │ Stream      │  │ Episodic  <5ms       ││
│  │  the-loop  │  │ Tool Call   │  │ Quarantine           ││
│  │            │  │ Verify      │  │ Semantic  (固化)     ││
│  └─────┬──────┘  │ Loop        │  │ Fleet     (多机共享)  ││
│        │         │             │  │ Safety    (永不衰减)  ││
│        │         │ Steering Q  │  │                      ││
│        │         │ FollowUp Q  │  │ Critic Pipeline      ││
│        ▼         └──────┬──────┘  └──────────┬───────────┘│
│  ┌──────────────────────▼────────────────────▼───────────┐ │
│  │                  Skill Engine                         │ │
│  │  Trajectory Replay │ RL/MPC Control │ VLA Model       │ │
│  │  Coordinator (resource arbitration)                   │ │
│  │  Safety Arbiter (single output gate)                  │ │
│  └──────────────────────┬────────────────────────────────┘ │
│  ┌──────────────────────▼────────────────────────────────┐ │
│  │              sdk2cli Layer                            │ │
│  │  CLI + Daemon + Manifest + ROBOT.md                   │ │
│  └──────────────────────┬────────────────────────────────┘ │
└─────────────────────────┼───────────────────────────────────┘
                          │
                ┌─────────▼──────────┐
                │   DDS / ROS2 Bus   │
                │  AGIBOT X2 (30DOF) │
                └────────────────────┘
```

## Layers

### 1. sdk2cli (I/O Layer)

CLI commands are the tool interface for the LLM agent.

- `robot <name> <command>` — uniform across all robots
- `manifest.txt` = LLM system prompt (96% token reduction vs MCP)
- `ROBOT.md` = robot self-model (like CLAUDE.md)
- Daemon for persistent state (0.24ms p99)
- Safety validation on every command

### 2. Memory (memkit)

Six-layer memory with critic pipeline:

| Layer | Latency | Purpose |
|-------|---------|---------|
| Reflex | <10ms | Current sensor state (ring buffer) |
| Episodic | <5ms | Current task log |
| Quarantine | — | Unverified new experience |
| Semantic | ms | Consolidated knowledge |
| Fleet | s | Multi-robot shared knowledge |
| Safety | <1ms | Rules that never decay |

Writes are earned: experience → quarantine → critic review → promotion.

### 3. Agent Loop (Pi-style)

Python port of Pi's agent-loop architecture:

```
Prompt → Stream LLM → Extract Tool Calls → Execute Tools
  ↑                                              │
  │        ┌──── Steering Queue (mid-turn) ◄─────┤
  │        │                                      │
  └────────┤     Follow-up Queue (after turn) ◄───┘
           │
           └──── Observe Robot State (verify) ──→ Memory
```

Key hooks:
- `before_tool_call` — safety checks, permission gates
- `after_tool_call` — memory writes, state diff observations
- `observe_robot_state` — verify physical outcome after each action

### 4. Gateway

LLM connection management, auth, human-in-the-loop collaboration.

### 5. Scenarios

Hackathon escape room with three levels:
- Level 1 "Explorer": Walk, observe, remember room layout
- Level 2 "Investigator": Find clues, solve a puzzle
- Level 3 "Escapist": Multi-room, multi-puzzle escape with skill creation

## Data Flow: "Find the key"

```
User: "Find the key hidden in the room"
  │
  ▼
1. Context Assembly
   - Load ROBOT.md → system prompt
   - Query Semantic memory → "last time key was under the blue cup"
   - Load Safety rules → "never force-open locked containers"
   - Load manifest → available tools
  │
  ▼
2. Agent Loop Turn 1
   LLM: "I'll look around first."
   Tool call: camera.get → room description
   Observe: see desk, cup, bookshelf, rug
   Memory write (Episodic): "Looked around, saw 4 objects"
  │
  ▼
3. Agent Loop Turn 2
   LLM: "Memory says key might be under cup. Let me check."
   Tool call: arm.interact target=blue_cup action=lift
   Observe: key found under cup!
   Memory write (Episodic): "Found key under blue cup"
  │
  ▼
4. Agent Loop Turn 3
   LLM: "Got the key. Task complete."
   Stop reason: end_turn (no more tool calls)
  │
  ▼
5. Consolidation
   Critic reviews episode:
   - Success? Yes → promote to Semantic
   - New knowledge: "key is under blue cup in this room"
   - Next time: agent retrieves this directly
```

## ROBOT.md Specification

```markdown
# I am [Robot Name], serial [Serial]

## What I am
- [DOF] DOF [type], [manufacturer]
- Onboard: [compute], [sensors]

## What I can do
### Always available
- [list of hardcoded skills]
### Learned (from Semantic memory)
- [dynamically populated]
### External models
- skill.vla: [DEPLOYED/NOT DEPLOYED]
- skill.dialog: [enabled/disabled]

## What I know
- [populated from Semantic memory at boot]

## Where I am
- Location: [location]
- Battery: [%]

## What I'm doing
- Current task: [task or idle]
- Resources claimed: [list]

## Who I serve
- Owner: [owner]
- Emergency stop: [methods]
```

## Safety Architecture

1. **Joint limits** (sdk2cli) — every actuator command validated
2. **Safety memory layer** (memkit) — rules that never decay, human-reviewed
3. **before_tool_call hook** — blocks dangerous commands
4. **Policy.yaml** — per-command risk levels, approval gates
5. **Physical mistakes are data** — captured in Episodic, reviewed by Critic
6. **Absolute red line** — harming humans is prevented by Safety layer rules

## Technology

| Component | Technology |
|-----------|-----------|
| Agent Loop | Python 3.9+, asyncio |
| LLM Client | anthropic SDK, openai SDK |
| Memory | memkit (6-layer, SQLite) |
| Robot I/O | sdk2cli (CLI + daemon) |
| DDS Bridge | memkit-adapter-dds |
| Tests | pytest, pytest-asyncio |

## File Structure

```
snakes-1.0/
├── ARCHITECTURE.md
├── pyproject.toml
├── snakes/
│   ├── __init__.py      # Exports
│   ├── agent.py         # Stateful Agent class
│   ├── loop.py          # Core agent loop (Pi port)
│   ├── types.py         # Type definitions
│   ├── context.py       # Context assembly
│   ├── tools.py         # Robot CLI → Agent tools
│   ├── robot_md.py      # ROBOT.md management
│   ├── llm_client.py    # Anthropic/OpenAI client
│   ├── memory_bridge.py # memkit integration
│   └── cli.py           # Entry point
├── scenarios/
│   ├── escape_room.py   # Room/puzzle engine
│   ├── x2_mock.py       # X2 mock for hackathon
│   └── scoring.py       # Hackathon scoring
└── tests/
    ├── conftest.py
    ├── test_loop.py
    ├── test_tools.py
    └── test_scenario.py
```
