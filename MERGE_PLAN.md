# Snakes 1.0 Merge Plan

Consolidate five separate repos into `snakes-1.0/` monorepo.

## Source Repos

| Source | Target path | Status |
|--------|-------------|--------|
| `zengury/sdk2cli` (registry) | `snakes-1.0/sdk2cli/` | exists, stable |
| `zengury/memory` (memkit) | `snakes-1.0/memkit/` | exists, stable |
| `zengury/mcp-ros-diagnosis` | `snakes-1.0/mcp/` | exists, stable |
| `zengury/cli-enhanced` (escape room) | `snakes-1.0/scenarios/` | exists, already ported |
| (new) `snakes/` | `snakes-1.0/snakes/` | created, 20 tests pass |

## Week 1: Import + Restructure

### Day 1: sdk2cli import
```bash
cd snakes-1.0
git subtree add --prefix=sdk2cli https://github.com/zengury/sdk2cli.git main --squash
# or clone locally and copy if subtree has issues
```

Move:
- `sdk2cli/registry/robot_cli_core/` → `snakes-1.0/sdk2cli/robot_cli_core/`
- `sdk2cli/registry/robots/` → `snakes-1.0/sdk2cli/robots/`
- Update `snakes-1.0/pyproject.toml` to include `sdk2cli` package

### Day 2: memkit import
```bash
git subtree add --prefix=memkit https://github.com/zengury/memory.git main --squash
```

Move:
- `memory/memkit/` → `snakes-1.0/memkit/`
- `memory/memkit-adapter-dds/` → `snakes-1.0/mcp/bridge/dds/` (DDS adapter belongs with mcp)

### Day 3: mcp-ros-diagnosis import
```bash
git subtree add --prefix=mcp https://github.com/zengury/mcp-ros-diagnosis.git main --squash
```

Move:
- `mcp-ros-diagnosis/src/manastone_diag/` → `snakes-1.0/mcp/servers/`
- `mcp-ros-diagnosis/config/` → `snakes-1.0/mcp/config/`
- `mcp-ros-diagnosis/storage/` → `snakes-1.0/mcp/storage/` (gitignored)

### Day 4: cli-enhanced escape room updates
Already ported. Verify `snakes-1.0/scenarios/` matches.

### Day 5: pyproject.toml consolidation
Single root `pyproject.toml` with optional dependencies per module:

```toml
[project]
name = "snakes"
version = "1.0.0"
dependencies = ["anthropic>=0.30.0"]

[project.optional-dependencies]
robots = []                               # sdk2cli has no extra deps
memory = ["pyyaml"]                       # memkit needs yaml
mcp = ["rclpy", "cyclonedds-python"]      # DDS bridge
dev = ["pytest", "pytest-asyncio"]
all = ["snakes[robots,memory,mcp,dev]"]

[tool.setuptools.packages.find]
include = ["snakes*", "sdk2cli*", "memkit*", "mcp*", "scenarios*"]
```

## Week 2: EventLog Unification

### Day 1-2: Define unified schema
Write `snakes-1.0/mcp/eventlog/schema.py` with `EventLogEntry` dataclass.

### Day 3: EventLog writer
Write `snakes-1.0/mcp/eventlog/writer.py`:
- `EventLogWriter` — JSONL file writer with rotation
- `.write_physical(snapshot)` — called by mcp servers
- `.write_cognitive(event)` — called by snakes agent loop
- `.write_command(cmd)` — called by sdk2cli daemon

### Day 4: Replace memkit.Episodic
- Update `snakes-1.0/snakes/memory_bridge.py` to write to EventLog instead of memkit.episodic
- Update `snakes-1.0/memkit/learner.py` to read from EventLog instead of its own episodic store
- Remove `memkit/layers/episodic.py`

### Day 5: Integration test
- Run one task end-to-end
- Verify EventLog contains aligned physical + cognitive entries
- Verify memkit.Critic processes EventLog correctly

## Week 3: Critic + Learner Upgrade

### Day 1-2: Update Critic for EventLog
```python
# memkit/critic/rule_based.py
def review_task(eventlog_entries: list[EventLogEntry]) -> Decision:
    grouped = group_by_task_id(eventlog_entries)
    for task in grouped:
        if task.outcome == "success":
            if is_novel_and_repeatable(task):
                return Decision.promote_to_quarantine(task)
        elif task.outcome == "failure":
            return Decision.annotate_failure(task)
```

### Day 3: Failure annotation pipeline
```python
# memkit/critic/failure_annotator.py
def annotate_failure(task):
    phenomenon = extract_phenomenon(task.physical)
    # "瓶身从指尖滑落 5cm" from torque drop + object pose change
    reason = infer_reason(task.cognitive, task.physical)
    # "grasp pose too low" from pose analysis
    return FailureRecord(phenomenon, reason, task)
```

### Day 4: Recurring failure → Safety rule
```python
# memkit/critic/safety_proposer.py
def detect_recurring_failures(window="30d"):
    failures = query_eventlog(outcome="failure", since=window)
    clusters = cluster_by_reason(failures)
    for cluster in clusters:
        if len(cluster) >= RECURRENCE_THRESHOLD:
            propose_safety_rule(cluster)  # -> human review queue
```

### Day 5: Tests for learning pipeline
Test the full loop:
1. Robot attempts task, fails
2. Critic annotates failure
3. Robot attempts again, succeeds
4. Critic promotes to Semantic
5. Next task queries Semantic, uses skill directly

## Week 4: Dataset Export + End-to-End

### Day 1-3: scripts/export_dataset.py
```bash
snakes export-dataset \
    --task "milk_grasp" \
    --format lerobot \
    --out ./datasets/milk_grasp_v1/
```

Supports:
- LeRobot format (HuggingFace standard)
- RLDS format (Google/TFDS)
- Custom (trajectory + task + reasoning JSON)

Filters:
- `--task <name>` — specific task
- `--outcome success` — only successful runs
- `--robot <name>` — specific robot type
- `--since <date>` — time window

### Day 4: First end-to-end hackathon run
- Load escape room Level 2
- Run snakes agent with Claude
- Verify EventLog captures everything
- Verify memkit learns the puzzle solution
- Run again, verify agent uses learned skill

### Day 5: Documentation + README
- Update `README.md` with the consolidated project
- Add `docs/GETTING_STARTED.md`
- Add `docs/ARCHITECTURE.md` (already done)
- Add `docs/EVENTLOG_SCHEMA.md`

## Commands Cheat Sheet

```bash
# Install
pip install -e ".[all]"

# Run a robot
snakes run --robot agibot-x2 --task "walk forward 1m"

# Start daemon
robot agibot-x2 daemon start &

# Run escape room
snakes scenario escape-room --level 1 --robot agibot-x2

# Start diagnostic MCP servers
snakes mcp start --robot unitree-g1

# Query memory
snakes memory query "grasp milk"

# Export training dataset
snakes export-dataset --task milk_grasp --format lerobot

# Replay from EventLog
snakes replay --from eventlog/2026-04-17.jsonl --speed 2x
```

## Risks + Mitigations

| Risk | Mitigation |
|------|-----------|
| Subtree merge loses history | Use `git subtree add` with squash, keep history refs in commit message |
| Dependency conflicts between modules | Optional deps per module, CI matrix testing |
| EventLog performance (high write rate) | Buffered JSONL writer, daily rotation, compressed archives |
| memkit's Episodic tests break | Migrate tests to use EventLog query instead of direct episodic access |
| mcp servers need ROS2 (not available everywhere) | Mock mode via `MANASTONE_MOCK_MODE=true` (already exists) |
| Large repo becomes slow | Use `git sparse-checkout` for contributors who only work on one module |

## Success Criteria (End of Week 4)

- [ ] Single `pip install -e .` installs everything
- [ ] `pytest` runs all tests across all modules
- [ ] Unified EventLog contains entries from all three sources
- [ ] At least one skill learned and promoted Quarantine → Semantic
- [ ] Export tool produces valid LeRobot dataset
- [ ] Hackathon escape room Level 2 runs end-to-end with a real LLM
- [ ] README documents the complete system
