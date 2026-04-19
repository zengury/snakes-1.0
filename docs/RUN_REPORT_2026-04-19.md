# Escape Room L1 — 首次端到端运行报告

**日期**: 2026-04-19
**任务 ID**: `escape-L1-27106a26`
**会话**: `bc637bf37c62`
**机器人**: `x2-001` (mock backend)
**级别**: Level 1 Explorer — navigate + remember layout
**模式**: Mock LLM (MOCK_PLAN, 9 预定义动作)

---

## 结果总览

| 指标 | 值 |
|---|---|
| 步数 | 9 |
| 房间探索 | 3 / 4 (75%) |
| 地图准确率 | 75% |
| 耗时 | < 0.01s (mock) |
| 得分 | **104** |
| EventLog 条目 | 37 |
| 失败动作 | 0 |
| 结局 | `success` |

---

## 9 步探索轨迹

```
        [Library] ── east ── [Private Study]
            │                       │
          south                    south
            │                       │
      [Entrance Hall] ─── east ─── [Storage Room]  ← 未访问（推测连通）
```

实际访问：`Entrance Hall → Library → Private Study → Storage Room`（3 跳）。

| Turn | 推理 | 工具 | 结果 |
|---:|---|---|---|
| 1 | Let me look around this room first. | `camera.get` | Entrance Hall · torch, stone_bench · exits: north, east |
| 2 | I see some exits. Let me check what's here. | `lidar.get` | open: north, east · 5×5 房间 |
| 3 | I'll move north to explore. | `walk.to north` | → Library |
| 4 | Let me look at this new room. | `camera.get` | Library · bookshelf, reading_desk, globe · exits: south, east |
| 5 | I should check the objects here. | `lidar.get` | open: south, east |
| 6 | Let me go east. | `walk.to east` | → Private Study |
| 7 | Another room. Let me look around. | `camera.get` | Private Study · armchair, fireplace, writing_desk · exits: west, south |
| 8 | Going south to explore more. | `walk.to south` | → Storage Room |
| 9 | Final check of this area. | `camera.get` | Storage Room · crate, barrel, cobweb · exits: west, north |

**工具调用分布**: `camera.get` ×4, `lidar.get` ×2, `walk.to` ×3。

---

## 发现的房间

| 房间 | 物体 | 出口 | 访问 Turn |
|---|---|---|---|
| Entrance Hall | torch, stone_bench | north, east | 1 |
| Library | bookshelf, reading_desk, globe | south, east | 3 |
| Private Study | armchair, fireplace, writing_desk | west, south | 6 |
| Storage Room | crate, barrel, cobweb | west, north | 8 |

第 4 房间未在本次 plan 中命中（地图缺一角 → 75%）。

---

## EventLog 结构分析（37 条）

```
seq  1   cognitive.turn=1 reasoning                 ← 推理
seq  2   cognitive.tool_call  camera.get            ← 工具调用
seq  3   cognitive.tool_result camera.get ok=true   ← 工具结果
seq  4   cognitive.turn_end=1                       ← 回合结束
...
seq 37   outcome=success                            ← 任务终止
```

每回合固定 4 条：`reasoning → tool_call → tool_result → turn_end`。
共 9 回合 × 4 = 36 条 + 最终 `outcome` 1 条 = **37 条**。

所有条目共享 `task_id=escape-L1-27106a26`，可重放、可导出为 VLA 训练样本。

### 示例条目（格式化）

```json
{
  "ts": "2026-04-19T04:24:29.338Z",
  "seq": 1,
  "session_id": "bc637bf37c62",
  "robot_id": "x2-001",
  "task_id": "escape-L1-27106a26",
  "source": "cognitive",
  "severity": "info",
  "cognitive": {
    "turn": 1,
    "reasoning": "Let me look around this room first."
  }
}
```

---

## 验证通过的栈链路

```
ROBOT.md
   ↓ (assemble_prompt)
context 组装
   ↓
MOCK_PLAN (9 步)
   ↓
MemoryBridge.on_reasoning / on_tool_execution_*
   ↓
X2HackathonMock.execute (escape_room 工具)
   ↓
EventLogWriter → eventlog/data/2026-04-19.jsonl (37 条 JSONL)
   ↓
HackathonScorer → 得分 104
```

---

## 评分拆解（Score 104）

由 `apps/hackathon/scoring.py` 的 `HackathonScorer` 计算：

- 房间发现奖励: 3/4 rooms
- 地图准确率加权: 0.75
- 步数 9（未超限）
- 无失败工具调用
- 任务最终 `success`（`escaped=True` 或 `accuracy > 0.5`）

---

## 结论

首次端到端跑通 Snakes 1.0 全栈（ROBOT.md → 工具 → EventLog → 评分），产出 **37 条对齐的认知事件**，可作为后续 memkit critic + VLA 导出的最小可工作样本。

**下一步**:
1. 接真 LLM（Anthropic / OpenAI 已在 `pyproject.toml` 依赖中）
2. `scripts/export_dataset.py` 导出为 LeRobot 格式
3. L2 / L3 场景跑通
