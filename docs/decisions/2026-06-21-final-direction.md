---
title: AgentMesh Runtime — 最终方向决策（纯开源化）
date: 2026-06-21
author: Claude Code（执笔）· 用户拍板
status: ✅ 当前执行依据
supersedes:
  - 2026-06-18-claude-产品化方案.md
incorporates:
  - 2026-06-18-claude-技术尽调与综合结论.md
  - 2026-06-19-codex-交叉评审综述.md（部分采纳）
tags: [agentmesh, runtime, 决策, 纯开源化, 单仓]
---

# AgentMesh Runtime — 最终方向决策（纯开源化）

## 关键背景变更（为什么这次重写）

经过和 Codex 的两轮事实级讨论 + 用户决策，**核心定位已经从「分仓 + CLI + Server 化」塌缩为「纯开源化」**：

1. **事实裁决已收敛**（2026-06-21）：双方一致认定原计划列为「server 端护城河」的能力（OODA Policy / Verification / Hybrid Memory hosted quality / Anti-pattern KB / Context Brief 智能化）**当前代码里全部不存在**——都是规则/启发式/阈值，不是 IP。归类为「未来要新建的 Server 路线图」，不是「现状护城河」。
2. **用户观察**（关键）：「我的智能体直接使用这一套，它自身就自带 LLM，根本不需要抽象相关的层出来。」ARS 是 agent 调的脚手架，智能在 agent 一侧，不该在产品内部凭空塞 LLM 层。
3. **用户拍板**：定位 = 「开源核心 + 可选轻量托管」。MVP 只做开源单仓；server 后期按需上一个**只代管 Neo4j+向量库**的极薄 server（不做智能层），不是 MVP。

---

## 目标形态：单仓，Apache 2.0 全开源

| 项 | 决策 |
|---|---|
| 仓库 | **单仓** `AgentMesh-Runtime`，Public，Apache 2.0 |
| 模式 | **只有本地模式**。无 BYOK/Hosted 双模式分裂 |
| Server | **MVP 不做**。预留口子，后期按需做「代管 Neo4j+向量库」的极薄 server |
| 计费 | 无 |
| 多租户 | 无（本地工具不涉及） |
| CLI 改造 | 不需要 Backend 抽象，纯本地 CLI |
| 集成 | 给 OpenClaw / Claude Code / Codex / Hermes 等 agent 用 |
| 工程量 | **几周**（脱敏 + 包重构 + 改名 + 工具链对齐） |

---

## Phase 0 — 脱敏 + 安装可用性 gate（开源前阻塞项）

**0.1 脱敏**：清掉硬编码私人 PII（人物实体、特定 episode UUID、品牌特定 hack 等）。

**0.2 工具链对齐生态范本**：`pip + setuptools` → **`uv + hatchling`**（对齐 AgentMesh-Lecturecast / lecturecast-server）。

**0.3 CLI 改名**：`xng`（内部梗）→ **`agentmesh-runtime`** + 短别名 `amr`；`xng` 保留 alias 一个版本。

**0.4 验证 gate**：grep 私人标识为空、`uv sync` 成功、`doctor` 绿、`recall`/`demo` 跑通。

## Phase 1 — 抽包 `agentmesh_runtime` + 修工程硬伤

**1.1 把强内聚核心团整体进包**：`src/agentmesh_runtime/` 包结构。

**1.2 修工程硬伤**：向量层 O(n) 暴力余弦搜索加文档警告；「SQLite FTS」名实不副的虚词改口。

**1.3 不引入多租户注入**——单仓无 server。

## Phase 2 — 文档 + 发布

**2.1 README / AGENTS.md / docs**——诚实卖点：
- ✅ 记忆栈（多后端 failover + 向量召回 + ingest 闭环）
- ✅ 一致性恢复（deferred sync + checkpoint + rehydrate）
- ✅ OODA 状态机骨架（决策智能由调用方 agent 提供）
- ✅ 反模式检测（规则版）
- ❌ **不再宣传** "first-principles runtime"（代码层不存在）
- ⚠️ ~~不再宣传 "FTS"（实为 LIKE）~~ ← **此条已撤回**：2026-06-22 执行 Phase 1.2 时实际核对代码，recall_sqlite() 用的是真 FTS5（bm25 + snippet），FTS 卖点真实成立，不需要改口。

**2.2-2.4**：可选落地页 / CI / 发布。

## Phase 3（后期按需）— 极薄托管 server

**触发条件**：有真实用户问「能不能帮我托管 Neo4j」，才做。不是 MVP。

只做：托管 Neo4j + 托管向量库 + 简单 API key 鉴权。

不做：LLM 智能层、语义验证、reranker、Anti-pattern KB——这些是 Codex §9 的「未来路线图」，触发条件未到不做。

## 风险 / 后期开放问题

1. 完全开源后，如果有用户复刻并加 server 卖钱，接受这个生态结果。
2. Phase 3 触发时，需要重新评估：是真做托管，还是引导用户用 Neo4j Aura 之类的现成托管服务。

## 端到端验收

1. `grep` 私人标识为空。
2. `uv sync` + `uv run agentmesh-runtime {doctor, memory recall, loop run examples/goal_frame.example.json, demo}` 全绿。
3. 文档无虚词。
4. CI 通过，可 `uv pip install` 安装运行。
5. GitHub repo Apache 2.0，有 release。

---

*署名：Claude Code · 2026-06-21 · 用户拍板*
