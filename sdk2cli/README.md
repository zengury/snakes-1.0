# sdk2cli — One CLI to Control Any Robot

**Install once. Run `robot <name> <command>`. Control 37 robots from 20+ manufacturers.**

```bash
pip install -e .

robot list                              # see all robots
robot agibot-a2 arm home                # AGIBOT A2 humanoid
robot boston-spot stand                  # Boston Dynamics Spot
robot xarm move-joint --angles 0,0,0,1.57,0,0,0   # UFACTORY xArm
robot leap-hand grasp pinch             # LEAP dexterous hand
robot agibot-x2 motion play 1002       # AGIBOT X2 wave gesture
robot fourier-gr1 walk --speed 0.5     # Fourier GR-1 humanoid
```

No hardware needed. Every robot ships with a **mock backend** that works out of the box.

---

## The Problem

You want to build an AI agent that controls robots. Today, each manufacturer gives you a different SDK:

| Manufacturer | SDK | Protocol | Language |
|---|---|---|---|
| Unitree | unitree_sdk2py | CycloneDDS | C++/Python |
| AGIBOT A2 | AimDK | HTTP RPC + ROS2 + Protobuf | C++/Python |
| AGIBOT X2 | AimDK_X2 | Pure ROS2 + aimdk_msgs | C++/Python |
| AGIBOT G2 | genie_sim | gRPC | Python |
| Boston Dynamics | bosdyn-client | gRPC/Protobuf | Python |
| Fourier | rocs_client | WebSocket + HTTP | Python |
| UFACTORY | xArm-Python-SDK | TCP socket | Python |
| Universal Robots | ur_rtde | RTDE @500Hz | C++/Python |

**8 manufacturers. 8 protocols. 8 APIs. 8 different ways to say "move joint 3 to 1.5 radians."**

Your agent needs to learn all of them. Your safety layer needs to validate all of them. Your logging needs to capture all of them. Your tests need to cover all of them.

## The Solution

```
robot <name> joint set <joint> --q 1.5
```

One command. Any robot. Same safety. Same logging. Same undo.

```
┌─────────────────────────────────────────────────┐
│              robot  <name>  <command>            │
│                 unified CLI layer                │
├──────┬──────┬──────┬──────┬──────┬──────┬───────┤
│ A2   │ X2   │ G2   │ Spot │ xArm │ GR-1 │ LEAP  │
│ HTTP │ ROS2 │ gRPC │ gRPC │ TCP  │ WS   │ Serial│
│ RPC  │ DDS  │      │ PB   │      │ HTTP │ Dyn.  │
└──────┴──────┴──────┴──────┴──────┴──────┴───────┘
```

The protocol differences disappear. Your agent sees one interface.

---

## Why This Matters

### 1. `--help` IS the LLM System Prompt

Every robot's `manifest.txt` is simultaneously:
- The output of `robot <name> --help` (what humans read)
- The system prompt fragment for an LLM agent (what AI reads)
- The canonical API reference (what developers check)

One artifact. Three audiences. Zero sync burden.

A typical robot's manifest is **~200 tokens**. The equivalent MCP tool schema would be **~5,000 tokens**. That's a **96% reduction** in context window cost — which means your agent can understand more robots in the same context.

### 2. Mock Backend = Instant Development

Every robot CLI works without hardware:

```bash
robot agibot-a2 walk --forward 0.3
# → {"forward": 0.3, "lateral": 0.0, "angular": 0.0, "backend": "mock"}
```

Build your agent logic, test your pipelines, run CI — all without a physical robot. When you're ready for real hardware, switch one environment variable:

```bash
export AGIBOT_A2_BACKEND=real
```

Same commands. Same output format. Same safety layer.

### 3. Safety as Argument Validation

Every actuator command passes through `validate_*()` before reaching hardware:

```bash
$ robot agibot-x2 joint set left_knee --q 999
agibot-x2: safety: left_knee(#3): q=999.000 out of range [0.00, 2.41]
$ echo $?
2
```

Joint limits are encoded per-robot from manufacturer specs and URDF data. No AST analysis, no sandbox, no whitelist — just: **is this number in range?** Safety errors return exit code `2` so agents can detect and recover.

### 4. Works With Any AI Agent

The CLI is text-in, text-out. Any agent framework can use it:

**Claude Code / Anthropic:**
```python
manifest = subprocess.check_output(["robot", "agibot-a2", "manifest"]).decode()
# Inject into system prompt — 200 tokens covers the entire robot
```

**OpenClaw / Open-source agents:**
```python
result = subprocess.run(["robot", "agibot-a2", "arm", "home"], capture_output=True)
state = json.loads(result.stdout)
```

**Direct library import (0.2ms latency):**
```python
from agibot_a2_cli.client import get_client
client = get_client("mock")
client.dispatch("arm.home", {})
```

**Or via the daemon (persistent state across calls):**
```bash
robot agibot-a2 daemon start &
robot agibot-a2 arm home
robot agibot-a2 arm joint-get   # state persists
robot agibot-a2 undo            # rollback last command
```

---

## What's Inside

### 12 Executable Robot CLIs

Every one of these has a working mock backend. Run them now.

| Robot | Type | DOF | Manufacturer | Protocol |
|---|---|---|---|---|
| `agibot-a2` | Humanoid | 28+ | AGIBOT 智元 | HTTP RPC + ROS2 |
| `agibot-x2` | Humanoid | 31 | AGIBOT 智元 | Pure ROS2 |
| `agibot-g2` | Wheeled Humanoid | 47 | AGIBOT 智元 | gRPC |
| `boston-spot` | Quadruped + Arm | 18 | Boston Dynamics | gRPC |
| `fourier-gr1` | Humanoid | 40 | Fourier/FFTAI | WebSocket |
| `xarm` | Robot Arm | 7 | UFACTORY | TCP |
| `universal-robots` | Robot Arm | 6 | Universal Robots | RTDE |
| `elephant-mycobot` | Desktop Arm | 6 | Elephant Robotics | Serial |
| `leap-hand` | Dexterous Hand | 16 | CMU LEAP | Dynamixel |
| `inspire-hand` | Dexterous Hand | 6 | Inspire Robots | Modbus |
| `dexrobot-hand` | Dexterous Hand | 19 | DexRobot | USB-CAN |
| `robotiq-2f` | Gripper | 1 | Robotiq | Modbus |

### 25 Additional Robot Manifests

Command surface documented and ready. Full CLI generated when you need it via the `/sdk2cli` Claude Code skill.

```
agibot-d1, agibot-omnihand, agibot-x1, agilex-piper, agilex-scout,
allegro-hand, clone-hand, dobot-cr, elite-cs, flexiv-rizon,
fourier-hand, franka-panda, jaka, kinova-gen3, kscale-kbot,
linkerbot-hand, nao, orca-hand, poppy-humanoid, psyonic-hand,
realman-rm, shadow-hand, unitree-g1, unitree-go2, xiaomi-cyberdog
```

### Shared Infrastructure

| Module | Purpose |
|---|---|
| `robot_cli_core/base_client.py` | Abstract client, JointMap, safety validators |
| `robot_cli_core/daemon.py` | Unix-socket daemon, thin client, auto-fallback |
| `robot_cli_core/formatter.py` | `--format json` (agent) or `--format text` (human) |
| `robot_cli_core/cli_builder.py` | Shared argparse patterns (joint/daemon/bench) |
| `robot_cli_core/main.py` | Unified `robot` entry point with auto-discovery |

---

## Quick Start

```bash
git clone https://github.com/zengury/sdk2cli.git
cd sdk2cli/registry
pip install -e .

# See what's available
robot list

# Try any robot (no hardware needed)
robot agibot-a2 --help
robot agibot-a2 action set arm-servo
robot agibot-a2 arm home
robot agibot-a2 walk --forward 0.3
robot agibot-a2 hand gesture grip --side left

# Try a different robot
robot boston-spot power on
robot boston-spot stand
robot boston-spot move --vx 0.5

# Human-readable output
robot --format text agibot-x2 joint list

# Get the combined manifest for all robots (for LLM system prompt)
robot manifest
```

## Add Your Own Robot

### Option A: Use the `/sdk2cli` skill (automatic)

```bash
# In Claude Code:
/sdk2cli ./path/to/your_robot_sdk
```

Claude analyzes the SDK, generates manifest + client + CLI, and runs tests. Takes ~2 minutes.

### Option B: Manual (10 minutes)

```bash
# Copy a template
cp -r registry/robots/boston-spot registry/robots/my-robot

# Edit 3 files:
#   manifest.txt  — command surface + joint map
#   my_robot_cli/client.py  — JointMap + MockClient + RealClient stub
#   my_robot_cli/cli.py  — argparse subcommands

# Verify
robot my-robot --help
robot my-robot joint list
```

The daemon, REPL, undo, formatter, and bench are shared — you don't write them.

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │    robot <name> <command>     │
                    │    unified CLI entry point     │
                    └─────────────┬────────────────┘
                                  │ auto-discover from
                                  │ registry/robots/
             ┌────────┬────────┬──┴──┬────────┬────────┐
             ▼        ▼        ▼     ▼        ▼        ▼
          agibot   agibot   boston  xarm    leap    fourier
           -a2      -x2     -spot           -hand    -gr1
             │        │        │     │        │        │
          manifest manifest manifest manifest manifest manifest
          client   client   client  client   client   client
             │        │        │     │        │        │
             └────────┴────────┴──┬──┴────────┴────────┘
                                  │
                    ┌─────────────┴────────────────┐
                    │       robot_cli_core          │
                    │  daemon · formatter · safety  │
                    │  cli_builder · base_client    │
                    └──────────────────────────────┘
```

### Per-Robot Files (you write these)

| File | Lines | What It Does |
|---|---|---|
| `manifest.txt` | ~60 | Command surface with risk tags and inline comments |
| `client.py` | ~200 | JointMap (names, limits, kp/kd) + MockClient + RealClient stub |
| `cli.py` | ~150 | argparse subcommands matching the manifest |

### Shared Files (you don't touch these)

| File | What It Does |
|---|---|
| `daemon.py` | Unix socket server, 0.24ms RTT, auto-fallback to local |
| `formatter.py` | `--format json` for agents, `--format text` for humans |
| `base_client.py` | JointMap, safety validators, MockClientBase |
| `cli_builder.py` | Shared argparse patterns (joint get/set/list, daemon, bench) |
| `main.py` | `robot list`, `robot <name>`, `robot manifest` |

---

## Design Decisions

**Why CLI, not MCP?**
CLI `--help` is 200 tokens. MCP tool schema is 5,000 tokens. LLMs understand CLI natively. And every robot's `--help` is also its system prompt — zero translation layer.

**Why a daemon?**
Robot SDKs have slow connection setup (DDS discovery: 1-2s, gRPC handshake: 0.5s). The daemon pays this cost once. Every subsequent command is a 0.24ms Unix socket round-trip. State persists across CLI invocations.

**Why mock backends?**
You shouldn't need a $100K robot to develop an agent that controls one. Mock backends simulate joint state, IMU noise, and safety responses. When you're ready for real hardware, change one env var.

**Why not just use ROS2?**
ROS2 is great for real-time control loops. But `ros2 topic pub` is not an agent interface — it requires knowing the exact message type, QoS profile, and topic name. `robot agibot-x2 walk --forward 0.3` is an agent interface.

---

## Supported Manufacturers

| Manufacturer | Robots | CLI Status |
|---|---|---|
| **AGIBOT 智元** | A2, X2, G2, D1, OmniHand, X1 | 3 full CLI + 3 manifest |
| **Unitree 宇树** | G1, Go2 | 2 manifest (full CLI in examples/) |
| **Boston Dynamics** | Spot | Full CLI |
| **Fourier/FFTAI** | GR-1, Hand | Full CLI + manifest |
| **UFACTORY** | xArm 5/6/7 | Full CLI |
| **Universal Robots** | UR3/5/10/16/20 | Full CLI |
| **Elephant Robotics** | myCobot 280/320 | Full CLI |
| **CMU** | LEAP Hand | Full CLI |
| **Inspire Robots** | RH56 series | Full CLI |
| **DexRobot** | DexHand021 | Full CLI |
| **Robotiq** | 2F-85/140 | Full CLI |
| **Wonik** | Allegro Hand V4/V5 | Manifest |
| **Shadow Robot** | Dexterous Hand | Manifest |
| **PSYONIC** | Ability Hand | Manifest |
| **Franka** | Panda/FR3 | Manifest |
| **Kinova** | Gen3 | Manifest |
| **Dobot** | CR series | Manifest |
| **JAKA** | Zu series | Manifest |
| **AgileX** | Scout, Piper | Manifest |
| **Xiaomi** | CyberDog | Manifest |

---

## For Agent Developers

### System Prompt Pattern

```python
# Get the manifest for one robot
manifest = subprocess.check_output(["robot", "agibot-a2", "manifest"]).decode()

system_prompt = f"""You control an AGIBOT A2 humanoid robot.
Available commands:
{manifest}
Execute commands by outputting them one per line. Output DONE when finished."""
```

### Multi-Robot Fleet

```python
# Get ALL robot manifests in one call
all_manifests = subprocess.check_output(["robot", "manifest"]).decode()
# ~2500 tokens for 12 robots — still less than one MCP tool schema
```

### Daemon for Persistent State

```python
import subprocess, json

subprocess.Popen(["robot", "agibot-a2", "daemon", "start"])

def send(cmd):
    r = subprocess.run(["robot", "agibot-a2"] + cmd.split(), capture_output=True)
    return json.loads(r.stdout)

send("action set arm-servo")
send("arm home")
state = send("arm joint-get")    # reflects home position
send("undo")                     # rollback to previous
```

---

## License

MIT. Generated CLIs are yours. No attribution required.

The mock backends are original implementations. Real backends wrap manufacturer SDKs under their respective licenses.
