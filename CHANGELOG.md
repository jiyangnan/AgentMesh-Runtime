# Changelog

## v2.2.0 — 2026-06-18

### Phase 1-3 运行时优化

#### New: context-brief（动态上下文摘要）
- `scripts/update_context_brief.py` — 自动维护 context-brief.md
- `skills/context-brief/SKILL.md` — Skill 文档

#### New: heartbeat-systemic（系统性心跳自检）
- `scripts/heartbeat_systemic.py` — 6 项健康检查（MEMORY/Neo4j/Cron/context-brief/sync/temp）
- `skills/heartbeat-systemic/SKILL.md` — Skill 文档

#### New: ooda-anti-patterns（OODA 闭环反模式检测）
- `skills/ooda-anti-patterns/SKILL.md` — 三种反模式文档
- 集成到 `scripts/ooda-driver.py`：blind_retry / phantom_progress / pivot_exhaustion

#### Updated: ha-memory（情景记忆系统）
- `src/vector_store.py` — Gemini Embedding 向量存储（gemini-embedding-2, 3072维, DoH DNS绕过）
- `src/unified_memory_recall.py` — 新增向量检索后端（recall_vector, weight=1.5）

#### Updated: ooda-loop
- `scripts/ooda-driver.py` — 反模式检测 + prompt 注入
