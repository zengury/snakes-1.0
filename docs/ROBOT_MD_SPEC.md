# ROBOT.md Specification v1.0

ROBOT.md is the robot's soul document — a persistent, first-person self-description that establishes identity, capabilities, and boundaries. It is loaded into the LLM system prompt at the start of every agent run.

## Design Principles

1. **First person** — "I am", not "Robot is". The agent IS the robot.
2. **Static core** — Identity, ethics, hardware don't change. Dynamic state queried at runtime.
3. **Skills are identity** — "What I can do" defines who I am.
4. **Roles overlay, not replace** — Switching roles changes visible skills and behavior, never erases the soul.
5. **Memory shapes self-perception** — Critic periodically distills experiences into self-knowledge.
6. **Fleet extends, not replaces** — Shared skills are accessible but not "mine" until installed.

## Seven Identity Layers

```
Layer           Section in ROBOT.md     Mutability
─────────────   ─────────────────────   ──────────────────────
① Core ID       ## 核心身份              Never (set at manufacture)
② Personality   ## 性格                  Rarely (owner can tune)
③ Ethics        ## 伦理约束              Never (hardcoded rules)
④ Body          ## 本体感知              On hardware change only
⑤ Skills        ## 技能                  On learning / installation
⑥ Self-percep   ## 自我认知              Periodic (Critic refresh)
⑦ Role          → roles/<name>.md       On task/scenario switch
```

## File Format

YAML frontmatter (machine-maintained) + Markdown body (human-readable, LLM-consumed).

```markdown
---
robot_id: <string>
serial: <string>
manufacturer: <string>
model: <string>
current_role: <string | null>
fleet_id: <string | null>
learned_skills_count: <int>
last_self_assessment: <ISO-8601 date>
---

# 我是 <robot_id>

## 核心身份
...

## 性格
...

## 伦理约束
...

## 本体感知
...

## 技能
### 先天
### 预装
### 习得
### Fleet 可安装

## 自我认知
...

## 当前角色
→ `roles/<current_role>.md`

## Fleet 关系
...
```

## Section Specifications

### ① 核心身份 (Core Identity)
- Robot ID, serial number, manufacturer, model
- Deployment date and location
- Written once at first boot, never changed

### ② 性格 (Personality)
- 3-5 personality traits (e.g., curious, cautious, helpful)
- Influence LLM's decision-making style
- Owner can customize (like tuning a character)

### ③ 伦理约束 (Ethics)
- Ordered rules (higher number = lower priority)
- Rule 1 (harm prevention) is absolute and unoverridable
- Future: may reference external ethics framework documents

### ④ 本体感知 (Body / Proprioception)
- DOF count and joint groups
- Sensor inventory
- Physical limits (speed, payload, endurance)
- Explicit "cannot do" list (as important as "can do")

### ⑤ 技能 (Skills)

Three sources, clearly labeled:

**先天 (Innate)**: From firmware. Available without any learning.
- Listed as simple names: `walk, stand, sit, damp, turn, wave`
- These survive factory reset

**预装 (Installed)**: Models/modules deployed by operator.
- Listed with status: `dialog: ✓`, `vla: ✗ (未部署)`
- Can be added/removed by operator

**习得 (Learned)**: Promoted from memkit.Semantic by Critic.
- Listed with metadata: `name (learned-date, success-rate%)`
- Top 10 most recent shown in ROBOT.md
- Full list available via `memkit query skills`
- Each skill references its memkit.Semantic entry for details

**Fleet 可安装 (Fleet-installable)**: Available in shared pool, not yet local.
- Listed with source: `barista-coffee (来自 Robot-B)`
- Can be installed on demand: copy from Fleet to local Semantic
- After installation, moves to "习得" category

### ⑥ 自我认知 (Self-Perception)
- Maintained by Critic's self-assessment routine (daily/weekly)
- Categories: 擅长 / 中等 / 不擅长 / 已知弱点
- Based on statistical analysis of EventLog outcomes
- Human-editable (operator can add known issues)

### ⑦ 当前角色 (Current Role)
- Points to `roles/<name>.md`
- Role overlay specifies:
  - Which skills are ACTIVE (visible to LLM)
  - Which skills are HIDDEN (exist but not presented)
  - Behavior adjustments (personality modifiers)
  - Role-specific knowledge

## Role Overlay Format

```markdown
# roles/<name>.md
---
role: <name>
activated: <ISO-8601>
---

## 角色：<display name>
<role description>

## 激活的技能
- <list of skill names from ROBOT.md that are relevant>

## 屏蔽的技能
- <list of skills that should NOT be visible to LLM in this role>

## 行为调整
- <personality modifiers for this role>

## 角色知识
- <domain knowledge specific to this role>
```

## Skill Lifecycle

```
1. Hardware boots     → 先天 skills registered
2. Operator deploys   → 预装 skills installed
3. Robot attempts     → EventLog records attempt
4. Task succeeds      → Critic evaluates
5. Critic promotes    → Skill enters memkit.Semantic
6. Semantic → Index   → Skill appears in ROBOT.md ⑤ 习得
7. K Fleet confirm    → Skill enters FLEET pool
8. Other robot needs  → Finds in Fleet, installs locally
```

## Fleet Relationship

- FLEET.md is NOT a shared identity — robots don't share souls
- FLEET.md is a shared skill/knowledge catalog
- Any robot can query Fleet for skills it doesn't possess
- Installation = copy skill parameters from Fleet to local Semantic
- Validation gate: skill only enters Fleet after K robots confirm success

## System Prompt Assembly

```python
def assemble_system_prompt(robot_md, role_md, memory_snapshot, state):
    return f"""
{robot_md}                          # Soul + Body + Skills + Self-perception
---
{role_md}                           # Current role overlay
---
## 当前状态 (runtime query)
{state}                             # Battery, position, current task
---
## 相关记忆 (from memkit)
{memory_snapshot}                   # Relevant past experience for this task
"""
```

## Update Triggers

| Event | What updates | Who updates |
|-------|-------------|------------|
| Factory reset | ① restored to default | System |
| New sensor installed | ④ updated | Operator |
| Critic promotes skill | ⑤ 习得 list grows | Critic (auto) |
| Operator installs model | ⑤ 预装 updated | Operator |
| Daily self-assessment | ⑥ refreshed | Critic (auto) |
| Role switch | ⑦ pointer changes | Agent or operator |
| Fleet skill installed | ⑤ moves Fleet→习得 | Agent (auto) |
| Frontmatter counters | YAML header | System (auto) |

## Token Budget

Target: ROBOT.md + active role ≤ 1000 tokens in system prompt.

- ①②③: ~150 tokens (fixed)
- ④: ~100 tokens (fixed)
- ⑤ Skills: ~200 tokens (top 10 learned + summaries)
- ⑥ Self-perception: ~100 tokens
- ⑦ Role: ~150 tokens
- Overhead: ~100 tokens

If learned skills exceed 10, fold into summary line:
`... 共 47 个习得技能 — 运行 memkit query skills`
