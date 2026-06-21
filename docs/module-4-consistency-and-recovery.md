# Module 4 — Consistency and Recovery

**Status**: Phase 1 consistency implemented, Phase 2 recovery implemented (checkpoint + rehydrate v1)

This module hardens the runtime against restart-order failures:

- OpenClaw may start before Neo4j
- SQLite may accept writes while Neo4j is still offline
- the system must later backfill those successful SQLite writes into Neo4j

---

## Problem

Without a deferred sync layer, the runtime can drift into a split-brain state:

- SQLite contains newer episodes/events
- Neo4j misses those same episodes/events
- recall still partially works
- graph relationships become stale over time

The design goal is therefore:

> allow temporary write asymmetry, but enforce eventual consistency.

---

## Phase 1 — Implemented consistency layer

### Components

1. **Sync ledger** — persistent write outcome log
2. **Sync status** — observable pending/drift view
3. **Backfill runner** — SQLite → Neo4j replay after recovery
4. **Doctor health** — environment + consistency status

### New commands

```bash
xng sync status
xng sync backfill
xng doctor
```

---

## Sync ledger schema

Stored at:

```text
state/sync-ledger.jsonl
```

Each line is an append-only state transition for one event.
The latest record for each `event_id` is treated as authoritative.

### Ledger record schema

```json
{
  "event_id": "loop:adda3d9d-6898-4c3f-942b-1608545b6da8:1",
  "session_id": "loop:adda3d9d-6898-4c3f-942b-1608545b6da8:1",
  "channel": "runtime",
  "kind": "loop_record",
  "summary": "Loop ars-demo-001 iteration 1",
  "topics": ["memory", "episodic-memory"],
  "entities": [{"name": "First-Principles-Only", "entity_type": "concept"}],
  "first_ts": "2026-04-29T12:04:31.186184+00:00",
  "last_ts": "2026-04-29T12:04:31.186184+00:00",
  "msg_count": 1,
  "sqlite_ok": true,
  "neo4j_ok": false,
  "needs_backfill": true,
  "retry_count": 0,
  "last_error": "neo4j_write_failed",
  "created_at": "2026-04-29T12:04:31.186184+00:00",
  "updated_at": "2026-04-29T12:04:31.186184+00:00"
}
```

### Stable ids

- session ingest: `event_id = episode:<session_id>`
- loop record: `event_id = loop:<loop_id>:<iteration>`
- generic runtime event: caller-provided or `episode:<session_id>`

These ids make replay and reconciliation deterministic.

---

## Write path contract

### Session ingest

```text
parse session -> extract meta -> write SQLite -> write Neo4j -> append ledger
```

### Loop record ingest

```text
loop record -> runtime log -> ingest_event -> write SQLite -> write Neo4j -> append ledger
```

### Success / degraded success

- `sqlite_ok=true, neo4j_ok=true` → normal double-write success
- `sqlite_ok=true, neo4j_ok=false` → degraded success, pending backfill
- `sqlite_ok=false` → primary local write failed, operator attention required

---

## Backfill design

Backfill uses SQLite as the source of truth for replay.

### Reason

SQLite is the primary durable local landing zone:

- writes happen there first
- it survives Neo4j startup lag
- it is simpler to restore after reboot

### Backfill flow

```text
load pending ledger entries
-> confirm Neo4j is reachable
-> fetch source text from SQLite by session_id/path
-> rebuild topics/entities if needed
-> write into Neo4j
-> append new ledger state
```

### Core functions

#### `sync_state.append_ledger_event(entry) -> dict`
Append one ledger state transition.

#### `sync_state.pending_ledger_entries(limit=None) -> list[dict]`
Return latest unresolved backfill entries.

#### `sync_state.sync_status_report(sample=5) -> dict`
Return consistency health summary.

#### `sync_backfill.fetch_sqlite_event(session_id) -> dict | None`
Fetch the persisted SQLite payload for replay.

#### `sync_backfill.backfill_one(entry) -> dict`
Replay one pending entry into Neo4j and append updated ledger state.

#### `sync_backfill.run_backfill(limit=None) -> dict`
Replay a batch of pending entries.

---

## CLI output contracts

### `xng sync status`

```json
{
  "ledger_path": ".../state/sync-ledger.jsonl",
  "ledger_entries": 14,
  "pending_backfill": 2,
  "neo4j_ready": true,
  "sqlite_success_entries": 14,
  "neo4j_success_entries": 12,
  "drift_detected": true,
  "backfill_needed": true,
  "recommended_action": "xng sync backfill",
  "pending_sample": [...],
  "recent_failures": [...]
}
```

### `xng sync backfill`

```json
{
  "neo4j_ready": true,
  "scanned": 2,
  "backfilled": 2,
  "failed": 0,
  "details": [...]
}
```

### `xng doctor`

Adds:

```json
{
  "memory_health": {
    "pending_backfill": 0,
    "drift_detected": false,
    "backfill_needed": false,
    "recommended_action": null
  }
}
```

---

## Phase 2 — Recovery layer (implemented v1)

### Goal

After consistency is restored, recover task state on startup.

### Files

- `src/checkpoint_store.py`
- `src/startup_rehydrate.py`

### Commands

```bash
xng rehydrate
xng bootstrap
```

### Checkpoint schema

```json
{
  "goal_id": "ars-demo-001",
  "title": "Integrate consistency layer",
  "status": "active",
  "current_phase": "phase-1-sync",
  "latest_decision": "Implement ledger + backfill before rehydrate",
  "blockers": [],
  "next_step": "Verify SQLite-only write can later reach Neo4j",
  "updated_at": "2026-04-29T22:00:00+08:00"
}
```

### Rehydrate snapshot schema

```json
{
  "active_goals": [],
  "open_loops": [],
  "recent_memory_hits": [],
  "recent_repo_changes": [],
  "suggested_next_focus": ""
}
```

---

## Acceptance criteria

### Phase 1

1. Neo4j can be offline while SQLite still accepts writes
2. those writes produce pending ledger entries
3. `xng sync status` exposes pending/drift clearly
4. `xng sync backfill` replays pending entries after Neo4j recovery
5. replayed entries become recallable through Neo4j-backed recall

### Startup integration path

Two startup-friendly outputs now exist:

1. **JSON snapshot** for programmatic orchestration
   ```bash
   xng rehydrate
   xng rehydrate --write-default --print-path
   ```
   Standard file: `state/rehydrate-snapshot.json`

2. **Bootstrap text** for direct session-context injection
   ```bash
   xng bootstrap
   xng bootstrap --stdout
   ```
   Standard file: `state/startup-context.txt`

Recommended startup flow:

```text
process starts
-> xng sync status
-> if pending_backfill > 0 and Neo4j is ready: xng sync backfill
-> xng bootstrap
-> read state/startup-context.txt
-> inject that bootstrap text into the new session startup context
```

### Phase 2

1. loop/checkpoint state survives restart
2. `xng rehydrate` restores current working state
3. startup bootstrap text can be generated for session injection
4. restart recovery depends on checkpoint first, recall second
5. `xng doctor` reports checkpoint health alongside sync health
