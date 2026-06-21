# Module 2 — High-Availability Episodic Memory

## Goal
Create a local episodic memory system that remains usable even when one backend fails.

## Architecture

```text
Recall:
Neo4j Episode Graph
  ↓ fallback
SQLite FTS
  ↓ fallback
Raw memory/session grep

Ingest:
Session transcript
  ↓
clean + summarize + topics + entities
  ↓
SQLite write first
  ↓
Neo4j write second
```

## What was implemented in the source system
- unified recall entrypoint
- Neo4j episode graph ingestion
- SQLite FTS fallback
- raw session/file grep as last resort
- checkpoint reindex support
- stable chunk IDs to avoid duplicate rebuild pollution
- entity extraction + normalization
- relationship rebuild safety (`TAGGED` / `MENTIONS` reset before rebuild)
- ranking improvements:
  - exact phrase
  - summary hit
  - body hit
  - topic hit
  - entity hit
  - recency boost
  - current-session echo penalty

## Use cases
- “Do you remember what we decided?”
- reconstructing prior upgrades or debugging sessions
- surviving embedding quota failures
- keeping recall available when graph service is down

## Value
- graceful degradation instead of amnesia
- local-first memory
- better historical recall quality
- reproducible agent memory behavior

## Core files
- `src/episode_ingest.py`
- `src/unified_memory_recall.py`
- `src/neo4j_recall.py`
