# AgentMesh Runtime

English · [中文](README.zh.md)

> 🟣 Part of **[AgentMesh](https://github.com/jiyangnan/agentmesh-core)** — see the [ecosystem index](https://github.com/jiyangnan/agentmesh-core/blob/main/docs/ECOSYSTEM.md) for all related repos.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](#)
[![Brand](https://img.shields.io/badge/brand-AgentMesh-6E4AFF.svg)](https://agentmesh360.com)
[![Website](https://img.shields.io/badge/website-runtime.agentmesh360.com-CC785C.svg)](https://runtime.agentmesh360.com)

> **Local-first runtime scaffolding for AI agents.** Give your agent (Claude Code, OpenClaw, Codex, Hermes, anything) a persistent memory across sessions, a bounded loop that records its work, and a clean way to pick up where it left off after a crash or restart. Core storage, recall, loop state, and recovery stay on your machine.

This is the runtime layer *underneath* your agent — it doesn't bring its own LLM, it doesn't make decisions for you. Your agent is still the brain. AgentMesh Runtime is the scaffolding that lets the brain remember, retry, and recover.

## What this gives you (honest list)

- 🧠 **Persistent episodic memory.** Multi-backend recall — optional local Neo4j graph → SQLite FTS5 (BM25) → raw-file grep → optional BYOK Gemini vector. Any backend can fail and the others keep serving.
- 🔁 **Bounded OODA loop scaffolding.** A state machine that records every Observe / Orient / Decide / Act / Verify / Record step into a durable trace. *Your agent supplies the actual decisions* — this just enforces the discipline and the log.
- 🛟 **Crash / restart recovery.** Deferred sync ledger across SQLite ↔ Neo4j, checkpoint store, and a `rehydrate` command that rebuilds "where I was" after an unexpected restart.
- 🩺 **Self-check.** `agentmesh-runtime doctor` reports Neo4j connectivity, SQLite health, ledger drift, and checkpoint state in one JSON blob.
- 🚧 **Rule-based anti-pattern detector** for OODA loops — `blind_retry` / `phantom_progress` / `pivot_exhaustion`. Plain counters and thresholds, not magic.

## What this is *not*

- ❌ Not an LLM and not an agent. It scaffolds the agent you already use.
- ❌ Not a hosted AgentMesh service. There is no AgentMesh cloud, account, runtime API key, credit, or billing. Optional Gemini vector recall is explicitly BYOK and off by default.
- ❌ Not a smart "OODA Policy Engine." The next-step logic is a tiny state machine; your agent decides what to actually do.
- ❌ Not (yet) a high-scale system. The vector layer is O(n) brute-force cosine — fine for personal / small-team scale; if you grow to millions of vectors, swap in pgvector or faiss.

---

## Install

```bash
git clone https://github.com/jiyangnan/AgentMesh-Runtime.git
cd AgentMesh-Runtime
uv sync
```

SQLite works immediately after install. If you also want relationship traversal, start the optional local **Neo4j** Community Edition with `docker/docker-compose.neo4j.yml`.

## Use

```bash
# environment self-check (JSON report)
uv run agentmesh-runtime doctor

# recall episodic memory
uv run agentmesh-runtime memory recall "your query here" --top-k 5

# ingest a session transcript
uv run agentmesh-runtime memory ingest-file /path/to/session.jsonl discord

# run the bundled OODA-loop demo against examples/goal_frame.example.json
uv run agentmesh-runtime demo

# rebuild "where I was" after a restart
uv run agentmesh-runtime rehydrate --write-default --print-path

# force an immediate release check
uv run agentmesh-runtime update check
```

Short alias: `amr` works wherever `agentmesh-runtime` does. The legacy `xng` name still works for one release.

## Configure

All paths and endpoints come from environment variables — no config file:

| Variable | Default | Purpose |
|---|---|---|
| `AGENTMESH_RUNTIME_HOME` | `~/.agentmesh/runtime` | Runtime-owned local data root |
| `AGENTMESH_RUNTIME_STATE_DIR` | `<runtime-home>/state` | Checkpoints, sync ledger, and update cache |
| `AGENTMESH_RUNTIME_MEMORY_DB` | existing OpenClaw DB, otherwise `<runtime-home>/memory.sqlite` | SQLite memory database |
| `AGENTMESH_RUNTIME_VECTOR_DB` | `<runtime-home>/vectors.sqlite` | Optional vector cache |
| `AGENTMESH_RUNTIME_SESSION_BASE` | existing `~/.openclaw/agents`, otherwise `<runtime-home>/agents` | Root of `<agent>/sessions/*.jsonl` transcripts |
| `AGENTMESH_RUNTIME_WORKSPACE` | existing `~/.openclaw/workspace`, otherwise `$PWD` | Workspace root |
| `AGENTMESH_RUNTIME_NEO4J_URI` | `bolt://localhost:7687` | Optional local Neo4j endpoint |
| `AGENTMESH_RUNTIME_NEO4J_USER` | `neo4j` | Neo4j user |
| `AGENTMESH_RUNTIME_NEO4J_PASSWORD` | `password` | Neo4j password |
| `AGENTMESH_RUNTIME_SKIP_UPDATE` | `0` | Set to `1` to disable background release checks |
| `GEMINI_API_KEY` | *(unset)* | Opts into Gemini embedding; text sent for embedding leaves the machine |
| `AGENTMESH_RUNTIME_DOH_BYPASS` | `0` | Set to `1` to enable DoH fallback for hostnames behind transparent-proxy DNS hijack |

The historical `ARS_*` names remain accepted for compatibility. A standalone install creates its own SQLite schema and user-owned state under `~/.agentmesh/runtime`; it never writes runtime data into `site-packages` or the Git checkout.

## Updates

Like the Job Agent CLI, Runtime performs a fail-open version check after normal commands. It reads only the public repository version, caches the result for five minutes, and never blocks local use if offline. It does not auto-install anything; when a release is available it prints the exact `git pull` / `uv sync` commands. Use `agentmesh-runtime update check` to check immediately or set `AGENTMESH_RUNTIME_SKIP_UPDATE=1` to opt out.

---

## Driving this from an AI agent

This whole repo is meant to be **invoked by your agent**, not by you. Start with **[AGENTS.md](AGENTS.md)** — it tells the agent how to use the commands inside a session, when to ingest, when to rehydrate, and what *not* to promise the human.

## Status

Alpha. The memory and consistency-recovery layers have shipped real work and have a clean test record. The OODA loop scaffolding works but its "decision intelligence" is intentionally minimal — that part is supposed to come from your agent, not from us.

## License

Apache 2.0. See [LICENSE](LICENSE).

For the cross-agent process that produced this product's current shape (and what was deliberately *not* built), see [docs/decisions/](docs/decisions/README.md).
