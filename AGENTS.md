# AGENTS.md — driving AgentMesh Runtime as an AI agent

You are an AI agent (Claude Code / OpenClaw / Cursor / Codex / Hermes …) and your human has installed AgentMesh Runtime to give *you* persistent memory, an OODA loop scaffold, and a way to pick up after a crash. **You are the brain**; this CLI is the scaffolding underneath you. There is no LLM behind it — only data structures, ranking, and durable logs.

This file tells you **when to call which command**, what each one actually does (and doesn't do), and what *not* to promise the human.

## The four things this scaffolding actually does

| You want… | Call | What it really does |
|---|---|---|
| Find out what you knew before | `agentmesh-runtime memory recall "<query>" --top-k 5` | Multi-backend ranked search: Neo4j → SQLite FTS5 (BM25) → file grep → optional Gemini vector. Returns ranked hits with snippets. |
| Persist a session you just ran | `agentmesh-runtime memory ingest-file <path/to/session.jsonl> <channel>` | Cleans transcript, extracts topics + entities, writes to SQLite first, then Neo4j. Idempotent. |
| Frame a goal as a bounded loop | `agentmesh-runtime loop run <goal_frame.json>` | Drives Observe → Orient → Decide, then stops at `waiting_human` when a real external executor is required. It never marks a simulated action successful. |
| Rebuild "where was I" after a restart | `agentmesh-runtime rehydrate --write-default --print-path` | Joins checkpoints + recent memory + repo state into one bootstrap snapshot. Output path is printed for you to inject into your next session. |
| Sanity-check the environment | `agentmesh-runtime doctor` | Reports Neo4j connectivity, SQLite tables, ledger drift, checkpoint state in a single JSON. Run this first if anything looks wrong. |

## When to call each

- **Start of a complex task** → `memory recall "<the task topic>"` first. If there are decisions or failures from prior runs, read them before planning.
- **After finishing a complex task** → `memory ingest-file <transcript> <channel>`. If you skip this, your future self loses the context.
- **You crashed / your human restarted you / a new session started cold** → `rehydrate`. Read the printed snapshot before doing anything else.
- **Something is producing weird results** → `doctor`. If Neo4j is down, recall will gracefully fall through to SQLite + files; tell the human which backends are healthy.
- **Multi-step goal that benefits from explicit Observe / Verify discipline** → `loop run <goal_frame.json>`. Execute the proposed action in your own tool layer; do not claim the Runtime executed it.
- **A newer version notice appears** → surface it to the human or run `agentmesh-runtime update check`. Never auto-run the upgrade commands without authorization.

## What you must NOT promise the human

- ❌ "AgentMesh Runtime will decide for you." It won't. The `decide()` step is a tiny rule-based stub. **You** still decide; this just records what you decided.
- ❌ "Verification is automatic." The default policy returns `unknown` until a real caller supplies execution and verification. Real verification is your job.
- ❌ "Memory recall is semantic." It's lexical + entity + recency-weighted. If you set `GEMINI_API_KEY`, vector recall is added — but it's still O(n) cosine, not a learned reranker.
- ❌ "This is FTS5 magic that solves search." FTS5 is real (BM25 + snippet), but ranking quality is bounded by the indexing pipeline. Don't oversell.
- ❌ "It runs in the AgentMesh cloud." It does not. Core state stays on the human's machine. If the human explicitly sets `GEMINI_API_KEY`, embedding text is sent to Gemini; disclose that exception.

## When something's missing

| Symptom | What to do |
|---|---|
| `doctor` shows `neo4j: optional/unavailable` | This is valid for SQLite-only use. Start local Neo4j with `docker compose -f docker/docker-compose.neo4j.yml up -d` only if graph recall is wanted. |
| `memory recall` returns nothing | Either nothing's been ingested yet, or the query doesn't hit lexical/entity matches. Try broader keywords or check `doctor` for SQLite health. |
| `loop run` returns `status: waiting_human` | Expected for the default fail-closed policy: a real caller/executor must perform and verify the proposed action. Only `agentmesh-runtime demo` uses the deterministic smoke policy. |
| `ingest-file` says "sqlite_ok: true, neo4j_ok: false" | Neo4j was down at write time. The sync ledger recorded it. Run `agentmesh-runtime sync backfill` once Neo4j is back to replay. |

## Don'ts

- **Don't** hand-edit files under `~/.agentmesh/runtime/state/` — they're durable logs the recovery layer depends on.
- **Don't** assume OpenClaw is installed. Standalone defaults are under `~/.agentmesh/runtime`; use `AGENTMESH_RUNTIME_*` only when the human requests custom locations.
- **Don't** push runtime data from `~/.agentmesh/runtime/` or legacy local state into git.
- **Don't** invent your own "decision intelligence" inside this repo. If you want smarter decide/verify, that's *your* layer — keep it in your agent, not in fork-and-modify here.

## More

- Human-facing intro: [README.md](README.md)
- Cross-agent decision history (why the product is this small): [docs/decisions/](docs/decisions/README.md)
- Goal frame schema: [schemas/goal_frame.schema.json](schemas/goal_frame.schema.json)
- Loop state schema: [schemas/loop_state.schema.json](schemas/loop_state.schema.json)
