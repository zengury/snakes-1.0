---
description: 归档今天的研发讨论到 RESEARCH_JOURNAL.md 和 CLAUDE.md
---

回顾今天这次会话里的所有讨论，做三件事：

## 任务 1：更新 docs/RESEARCH_JOURNAL.md

在文件末尾追加新章节，格式：

```
## 阶段 N：<今日主题>（YYYY-MM-DD）

### 决策 XX：<标题>
**背景**：<为什么讨论这个>
**选择**：<最终选了什么>
**原因**：<为什么选这个而非替代方案>

### 决策 XX+1：...

### 今日待解决
- <新发现的开放问题>
```

要求：
- 决策编号接续现有最大编号，不要重启
- 每个决策必须有 Why（一两句说清楚）
- 只记真正的决策和转折，不记闲聊
- 如果今天没有新决策，写"无新决策，继续执行"

## 任务 2：检查 CLAUDE.md

如果今天的决策改变了以下任何一项，更新 CLAUDE.md：
- 架构模块或数据流
- "Key Design Decisions" 列表
- "Current Status" 的 checkbox
- "Related Repos" 表格
- 技术选型

如果没变化，不要碰 CLAUDE.md。

## 任务 3：提交推送

```bash
git add docs/RESEARCH_JOURNAL.md CLAUDE.md
git commit -m "Journal: YYYY-MM-DD <今日主题一句话概括>"
git push
```

## 完成后报告

用这个格式：

```
📋 今日归档完成
- 新增决策：#XX - #XX
- 更新文件：RESEARCH_JOURNAL.md [, CLAUDE.md]
- 开放问题：N 个新增
- commit: <hash>
```
