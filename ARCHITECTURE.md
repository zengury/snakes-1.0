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

## File Structure (Target Monorepo)

```
snakes-1.0/
├── ARCHITECTURE.md
├── MERGE_PLAN.md             # path to consolidate sub-projects
├── pyproject.toml
│
├── snakes/                   # Agent Runtime core
│   ├── agent.py, loop.py, types.py
│   ├── context.py, tools.py
│   ├── robot_md.py, llm_client.py
│   ├── memory_bridge.py
│   └── cli.py
│
├── sdk2cli/                  # [merged from sdk2cli-registry]
│   ├── robot_cli_core/
│   └── robots/               # 37 robots
│
├── memkit/                   # [merged from zengury/memory]
│   ├── layers/               # Reflex, Semantic, Quarantine, Fleet, Safety
│   ├── critic/               # RuleBased + LLM critic
│   └── learner.py            # learns from EventLog
│
├── mcp/                      # [merged from zengury/mcp-ros-diagnosis]
│   ├── servers/              # manastone-joints, -power, -imu, ...
│   ├── eventlog/             # UNIFIED event log (replaces Episodic too)
│   ├── schema/               # robot_schema.yaml
│   └── bridge/               # DDS ↔ EventLog
│
├── scenarios/                # [merged from cli-enhanced]
│   ├── escape_room/
│   ├── retail/               # future
│   └── scoring.py
│
├── gateway/                  # future: LLM auth + multi-model
│
├── scripts/
│   └── export_dataset.py     # EventLog → VLA training set
│
└── tests/
```

---

## The Data Flywheel (Grand Strategy)

The terminal goal is not a working runtime — it's the world's largest cognitive-physical aligned dataset, and a VLA trained on it.

```
1,000s of deployed Snakes robots run tasks
    │
    ├── sdk2cli   → command events    ┐
    ├── snakes    → cognitive events  ├── EventLog (unified)
    └── mcp       → physical events   ┘
                                       │
                                       ▼
                              memkit Critic Pipeline
                                       │
                    ┌──────────────────┴──────────────────┐
                    │                                     │
             Success → Semantic                    Failure → annotated
             (as reusable skill)              (phenomenon + reason)
                    │                                     │
                    └──────────────┬──────────────────────┘
                                   │
                                   ▼
                    scripts/export_dataset.py
                                   │
                                   ▼
                    Training corpus (LeRobot / RLDS / custom)
                    - trajectory + torque + IMU (500Hz)
                    - task labels
                    - reasoning chains
                    - success/failure labels
                    - environment context
                                   │
                                   ▼
                       Train VLA (π0/OpenVLA/RT-2-like)
                                   │
                                   ▼
                    Deploy VLA as `skill.vla` in sdk2cli
                                   │
                                   ▼
                         flywheel spins faster
```

**Why this dataset is unique:**
- Google/Nvidia: trajectories but no reasoning chains
- OpenAI/Anthropic: reasoning but no physical trajectories
- **Snakes: both, aligned at millisecond resolution, from real deployments**

---

## Unified EventLog (Replaces Episodic + EventLog)

One canonical append-only stream. Written by mcp (physical), snakes agent loop (cognitive), and sdk2cli (commands). Read by memkit.Critic for learning and scripts/export_dataset.py for VLA training.

```python
@dataclass
class EventLogEntry:
    ts: str                # ISO-8601 UTC with ms
    seq: int               # monotonic per daemon session
    robot_id: str
    task_id: str | None    # optional task grouping
    
    # Classification
    source: Literal["physical", "cognitive", "safety", "command"]
    severity: Literal["info", "warn", "critical"]
    tags: list[str]
    
    # Physical (from mcp/)
    physical: dict | None  # {joints: [...], torque: [...], imu: {...}, temps: {...}}
    
    # Cognitive (from snakes agent loop)
    cognitive: dict | None  # {reasoning: "...", tool_call: {...}, tool_result: {...}}
    
    # Command (from sdk2cli)
    command: dict | None    # {cmd: "walk", args: {...}, executor: "daemon"}
    
    # Outcome (added when task ends)
    outcome: Literal["success", "failure", "partial"] | None
    failure_reason: str | None       # e.g. "grasp_slipped"
    failure_phenomenon: str | None   # e.g. "object fell from gripper at 3cm lift"
```

Full spec in `docs/EVENTLOG_SCHEMA.md`.

**Key design:** Physical and cognitive events share `task_id` and timestamps, so memkit can automatically align reasoning chains with joint trajectories. No post-hoc join needed. This is the property that makes the exported dataset unique.

---

## memkit's New Role (Learning, Not Storage)

With EventLog taking over raw log storage, memkit focuses on:

1. **Critic Pipeline** — reads EventLog, decides what becomes skill
2. **Semantic layer** — consolidated, queryable knowledge
3. **Quarantine** — holding tank for new experiences pending review
4. **Fleet** — cross-robot validated knowledge broadcast
5. **Safety** — hardcoded rules + rules promoted from recurring failures
6. **Reflex** — real-time sensor snapshots (unchanged)

The old `Episodic` layer is replaced by a **view** over EventLog:

```python
# Before:
memory.episodic.get_recent(n=20)

# After:
eventlog.query(task_id=current_task, limit=20)
```

---

## Success/Failure Semantics

**Success path** (promotes knowledge):
```
Task completes → EventLog entries marked outcome="success" 
→ Critic extracts: trajectory + reasoning + environment
→ If novel and repeatable → Quarantine (24h holding)
→ If still holds after review → Semantic (becomes skill)
→ If K fleet-members confirm → Fleet (broadcast)
```

**Failure path** (preserves data):
```
Task fails → EventLog entries marked outcome="failure"
→ Critic demands phenomenon + reason annotations:
   phenomenon: "瓶身从指尖滑落 5cm"
   reason: "grasp pose too low"
   physical_context: <joint + torque snapshot>
   cognitive_context: <reasoning chain that led here>
→ Data retained as VLA training signal
→ If recurring → propose new Safety rule
```

**This is why failures are assets, not bugs.** Every failure is annotated, preserved, and contributes to either:
- Next attempt's plan (via memkit.Semantic query)
- Future VLA training (via dataset export)
- New Safety rule (via recurrence detection)

---

## Current Status

- [x] snakes/ — Agent runtime core, 20/20 tests passing
- [x] sdk2cli-registry — separate repo, ready to merge
- [x] memkit (memory repo) — separate repo, ready to merge
- [x] mcp-ros-diagnosis — separate repo, ready to merge
- [x] cli-enhanced — separate repo, ready to merge
- [ ] Monorepo consolidation (see MERGE_PLAN.md)
- [ ] Unified EventLog implementation
- [ ] scripts/export_dataset.py
- [ ] First real robot run
- [ ] First learned skill promoted Semantic → reused

See `MERGE_PLAN.md` for the step-by-step consolidation plan.
