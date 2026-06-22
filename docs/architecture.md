# Architecture

AgentMesh Runtime sits *under* a caller agent. The agent supplies the reasoning; this runtime supplies three things: a place to remember, a state machine to record what is being attempted, and a way to recover after a crash.

## Three layers

### 1. Episodic memory
Multi-backend ingest and recall. Sessions are summarized, tagged with topics and entities, and stored in SQLite first, then Neo4j. Recall fans out across Neo4j → SQLite FTS5 (BM25) → raw file grep → optional Gemini vector, then merges and re-ranks.

### 2. OODA loop scaffolding
A state machine — Observe / Orient / Decide / Act / Verify / Record — that drives a single bounded goal toward `done`, `blocked`, `waiting_human`, or `aborted`. The decide and verify steps are intentionally minimal stubs; the *caller agent* supplies real reasoning. The runtime's job is to enforce that every step happens and that every action is recorded.

### 3. Consistency and recovery
A deferred sync ledger across SQLite ↔ Neo4j, a checkpoint store for active loops, and a `rehydrate` command that joins them into a startup snapshot. Lets the agent pick up where it left off after a crash, a restart, or a backend outage.

## Memory flow

### Ingest path
1. read session transcript
2. strip metadata noise
3. extract summary
4. extract topics
5. extract entities
6. write SQLite first
7. write Neo4j second; on failure, append a pending entry to the sync ledger
8. `agentmesh-runtime sync backfill` replays the ledger once Neo4j is back

### Recall path
1. query Neo4j (graph + Cypher)
2. query SQLite FTS5 (BM25 + snippet)
3. grep raw files / sessions
4. *(optional)* Gemini vector cosine — only when `GEMINI_API_KEY` is set
5. dedupe + re-rank with per-backend weights, recency boost, source adjustment

## Reliability principle

The system must not depend on a single backend.

| Backend | Purpose | Failure impact |
|---|---|---|
| Neo4j | graph / episode recall + relationship traversal | degraded quality only |
| SQLite FTS5 | local text fallback with BM25 ranking | degraded quality only |
| raw grep | final safety net | ugly but still recallable |
| Gemini vector (optional) | semantic recall | absent if no API key; everything else still works |

## What is intentionally not in this architecture

- **No LLM call** anywhere in this package. The "intelligence" comes from the caller agent.
- **No server, no multi-tenant layer.** Everything runs in one local process.
- **No reranker model.** Re-ranking is per-backend weights + simple heuristics.
- **No automated decision/verify intelligence.** Those are caller-side responsibilities.

For *why* these are absent, see [`docs/decisions/`](decisions/README.md).
