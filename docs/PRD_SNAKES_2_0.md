# Snakes Runtime 2.0 — PRD

版本：0.1（对齐用）  
定位：机器人长周期任务的 **Agent Runtime + CLI 工具链 + Failure-first 语义 + 统一事件流 + 技能沉淀**  
原则：不做过度设计；先把“贯穿链路”跑通。

> 补充说明：PRD 保持可执行与简洁；更完整的讨论与设计取舍收录在 `docs/design/NOTES_SNAKES_2_0.md`。

---

## 1. 背景

我们用“密室逃脱”来抽象一类真实机器人长周期任务的共同难点（并不限定为比赛）：

- **多模态频繁切换**：观察 → 移动 → 操作 → 思考，任何环节都可能中断或漂移。
- **失败是常态**：视觉误检/遮挡、操作滑落/夹空、系统超时/断连。
- **缺乏统一的失败语义与恢复机制** 会导致任务时间暴涨。
- **缺少可复盘证据链**，无法解释“为什么失败/为什么成功/如何变快”。

前期探索（diagnosis、CLI、PID tuner、agent 框架等）本质上都在补齐“模型之外的系统能力”。Snakes 2.0 的目标是把这些能力收敛成一个可复用的 runtime 主线：**执行闭环 + 失败语义 + 事件总线 + 技能沉淀**。

---

## 2. 目标（Goals）

G1. **一条黄金路径**：所有执行必须走 `AgentLoop → Tools → Observe/Verify → EventLog`。

G2. **Failure-first（强制契约）**：所有工具返回统一结构（成功/失败/超时、失败类型、现象、可重试、成本）。runtime 强制校验并记录。

G3. **CLI 工具链是特色与主入口**：以 manifest/CLI 的方式接入跨本体能力，并提供组合语义（并发读、超时、重试、取消）。diagnosis 也作为 CLI 工具的一类。

G4. **EventLog 是唯一事实源**：认知、工具调用、观测、诊断、系统故障都写入统一事件流；支持 watch/replay/score。

G5. **技能框架（skillpack）**：可复用能力池，包含脚本/工作流/VLA/诊断恢复流程；沉淀重点优先是 **验证器与恢复器**。

G6. **默认完全自主（Autonomy）**：运行中不允许人类注入策略/动作；只允许监控与 e-stop（e-stop 记入日志）。

---

## 3. 非目标（Non-goals）

- 不把系统称为“操作系统（OS）”，避免误导；2.0 是 runtime/toolchain。
- 不做复杂知识图谱平台；ontology 只保留最小语义字段服务 verify/recover。
- 不做端到端训练管线；VLA 以“skill”形式封装即可。
- 不做通用评测系统；场景/关卡属于应用层。

---

## 4. 核心用户

- 策略/应用开发者：希望在不确定环境中更快完成任务（用时优先）。
- 运维/测试：希望快速定位失败原因、回放复盘、提升稳定性。

---

## 5. 产品形态（用户可见）

### CLI

- `snakes run ...` 运行一次任务（autonomy）
- `snakes watch --task-id ...` 实时监控（从 EventLog 聚合）
- `snakes replay --task-id ...` 回放
- `snakes score --task-id ...` 输出用时与失败统计
- `snakes diag ...` 诊断（写入 EventLog）

补充：提供 `--provider mock` 用于离线回归测试主线（无 API key），不作为产品能力宣传点。

---

## 6. 架构（2.0）

```text
┌─────────────────────────────────────────────────────────┐
│                 Runtime Kernel (Agent Loop)              │
│  stream → tool → observe/verify → recover → loop         │
└───────────────┬───────────────────────────┬──────────────┘
                │                           │
                │ executes                  │ writes/reads
                ▼                           ▼
┌───────────────────────────────┐   ┌──────────────────────────────┐
│        CLI Toolchain           │   │            EventLog           │
│  manifest → tools schema       │   │ unified JSONL timeline        │
│  composition: parallel/timeout │   │ watch / replay / score        │
│  ALWAYS returns ToolOutcome    │   └───────────────┬──────────────┘
└───────────────┬───────────────┘                   │
                │ uses                               │ feeds
                ▼                                    ▼
┌───────────────────────────────┐         ┌──────────────────────────┐
│ Failure-first Semantics        │         │ Skills (skillpack)        │
│ ToolOutcome + Taxonomy + Cost  │         │ workflow/script/VLA        │
└───────────────────────────────┘         └──────────────────────────┘

(Gateway/权限/通道为后续模块：2.0 仅预留字段与接口，不实现服务)

此外，架构中预留 **机器人本地小模型（on-device small model）** 的位置：用于离线/低延迟能力（例如观测压缩、快速分类、基础恢复决策），并可与云端大模型协同。2.0 只预留 provider/接口，不做强绑定。
```

---

## 7. 2.0 里程碑（A→B→C）

### A：Failure-first 语义 + EventLog 可观测
- ToolOutcome/Taxonomy 强制校验（不合格写 warn）
- `watch/replay/score` 完整可用
- run_start 写入版本指纹（git_sha、模型、配置）

### B：skillpack/strategy 扩展（不动内核）
分步交付，避免一次做大：
- B1：skillpack 格式与加载（2.0 先用 JSON：`skillpack.json`，stdlib-only）
- B2：skillpack 执行器（以 tools 为后端）
- B3：strategy 插件（run 前选择，run 中不可改）
- B4：提供 1 个 baseline strategy（time-first）用于回归与示例

### C：接入真实 sdk2cli
- daemon 执行器，系统故障语义（timeout/disconnect）
- 资源互斥与硬安全闸在工具链层落实
