# memkit

A reusable memory architecture for agent runtimes — designed first for
robotics (dual-loop, latency-critical), but project-agnostic enough to drop
into any long-running agent.

**Version:** 0.2.0 · **Tests:** 109 passing · **Dependencies:** stdlib only
(plus `pytest` + `pytest-asyncio` for the test suite)

## Why

Agent runtimes need memory that is:

- Fast enough for a real-time control loop (reflex)
- Durable enough to survive restarts (episodic, semantic, quarantine)
- Shareable across robots without contamination (fleet, validation-gated)
- Safe — with a synchronous gate that blocks unsafe commands before they reach
  the robot
- Project-agnostic — no robotics-specific code in the core

memkit gives you all five behind one small facade.

## Install

```bash
pip install -e .                 # core
pip install -e ".[test]"         # with pytest + pytest-asyncio
```

## Quick start (synchronous)

```python
from memkit import Memory, MemoryConfig, Command, Outcome, SafetyRule, Severity

mem = Memory.from_config(MemoryConfig.local_only(
    data_dir="./memkit_data",
    agent_id="robot_01",
))

# Install a safety rule
mem.safety.add_rule(SafetyRule(
    rule_id="safety_human_nearby",
    severity=Severity.HARD_STOP,
    context_predicate={"fact": "human_in_envelope", "value": True},
    forbidden_command_pattern="nav.*",
))

# Hot path — snapshot reflex state each tick
mem.reflex.snapshot({"human_in_envelope": False, "battery_pct": 72})

# Task lifecycle
ep = mem.begin_task("task_1", env_fingerprint="indoor_residential")

cmd = Command(name="arm.grasp", params={"target": "handle", "force": 12})
mem.check_command(cmd)                            # raises SafetyViolation if blocked
mem.record_command(ep.episode_id, cmd)
# ... execute cmd ...
mem.record_result(ep.episode_id, cmd, Outcome.SUCCESS)

mem.end_task(ep.episode_id, Outcome.SUCCESS)      # auto-bundles into quarantine

# Slow path — critic promotes durable skills
mem.process_quarantine()

# Plan a new task using learned skills
skills = mem.query_skills(environment_class="indoor_residential")
```

## Async usage

For asyncio-based runtimes — the fast path stays sync (no value in making
a 1µs rule check awaitable), blocking I/O goes through a thread pool.

```python
from memkit import AsyncMemory, MemoryConfig, Command, Outcome

amem = AsyncMemory.from_config(MemoryConfig.local_only(data_dir="./data"))

# Fast path: still synchronous on purpose
amem.reflex.snapshot({"battery_pct": 80})
amem.check_command(cmd)

# Slow path: async
ep = await amem.begin_task("task_1", env_fingerprint="indoor_residential")
await amem.record_command(ep.episode_id, cmd)
await amem.record_result(ep.episode_id, cmd, Outcome.SUCCESS)
await amem.end_task(ep.episode_id, Outcome.SUCCESS)

await amem.process_quarantine()
skills = await amem.query_skills(environment_class="indoor_residential")
```

## Fleet memory (cross-robot learning)

Fleet memory is validation-gated: a skill surfaces in `fleet.query()` only
after K distinct agents have contributed it. Prevents one bad robot from
polluting the fleet.

```python
# Robot A and Robot B share a fleet DB
config_a = MemoryConfig(
    data_dir="./robot_a",
    fleet_db_path="/shared/fleet.db",
    agent_id="robot_a",
)
config_b = MemoryConfig(
    data_dir="./robot_b",
    fleet_db_path="/shared/fleet.db",
    agent_id="robot_b",
)

# When either robot's critic promotes a skill locally, it's auto-contributed
# to the fleet under that robot's agent_id.

# Robot C (a fresh robot) queries fleet — gets validated skills back
robot_c = Memory.from_config(MemoryConfig(
    data_dir="./robot_c",
    fleet_db_path="/shared/fleet.db",
    agent_id="robot_c",
))
skills = robot_c.query_skills(
    environment_class="indoor_residential",
    include_fleet=True,     # merges local + fleet
)
```

See `examples/fleet_demo.py` for a runnable demonstration.

## Architecture

| Layer | Read latency | Write path | Retention |
|---|---|---|---|
| **Reflex** (ring buffer) | <10ms | Direct sync | Overwrite |
| **Episodic** (SQLite or in-memory) | <5ms | Direct async | Task-completion + TTL |
| **Quarantine** (SQLite or in-memory) | n/a | Bundled on task end | 24h if unreviewed |
| **Semantic** (SQLite or in-memory) | ms | Critic-promoted only | Confidence decay |
| **Fleet** (SQLite or in-memory) | s | Critic-promoted only | Validation-threshold gated |
| **Safety Gate** (rule-based) | <1ms sync | Human review only | Never decays |

### Design principles

1. **Memory is stratified by latency budget, not by semantics.** Layers are
   defined by their access latency envelope.
2. **Safety is a separate subsystem.** Synchronous, rule-based, structured.
   Never driven by embedding similarity.
3. **Writes are earned.** Every durable memory passes through quarantine →
   critic → promotion. The fast loop never writes to semantic memory.
4. **Granularity matches action granularity.** Skills are indexed by command
   sequences (name + param keys), not by free-text descriptions.
5. **Forgetting is a feature.** Every layer has an explicit retention policy.
6. **Fleet memory is a first-class citizen.** Cross-agent learning is
   validation-gated from day one.

### The critic

`RuleBasedCritic` is the default — deterministic, used in tests and as a
cheap pre-filter. It detects:

- Failure outcomes → discard
- Anomaly flags → needs human review
- Exact signature match → merge into existing skill
- Near-duplicate (same commands, different params) with high-confidence
  existing → merge; with low-confidence → needs human review
- Contradiction (same signature, very different success rate vs.
  high-confidence existing) → needs human review

`LLMCritic` is LLM-agnostic — it takes a `call_llm: Callable[[str], str]`.
memkit has zero LLM SDK dependencies; projects wire in their own client.

```python
from memkit.critic import LLMCritic

def my_llm(prompt: str) -> str:
    # call anthropic/openai/local/whatever
    ...

mem.critic = LLMCritic(call_llm=my_llm)
```

## Package layout

```
memkit/
├── __init__.py              # public API
├── protocols.py             # Protocol interfaces + dataclasses
├── memory.py                # Memory facade
├── async_memory.py          # AsyncMemory wrapper
├── layers/
│   ├── reflex.py            # ring buffer
│   ├── episodic.py          # in-memory episodic
│   ├── quarantine.py        # in-memory quarantine
│   ├── semantic.py          # in-memory semantic
│   └── safety.py            # rule-based safety gate
├── stores/
│   ├── sqlite.py            # SQLiteEpisodicStore, SQLiteSemanticStore
│   └── sqlite_extras.py     # SQLiteQuarantineStore, SQLiteFleetStore, InMemoryFleetStore
└── critic/
    └── critic.py            # RuleBasedCritic, LLMCritic
```

## Running the tests and examples

```bash
python -m pytest tests/                    # 109 tests
python examples/escape_room.py             # single-robot demo
python examples/fleet_demo.py              # three-robot fleet demo
```

## Extending memkit

Every layer is a `Protocol`. To swap in a custom backend — say, PostgreSQL
for semantic memory, or Redis for reflex — implement the protocol and pass
it to the `Memory` constructor directly:

```python
from memkit import Memory
from memkit.layers import RingReflexStore, RuleBasedSafetyGate
from my_project.stores import MyPostgresSemanticStore

mem = Memory(
    reflex=RingReflexStore(capacity=512),
    episodic=...,
    quarantine=...,
    semantic=MyPostgresSemanticStore(dsn="..."),
    safety=RuleBasedSafetyGate(),
    critic=...,
)
```

## Status and known limitations

- **Single-node fleet store.** `SQLiteFleetStore` is single-machine. For
  real multi-robot deployment, you want an HTTP/gRPC fleet service. The
  protocol shape is the same — drop in a networked implementation.
- **No async at the storage layer.** `AsyncMemory` offloads to a thread
  pool. For very high concurrency, you'd want native async drivers
  (`aiosqlite`, `asyncpg`). Trivial to add — keeps the same protocol.
- **Critic is local-only for now.** The production pattern is to run the
  critic loop on the cloud side against a shared quarantine queue, not
  in-process. `process_quarantine()` is synchronous to make this refactor
  obvious when you get there.
