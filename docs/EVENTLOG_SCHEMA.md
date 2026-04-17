# EventLog Schema Specification

The unified event log — Snakes' single source of truth for everything that happens to/in a robot.

Replaces both:
- `EventLog` from `mcp-ros-diagnosis` (physical events)
- `Episodic` layer from `memkit` (cognitive events)

Written to: `mcp/storage/eventlog/<YYYY-MM-DD>.jsonl` (rotating daily)

## Design Principles

1. **Append-only, never modified** — immutability enables replay + audit
2. **JSONL** — one entry per line, streaming-friendly, tool-agnostic
3. **Millisecond-aligned** — physical and cognitive events share timestamps
4. **task_id groups related events** — enables per-task retrieval for critic review
5. **Outcome labeled at task end** — set by the agent loop when task concludes
6. **Self-describing** — all context (physical + cognitive) in one record

## Entry Schema

```python
from dataclasses import dataclass
from typing import Literal, Optional

Source = Literal["physical", "cognitive", "safety", "command"]
Severity = Literal["info", "warn", "critical"]
Outcome = Literal["success", "failure", "partial"]

@dataclass
class EventLogEntry:
    # Identity
    ts: str                        # ISO-8601 UTC, e.g. "2026-04-17T10:30:00.123Z"
    seq: int                       # monotonic per daemon session
    session_id: str                # daemon session (regenerated on restart)
    robot_id: str                  # e.g. "unitree-g1-001"
    task_id: Optional[str] = None  # groups related events
    
    # Classification
    source: Source = "cognitive"
    severity: Severity = "info"
    tags: list[str] = None         # e.g. ["grasp", "milk-2L", "aisle-3"]
    
    # Payloads (at most one non-None per entry)
    physical: Optional[dict] = None
    cognitive: Optional[dict] = None
    safety: Optional[dict] = None
    command: Optional[dict] = None
    
    # Outcome (populated at task end by agent loop)
    outcome: Optional[Outcome] = None
    failure_reason: Optional[str] = None       # e.g. "grasp_slipped"
    failure_phenomenon: Optional[str] = None   # e.g. "object slipped 5cm during lift"
    
    # Agent correlation (optional, for cross-system tracing)
    trace_id: Optional[str] = None
    user: Optional[str] = None                 # "cli" | "agent-claude" | "repl"
    latency_us: Optional[int] = None
```

## Payload Structures

### physical

Written by `mcp/` servers (manastone-joints, -power, -imu, etc.).

```python
physical = {
    "joints": {                    # from manastone-joints @ 500Hz
        "q": [0.0, -0.66, ...],    # positions (rad)
        "dq": [...],               # velocities (rad/s)
        "tau_est": [...],          # torque estimates (Nm)
        "temperature": [...],      # celsius
    },
    "imu": {                       # from manastone-imu @ 500Hz
        "accel": [ax, ay, az],     # m/s^2
        "gyro": [gx, gy, gz],      # rad/s
        "quaternion": [w, x, y, z],
    },
    "power": {                     # from manastone-power @ 10Hz
        "battery_soc": 0.78,
        "voltage": 48.2,
        "current_draw": 3.5,
    },
    "foot_force": [100, 95, 88, 102],  # if quadruped or bipedal
}
```

**Rate:** Physical events can be high-frequency. Writer buffers and batches. Safety-critical fields (e.g. joint temp exceeding threshold) bypass rate limits.

### cognitive

Written by `snakes/loop.py` during agent execution.

```python
cognitive = {
    "turn": 3,
    "reasoning": "I need to approach from the top to avoid collision with neighboring bottles.",
    "tool_call": {
        "name": "skill.grasp",
        "arguments": {
            "target": "milk-2L",
            "approach": "top",
            "pose": {"x": 1.23, "y": 0.45, "z": 1.2}
        }
    },
    "tool_result": {
        "success": True,
        "duration_ms": 2340,
        "final_pose": {...}
    },
    "streaming_partial": False,
}
```

### safety

Written when safety layer intervenes.

```python
safety = {
    "rule": "never_exceed_0.3mps_near_humans",
    "triggered_by": "commanded_velocity=0.8mps",
    "action": "blocked" | "clamped" | "warned",
    "original_command": {...},
    "modified_command": {...}
}
```

### command

Written by `sdk2cli/` daemon.

```python
command = {
    "cmd": "walk",
    "args": {"vx": 0.3, "vy": 0, "vyaw": 0},
    "executor": "daemon" | "local",
    "exit_code": 0,
    "stdout": "...",
    "stderr": "",
}
```

## Task Grouping

The agent loop assigns a unique `task_id` at the start of a user request and propagates it through every subsequent physical / cognitive / command event via context.

```python
# snakes/loop.py
async def run_agent_loop(prompts, context, config, emit):
    task_id = generate_task_id()  # e.g. "task-abc-20260417-103000"
    context.task_id = task_id
    eventlog.bind_task(task_id)   # propagates to mcp + sdk2cli
    try:
        ...
    finally:
        eventlog.set_outcome(task_id, outcome="success")
        eventlog.unbind_task()
```

## Example Complete Task

```jsonl
{"ts":"2026-04-17T10:30:00.000Z","seq":1,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","tags":["task_start"],"cognitive":{"reasoning":"User asked me to get milk. Let me plan.","turn":0}}
{"ts":"2026-04-17T10:30:01.200Z","seq":2,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","cognitive":{"turn":1,"tool_call":{"name":"skill.walk","arguments":{"to":"aisle-3"}}}}
{"ts":"2026-04-17T10:30:01.250Z","seq":3,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"command","command":{"cmd":"walk","args":{"to":"aisle-3"},"executor":"daemon","exit_code":0}}
{"ts":"2026-04-17T10:30:01.450Z","seq":4,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"physical","physical":{"joints":{"q":[0.0,0.1,...]},"imu":{"accel":[0.02,9.81,0.01]}}}
// ... more physical events during walking ...
{"ts":"2026-04-17T10:30:18.500Z","seq":247,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","cognitive":{"turn":2,"tool_call":{"name":"skill.grasp","arguments":{"target":"milk-2L"}}}}
{"ts":"2026-04-17T10:30:20.840Z","seq":289,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","cognitive":{"turn":2,"tool_result":{"success":false,"reason":"slipped"}}}
{"ts":"2026-04-17T10:30:21.000Z","seq":290,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","cognitive":{"turn":3,"reasoning":"Grasp slipped. Let me try a higher grip point."}}
// ... retry succeeds ...
{"ts":"2026-04-17T10:30:45.000Z","seq":412,"session_id":"s1","robot_id":"g1-01","task_id":"t-abc","source":"cognitive","tags":["task_end"],"outcome":"success","cognitive":{"reasoning":"Milk delivered to customer."}}
```

## Querying EventLog

```python
from mcp.eventlog import EventLogReader

reader = EventLogReader("mcp/storage/eventlog/")

# All events for one task
entries = reader.query(task_id="t-abc")

# Only failures for grasp tasks in last 24h
failures = reader.query(
    tags=["grasp"],
    outcome="failure",
    since="2026-04-16T10:00:00Z"
)

# Physical trajectory of a specific task
trajectory = reader.get_trajectory(task_id="t-abc", field="joints.q")

# Reasoning chain of a specific task
chain = reader.get_reasoning_chain(task_id="t-abc")
```

## Rotation and Retention

- **File rotation:** daily, UTC boundaries (`2026-04-17.jsonl`)
- **Compression:** files older than 7 days → `.jsonl.gz`
- **Retention:** keep 90 days locally, offload older to object storage
- **Export for training:** scripts/export_dataset.py reads archived files

## Privacy / Security

- **Robot ID is not PII** — but `user` field may be. Hash or redact for dataset export.
- **Camera images are NOT stored inline** — physical payload references hash + S3 path
- **Reasoning chains may reveal user goals** — filter `trace_id` and `user` on export

## Replay

```bash
snakes replay --eventlog path/to/2026-04-17.jsonl --speed 2x
# Replays a task through the daemon, useful for:
# - Regression testing after code changes
# - Reproducing bugs reported by fleet
# - Debugging why a task failed
```

Replay respects policy.yaml — danger commands still require approval unless `--force`.
