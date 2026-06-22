# Quickstart

## 1. Start Neo4j (optional but recommended)
```bash
docker compose -f docker/docker-compose.neo4j.yml up -d
```

## 2. Install
```bash
uv sync
```

## 3. Configure (env)
Defaults still point at `~/.openclaw/*` because that's where this code originally lived. If you don't run OpenClaw, set these:
```bash
export ARS_NEO4J_URI=bolt://localhost:7687
export ARS_NEO4J_USER=neo4j
export ARS_NEO4J_PASSWORD=password
export ARS_SESSION_BASE=~/your-agent/agents      # where <agent>/sessions/*.jsonl live
export ARS_MEMORY_DB=~/your-agent/main.sqlite
export ARS_WORKSPACE=$PWD
# optional:
# export GEMINI_API_KEY=...                       # enables Gemini vector recall
```

## 4. Self-check
```bash
uv run agentmesh-runtime doctor
```
A clean run prints a JSON report with `neo4j_port_7687: ok`, the SQLite table count, and ledger / checkpoint health.

## 5. Ingest a transcript
```bash
uv run agentmesh-runtime memory ingest-file /path/to/session.jsonl discord
```

## 6. Recall
```bash
uv run agentmesh-runtime memory recall "your query" --top-k 5

# JSON output for programmatic use
uv run agentmesh-runtime memory recall "your query" --top-k 5 --json
```

## 7. Failover smoke-tests
The recall layer should still produce results when a backend is down:
```bash
uv run agentmesh-runtime memory recall "query" --no-neo4j
uv run agentmesh-runtime memory recall "query" --no-neo4j --no-sqlite
```

## 8. Run the bundled OODA demo
```bash
uv run agentmesh-runtime demo
```
This drives `examples/goal_frame.example.json` through the loop. It converges in 1 iteration by design — for real work, write your own `goal_frame.json` (see [schemas/goal_frame.schema.json](../schemas/goal_frame.schema.json)).

## 9. Recover after a restart
```bash
uv run agentmesh-runtime rehydrate --write-default --print-path
```
The printed file is the snapshot you can inject into your next session's bootstrap.

---

For an AI agent driving this CLI, start with [`AGENTS.md`](../AGENTS.md). For why the product looks like this (and what was deliberately not built), see [`docs/decisions/`](decisions/README.md).
