# Run Report — mock matrix level 3 (2026-04-20)

Purpose: regression of golden path on escape-room level3 under probabilistic failures (no external API keys).

Command:

```bash
python3 scripts/run_matrix_mock.py --level 3 --seeds 3 --p-vision 0.15 --p-manip 0.15 --p-timeout 0.05
```

Summary:
- 3/3 seeds succeeded.
- Provider: mock (deterministic policy). Used to validate runtime/toolchain/eventlog/recovery plumbing.

Raw output:

```json
{
  "results": [
    {
      "seed": 0,
      "outcome": "success",
      "score": {
        "scenario": "escape-room",
        "level": 3,
        "escaped": true,
        "time_s": 0.016284042000000006,
        "sim_time_s": 7.249999999999998,
        "moves": 5,
        "hints_used": 0
      },
      "cfg": {
        "seed": 0,
        "p_vision_fail": 0.15,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.15,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.05,
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
        "level": 3,
        "escaped": true,
        "time_s": 0.01263375,
        "sim_time_s": 7.249999999999998,
        "moves": 5,
        "hints_used": 0
      },
      "cfg": {
        "seed": 1,
        "p_vision_fail": 0.15,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.15,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.05,
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
        "level": 3,
        "escaped": true,
        "time_s": 0.011701000000000003,
        "sim_time_s": 7.249999999999998,
        "moves": 5,
        "hints_used": 0
      },
      "cfg": {
        "seed": 2,
        "p_vision_fail": 0.15,
        "p_vision_corrupt": 0.0,
        "p_manip_fail": 0.15,
        "p_slip_after_grasp": 0.0,
        "p_system_timeout": 0.05,
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
