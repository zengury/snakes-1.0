# Snakes 研发日志

记录从 sdk2cli → Snakes 1.0 的完整思考过程。每个决策都记录了 Why，方便回溯。

---

## 阶段 1：CLI 统一层（sdk2cli）

### 起点：一个洞察

**问题**：8 家机器人厂商，8 种 SDK，8 种协议。每个机器人的 API 不同，AI agent 适配成本 O(N×M)。

**洞察**：CLI `--help` 是有史以来最密集的 API 描述格式。

```
robot joint set <id> <angle:F> [--speed F=1.0]
```

一行编码了：命令组、动词、位置参数、类型、标志、默认值。等价的 MCP tool schema 需要 ~50 行 JSON。

**决策 1**：用 CLI 而非 MCP 作为 Agent 接口。
- CLI manifest = 200 tokens/机器人
- MCP schema = 5000 tokens/机器人
- 96% token 节省 → agent 可以同时理解更多机器人

**决策 2**：manifest.txt = `--help` 输出 = LLM system prompt。三合一，零维护。

### Daemon 架构

**问题**：subprocess 冷启动 ~160ms，太慢。

**解法**：Unix socket daemon，一次启动，后续调用 0.24ms p99。

**决策 3**：daemon + LocalExecutor 自动切换。有 daemon 走 socket，没有走进程内。

### Mock 后端

**决策 4**：每个机器人出厂带 mock backend。无需硬件即可开发。
- `AGIBOT_X2_BACKEND=mock`（默认）
- `AGIBOT_X2_BACKEND=real`（真机）

### 安全

**决策 5**：安全 = 参数校验。每个 `joint set` 都过 `validate_position()`，超限返回 exit code 2。不用沙箱、不用白名单——就是"这个数在不在范围内"。

### 覆盖面

做了 12 个完整 CLI + 25 个 manifest。覆盖 8 种协议：CycloneDDS, HTTP RPC, ROS2, gRPC, WebSocket, TCP, Modbus, Dynamixel。

---

## 阶段 2：关节数据 + HAL 分析

### DOF 膨胀问题

**问题**：X2 显示 51 关节（官方 30），G2 显示 46（官方 26）。为什么？

**原因**：把被动联动（gripper linkage）和可选配件（OmniHand）也算进去了。

**决策 6**：joint_limits.yaml 加 `controllable: true/false` + `optional: true` + `active_dof` vs `total_joints` 双计数。

### HAL 层分析

**问题**：sdk2cli 目前只包装了语义层（arm.home, walk --forward），HAL 层（电流、温度、编码器、力矩）有吗？

**发现**：
- 大部分 vendor SDK 有丰富的 HAL API（Unitree LowCmd 有 q/dq/tau/Kp/Kd/temperature）
- sdk2cli 几乎没有透传 HAL

**关键洞察**：SDK 没包装的 ≠ DDS 上没有。X2 是 Pure ROS2，`ros2 topic list` 可以发现 SDK 没暴露的 topic（如 motor_temperature, diagnostics）。

**决策 7**：未来加 `hal.discover` / `hal.tap` 命令，直接从 DDS 总线抓 SDK 之外的数据。

### Unitree vs 智元 HAL 对比

| | Unitree SDK2 | 智元 X2 |
|---|---|---|
| 力矩命令 | ✅ tau 直接下发 | ❌ 只能通过阻抗公式间接 |
| 电机温度 | ✅ motor_state[i].temperature | ❌ |
| 电池 | ✅ bms_state | ❌ |
| HAL 深度 | 关节级 + 传感器级 | 关节级（阻抗），传感器缺失 |

---

## 阶段 3：从"CLI 工具"到"Agent Runtime"

### 分层控制

**问题**：如果目标是"控制机器人"，CLI 够吗？

**回答**：CLI 是 L4→L3 的接口（Agent → Skill），不是控制器。

```
L4  LLM Agent (0.1-5Hz)        ← CLI 在这里
L3  Skill (10-30Hz)
L2  Controller (50-1000Hz)
L1  HAL (500-2000Hz)
L0  Motor
```

**决策 8**：CLI 永远不进内环。CLI 是"触发器"，不是"控制器"。

### 三种 Skill

**决策 9**：Skill 有三种实现方式，对 Agent 透明：
1. 轨迹回放（舞蹈、挥手）
2. 算法控制（walk 用 RL、grasp 用 MPC/IK）
3. VLA 神经网络（"把杯子递给我"）

Agent 调的都是 `skill.<name>`，不关心内部用什么算法。

### 语音对话

**决策 10**：语音和运动是并行管道，通过 Intent Bus 解耦。"停下"等关键词走快路径（ASR 直接到 Safety），不经过 LLM。

### 并行执行

**问题**：当前机器人怎么协调多任务（VLA + walk + dialog）？

**发现**：大多数机器人没有真正的协调器。ROS2 靠 Controller Manager + Behavior Tree，自研栈靠闭源 Behavior Manager。

**决策 11**：Snakes daemon 加显式 Coordinator，每个 Skill 声明占用的资源（arm_l, arm_r, legs, head, voice），Coordinator 做仲裁和抢占。

### Capability Check

**决策 12**：LLM 调 skill 前必须 `robot x2 capability.check`。没有的能力（如 VLA 未部署）返回 `CAPABILITY_UNAVAILABLE` + 替代方案。避免 LLM 幻觉出不存在的能力。

---

## 阶段 4：Snakes 定位升格

### 关键转折

**用户输入**："这个项目属于一个大项目叫 Snakes，定位是机器人的 Agent Runtime……类似 Claude Code 和 OpenClaw。"

**重新理解**：这不是 SDK 统一器，是 "Claude Code for Robotics"。

**决策 13**：评价维度从"多机器人覆盖"转到"单机器人深度认知循环"。

**Claude Code 的聪明 70% 在哪**：
- CLAUDE.md 约定
- TodoWrite 强制规划
- Task 工具和 subagent
- 读-修改-验证循环
- 跨会话持久化

**Snakes 对应需要**：
- ROBOT.md（机器人的 CLAUDE.md）
- 任务 Plan→Execute→Verify loop
- 子 skill 委派
- 读-动作-验证循环
- 长期记忆

### memkit 6 层与 Snakes 的对应

| memkit 层 | Snakes 用途 |
|---|---|
| Reflex <10ms | 当前传感器状态 |
| Episodic <5ms | 当前任务日志 |
| Quarantine | 未验证的新经验（24h 隔离） |
| Semantic | 固化后的技能和知识 |
| Fleet | 多机器人共享（K 验证门控） |
| Safety | 绝对规则（永不衰减，人工审批） |

**决策 14**："Writes are earned" — 新经验必须过 Quarantine + Critic 才能进入 Semantic。

### mcp-ros-diagnosis 的战略角色

**用户揭示**：mcp-ros-diagnosis 不是诊断工具——它是数据采集层。

**数据飞轮**：
```
机器人运行 → mcp 录关节轨迹 → snakes 录推理链 → memkit 录成败标签
→ 三者融合 = 世界唯一的 认知-物理 对齐数据集
→ 训练 VLA → 部署为 skill → 更多数据 → 更好的 VLA
```

**决策 15**：Snakes 的终极目标不是 runtime，是**通过 runtime 产生数据来训练最好的 VLA**。

---

## 阶段 5：EventLog 统一

### Episodic vs EventLog

**问题**：memkit 有 Episodic 层记录任务日志，mcp-ros-diagnosis 有 EventLog 记录物理事件。两套系统。

**用户决策**："保留一个，我更喜欢 EventLog。"

**决策 16**：EventLog 成为单一真相来源。memkit 的 Episodic 层改为 EventLog 的查询视图，不再独立存储。

**统一后的 EventLog entry**：
```json
{
  "ts": "...", "task_id": "...",
  "physical": {关节, 力矩, IMU},        // ← 来自 mcp
  "cognitive": {推理链, 工具调用, 结果},  // ← 来自 snakes loop
  "outcome": "success/failure",
  "failure_reason": "...",
  "failure_phenomenon": "..."
}
```

**决策 17**：memkit 聚焦"学习"——Critic Pipeline 从 EventLog 读取，成功提升为 Skill，失败标注保留为训练数据。

### 合并为 monorepo

**决策 18**：所有子项目合并到 snakes-1.0 monorepo（方案 A）。MVP 的完整性比可扩展性重要。

```
snakes-1.0/
├── snakes/      (agent runtime)
├── sdk2cli/     (from zengury/sdk2cli)
├── memkit/      (from zengury/memory)
├── mcp/         (from zengury/mcp-ros-diagnosis)
├── scenarios/   (from zengury/cli-enhanced)
└── gateway/     (future)
```

---

## 阶段 6：零售场景分析

### 零售任务拆解

用 Snakes 架构分析"客户点单 → 机器人取货"：

**能用的**：Agent loop（任务拆解）、memkit（记货架位置）、Safety（限速）、Fleet（多机器人共享货架知识）

**缺的**：订单接入层（Order Gateway）、SLAM/地图、商品视觉识别（VLM/YOLO）、抓取策略（VLA/grasp policy）、多机器人调度

### 没有 VLA 能行吗？

**能，但冷启动更痛。** 关键洞察：

```
Trial 1: LLM 推理 "从正面抓" → 失败
Trial 2: 读 Episodic，推理 "试更高位置" → 失败
Trial 3: 推理 "从上方抓瓶颈" → 成功
→ Critic 提升到 Semantic
Trial 4 (下一单): 直接用 Semantic 里的参数 → 成功
```

**决策 19**：VLA 和自学习不是二选一。VLA 减少冷启动痛苦（10→1 次失败），自学习覆盖长尾（10 万 SKU VLA 不可能全训练到）。

### 生命周期成本

**用户关键输入**："对比的不是冷启动速度，而是全生命周期成本。VLA 要泛化需要海量训练数据，拿牛奶可能是千分之一的场景。"

**决策 20**：Snakes 的经济优势在长尾——10,000 台机器人在真实环境中自学习，比实验室里 teleop 采集数据更便宜、更多样、更真实。

**决策 21**：Snakes 产出的 EventLog 数据（轨迹 + 推理链 + 成败标签）= VLA 训练数据的最佳来源。飞轮：运行 → 采集 → 训练 VLA → 部署 → 运行更好 → 更多数据。

---

## 技术选型汇总

| 决策 | 选择 | 原因 |
|------|------|------|
| Agent 接口 | CLI (非 MCP) | 96% token 节省 |
| Agent Loop | Pi's agent-loop 架构 | 用户喜欢，成熟且灵活 |
| 记忆 | memkit 6 层 | 自研，已验证 |
| 统一日志 | EventLog (JSONL) | 取代 Episodic，单一来源 |
| 第一台机器人 | AGIBOT X2 | 纯 ROS2，30 DOF，有 SDK |
| 第一个场景 | 密室逃脱黑客马拉松 | 学生可参与，验证学习闭环 |
| 语言 | 全 Python | LLM SDK 生态最全 |
| Monorepo | 方案 A (单体) | MVP 完整性 > 可扩展性 |

---

## 待解决的开放问题

1. **自学习能否工业级可靠**？SayCan/AutoRT 是研究成果，无大规模落地验证
2. **记忆索引规模**：一年的 EventLog 怎么高效检索？向量库 + RAG 够吗？
3. **Critic 准确率**：RuleBased 覆盖有限，LLM Critic 有幻觉风险
4. **sim2real gap**：Mock/仿真学到的 skill 在真机上能用吗？
5. **Safety 的真实有效性**：关节限位只是第一层，碰撞预测、工作空间约束需要更深层安全
6. **身份持久化**：ROBOT.md 跨 session 的更新机制（学到新 skill 后自动更新）

---

## 文件参考

| 文件 | 说明 |
|------|------|
| `ARCHITECTURE.md` | 架构蓝图（系统图 + 数据流 + 层级定义） |
| `MERGE_PLAN.md` | 4 周合并路线图 |
| `CLAUDE.md` | 未来 Claude 会话自动加载的项目上下文 |
| `docs/EVENTLOG_SCHEMA.md` | EventLog 完整 schema 规范 |
| 本文件 | 研发过程的完整思路链 |

---

*最后更新：2026-04-18*
*涉及的 Claude 会话：sdk2cli 设计 → 智元机器人分析 → HAL 审计 → 控制架构 → Snakes 定位 → 记忆集成 → EventLog 统一 → 零售分析 → 数据飞轮战略*
