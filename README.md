# agent-reinforcement-system

> Official command surface: **xiaonangua CLI** (`xng`)

A production-minded agent runtime toolkit built around three reinforcement layers:

1. **First-Principles Runtime** — forces the agent to reason from axioms instead of habits.
2. **HA Episodic Memory** — a high-availability local memory stack with automatic failover across Neo4j, SQLite FTS, and raw session/files.
3. **Autonomous-Loop** — a bounded execution loop that lets the agent keep pushing a goal until it is done, blocked, waiting for human input, or aborted.
4. **Consistency and Recovery** — a deferred sync + checkpoint + rehydrate layer that keeps SQLite and Neo4j eventually consistent across restart-order failures and restores working state after reboot.

This repository packages the core runtime pieces so another agent/operator can reproduce the same behavior: stricter reasoning, durable memory, and bounded autonomous execution.

---

## Why this exists

Most agent demos break in three predictable ways:
- reasoning becomes hand-wavy
- memory disappears when one backend fails
- autonomy loops without a bounded runtime contract

This repo fixes those three failure modes as one system.

---

## What this project gives you

### Module 1 — First-Principles Runtime
Turns “first-principles-only” from a vague prompt idea into a runtime discipline.

**Effects**
- reduces hand-wavy answers
- forces explicit assumptions
- improves debugging and root-cause analysis
- makes output more explainable and auditable

### Module 2 — High-Availability Episodic Memory
Builds a local memory layer that does **not collapse when one backend fails**.

**Recall order**
1. Neo4j episode graph
2. SQLite FTS
3. raw memory/session grep

**Effects**
- avoids single-provider amnesia
- enables durable recall of prior sessions, decisions, and upgrades
- keeps memory usable even when embeddings or graph services fail

### Module 3 — Autonomous-Loop
Builds the execution reinforcement layer:
- Observe
- Orient
- Decide
- Act
- Verify
- Record
- Loop / Exit

This is what turns the agent from a smart responder into a bounded autonomous worker.

**Integrated runtime behavior**
- **Observe** calls HA memory recall
- **Orient / Decide** use first-principles reasoning rules
- **Record** writes loop memory events to both the runtime log and the main memory index

**Core runtime artifacts**
- `docs/module-3-autonomous-loop.md`
- `docs/module-4-consistency-and-recovery.md`
- `schemas/goal_frame.schema.json`
- `schemas/loop_state.schema.json`
- `src/autonomous_loop.py`
- `src/checkpoint_store.py`
- `src/startup_rehydrate.py`
- `src/sync_backfill.py`
- `src/sync_state.py`

---

## Repo structure

```text
agent-reinforcement-system/
├── README.md
├── pyproject.toml
├── requirements.txt
├── xng
├── docs/
│   ├── architecture.md
│   ├── module-1-first-principles.md
│   ├── module-2-ha-episodic-memory.md
│   ├── module-3-autonomous-loop.md
│   ├── module-4-consistency-and-recovery.md
│   └── quickstart.md
├── src/
│   ├── autonomous_loop.py
│   ├── checkpoint_store.py
│   ├── episode_ingest.py
│   ├── neo4j_recall.py
│   ├── startup_rehydrate.py
│   ├── sync_backfill.py
│   ├── sync_state.py
│   ├── unified_memory_recall.py
│   └── xng.py
├── examples/
│   ├── first_principles_system_prompt.md
│   ├── goal_frame.example.json
│   └── env.example
├── schemas/
│   ├── goal_frame.schema.json
│   └── loop_state.schema.json
└── docker/
    └── docker-compose.neo4j.yml
```

---

## Quick start

### CLI identity
- Product name: **xiaonangua CLI**
- Command: **`xng`**

### Install
```bash
pip install -e .
```

After install:
```bash
xng doctor
```

For local no-install usage:
```bash
./xng doctor
```

### 1. Start Neo4j
```bash
cd docker
cp ../examples/env.example .env
docker compose -f docker-compose.neo4j.yml up -d
```

### 2. Install Python deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Set environment
```bash
export ARS_NEO4J_URI=bolt://localhost:7687
export ARS_NEO4J_USER=neo4j
export ARS_NEO4J_PASSWORD=password
export ARS_SESSION_BASE=~/.openclaw/agents
export ARS_MEMORY_DB=~/.openclaw/memory/main.sqlite
export ARS_WORKSPACE=$PWD
```

### 4. Ingest sessions
```bash
xng memory ingest-file /path/to/session.jsonl discord
```

### 5. Recall memory
```bash
xng memory recall "First-Principles-Only"
xng memory recall "Hybrid-Vector-Graph neo4j ollama"
```

### 6. Run the autonomous loop demo
```bash
xng demo
xng loop run examples/goal_frame.example.json
```

### 7. Generate startup recovery context
```bash
xng rehydrate
xng rehydrate --write-default --print-path
xng bootstrap
xng bootstrap --stdout
```

Standard startup recovery paths:
- JSON snapshot → `state/rehydrate-snapshot.json`
- bootstrap text → `state/startup-context.txt`

This demo now exercises the integrated stack:
- recalls prior memory through `unified_memory_recall.py`
- uses first-principles-oriented reasoning for action selection
- writes loop events to `./runtime/loop_memory.jsonl`
- persists loop events into the main Neo4j + SQLite memory path

---

## Key design principle

> Memory must degrade gracefully, not disappear.

If Neo4j fails, SQLite still works.
If SQLite fails, raw file recall still works.
If embeddings fail, keyword + graph recall still works.

---

## CLI commands

```bash
xng --help
xng memory --help
xng loop --help

xng memory recall "query"
xng memory ingest-file path/to/session.jsonl
xng memory ingest-session <session-id>
xng loop run examples/goal_frame.example.json
xng loop step examples/goal_frame.example.json
xng sync status
xng sync backfill
xng rehydrate
xng bootstrap
xng doctor
xng demo
```

---

## Polish / repo hygiene

- runtime logs are ignored (`runtime/*.jsonl`)
- state ledgers/checkpoints are ignored (`state/*.jsonl`, `state/checkpoints/`)
- packaging artifacts are ignored (`*.egg-info/`)
- installable entrypoint is defined in `pyproject.toml`

## Core scripts

### `src/episode_ingest.py`
- ingests session transcripts into SQLite + Neo4j
- writes SQLite first, then Neo4j
- supports `ingest`, `ingest-file`, `idle`, and `ending`
- extracts topics and entities
- rebuild-safe: stable IDs + relationship reset before rebuild

### `src/unified_memory_recall.py`
- single recall entrypoint
- ranks results across backends
- down-ranks current-session echo
- prefers meaningful entity hits over technical noise

### `src/neo4j_recall.py`
- lightweight Neo4j-only recall script
- useful for debugging the graph layer directly

### `src/autonomous_loop.py`
- executable bounded autonomy skeleton
- enforces loop state transitions
- integrates first-principles reasoning + HA memory recall
- supports `step` and `run`
- serializes loop state to JSON

### `src/xng.py`
- unified CLI surface for the whole runtime
- wraps memory, loop, sync, doctor, rehydrate, bootstrap, and demo flows

---

## Reproducibility goal

This repo is meant to let another operator reproduce the same reinforcement capabilities used in the original assistant:
- a first-principles reasoning discipline
- a robust local episodic memory system
- a bounded autonomous execution loop

---

## License

MIT
