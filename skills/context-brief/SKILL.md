---
name: context-brief
version: 1.0
description: |
  动态上下文摘要机制。在复杂任务完成后自动更新 context-brief.md，
  新会话启动时注入上下文，解决会话间上下文丢失问题。
  触发时机：复杂任务（>3 步 OODA 闭环）完成后。
trigger: |
  当完成一个复杂任务（3+ 步骤、有明确目标的任务）时，
  调用 update_context_brief.py 写入当前工作上下文。
  不需要每次单轮对话都更新。
---

# context-brief — 动态上下文摘要

## 概念

context-brief.md 是一个自动维护的结构化文件，记录：
- 当前进行中的任务（状态、步骤、下一步）
- 近期完成的决策和任务
- 已知问题
- 计划提醒

**目标**：新会话启动时无需翻 memory/ 日志，直接读 context-brief 即可了解当前状态。

## 文件格式

```markdown
# 📋 Context Brief — 近期工作上下文

> 最后更新：YYYY-MM-DD HH:MM · 复杂任务完成后自动更新
> ⚠️ 不要手动编辑此文件，由 update_context_brief.py 自动维护

## 🔨 进行中
### [任务名]
- **状态**：Phase X/Y
- **当前步骤**：...
- **下一步**：...
- **阻塞**：...

## ✅ 近期完成（最近 3 次会话）
- **YYYY-MM-DD**: [任务描述]

## 📋 重要决策记录
- **YYYY-MM-DD**: [决策内容] → [理由]

## ⚠️ 已知问题
- [问题描述]（发现日期）

## 📅 计划提醒
- **YYYY-MM-DD**: [要做的事]
```

## 核心脚本

**路径**：`{WORKSPACE}/scripts/update_context_brief.py`

| 命令 | 功能 |
|------|------|
| `python3 update_context_brief.py` | 全量扫描，更新全部字段 |
| `python3 update_context_brief.py --task "完成了XXX"` | 追加任务完成记录 |
| `python3 update_context_brief.py --status` | 输出 JSON 状态（程序化读取） |

## 与 AGENTS.md 的集成

在 AGENTS.md 的「Every Session」步骤 5 之后加入：

```
6. **Read `context-brief.md`** — 了解近期工作上下文（自动更新，不要手动编辑）
```

## 与 OODA 闭环的集成

当 OODA 闭环到达终态（done/blocked）时，agent 应执行：

```bash
python3 {WORKSPACE}/scripts/update_context_brief.py --task "完成了[任务名]：[结果摘要]"
```

## 触发时机规则

| 场景 | 是否更新 |
|------|----------|
| 单轮简单问答 | ❌ 不更新 |
| 2 步以内完成的任务 | ❌ 不更新 |
| OODA 闭环结束 | ✅ 更新 |
| Cron 任务完成 | ✅ 更新 |
| 用户明确要求 | ✅ 更新 |

## 状态检查

```bash
python3 update_context_brief.py --status
# 输出示例：
# {
#   "active_checkpoints": 1,
#   "recent_completions": 5,
#   "known_issues": 2,
#   "brief_exists": true,
#   "last_updated": "2026-06-18T19:39:00"
# }
```

## 与 ACK Generic Heartbeat 的区别

| 维度 | ACK | ARS context-brief |
|------|-----|-------------------|
| 触发时机 | Cron 定期（每周日） | 复杂任务完成时 |
| 内容 | 健康检查 + MEMORY 清理 | 项目状态 + 决策记录 |
| 面向 | Agent 自我维持 | 会话上下文传递 |
| 可被人类读 | 否 | 是 |
