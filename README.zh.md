# AgentMesh Runtime

[English](README.md) · 中文

> 🟣 **[AgentMesh](https://github.com/jiyangnan/agentmesh-core)** 生态成员 — 全部相关仓库见 [生态索引](https://github.com/jiyangnan/agentmesh-core/blob/main/docs/ECOSYSTEM.zh.md)。

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#)
[![Brand](https://img.shields.io/badge/brand-AgentMesh-6E4AFF.svg)](https://agentmesh360.com)
[![Website](https://img.shields.io/badge/website-runtime.agentmesh360.com-CC785C.svg)](https://runtime.agentmesh360.com)

> **本地优先的 AI Agent 运行时脚手架。** 给你的 Agent(Claude Code、OpenClaw、Codex、Hermes,任何一个)加上跨会话的持久记忆、一个把任务执行过程结构化记录下来的有界循环,以及崩溃/重启后干净拾起的能力。所有数据都在你自己的机器上。

这是位于你的 Agent **下面一层**的运行时——它不自带 LLM,也不替你做决策。**你的 Agent 仍然是脑子**。AgentMesh Runtime 是让这颗脑子能记住、能重试、能恢复的脚手架。

## 它真正给你的能力(诚实清单)

- 🧠 **持久情景记忆。** 多后端召回 — Neo4j 图 → SQLite FTS5(BM25)→ 原始文件 grep → 可选 Gemini 向量。任一后端挂掉,其余继续服务。
- 🔁 **有界 OODA 循环脚手架。** 一个状态机,把每一步 Observe / Orient / Decide / Act / Verify / Record 落到持久轨迹里。**真正的决策由你的 Agent 提供**——这一层只做纪律约束和记录。
- 🛟 **崩溃 / 重启恢复。** SQLite ↔ Neo4j 的延迟同步账本、checkpoint 存储、`rehydrate` 命令,重启后能重建"我刚才到哪了"。
- 🩺 **自检。** `agentmesh-runtime doctor` 一条命令吐出 Neo4j 连通性、SQLite 健康、账本漂移、checkpoint 状态的 JSON 报告。
- 🚧 **规则式反模式检测**(OODA 循环用)—— `blind_retry` / `phantom_progress` / `pivot_exhaustion`。就是计数器和阈值,不是什么魔法。

## 它**不是**什么

- ❌ 不是 LLM,也不是 Agent。它给你已经在用的 Agent 做脚手架。
- ❌ 不是托管服务。没有云、没有账户、没有 API key。
- ❌ 不是"智能 OODA Policy Engine"。下一步逻辑是一个小状态机;具体怎么做由你的 Agent 决定。
- ❌ 不是(暂时不是)大规模系统。向量层是 O(n) 暴力余弦——个人 / 小团队规模够用;百万级向量请换 pgvector 或 faiss。

---

## 安装

```bash
git clone https://github.com/jiyangnan/AgentMesh-Runtime.git
cd AgentMesh-Runtime
uv sync
```

想用图后端的话,你还需要一个 **Neo4j**(社区版即可)。`docker/docker-compose.neo4j.yml` 一条 `docker compose up` 起好。

## 使用

```bash
# 环境自检(JSON 报告)
uv run agentmesh-runtime doctor

# 召回情景记忆
uv run agentmesh-runtime memory recall "你的查询" --top-k 5

# 摄入一份会话 transcript
uv run agentmesh-runtime memory ingest-file /path/to/session.jsonl discord

# 跑内置 OODA 循环 demo(用 examples/goal_frame.example.json)
uv run agentmesh-runtime demo

# 重启后重建"我刚才到哪了"
uv run agentmesh-runtime rehydrate --write-default --print-path
```

短别名:`amr` 在任何能用 `agentmesh-runtime` 的地方都可以用。旧名 `xng` 还能用一个版本周期。

## 配置

所有路径和端点都走环境变量——没有配置文件:

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ARS_NEO4J_URI` | `bolt://localhost:7687` | Neo4j 端点 |
| `ARS_NEO4J_USER` | `neo4j` | Neo4j 用户名 |
| `ARS_NEO4J_PASSWORD` | `password` | Neo4j 密码 |
| `ARS_SESSION_BASE` | `~/.openclaw/agents` | `<agent>/sessions/*.jsonl` 根目录 |
| `ARS_MEMORY_DB` | `~/.openclaw/memory/main.sqlite` | SQLite 数据库路径 |
| `ARS_WORKSPACE` | `$PWD` | 工作空间根 |
| `GEMINI_API_KEY` | *(空)* | 设置后启用 Gemini embedding 向量召回 |
| `AGENTMESH_RUNTIME_DOH_BYPASS` | `0` | 设为 `1` 启用 DoH 兜底(透明代理 DNS 劫持环境下用) |

> 默认值还指向 `~/.openclaw/*` 是因为这段代码原生来自那里。你不跑 OpenClaw 的话,把 `ARS_SESSION_BASE` 和 `ARS_MEMORY_DB` 设到你自己存 transcript 和记忆的地方就行。把 env 前缀重命名为 `AGENTMESH_RUNTIME_*` 在路线图里。

---

## 让 AI Agent 来驱动这个

整个仓库的设计是**让你的 Agent 调用**,不是让你手动调。从 **[AGENTS.md](AGENTS.md)** 开始——它告诉 Agent 在会话内怎么用这些命令、什么时候摄入、什么时候 rehydrate、什么话**不能对人类许诺**。

## 状态

Alpha。记忆与一致性恢复层已经在真实工作里跑过,有干净的修复记录。OODA 循环脚手架能跑,但它的"决策智能"是故意做得很轻——那部分应当来自你的 Agent,不来自我们。

## License

Apache 2.0。详见 [LICENSE](LICENSE)。

跨 Agent 协作产生这个产品形态的过程(以及**有意没做**什么),见 [docs/decisions/](docs/decisions/README.md)。
