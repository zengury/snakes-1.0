# Run Report — mock matrix (2026-04-20)

Purpose: quick regression of golden path under probabilistic failures (no external API keys).

Command:

```bash
python3 scripts/run_matrix_mock.py --level 2 --seeds 3 --p-vision 0.2 --p-manip 0.2 --p-timeout 0.1
```

Summary:
- All 3 seeds succeeded.
- This run uses provider=mock (deterministic policy), intended to validate kernel/toolchain/eventlog plumbing.

Raw output:

```json
{
  "results": [
    {
      "seed": 0,
      "outcome": "success",
      "score": {
        "scenario": "escape-room",
        "level": 2,
        "escaped": true,
        "time_s": 0.014112167000000002,
        "sim_time_s": 2.65,
        "moves": 0,
        "hints_used": 0
      },
      "cfg": {
        "seed": 0,
        "p_vision_fail": 0.2,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.2,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.1,
        "p_system_disconnect": 0.0,
        "force_vision_fail": 0,
        "force_manip_fail": 0,
        "force_system_timeout": 0,
        "force_system_disconnect": 0
      }
    },
    {
      "seed": 1,
      "outcome": "success",
      "score": {
        "scenario": "escape-room",
        "level": 2,
        "escaped": true,
        "time_s": 0.0106155,
        "sim_time_s": 2.65,
        "moves": 0,
        "hints_used": 0
      },
      "cfg": {
        "seed": 1,
        "p_vision_fail": 0.2,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.2,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.1,
        "p_system_disconnect": 0.0,
        "force_vision_fail": 0,
        "force_manip_fail": 0,
        "force_system_timeout": 0,
        "force_system_disconnect": 0
      }
    },
    {
      "seed": 2,
      "outcome": "success",
      "score": {
        "scenario": "escape-room",
        "level": 2,
        "escaped": true,
        "time_s": 0.010896292000000002,
        "sim_time_s": 2.65,
        "moves": 0,
        "hints_used": 0
      },
      "cfg": {
        "seed": 2,
        "p_vision_fail": 0.2,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.2,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.1,
        "p_system_disconnect": 0.0,
        "force_vision_fail": 0,
        "force_manip_fail": 0,
        "force_system_timeout": 0,
        "force_system_disconnect": 0
      }
    }
  ]
}
```
