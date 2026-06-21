# Architecture

## Three-module reinforcement system

### Module 1 — First-Principles Runtime
A reasoning reinforcement layer.

### Module 2 — High-Availability Episodic Memory
A memory reinforcement layer.

### Module 3 — Autonomous-Loop
An execution reinforcement layer.

These three modules work together:
- module 1 improves decision quality
- module 2 preserves context and prior decisions
- module 3 keeps the agent moving toward completion

---

## Memory flow

### Ingest path
1. read session transcript
2. strip metadata noise
3. extract summary
4. extract topics
5. extract entities
6. write SQLite first
7. write Neo4j second

### Recall path
1. query Neo4j
2. if insufficient, query SQLite FTS
3. if still weak, grep raw files/sessions
4. dedupe + rank

---

## Reliability principle

The system must not depend on a single backend.

| Backend | Purpose | Failure impact |
|---|---|---|
| Neo4j | graph/episode recall | degraded quality only |
| SQLite FTS | local text fallback | degraded quality only |
| raw grep | final safety net | ugly but still recallable |

---

## Publishability
This repository intentionally separates generic logic from operator-specific files and paths by using environment variables.
