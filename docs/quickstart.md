# Quickstart

## 1. Start Neo4j (optional)
```bash
docker compose -f docker/docker-compose.neo4j.yml up -d
```

## 2. Install
```bash
uv sync
```

## 3. Configure (env)
Standalone defaults work without configuration. Set these only when you want custom locations or the optional graph backend:
```bash
export AGENTMESH_RUNTIME_NEO4J_URI=bolt://localhost:7687
export AGENTMESH_RUNTIME_NEO4J_USER=neo4j
export AGENTMESH_RUNTIME_NEO4J_PASSWORD=password
export AGENTMESH_RUNTIME_SESSION_BASE=~/your-agent/agents
export AGENTMESH_RUNTIME_MEMORY_DB=~/your-agent/main.sqlite
export AGENTMESH_RUNTIME_WORKSPACE=$PWD
# optional:
# export GEMINI_API_KEY=...                       # enables Gemini vector recall
```

## 4. Self-check
```bash
uv run agentmesh-runtime doctor
```
A clean standalone run reports an initialized SQLite database and user-owned state directory. Neo4j may report `optional/unavailable`; SQLite recall remains usable.

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

The bundled demo uses a deterministic smoke policy. A normal `loop run` never pretends an action happened: without an external caller/executor it stops at `waiting_human` and saves a resumable checkpoint.

## 9. Recover after a restart
```bash
uv run agentmesh-runtime rehydrate --write-default --print-path
```
The printed file is the snapshot you can inject into your next session's bootstrap.

## 10. Check for updates

```bash
uv run agentmesh-runtime update check
```

Normal commands also perform a five-minute cached, fail-open check against the public repository. Set `AGENTMESH_RUNTIME_SKIP_UPDATE=1` to disable it.

---

For an AI agent driving this CLI, start with [`AGENTS.md`](../AGENTS.md). For why the product looks like this (and what was deliberately not built), see [`docs/decisions/`](decisions/README.md).
