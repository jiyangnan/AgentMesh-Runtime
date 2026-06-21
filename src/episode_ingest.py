#!/usr/bin/env python3
"""
Episode Ingest — writes session episodes to Neo4j.
Designed for three trigger modes:
  1. cron idle (5min no activity)
  2. ending phrase detection (user says "就这样" etc.)
  3. session close detection (compaction triggered)
"""

import sys, json, os, re, sqlite3, hashlib, time
from datetime import datetime, timezone

# Ensure src/ is importable (sync_state lives there)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_scripts_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from sync_state import append_ledger_event


NEO4J_URI = os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("ARS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("ARS_NEO4J_PASSWORD", "password")

SESSION_BASE = os.getenv("ARS_SESSION_BASE", os.path.expanduser("~/.openclaw/agents"))
MEMORY_DB = os.getenv("ARS_MEMORY_DB", os.path.expanduser("~/.openclaw/memory/main.sqlite"))


def _discover_agent_dirs(session_base: str) -> list[str]:
    """Return agent names found under ``session_base`` whose layout is
    ``<session_base>/<agent>/sessions/``.

    The previous version hard-coded the operator's local agent roster
    (``["main", "growth", "invest"]``). Auto-discovery lets the package
    work for any operator without configuration.
    """
    if not os.path.isdir(session_base):
        return []
    return [
        name for name in sorted(os.listdir(session_base))
        if os.path.isdir(os.path.join(session_base, name, "sessions"))
    ]


LEDGER_KIND_SESSION = "session"
LEDGER_KIND_EVENT = "event"
LEDGER_KIND_LOOP_RECORD = "loop_record"

END_PHRASES = ["就这样", "先这样", "好了", "没了", "谢谢", "行", "好", "OK", "ok", "好的", "知道了", "明白了", "拜拜", "再见"]
SKIP_MARKERS = ["HEARTBEAT_OK", "NO_REPLY", "System (untrusted)", "Exec completed", "Cron job", "queued messages"]

TOPIC_KEYWORDS = {
    "neo4j": "neo4j", "向量": "vector-index", "memory": "memory",
    "episodic": "episodic-memory", "episode": "episodic-memory",
    "discord": "discord", "telegram": "telegram", "feishu": "feishu",
    "cron": "cron", "skill": "skill", "写作": "writing",
    "article": "writing", "公众号": "wechat", "twitter": "twitter",
    "x.com": "twitter", "产品": "product", "独立开发": "indie-dev",
    "openclaw": "openclaw", "agent": "agent", "claude": "claude",
    "gemini": "gemini", "ollama": "ollama", "embedding": "embedding",
}

# Generic, public-facing entity catalogue. Operators can extend this dict at
# runtime (see docs) to teach the ingest layer their own people / products /
# tools without modifying the package source.
KNOWN_ENTITIES = {
    "Neo4j": ("Neo4j", "technology"),
    "Ollama": ("Ollama", "technology"),
    "Claude Code": ("Claude Code", "tool"),
    "Codex": ("Codex", "tool"),
    "MEMORY.md": ("MEMORY.md", "file"),
    "AGENTS.md": ("AGENTS.md", "file"),
    "Telegram": ("Telegram", "channel"),
    "Discord": ("Discord", "channel"),
    "Feishu": ("Feishu", "channel"),
}

ENTITY_STOPWORDS = {
    # --- Pronouns / Fillers ---
    'Now', 'None', 'True', 'False', 'Also', 'Just', 'Like', 'More', 'Some',
    'Then', 'Here', 'There', 'These', 'Those', 'What', 'When', 'Where', 'Which',
    'Both', 'Each', 'From', 'Into', 'After', 'Before', 'Around', 'About',
    'Since', 'Until', 'Between', 'Through', 'During', 'Across', 'Against',
    # --- Common verbs ---
    'Allow', 'Added', 'Adding', 'Begin', 'Bring', 'Build', 'Call', 'Case',
    'Check', 'Click', 'Close', 'Could', 'Count', 'Create', 'Created', 'Doing',
    'Done', 'Edit', 'Execute', 'Executing', 'Exit', 'Extract', 'Fail', 'Failing',
    'Follow', 'Found', 'Get', 'Getting', 'Give', 'Going', 'Keep', 'Made', 'Make',
    'Need', 'Over', 'Overall', 'Possible', 'Read', 'Replace', 'Replaced', 'Return',
    'Running', 'Should', 'Skip', 'Skipping', 'Start', 'Starting', 'Stop', 'Take',
    'Think', 'This', 'Write',
    # --- Adjectives / Adverbs ---
    'Actually', 'Already', 'Always', 'Available', 'Avoid', 'Based', 'Better',
    'Current', 'Custom', 'Different', 'Double', 'Easy', 'Enough', 'Every',
    'Excellent', 'Existing', 'External', 'Final', 'First', 'Free', 'Full',
    'General', 'Good', 'Great', 'Hard', 'High', 'Internal', 'Last', 'Latest',
    'Long', 'Low', 'Main', 'Multiple', 'Native', 'Near', 'Nearly', 'New', 'Next',
    'Nice', 'Only', 'Other', 'Own', 'Previous', 'Public', 'Real', 'Recent',
    'Right', 'Same', 'Short', 'Silent', 'Simple', 'Small', 'Still', 'Such',
    'Top', 'True', 'Unknown', 'Using', 'Very', 'Well', 'Without',
    # --- Day names ---
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
    # --- Months ---
    'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December',
    # --- Tech noise ---
    'Conversation', 'Sender', 'Message', 'Description', 'Community', 'Reply',
    'Episode', 'Entity', 'Users', 'User', 'Content', 'Result', 'Results',
    'Status', 'Summary', 'Config', 'Cache', 'Error', 'Response', 'Request',
    'Note', 'Notes', 'Output', 'Input', 'Default', 'Example', 'Version',
    'Type', 'Name', 'Value', 'Key', 'Data', 'Field', 'Format', 'Path',
    # --- Programming noise ---
    'API', 'CPU', 'GPU', 'HTTP', 'HTTPS', 'JSON', 'JSONL', 'HTML', 'CSS',
    'MEDIA', 'MERGE', 'MENTIONS', 'TAGGED', 'CONTAINS', 'SKILL',
    'py_compile', 'full_text', 'entity_names', 'entities', 'password',
    'Memory', 'Image', 'Gateway', 'Desktop', 'Browser', 'Benchmark',
    'Retest', 'OCR', 'Keep', 'SQLite', 'OpenAI', 'FTS',
    # --- Programming terms that are too generic ---
    'Append', 'Appendending', 'Archive', 'Archived', 'Archiver', 'Archiving',
    'Auth', 'Boolean', 'Callback', 'Chunk', 'Column', 'Commit', 'Compiler',
    'Debug', 'Delete', 'Deploy', 'Doc', 'Download', 'Endpoint', 'Env',
    'Filter', 'Flag', 'Flush', 'Group', 'Handler', 'Hash', 'Header', 'Hook',
    'Import', 'Index', 'Init', 'Install', 'Interface', 'Iterate', 'Label',
    'Layer', 'Link', 'List', 'Load', 'Lock', 'Log', 'Map', 'Merge', 'Method',
    'Mock', 'Module', 'Node', 'Null', 'Object', 'Param', 'Parse', 'Patch',
    'Pattern', 'Pipe', 'Pool', 'Port', 'Prefix', 'Proxy', 'Push', 'Queue',
    'Query', 'Raw', 'Ref', 'Regex', 'Render', 'Repo', 'Resolve', 'Retry',
    'Role', 'Route', 'Row', 'Rule', 'Run', 'Scope', 'Seed', 'Server',
    'Set', 'Shell', 'Slice', 'Socket', 'Sort', 'Split', 'Stack', 'State',
    'Store', 'Stream', 'String', 'Swap', 'Sync', 'Table', 'Tag', 'Task',
    'Thread', 'Token', 'Tool', 'Trace', 'Tuple', 'Type', 'Update', 'Upload',
    'Variable', 'Vector', 'View', 'Watcher', 'Worker', 'Wrapper',
}

ENTITY_TYPE_PRIORITY = {
    'person': 1,
    'agent': 2,
    'product': 3,
    'project': 4,
    'file': 5,
    'tool': 6,
    'technology': 7,
    'channel': 8,
    'concept': 9,
    'endpoint': 10,
    'command': 11,
}


def _clean_text(text):
    text = re.sub(r'Conversation info \(untrusted metadata\):\s*```json.*?```', ' ', text, flags=re.S)
    text = re.sub(r'Sender \(untrusted metadata\):\s*```json.*?```', ' ', text, flags=re.S)
    text = re.sub(r'Replied message \(untrusted.*?```', ' ', text, flags=re.S)
    text = re.sub(r'\{\s*"message_id".*?\}', ' ', text, flags=re.S)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def neo4j_write(session_id, summary, full_text, channel, topics, entities, first_ts, last_ts, msg_count):
    """Write episode node to Neo4j. Return True/False instead of hard failing."""
    try:
        import socket
        host = NEO4J_URI.replace("bolt://", "").replace("neo4j://", "").split(":")[0]
        port = int(NEO4J_URI.split(":")[-1]) if NEO4J_URI.split(":")[-1].isdigit() else 7687
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
    except Exception:
        return False
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=5, max_transaction_retry_time=5)
        with driver.session() as sess:
            sess.run("""
                MERGE (e:Episode {session_id: $sid})
                SET e.channel = $ch,
                    e.summary = $sum,
                    e.topics = $topics,
                    e.entity_names = $entity_names,
                    e.first_timestamp = $fts,
                    e.last_timestamp = $lts,
                    e.message_count = $cnt,
                    e.full_text = $ft,
                    e.updated_at = datetime()
            """, sid=session_id, ch=channel, sum=summary, topics=topics,
               entity_names=[e['name'] for e in entities],
               fts=first_ts, lts=last_ts, cnt=msg_count, ft=full_text[:30000])

            sess.run("""
                MATCH (e:Episode {session_id: $sid})-[r:TAGGED|MENTIONS]->()
                DELETE r
            """, sid=session_id)

            for t in topics:
                sess.run("""
                    MERGE (t:Topic {name: $name})
                    WITH t
                    MATCH (e:Episode {session_id: $sid})
                    MERGE (e)-[:TAGGED]->(t)
                """, name=t, sid=session_id)

            for ent in entities:
                sess.run("""
                    MERGE (n:Entity {name: $name, entity_type: $etype})
                    WITH n
                    MATCH (e:Episode {session_id: $sid})
                    MERGE (e)-[:MENTIONS]->(n)
                """, name=ent['name'], etype=ent['entity_type'], sid=session_id)

            # Link to previous episode (FOLLOWED_BY)
            sess.run("""
                MATCH (prev:Episode)
                WHERE prev.last_timestamp < $fts
                  AND prev.session_id <> $sid
                WITH prev
                ORDER BY prev.last_timestamp DESC
                LIMIT 1
                MATCH (e:Episode {session_id: $sid})
                MERGE (prev)-[:FOLLOWED_BY]->(e)
            """, sid=session_id, fts=first_ts)
        driver.close()
        return True
    except Exception:
        try:
            driver.close()
        except Exception:
            pass
        return False


def sqlite_write(session_id, summary, full_text, channel, topics, first_ts, last_ts, msg_count):
    """Write episode to OpenClaw's local SQLite memory (for FTS search). Return True/False."""
    conn = sqlite3.connect(MEMORY_DB)
    cur = conn.cursor()
    chunk_id = "ep_" + hashlib.sha1(session_id.encode()).hexdigest()
    path = f"episode:{session_id}"
    emb = json.dumps([0.0] * 768)
    now_ms = int(time.time() * 1000)
    h = hashlib.sha256(full_text[:500].encode()).hexdigest()
    try:
        cur.execute("DELETE FROM chunks WHERE path = ?", (path,))
        cur.execute("""
            INSERT OR REPLACE INTO chunks (id, path, source, start_line, end_line, hash, model, text, embedding, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chunk_id, path, channel, 0, 0, h, "none", full_text[:30000], emb, now_ms))
        cur.execute("""
            INSERT OR REPLACE INTO files (path, source, hash, mtime, size)
            VALUES (?, ?, ?, ?, ?)
        """, (path, channel, h, now_ms, len(full_text)))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def parse_messages(fpath):
    """Parse JSONL session file, return messages + detected end phrase."""
    entries = []
    ended_by_phrase = None
    with open(fpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if c.get("type") in ("text", "output")]
                    content = " ".join(texts)
                role = msg.get("role", "?")
                ts = obj.get("timestamp", "")
                if not content or role not in ("user", "assistant"):
                    continue
                if any(m in content[:30] for m in SKIP_MARKERS):
                    continue
                if role == "user":
                    for phrase in END_PHRASES:
                        if phrase in content:
                            ended_by_phrase = phrase
                entries.append({"role": role, "text": content, "timestamp": ts})
            except:
                pass
    # Skip cron-initiated sessions (detected by first user message pattern)
    CRON_PATTERNS = [
        re.compile(r'^\[cron:'),
        re.compile(r'^\[[A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2} GMT[+\-]\d+\]'),
        re.compile(r'^Read HEARTBEAT\.md'),
        re.compile(r'^Write a dream diary entry'),
        re.compile(r'^Continue where you left off'),
        re.compile(r'^System: \[\d{4}-\d{2}-\d{2}'),
        re.compile(r'^\[Subagent Context\]'),
    ]
    first_user = next((e for e in entries if e["role"] == "user"), None)
    if first_user:
        txt = first_user["text"]
        if any(p.search(txt) for p in CRON_PATTERNS):
            return [], ended_by_phrase
    return entries, ended_by_phrase


def normalize_entity(name, entity_type):
    key = name.strip()
    if key in KNOWN_ENTITIES:
        canon, canon_type = KNOWN_ENTITIES[key]
        return canon, canon_type
    return key, entity_type


def is_noise_entity(token: str) -> bool:
    token = token.strip()
    if not token or token in ENTITY_STOPWORDS:
        return True
    if len(token) < 2:
        return True
    if token.lower() in {x.lower() for x in ENTITY_STOPWORDS}:
        return True
    # Block URLs and connection strings entirely
    if re.search(r'://', token):
        return True
    # Block env vars and assignments (KEY=VALUE)
    if '=' in token and not token.startswith('--'):
        return True
    # Block timestamps and date-like strings
    if re.search(r'\d{4}-\d{2}-\d{2}', token):
        return True
    # Block pure numeric/symbol tokens (port numbers, etc.)
    if re.fullmatch(r'[0-9\-_:/.]+', token):
        return True
    # Block hex colors and long hex strings
    if re.fullmatch(r'[0-9A-Fa-f]{6,}', token):
        return True
    # Block CVE identifiers
    if re.match(r'CVE-\d{4}-\d+', token):
        return True
    # Block very short all-caps (but allow known acronyms >= 3 chars)
    if re.fullmatch(r'[A-Z]{1,4}', token):
        return True
    # Block partial hashes (ending with ...)
    if token.endswith('...'):
        return True
    # Block Docker flags
    if token.startswith('--') and len(token) > 20:
        return True
    # Block Discord mentions
    if token.startswith('<@') and token.endswith('>'):
        return True
    return False


def extract_entities(messages, full_text):
    found = {}
    for name, pair in KNOWN_ENTITIES.items():
        if name.lower() in full_text.lower():
            canon, etype = pair
            found[canon] = etype

    # backticked files / commands — STRICT: only well-known patterns
    for token in re.findall(r'`([^`]{2,80})`', full_text):
        token = token.strip()
        if is_noise_entity(token):
            continue
        if token.endswith(('.md', '.py', '.json', '.jsonl', '.yaml', '.yml', '.sh')):
            canon, etype = normalize_entity(token, 'file')
            found[canon] = etype
        # NOTE: removed loose command/endpoint extraction.
        # Backticked URLs, flags, and generic ASCII strings are NOT entities.
        # Only KNOWN_ENTITIES matched above will be used for tech/tool concepts.

    # English product/tool style entities — STRICT: only if in KNOWN_ENTITIES
    # Generic PascalCase words are too noisy. Only accept known entities.
    for token in re.findall(r'\b[A-Z][A-Za-z0-9]+(?:[\-\.][A-Za-z0-9]+)*\b', full_text):
        if token in KNOWN_ENTITIES or token.lower() in {k.lower() for k in KNOWN_ENTITIES}:
            pair = KNOWN_ENTITIES.get(token) or KNOWN_ENTITIES.get(next((k for k in KNOWN_ENTITIES if k.lower() == token.lower()), token))
            if pair:
                canon, etype = pair
                found[canon] = etype

    # Chinese proper-noun hints
    for token in ['第一性原理', '图数据库', '向量索引', '情景记忆', '语义知识', '强制规则', '混合索引']:
        if token in full_text:
            canon, etype = normalize_entity(token, 'concept')
            found.setdefault(canon, etype)

    entities = []
    for k, v in found.items():
        if is_noise_entity(k):
            continue
        entities.append({"name": k, "entity_type": v})
    entities.sort(key=lambda x: (ENTITY_TYPE_PRIORITY.get(x['entity_type'], 99), x['name']))
    return entities[:16]


def extract_meta(messages):
    """Extract metadata from messages without external LLM."""
    if not messages:
        return None
    msgs = sorted(messages, key=lambda x: x.get("timestamp", ""))
    first_ts = msgs[0].get("timestamp", "")
    last_ts = msgs[-1].get("timestamp", "")

    cleaned_candidates = []
    for m in msgs:
        cleaned = _clean_text(m["text"])
        if cleaned and len(cleaned) >= 6:
            cleaned_candidates.append((m["role"], cleaned))

    summary_src = ""
    for role, cleaned in cleaned_candidates:
        if role == "user":
            summary_src = cleaned
            break
    if not summary_src and cleaned_candidates:
        summary_src = cleaned_candidates[0][1]
    summary = summary_src[:160] + ("..." if len(summary_src) > 160 else "")

    full_text = "\n".join(f"[{m['role']}] {_clean_text(m['text'])[:800]}" for m in msgs)
    full_text = full_text[:30000]
    combined = full_text.lower()
    topics = []
    for kw, topic in TOPIC_KEYWORDS.items():
        if kw in combined and topic not in topics:
            topics.append(topic)
    entities = extract_entities(msgs, full_text)
    return {
        "summary": summary or (msgs[0]['text'][:80] if msgs else ''),
        "topics": topics,
        "entities": entities,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "msg_count": len(msgs),
        "full_text": full_text,
    }


def _record_sync_ledger(event_id, session_id, channel, kind, summary, topics, entities, first_ts, last_ts, msg_count, sqlite_ok, neo4j_ok, last_error=None):
    """Write a ledger entry via sync_state.append_ledger_event."""
    entry = {
        "event_id": event_id,
        "session_id": session_id,
        "channel": channel,
        "kind": kind,
        "summary": summary,
        "topics": topics,
        "entities": entities,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "msg_count": msg_count,
        "sqlite_ok": sqlite_ok,
        "neo4j_ok": neo4j_ok,
    }
    if last_error:
        entry["last_error"] = last_error
    return append_ledger_event(entry)


def ingest_event(session_id, summary, full_text, channel="runtime", first_ts=None, last_ts=None, msg_count=1, kind=LEDGER_KIND_EVENT, event_id=None):
    """Ingest a synthetic event/memory item into both SQLite and Neo4j."""
    first_ts = first_ts or datetime.now(timezone.utc).isoformat()
    last_ts = last_ts or first_ts
    cleaned_summary = _clean_text(summary)
    cleaned_full_text = _clean_text(full_text)
    combined = cleaned_full_text.lower()
    topics = []
    for kw, topic in TOPIC_KEYWORDS.items():
        if kw in combined and topic not in topics:
            topics.append(topic)
    entities = extract_entities([{"role": "assistant", "text": cleaned_full_text, "timestamp": first_ts}], cleaned_full_text)
    sqlite_ok = sqlite_write(session_id, cleaned_summary, cleaned_full_text, channel, topics, first_ts, last_ts, msg_count)
    neo4j_ok = neo4j_write(session_id, cleaned_summary, cleaned_full_text, channel, topics, entities, first_ts, last_ts, msg_count)
    ledger = _record_sync_ledger(
        event_id=event_id or f"episode:{session_id}",
        session_id=session_id,
        channel=channel,
        kind=kind,
        summary=cleaned_summary,
        topics=topics,
        entities=entities,
        first_ts=first_ts,
        last_ts=last_ts,
        msg_count=msg_count,
        sqlite_ok=sqlite_ok,
        neo4j_ok=neo4j_ok,
        last_error=None if neo4j_ok else "neo4j_write_failed",
    )
    return {
        "summary": cleaned_summary,
        "topics": topics,
        "entities": entities,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "msg_count": msg_count,
        "full_text": cleaned_full_text,
        "sqlite_ok": sqlite_ok,
        "neo4j_ok": neo4j_ok,
        "ledger": ledger,
    }


def ingest_session(session_id, fpath, channel="discord"):
    """Ingest a session file to both Neo4j and SQLite with graceful degradation."""
    messages, ended = parse_messages(fpath)
    if not messages:
        return None
    meta = extract_meta(messages)
    if not meta:
        return None
    sqlite_ok = sqlite_write(session_id, meta["summary"], meta["full_text"], channel,
                             meta["topics"], meta["first_ts"], meta["last_ts"], meta["msg_count"])
    neo4j_ok = neo4j_write(session_id, meta["summary"], meta["full_text"], channel,
                           meta["topics"], meta["entities"], meta["first_ts"], meta["last_ts"], meta["msg_count"])
    ledger = _record_sync_ledger(
        event_id=f"episode:{session_id}",
        session_id=session_id,
        channel=channel,
        kind=LEDGER_KIND_SESSION,
        summary=meta["summary"],
        topics=meta["topics"],
        entities=meta["entities"],
        first_ts=meta["first_ts"],
        last_ts=meta["last_ts"],
        msg_count=meta["msg_count"],
        sqlite_ok=sqlite_ok,
        neo4j_ok=neo4j_ok,
        last_error=None if neo4j_ok else "neo4j_write_failed",
    )
    return {"ended_by": ended, "sqlite_ok": sqlite_ok, "neo4j_ok": neo4j_ok, "ledger": ledger, **meta}


# ────────────────────────────────────────────────────────────────────────────
# Trigger 1: Idle detection (called by cron)
# ────────────────────────────────────────────────────────────────────────────
def trigger_idle_check(idle_minutes=5, current_session_id=None):
    """Scan all sessions, ingest those idle for > idle_minutes."""
    now_ts = time.time()
    ingested = []
    for agent in _discover_agent_dirs(SESSION_BASE):
        sessions_dir = f"{SESSION_BASE}/{agent}/sessions"
        if not os.path.exists(sessions_dir):
            continue
        for fname in os.listdir(sessions_dir):
            if not fname.endswith(".jsonl"):
                continue
            session_id = fname.replace(".jsonl", "")
            # Skip current active session
            if current_session_id and session_id == current_session_id:
                continue
            fpath = os.path.join(sessions_dir, fname)
            if not os.path.exists(fpath):
                continue
            mtime = os.path.getmtime(fpath)
            # Must be idle for at least idle_minutes
            if now_ts - mtime < idle_minutes * 60:
                continue
            messages, _ = parse_messages(fpath)
            if not messages:
                continue
            # Skip sessions with < 3 real user messages (likely cron/system)
            real_user_msgs = [m for m in messages if m["role"] == "user"]
            if len(real_user_msgs) < 3:
                continue
            last_msg_ts = messages[-1].get("timestamp", "")
            try:
                last_ts_epoch = datetime.fromisoformat(last_msg_ts.replace("Z", "+00:00")).timestamp()
            except:
                last_ts_epoch = mtime
            if now_ts - last_ts_epoch < idle_minutes * 60:
                continue
            channel = _detect_channel(session_id, agent)
            result = ingest_session(session_id, fpath, channel)
            if result:
                ingested.append((session_id, result["summary"][:60]))
    return ingested


def _detect_channel(session_id, agent):
    """Heuristic: detect channel from session_id parts."""
    s = session_id.lower()
    for ch in ["discord", "telegram", "feishu", "signal"]:
        if ch in s:
            return ch
    return "discord"


# ────────────────────────────────────────────────────────────────────────────
# Trigger 2: Ending phrase detection (called immediately when phrase detected)
# ────────────────────────────────────────────────────────────────────────────
def trigger_ending_phrase(session_key):
    """Called when user says an ending phrase. Ingest that session immediately."""
    # session_key format: agent:<agent>:<channel>:<scope>:<route>:<sid>
    parts = session_key.split(":")
    known_agents = _discover_agent_dirs(SESSION_BASE)
    agent = known_agents[0] if known_agents else None
    for p in parts:
        if p in known_agents:
            agent = p
            break
    if agent is None:
        return None
    channel = "discord"
    for p in parts:
        if p in ("discord", "telegram", "feishu", "signal"):
            channel = p
    # Find the latest session file for this agent
    sessions_dir = f"{SESSION_BASE}/{agent}/sessions"
    if not os.path.exists(sessions_dir):
        return None
    files = [(f, os.path.getmtime(os.path.join(sessions_dir, f)))
             for f in os.listdir(sessions_dir) if f.endswith(".jsonl")]
    if not files:
        return None
    latest = max(files, key=lambda x: x[1])[0]
    session_id = latest.replace(".jsonl", "")
    fpath = os.path.join(sessions_dir, latest)
    return ingest_session(session_id, fpath, channel)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "idle":
        idle_minutes = 5
        current_session_id = None
        if len(sys.argv) > 2:
            if str(sys.argv[2]).isdigit():
                idle_minutes = int(sys.argv[2])
                current_session_id = sys.argv[3] if len(sys.argv) > 3 else None
            else:
                current_session_id = sys.argv[2]
        results = trigger_idle_check(idle_minutes=idle_minutes, current_session_id=current_session_id)
        if not results:
            print("No idle sessions to ingest.")
        else:
            for sid, summary in results:
                print(f"✅ {sid[:20]}... | {summary}")
    elif cmd == "ending":
        session_key = sys.argv[2] if len(sys.argv) > 2 else "agent:main:discord:default:direct:example-user"
        result = trigger_ending_phrase(session_key)
        if result:
            print(f"✅ Ingested (ended by '{result['ended_by']}'): {result['summary'][:80]} | sqlite={result['sqlite_ok']} neo4j={result['neo4j_ok']}")
        else:
            print("Nothing to ingest.")
    elif cmd == "ingest":
        session_id = sys.argv[2]
        channel = sys.argv[3] if len(sys.argv) > 3 else "discord"
        # Find file
        for agent in _discover_agent_dirs(SESSION_BASE):
            fpath = f"{SESSION_BASE}/{agent}/sessions/{session_id}.jsonl"
            if os.path.exists(fpath):
                result = ingest_session(session_id, fpath, channel)
                if result:
                    print(f"✅ {result['summary'][:80]} | sqlite={result['sqlite_ok']} neo4j={result['neo4j_ok']}")
                break
        else:
            print(f"Session not found: {session_id}")
    elif cmd == "ingest-file":
        fpath = sys.argv[2]
        channel = sys.argv[3] if len(sys.argv) > 3 else "discord"
        session_id = os.path.basename(fpath).replace('.jsonl','')
        result = ingest_session(session_id, fpath, channel)
        if result:
            print(f"✅ {result['summary'][:80]} | sqlite={result['sqlite_ok']} neo4j={result['neo4j_ok']}")
        else:
            print("Nothing to ingest.")
    else:
        print("Usage:")
        print("  episode_ingest.py idle [idle_minutes] [current_session_id]  # scan and ingest idle sessions")
        print("  episode_ingest.py ending <key>  # trigger on ending phrase")
        print("  episode_ingest.py ingest <session_id> [channel]")
        print("  episode_ingest.py ingest-file <file_path> [channel]")
