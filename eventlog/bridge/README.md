# memkit-adapter-dds

DDS ↔ [memkit](https://github.com/your-org/memkit) adapter. Routes robot
state from DDS topics into memkit's reflex layer, gates outbound commands
through memkit's safety layer, and records command lifecycles into the
active episode.

**Version:** 0.1.0 · **Tests:** 47 passing · **Core dependencies:**
memkit only (DDS bindings are optional)

## Why this exists

Dropping memkit into a real robot runtime creates two integration questions:

1. **How does robot state get into reflex memory?** DDS publishes state at
   hundreds of Hz on typed topics. Reflex needs a flat dict. There's a
   mismatch in schema, rate, and threading.
2. **How do outbound commands get gated by safety?** The runtime must be
   physically unable to publish a command without going through
   `mem.check_command()`.

This adapter handles both. It's intentionally small (~400 LOC) and has no
DDS-vendor dependency — you plug in Cyclone, RTI, FastDDS, or a mock.

## Design invariants

These are the rules the adapter enforces structurally:

1. **DDS callbacks only ever touch reflex.** Never episodic, never semantic,
   never critic. DDS threads must not block on SQLite or LLM calls.
2. **Every outbound command goes through `mem.check_command()` first.**
   There is one publish path: `adapter.emit_command()`. No bypass.
3. **Safety-critical state bypasses rate limits.** Fields flagged
   `safety_critical=True` apply even when the topic is rate-limited. Stale
   safety state is worse than bandwidth.
4. **Anomaly detection is structural, synchronous, in-thread.** No LLM in
   the DDS callback path — simple predicates only.

## Install

```bash
pip install -e .                 # core (pulls in memkit)
pip install -e ".[test]"         # with pytest
pip install -e ".[cyclone]"      # with Cyclone DDS backend (production)
```

## Quick start

```python
from memkit import Memory, MemoryConfig, Command, SafetyRule, Severity

from memkit_adapter_dds import (
    DDSAdapter, FakeDDSBus,
    TopicMapping, FieldMapping,
    AdapterConfig, AnomalyRule,
)

# 1. Build your memkit Memory as usual
mem = Memory.from_config(MemoryConfig.local_only(
    data_dir="./robot_data", agent_id="g1_alpha",
))
mem.safety.add_rule(SafetyRule(
    rule_id="safety_low_battery",
    severity=Severity.SOFT_STOP,
    context_predicate={"fact": "battery_pct", "below": 10},
    forbidden_command_pattern="nav.*",
    unless_params={"mode": "return_to_dock"},
))

# 2. Declare topic mappings — which DDS fields go to which reflex keys
mappings = [
    TopicMapping(
        topic="rt/lowstate",
        min_interval_s=0.02,  # 50Hz into reflex
        fields=[
            FieldMapping(reflex_key="battery_pct",
                         source_path="bms_state.soc",
                         safety_critical=True),
            FieldMapping(reflex_key="imu_temp",
                         source_path="imu_state.temperature"),
        ],
    ),
]

# 3. Wire the adapter to your DDS bus
bus = FakeDDSBus()  # or CycloneDDSBus(domain_id=0) in production
adapter = DDSAdapter(
    memory=mem,
    bus=bus,
    mappings=mappings,
    config=AdapterConfig(anomaly_rules=[
        AnomalyRule(
            name="battery_critical",
            reflex_key="battery_pct",
            check=lambda v: v is not None and v < 5,
        ),
    ]),
)
adapter.start()

# 4. Runtime: task lifecycle drives adapter's active episode
ep = mem.begin_task("task_1", env_fingerprint="indoor_residential")
adapter.set_active_episode(ep.episode_id)

# 5. Emit commands — all gated through safety, recorded into episode
adapter.emit_command(Command(name="nav.approach", params={"target": "door"}))

# 6. End the task
mem.end_task(ep.episode_id, Outcome.SUCCESS)
adapter.set_active_episode(None)
```

## Unitree G1 preset

Reference TopicMapping for the Unitree G1 humanoid, based on Unitree's DDS
IDL. Covers `rt/lowstate` (IMU, battery) and `rt/sportmodestate` (body state,
foot forces).

```python
from memkit_adapter_dds.presets.unitree_g1 import (
    default_g1_mappings,
    default_g1_anomaly_rules,
)

adapter = DDSAdapter(
    memory=mem,
    bus=bus,
    mappings=default_g1_mappings(),
    config=AdapterConfig(anomaly_rules=default_g1_anomaly_rules()),
)
```

The G1 preset flags `battery_pct` and `battery_temp_max` as
`safety_critical=True` — they always apply even when their topic is
rate-limited.

**Firmware versioning:** Unitree has shipped topic-name changes between SDK
revisions (e.g., `rt/lf/lowstate` vs. `rt/lowstate`). Treat the preset as a
starting point and check it matches your firmware.

## Key concepts

### TopicMapping

Declares how one DDS topic becomes reflex state updates.

- `topic`: DDS topic name to subscribe to
- `fields`: list of `FieldMapping`, one per reflex key
- `min_interval_s`: rate limit for this topic (0 = no limit)
- `merge`: if True, fields are merged into existing reflex state; if False,
  the snapshot replaces reflex state

**Multiple mappings on the same topic are auto-merged.** You can declare
`low_state_mapping` and `battery_mapping` both pointing at `rt/lowstate` —
the adapter combines them into one subscription.

### FieldMapping

One value extracted from a DDS message.

- `reflex_key`: destination key in reflex state
- `source_path`: dotted path into the message (e.g., `"imu_state.quaternion.0"`)
- `transform`: optional callable to convert the value
- `required`: if True, a missing field drops the entire snapshot
- `safety_critical`: if True, always applies regardless of rate limit

### AnomalyRule

Lightweight predicate evaluated on every reflex update. When the predicate
fires, an `anomaly` event is appended to the active episode — which feeds
into memkit's critic at task end.

```python
AnomalyRule(
    name="battery_critical",
    reflex_key="battery_pct",
    check=lambda v: v is not None and v < 5,
)
```

Keep these simple. LLM-based anomaly reasoning belongs in the slow loop,
not in the DDS callback thread.

## Performance

Measured on a standard x86 laptop:

- `mem.check_command()` with 10 safety rules: **~4 µs per call** (250 k
  calls/sec)
- Full adapter test suite: 47 tests in 0.4s

The safety gate is the adapter's tightest hot path. It's comfortable inside
a 1 kHz control loop's budget.

## Writing a real DDS backend

Any object that satisfies the `DDSBus` protocol works. The full surface:

```python
class DDSBus(Protocol):
    def subscribe(self, topic: str, callback: Callable[[dict], None]) -> None: ...
    def publish(self, topic: str, payload: dict) -> None: ...
    def unsubscribe(self, topic: str) -> None: ...
    def close(self) -> None: ...
```

For Cyclone DDS on the Unitree G1:

```python
# Sketch — your actual implementation depends on the IDL bindings
from cyclonedds.domain import DomainParticipant
from cyclonedds.sub import Subscriber, DataReader

class CycloneDDSBus:
    def __init__(self, domain_id: int = 0):
        self.participant = DomainParticipant(domain_id)
        self._readers = {}

    def subscribe(self, topic: str, callback):
        # Create a DataReader for `topic`, spawn a listener that
        # converts each sample to a dict and invokes callback(sample_dict)
        ...
```

Callbacks may run on DDS's own thread. The adapter is thread-safe where it
matters (stats, active episode) and the reflex layer is lock-free.

## Running tests and examples

```bash
python -m pytest tests/            # 47 tests
python examples/g1_session.py      # simulated G1 session (no real DDS)
```

The example walks through: healthy state → task start → command emit →
battery drop → safety block → anomaly recorded → task end.

## What this adapter does NOT do

- **Task lifecycle.** The runtime decides when a task begins and ends;
  the adapter just needs to be told via `set_active_episode()`.
- **Planning.** Slow-loop concern. Live above the adapter.
- **Critic promotion.** Happens in memkit, not here. Call
  `mem.process_quarantine()` from a separate thread or scheduler.
- **Multi-robot fleet sync.** That's in memkit's `FleetStore`. This
  adapter is single-robot; one instance per robot.

## Package layout

```
memkit_adapter_dds/
├── __init__.py           # public API
├── adapter.py            # DDSAdapter + AdapterConfig + AnomalyRule
├── bus.py                # DDSBus protocol
├── fake_bus.py           # FakeDDSBus + ThreadedFakeDDSBus
├── mapping.py            # TopicMapping + FieldMapping
└── presets/
    └── unitree_g1.py     # G1 reference topic mappings
```

## Status

- Core adapter, fake bus, mapping, G1 preset: **shipped and tested**
- Real Cyclone DDS backend: **not included** (sketch above — drop in your
  own, the protocol is narrow)
- Per-field rate limiting: **not implemented** (topic-level only;
  safety_critical is the escape hatch for now)
- Async API: **not in this package** — use `AsyncMemory` from memkit and
  wire it through the adapter's synchronous `emit_command`
