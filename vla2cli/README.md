# vla2cli — VLA Dataset → Snakes Data Pipeline

Extract Snakes-usable datasets from public VLA training corpora and convert them to CLI commands, EventLog records, or LLM fine-tune pairs.

## Why

VLA datasets (LeRobot, Open X-Embodiment, DROID, Octo, RT-X) contain:
- Trajectories (joint positions, velocities, torques)
- Task labels (natural language descriptions)
- Observations (images, proprioception)

But they lack:
- Reasoning chains
- CLI-level action encoding
- Failure annotations

This pipeline bridges the gap: ingest VLA data, derive the missing pieces, output in the format Snakes (and other tool-use agents) can consume.

## Three Output Modes

### 1. CLI Skill Library

For each successful trajectory, generate a named skill that can be replayed:

```
input:  LeRobot episode "pick_cup" with 500 timesteps
output: apps/hackathon/skills/pick_cup.json
        + sdk2cli command: robot x2 skill pick-cup --target <pose>
```

Benefit: the agent gets a large library of proven trajectories without training anything.

### 2. EventLog Import

Convert VLA data into Snakes' EventLog format so memkit Critic can process it:

```
input:  Open X-Embodiment episode
output: eventlog/2026-04-18.jsonl entries (task_id + physical + cognitive)
```

Benefit: Snakes' Semantic memory bootstraps with thousands of pre-learned skills before any real deployment.

### 3. LLM Fine-tune Data

Prepare supervised fine-tuning pairs so smaller local LLMs output correct CLI:

```
input:  task label + trajectory
output: {prompt: "pick the red cup", completion: "robot x2 arm pick --target cup_red --pose 0.3,0.1,0.5"}
```

Benefit: run tool-use reliably on a 3B-7B local model without calling Claude/GPT-4.

## Architecture

```
vla2cli/
├── extractors/      # Read VLA datasets
│   ├── lerobot.py
│   ├── rlds.py
│   └── droid.py
├── derivers/        # Fill missing pieces
│   ├── reasoning.py    # task label → reasoning chain via LLM
│   ├── cli_mapper.py   # trajectory → CLI command sequence
│   └── failure.py      # detect failures, annotate
├── writers/         # Output in target formats
│   ├── skill_library.py
│   ├── eventlog.py
│   └── finetune.py
└── cli.py           # vla2cli <command>
```

## Usage (planned)

```bash
# Convert a LeRobot dataset to Snakes skill library
vla2cli ingest --source lerobot --path ./lerobot_cache/task_pick_cup \
               --output-mode skill --out apps/hackathon/skills/

# Import Open X-Embodiment into Snakes EventLog
vla2cli ingest --source oxe --task grasp --limit 1000 \
               --output-mode eventlog --out eventlog/imported/

# Build fine-tune dataset for local LLM
vla2cli ingest --source rlds --task-filter manipulation \
               --output-mode finetune --out datasets/ft_cli_v1/

# List supported sources
vla2cli sources

# Validate extracted data
vla2cli validate --path eventlog/imported/
```

## Status

Skeleton only. Implementation order:
1. LeRobot extractor (most common format)
2. EventLog writer (uses existing `eventlog/schema.py`)
3. Skill library writer
4. LLM fine-tune writer
5. RLDS and OXE extractors
6. Reasoning chain deriver (LLM-powered)
