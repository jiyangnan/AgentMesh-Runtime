# Quickstart

## 1. Start Neo4j
```bash
cd docker
docker compose -f docker-compose.neo4j.yml up -d
```

## 2. Install deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure env
```bash
export ARS_NEO4J_URI=bolt://localhost:7687
export ARS_NEO4J_USER=neo4j
export ARS_NEO4J_PASSWORD=password
export ARS_SESSION_BASE=~/.openclaw/agents
export ARS_MEMORY_DB=~/.openclaw/memory/main.sqlite
export ARS_WORKSPACE=$PWD
```

## 4. Ingest
```bash
python3 src/episode_ingest.py ingest-file /path/to/session.jsonl discord
```

## 5. Recall
```bash
python3 src/unified_memory_recall.py "First-Principles-Only"
python3 src/unified_memory_recall.py "Hybrid-Vector-Graph neo4j ollama"
```

## 6. Degradation tests
```bash
python3 src/unified_memory_recall.py "query" --no-neo4j
python3 src/unified_memory_recall.py "query" --no-neo4j --no-sqlite
```
