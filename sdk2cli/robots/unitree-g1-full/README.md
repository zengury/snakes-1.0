# unitree-cli

Agent-native CLI wrapper around `unitree_sdk2_python` for the Unitree G1
humanoid. A long-running daemon owns the DDS connection; the CLI is a thin
client that talks to the daemon over a Unix socket. Human debugging and
LLM-driven agent execution go through exactly the same command surface.

> Status: P0 scaffolding. The `mock` backend works out of the box. The
> `real` backend is stubbed — wire it into `unitree_sdk2py` after
> validating the daemon on hardware.

## Quick start (no hardware required)

```bash
# Run commands directly against the mock backend (each invocation creates
# a fresh in-process client — state does not persist across calls).
python3 -m unitree_cli joint set left_hip_yaw 15.0 --speed 0.5
python3 -m unitree_cli battery status
python3 -m unitree_cli manifest    # print the help/manifest

# Start the daemon and reuse a single mock instance across calls.
python3 -m unitree_cli daemon start &
python3 -m unitree_cli daemon status
python3 -m unitree_cli joint set left_hip_yaw 15.0
python3 -m unitree_cli joint get left_hip_yaw   # => angle: 15.0  (persists)
python3 -m unitree_cli imu get --stream --hz 10 # Ctrl+C to stop
```

## Architecture

```
   human shell                 agent runtime
       │                             │
       │ unitree joint set ...       │ exec = get_executor(...)
       ▼                             ▼ executor.call("joint.set", ...)
  ┌─────────┐  unix socket   ┌───────────────┐
  │   CLI   │ ─────────────▶ │    Daemon     │───► unitree_sdk2py
  │ (thin)  │ ◀───────────── │ (owns DDS)    │     ► CycloneDDS
  └─────────┘    JSONL       └───────────────┘     ► G1 robot
       │
       └── fallback: LocalExecutor (spawns its own LocoClient)
```

- `unitree_cli/client.py` — `LocoClient` abstract base, `MockLocoClient`,
  `RealLocoClient` (scaffold), G1 29-DOF joint map, safety validators.
- `unitree_cli/daemon.py` — `Daemon` (Unix socket server), `DaemonClient`
  (thin client), `LocalExecutor` (fallback), `get_executor()` transport
  selection, `dispatch()` command router used by both daemon and fallback.
- `unitree_cli/cli.py` — `argparse` surface mirroring `manifest.txt`.
- `manifest.txt` — the canonical help document. Printed by `unitree --help`
  and also meant to be injected into an agent's system prompt verbatim.

All safety checks (joint ranges, speed limits, gripper aperture, estop
state) live in `client.py` and run before any actuation, regardless of
which transport executes the command.

## P0 latency validation

The architectural bet is that a daemon-fronted CLI has latency low enough
that `agent → CLI command → daemon → result` is indistinguishable from
direct function calls. Measured on this machine:

```
$ unitree daemon start &
$ unitree bench --count 2000 --with-cold-start --cold-count 30

{
  "in_process_rtt_us":   {"n": 2000, "mean": 131.6, "p50": 126.7,
                          "p95": 189.9, "p99": 240.7,  "max": 635.0},
  "subprocess_cold_ms":  {"n":   30, "mean": 135.6, "p50": 134.0,
                          "p95": 159.1, "p99": 161.1,  "max": 161.1}
}

P0 gate (≤50ms): FAIL  [in-process p99=0.24ms, cold p99=161.14ms]
```

### Interpretation

| Access path                                   | p99       | Verdict |
|-----------------------------------------------|-----------|---------|
| Daemon socket RTT (persistent connection)     | **0.24 ms** | ✅ free  |
| Subprocess cold start (`python3 -m unitree_cli …`) | 161 ms  | ❌ too slow |

The daemon itself is essentially free. The 161 ms cold-start cost is
100 % Python interpreter + transitive imports (argparse → inspect →
dataclasses → shutil → bz2 → lzma → …), verified with `python3 -X importtime`:

- Python no-op startup: ~30 ms
- `unitree_cli.cli` import tree: ~62 ms
- argparse parsing + socket connect + JSON: ~40 ms

### Implications for the final architecture

1. **Agent imports `unitree_cli` as a library** (no subprocess) — the
   daemon RTT is ~0.2 ms, which is free. **This is the intended final
   form** and it meets the gate comfortably.
2. **Human debugging at the shell** — 135 ms per command is usable but
   annoying. If that's a priority, write the CLI client in Rust or Go
   (one file, `connect → send → recv → print`); expected cold start ~5 ms.
3. **Long-lived REPL** (`unitree shell`) — one Python process, many
   commands via stdin. ~0.2 ms per command. Not implemented yet.

The architectural conclusion stands: **proceed with the CLI-as-manifest /
daemon-as-runtime design.** The "AST sandbox + Python `exec()`" route
from the v2 PRD is not needed — safety reduces to CLI argument
validation at the daemon entrypoint (`client.py` already does this).

## Safety model

Two layers, both enforced before any DDS publish:

1. **Per-parameter validators** (`client.py`): joint ID lookup, angle
   range check against `G1_JOINT_MAP`, speed ∈ (0, 2.0] rad/s, gripper
   aperture ∈ [0, 1], emergency-stop latch.
2. **Command dispatch** (`daemon.py::dispatch`): whitelist of known
   command names. Unknown commands raise before reaching the backend.

Safety errors return `{"ok": false, "code": "SAFETY"}` over the wire and
exit code `2` at the shell. Other errors return `INTERNAL` / `PROTOCOL`.

## Not yet done

- `RealLocoClient` — needs to be mapped to `unitree_sdk2py`'s actual
  `LowCmd` / `LocoClient` surface on real hardware.
- `unitree daemon stop` — currently prints "not implemented". Use a PID
  file or a `shutdown` command over the socket.
- `unitree camera rgb --describe` — plumb a vision model.
- `unitree shell` — interactive REPL over the daemon socket.
- Rust/Go thin client for sub-5 ms cold start at the shell.
