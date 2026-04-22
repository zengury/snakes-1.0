# Current Runtime Capabilities (Snakes 2.0 mainline)

本文档用于“对齐现状”：当前 `main` 分支上的 Snakes Runtime 已经具备哪些核心能力（偏主线闭环与可复盘能力，不纠结字段细节）。

> 适用范围：`snakes-1.0` repo 的 Snakes 2.0 主线迭代（escape-room 用作高压验证场景）。

---

## 1) 统一运行主线（Run）

- `snakes run`：统一入口，走 Runner + Agent Loop + Scenario。
- Provider：
  - Anthropic（真实 LLM）
  - Mock（离线回归用途）
- 常用运行参数：
  - `--max-tokens`
  - `--max-turns`
  - `--eventlog-dir`

## 2) Agent Loop（Autonomy-first）

- 主模式：完全自主（autonomy）。不允许人类在线注入策略/动作（只监控/e-stop）。
- 每回合：LLM → tool_use → observe/verify → 下一步。
- Toolchain 最小语义（但可用于主线稳定性）：
  - `timeout_s`
  - `max_retries`
  - system 类失败自动重试（一次）
  - attempts / retry_history 回写进工具结果并进入 EventLog

## 3) Failure-first：可失败、可恢复、可复盘

- 工具结果结构化（ToolOutcome-like）：
  - `outcome`（success/fail）
  - `failure_type`（perception/manipulation/system/unknown 等）
  - `phenomenon`（现象/错误信息）
  - `retryable`
  - metrics（latency 等）
- Failure 注入（scenario 层）：vision/manip/system timeout/disconnect 等概率注入；seed 可控，用于回归复现。

## 4) Autonomy-safe 护栏与恢复注入

- 工具失败且 retryable：注入一次 `[Recovery]`（每 turn 限流）。
- 同一 tool+args 重复达到阈值：anti-loop 注入 `[Recovery]`。
- assistant 一轮无 tool_use 且 scenario 未完成：注入 `[Continue]` + fresh observation（带上限）。
- 所有注入都会进入 EventLog，便于复盘与统计。

## 5) Scenario 一等公民（场景可插拔）

- 抽象：`snakes/scenarios/base.py`（reset/observe/is_done/score/tools/prompt_instructions）。
- escape-room mock 场景：
  - Level 1/2/3
  - 工具集：`camera.get` / `head.look` / `head.scan` / `walk.to` / `arm.interact` / `arm.grab` / `arm.release` / `arm.use` / `status.`
  - Observation：包含 room/objects/exits/inventory，并已补齐 puzzles 元信息、左右手持物、head_target 等关键状态，减少长周期漂移。
  - 环境语义/工具可用性多轮最小修复后：在真实 Anthropic + 失败注入下可稳定通关（Level 2/3）。

## 6) Provider 适配层（真实 LLM 可跑）

- Anthropic 工具名约束兼容：内部工具名 ↔ provider-safe 名映射（支持 `camera.get` 这类点号命名）。
- 预留本地小模型接入：OpenAI-compatible endpoint（通过 `OPENAI_BASE_URL`）。

## 7) EventLog：可观测与复盘工具链

- EventLog 记录：run_start/end、每轮 reasoning、tool_call/tool_result、观察、恢复注入、score 等。
- CLI：
  - `snakes watch`：实时观察
  - `snakes replay`：按 task_id 回放
  - `snakes score`：聚合统计（失败分布、timeouts、retry_attempts、tool latency 分桶等）

## 8) 离线回归（Mock Regression）

- `--provider mock`：用于离线回归（deterministic policy level2/level3），不作为产品卖点。
- 矩阵脚本：`scripts/run_matrix_mock.py` + 输出报告到 `docs/dev/`。

---

## 快速验证（推荐命令）

> 注意：尽量单行命令，避免 zsh 多行粘贴导致参数断裂。

- 运行（Anthropic）：
  - `snakes run --provider anthropic --scenario escape-room --level 3 ...`
- 复盘：
  - `snakes score --task-id <id> --eventlog-dir eventlog/data`
  - `snakes replay --task-id <id> --eventlog-dir eventlog/data`
