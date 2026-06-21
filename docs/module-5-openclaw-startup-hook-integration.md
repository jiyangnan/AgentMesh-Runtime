# Module 5 — OpenClaw Startup Hook Integration

This document connects the `xiaonangua CLI` recovery pipeline to real OpenClaw hook surfaces.

## Goal

Move from:
- manual `xng rehydrate`
- manual `xng bootstrap`

To:
- Gateway startup refreshes recovery artifacts
- new session bootstrap automatically receives startup recovery context

---

## Relevant OpenClaw hook events

From OpenClaw internal hooks:

- `gateway:startup` — after channels start and hooks are loaded
- `agent:bootstrap` — before workspace bootstrap files are injected

These two events are enough to wire startup recovery into real session startup.

---

## Hook design

Hook name:
- `startup-rehydrate-bootstrap`

### On `gateway:startup`

Run:
1. `xng sync backfill`
2. `xng bootstrap`

Effect:
- if Neo4j is ready, pending SQLite-only writes are replayed
- `state/startup-context.txt` is refreshed for later use

### On `agent:bootstrap`

Run:
1. `xng bootstrap`
2. read `state/startup-context.txt`
3. inject that content into `BOOTSTRAP.md` content before prompt injection

Effect:
- each new session receives current recovery context automatically

---

## Standard files used

- `state/startup-context.txt`
- `state/rehydrate-snapshot.json`

---

## Workspace hook location

For a live OpenClaw workspace, place the hook under:

```text
<workspace>/hooks/startup-rehydrate-bootstrap/
├── HOOK.md
└── handler.ts
```

This project also ships a reference implementation in the current workspace for immediate use.

---

## Suggested config entry

```json
{
  "hooks": {
    "internal": {
      "entries": {
        "startup-rehydrate-bootstrap": {
          "enabled": true,
          "repoDir": "{path-to-your-agent-reinforcement-system}",
          "injectInto": "BOOTSTRAP.md",
          "autoBackfill": true
        }
      }
    }
  }
}
```

### Fields

- `repoDir`: absolute path to the `agent-reinforcement-system` repo
- `injectInto`: target bootstrap filename; default `BOOTSTRAP.md`
- `autoBackfill`: whether gateway startup should attempt `xng sync backfill`

---

## Recommended rollout

1. Create the hook in workspace `hooks/`
2. Enable the hook via OpenClaw hooks/config
3. Restart or reload gateway if required by your environment
4. Confirm:
   - gateway startup refreshes `state/startup-context.txt`
   - new sessions include injected startup recovery context

---

## Verification checklist

### A. Gateway startup path
- `xng sync status` shows pending or clean state as expected
- startup regenerates `state/startup-context.txt`
- if Neo4j has recovered, pending backfill count drops

### B. Agent bootstrap path
- new session bootstrap includes a `Startup Recovery Context` section
- context includes sync health, recent checkpoint, and suggested next focus

### C. Restart resilience
- reboot computer
- let OpenClaw start before Neo4j
- create or ingest data while Neo4j is still unavailable
- once Neo4j recovers, startup or manual backfill reconciles state
- new session bootstrap still receives fresh recovery context

---

## Why this is the final missing layer

Before this module, recovery was available but still manual.

After this module:
- recovery artifacts are standard files
- startup generation is hookable
- session bootstrap injection is automatable

That is the bridge from “recoverable system” to “actually self-recovering startup flow.”
