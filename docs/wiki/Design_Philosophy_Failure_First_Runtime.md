# Design Philosophy — Failure-First Robot Runtime（面向密室逃脱通关）

> 目标：**世界上第一次机器人在密室逃脱游戏中通关**。
>
> 关键洞察：长周期任务的难点不在于“单步动作能不能做”，而在于 **持续探索 + 记忆 + 多模态切换 + 失败恢复**。
>
> 因此 Snakes V1 必须从“成功假设的表面行动”升级为 **Failure-First（失败是一等公民）** 的闭环系统。

---

## 1. 为什么“更好的模型”不能替代 Runtime / sdk2cli

在纯软件任务中，更强模型常常能用 prompt + tool 直接做完；但在机器人任务里，模型强并不能让物理世界变得确定、安全或可复现。

### 1.1 sdk2cli 的意义：把机器人变成“可控的计算机”

sdk2cli 的核心价值不在于让 LLM“能调用工具”，而在于提供模型无法替代的系统能力：

1) **统一控制契约（跨机器人可迁移）**
- 屏蔽不同机器人底层差异（坐标系、速度/加速度限制、关节语义、传感器 availability）。
- 让策略/队伍只面对稳定的命令契约与 manifest，而不是 ROS2 topic 与设备细节。

2) **确定性安全闸（硬拦截）**
- joint/workspace/velocity 限制、互斥资源仲裁、危险命令 gating。
- 这些必须在低延迟、同步、确定性路径上执行，不能依赖“提示模型要小心”。

3) **可观测、可审计、可回放**
- “世界第一次通关”需要证据链：每一步命令/观测/失败原因都可追溯。
- 这是 runtime + eventlog 的系统资产，模型本身不会自动提供。

### 1.2 安装 runtime 的机器人 vs 没安装：真正差异

如果每一步默认成功，那么安装 runtime 的差异会被抹平；要让差异变大，runtime 必须提供：

- **闭环执行**：Plan → Act → Verify → Recover（每步验证 + 失败恢复）
- **失败一等公民**：失败被结构化记录、分类、聚类，进入学习/安全/复盘
- **跨模态切换契约**：观察/移动/操作/思考的进入/退出条件与异常语义统一
- **策略可插拔**：队伍写策略/技能/启发式，而不是改 agent loop 核心

---

## 2. 现阶段的关键问题：Skill 变成“成功脚本”，因此无迁移价值

目前常见的伪 skill：
- “这次钥匙在蓝杯子下面” → 这是 episodic 线索，不应被当作可迁移技能

### 2.1 Skill 需要具备：适用条件 + 可验证目标 + 失败模式 + 恢复动作

一个可迁移 skill 的最小结构：

- **Preconditions（适用条件）**：环境/物体/可达性/夹爪状态
- **Action**：执行的 tool sequence（可含参数策略）
- **Postconditions（可验证目标）**：如何确认成功（视觉/触觉/力矩/状态差分）
- **Failure modes（失败模式）**：抓取滑落、误检、遮挡、超时、系统错误
- **Recovery（恢复策略）**：换视角、重试、调整参数、退回重定位、请求帮助

没有这些结构，skill 只能是“同场景复读脚本”，在其他环境必然失效。

### 2.2 V1 应优先固化的 skill 类型：验证器与恢复器（跨场景价值最高）

相比“成功路径脚本”，V1 更值得学习的是：
- `verify_grasp_success()`
- `recover_from_slip()`
- `change_viewpoint_to_reduce_occlusion()`
- `retry_with_adjusted_params()`
- `handle_system_fault_and_resume()`

这些 skill 的迁移性强，且直接对应长周期任务最常见的断点。

---

## 3. V1 设计总原则：Failure-First 闭环（不是 Success-Assumed 行为演示）

### 3.1 工具调用必须返回结构化 outcome（不是 ok/文本）

统一建议返回（示例）：

```json
{
  "outcome": "success|fail|partial|timeout",
  "failure_type": "perception|manipulation|system|safety|unknown",
  "phenomenon": "可观测现象（必须可复盘）",
  "reason_hypothesis": "可选：推断原因",
  "retryable": true,
  "metrics": {"latency_ms": 123, "slip": 0.2, "pose_error": 0.05},
  "state_delta": {"gripper": "closed"}
}
```

否则 agent 无法学习“哪里会坏、为什么坏、怎么修复”，数据也无法用于后续训练。

### 3.2 Verify 必须是强制步骤（runtime 层硬要求）

- 每次 tool call 后都必须 observe（哪怕 mock 也要返回 observation）
- Postcondition 不满足则自动写 failure，并触发 recovery 分支

### 3.3 在 Mock 场景里必须引入“可控失败注入”（否则策略无法拉开差距）

本项目 V1 指定的三类失败注入优先级：

1) **视觉（Perception）**
- 遮挡、模糊、误检、漏检、反光
- 返回可复盘 phenomenon（例如："blue_cup confidence dropped"）

2) **操作（Manipulation）**
- 抓取滑落、夹爪打滑、力度不足、碰撞
- 产生可量化 metrics（slip score / torque spike / retry count）

3) **系统（System）**
- tool 超时、daemon 断连、返回码异常、资源被占用
- 要求 recovery：重连/降级/暂停/安全停机

失败注入必须：可配置概率、可设置 seed、可在 eventlog 中复现。

---

## 4. EventLog：比赛的“裁判记录仪”与学习数据资产

EventLog 的地位：
- 既是比赛评测证据链（动作、用时、失败恢复）
- 又是学习/技能固化/后续训练数据的唯一真相来源

V1 对 EventLog 的最低要求：
- 记录每次 tool_call/tool_result 的结构化 outcome
- 记录每次 observe 的 observation 摘要
- 记录 task_end：outcome + score + 用时
- 支持 replay（从 log 重放并复盘策略）

---

## 5. Hackathon 的产品形态：Runtime 提供平台能力，队伍只写策略

为了让参赛队在 Snakes 上做“二次开发策略”，V1 必须提供明确扩展点：

- Strategy 插件接口（hooks / policy / prompt / skill selection）
- 固定的 agent loop（不可被队伍随意改动，否则不可比）
- 统一 tools 契约与资源仲裁

这样比赛比的是：
- 谁更会探索（信息增益）
- 谁更会验证与恢复（Failure-First 能力）
- 谁更会用记忆减少重复（长周期优势）

---

## 6. 评分导向（V1 约束）：用时优先

本项目 V1 的评分权重决定为：**用时优先**。

因此 runtime 必须显式暴露并记录：
- 总用时、每步 latency、重试次数
- recovery 是否有效（有效则节省时间）
- 是否存在无效动作循环（探索效率差）

在 Failure-First 的前提下，“用时”才是可比较的能力指标，而不是脚本式成功。

---

## 7. V1 的一句话验收标准（建议）

在开启视觉/操作/系统三类失败注入的条件下：

- 同一 seed 的密室逃脱场景，策略在第二次运行中能显著降低用时（通过记忆与恢复策略）
- EventLog 能完整解释：哪些失败发生了、采取了什么恢复、为什么最终节省时间
- 队伍只通过 Strategy/Skills 扩展点即可参赛，不需要改 runtime 核心
