# apps/diagnosis — Robot Maintenance via CLI

Wraps manastone diagnostic MCP servers with a unified CLI interface.

## Why

Robot operations teams need to:
- Check joint health (temperature, torque, fault codes)
- Monitor power (SOC, voltage, current draw)
- Verify sensor data (IMU, cameras)
- Tune PID parameters
- Replay failure events for debugging

Previously this required an MCP client. Now it's just:

```bash
snakes diag joint temp --id left_knee
```

## Architecture

```
apps/diagnosis/
├── servers/         # (merged from mcp-ros-diagnosis) manastone-joints, -power, ...
├── schema/          # robot_schema.yaml, alert thresholds
├── storage/         # gitignored — eventlog, pid_workspace, memories
├── bridge/          # DDS ↔ diagnosis schema
└── cli.py           # snakes diag <subsystem> <command>
```

## Data flow

```
Robot DDS topics
    │
    ├──► diagnosis bridge (subscribes)
    │       ↓
    │   EventLog writer (physical events tagged severity)
    │       ↓
    │   Alert engine (threshold checks)
    │       ↓
    │   CLI output (for human operator)
    │
    └──► manastone MCP servers (per-subsystem)
            ↓
            optional: Claude / Agent consume via MCP
```

## Integration with Snakes

- Writes to the same `eventlog/` that snakes agent loop writes to
- So memkit Critic can learn from maintenance events too (e.g., "when
  knee temp exceeds 55°C after 30min walking, slow down")
- Diagnosis alerts become Safety rules after K occurrences

## Status

Skeleton only. Merge plan for source from `zengury/mcp-ros-diagnosis`:

1. Copy `src/manastone_diag/` → `apps/diagnosis/servers/`
2. Copy `config/robot_schema.yaml` → `apps/diagnosis/schema/`
3. Wrap each server as CLI subcommand under `apps/diagnosis/cli.py`
4. Route all DDS event captures to root `eventlog/` (not private storage)
5. Bridge manastone's alert engine to Snakes Safety layer

See `MERGE_PLAN.md` Week 1 Day 3.
