#!/usr/bin/env python3
"""
Unified HA Memory Recall

Single entrypoint for local memory recall with automatic failover:
1) Neo4j episodic memory
2) SQLite FTS memory
3) File/session grep fallback

Goal: graceful degradation instead of memory collapse.
"""

from __future__ import annotations
import argparse, glob, json, os, re, sqlite3, subprocess, sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Optional

ENTITY_TYPE_WEIGHT = {
    'person': 2.2,
    'agent': 2.0,
    'product': 1.8,
    'project': 1.7,
    'file': 1.5,
    'tool': 1.2,
    'technology': 1.0,
    'channel': 0.7,
    'concept': 0.9,
    'endpoint': 0.2,
    'command': 0.1,
}

# ── C1: Ripgrep Enhancement Config ──────────────────────────────────────────
SNIPPET_SPAN = 200          # chars around keyword for snippet generation
FRONTMATTER_FIELDS = {'title', 'tags', 'created', 'date'}  # extractable frontmatter
HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)', re.MULTILINE)  # ## headings as semantic boundaries

# ── C2: Unified Ranking Weights ────────────────────────────────────────────
BACKEND_WEIGHTS = {
    'neo4j': 1.0,
    # vector: raw cosine similarity (0-1) is multiplied by this weight.
    # score >= 0.75 (strong semantic match) → effective score >= 1.125
    # score >= 0.85 (excellent match) → effective score >= 1.275
    # score >= 0.90 (near-perfect) → effective score >= 1.35
    # sqlite_fts typical scores: 7-10 (after weight 0.6 → 4.2-6.0)
    # neo4j typical scores: 5-8 (after weight 1.0 → 5-8)
    # Vector 强匹配(0.85+) 可以与 neo4j 竞争；弱匹配被压制
    'vector': 1.5,
    'sqlite_fts': 0.6,
    'ripgrep': 0.3,
}

# Lazy import for vector store (optional, requires GEMINI_API_KEY)
_VS: Optional["VectorStore"] = None


def _get_vs() -> Optional["VectorStore"]:
    global _VS
    if _VS is False:  # already tried and failed
        return None
    if _VS is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            _VS = False
            return None
        try:
            from vector_store import VectorStore
            _VS = VectorStore()
        except Exception:
            _VS = False
            return None
    return _VS

WORKSPACE = os.getenv("ARS_WORKSPACE", os.path.expanduser("~/.openclaw/workspace"))
SQLITE_DB = os.getenv("ARS_MEMORY_DB", os.path.expanduser("~/.openclaw/memory/main.sqlite"))
_AGENTS_BASE = os.getenv("ARS_SESSION_BASE", os.path.expanduser("~/.openclaw/agents"))


def _discover_session_dirs(base: str) -> list[str]:
    """Auto-discover ``<base>/<agent>/sessions`` directories.

    Replaces a previously hard-coded operator-specific agent roster so the
    recall layer works for any host without configuration.
    """
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        candidate = os.path.join(base, name, "sessions")
        if os.path.isdir(candidate):
            out.append(candidate)
    return out


SESSION_DIRS = _discover_session_dirs(_AGENTS_BASE)
NEO4J_URI = os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("ARS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("ARS_NEO4J_PASSWORD", "password")


@dataclass
class Hit:
    backend: str
    score: float
    title: str
    location: str
    snippet: str
    meta: dict


def tokenize(query: str) -> list[str]:
    """Tokenize query into searchable tokens.
    English: split on word boundaries.
    Chinese: produce the full phrase + bigram (2-char) sliding windows for broader matching."""
    out = []
    seen = set()

    # English tokens
    for w in re.findall(r"[A-Za-z0-9_\-\.]+", query.lower()):
        if len(w) >= 2 and w not in seen:
            seen.add(w)
            out.append(w)

    # Chinese: extract continuous Chinese runs
    zh_runs = re.findall(r'[\u4e00-\u9fff]+', query)
    for run in zh_runs:
        # Add the full run as one token
        if len(run) >= 2 and run not in seen:
            seen.add(run)
            out.append(run)
        # Add bigrams for runs longer than 2 chars (broader matching)
        if len(run) > 2:
            for i in range(len(run) - 1):
                bg = run[i:i+2]
                if bg not in seen:
                    seen.add(bg)
                    out.append(bg)

    return out or [query.strip()]


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def recency_boost(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        if days < 1:
            return 0.18
        if days < 7:
            return 0.16
        if days < 30:
            return 0.08
    except Exception:
        pass
    return 0.0


def source_adjustment(location: str, title: str) -> float:
    score = 0.0
    if '.checkpoint.' in location:
        score += 0.25
    if 'Conversation info (untrusted metadata)' in title:
        score -= 0.2
    return score


def score_text_match(query: str, tokens: list[str], summary: str, text: str, topics=None, entities=None) -> float:
    summary_n = normalize_text(summary).lower()
    text_n = normalize_text(text).lower()
    query_n = normalize_text(query).lower()
    topics_n = [str(x).lower() for x in (topics or [])]
    entity_pairs = []
    for x in (entities or []):
        if isinstance(x, dict):
            entity_pairs.append((str(x.get('name','')).lower(), str(x.get('entity_type','concept'))))
        else:
            entity_pairs.append((str(x).lower(), 'concept'))
    score = 0.0
    if query_n and query_n in summary_n:
        score += 4.0
    if query_n and query_n in text_n:
        score += 2.5
    for t in tokens:
        if t.lower() in summary_n:
            score += 1.4
        if t.lower() in text_n:
            score += 0.7
        if any(t.lower() in x for x in topics_n):
            score += 1.2
        for ename, etype in entity_pairs:
            if t.lower() in ename:
                score += ENTITY_TYPE_WEIGHT.get(etype, 0.8)
                break
    # exact entity match bonus
    for ename, etype in entity_pairs:
        if query_n and query_n == ename:
            score += ENTITY_TYPE_WEIGHT.get(etype, 0.8) + 1.2
    return score


def extract_snippet(text: str, tokens: list[str], span: int = 140) -> str:
    lower = text.lower()
    for t in tokens:
        idx = lower.find(t.lower())
        if idx >= 0:
            start = max(0, idx - span)
            end = min(len(text), idx + len(t) + span)
            s = text[start:end].replace("\n", " ")
            return ("..." if start > 0 else "") + s + ("..." if end < len(text) else "")
    return text[:span*2].replace("\n", " ")


def recall_neo4j(query: str, top_k: int) -> list[Hit]:
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []
    tokens = tokenize(query)
    clauses = []
    params = {}
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = tok.lower()
        clauses.append(f"toLower(coalesce(e.summary, '')) CONTAINS $t{i}")
        clauses.append(f"toLower(coalesce(e.full_text, '')) CONTAINS $t{i}")
        clauses.append(f"ANY(x IN coalesce(e.topics, []) WHERE toLower(x) CONTAINS $t{i})")
        clauses.append(f"ANY(x IN coalesce(e.entity_names, []) WHERE toLower(x) CONTAINS $t{i})")
    cypher = f"""
    MATCH (e:Episode)
    WHERE {' OR '.join(clauses)}
    OPTIONAL MATCH (e)-[:MENTIONS]->(n:Entity)
    WITH e, collect(DISTINCT {{name:n.name, entity_type:n.entity_type}}) AS entity_rows
    RETURN e.session_id AS sid,
           e.summary AS summary,
           e.full_text AS full_text,
           e.topics AS topics,
           e.first_timestamp AS ts,
           e.channel AS channel,
           e.message_count AS cnt,
           entity_rows AS entity_rows
    ORDER BY e.first_timestamp DESC
    LIMIT $limit
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    hits: list[Hit] = []
    with driver.session() as s:
        for r in s.run(cypher, **params, limit=top_k):
            text = (r["full_text"] or "")
            entities = [x for x in (r["entity_rows"] or []) if x and x.get('name')]
            score = 2.0 + score_text_match(query, tokens, r["summary"] or "", text, r["topics"] or [], entities) + recency_boost(r["ts"]) + source_adjustment(f"episode:{r['sid']}", r["summary"] or r["sid"])
            hits.append(Hit(
                backend="neo4j",
                score=score,
                title=r["summary"] or r["sid"],
                location=f"episode:{r['sid']}",
                snippet=extract_snippet(text or (r["summary"] or ""), tokens),
                meta={"topics": r["topics"] or [], "entities": entities, "ts": r["ts"], "channel": r["channel"], "message_count": r["cnt"]},
            ))
    driver.close()
    return hits


def recall_neo4j_concepts(query: str, top_k: int) -> list[Hit]:
    """D4: Recall Concept nodes from Neo4j."""
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []
    tokens = tokenize(query)
    clauses = []
    params = {}
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = tok.lower()
        clauses.append(f"toLower(c.title) CONTAINS $t{i}")
        clauses.append(f"toLower(c.description) CONTAINS $t{i}")
        clauses.append(f"ANY(x IN coalesce(c.tags, []) WHERE toLower(x) CONTAINS $t{i})")
    if not clauses:
        return []
    cypher = f"""
    MATCH (c:Concept)
    WHERE {' OR '.join(clauses)}
    RETURN c.title AS title, c.description AS desc, c.source_path AS spath, c.tags AS tags
    LIMIT $limit
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    hits = []
    with driver.session() as s:
        for r in s.run(cypher, **params, limit=top_k):
            desc = r["desc"] or ""
            score = 1.8 + score_text_match(query, tokens, r["title"] or "", desc)
            hits.append(Hit(
                backend="neo4j",
                score=score,
                title=f"📘 {r['title']}",
                location=r["spath"] or f"concept:{r['title']}",
                snippet=extract_snippet(desc, tokens),
                meta={"node_type": "Concept", "tags": r["tags"] or []},
            ))
    driver.close()
    return hits


def recall_neo4j_rules(query: str, top_k: int) -> list[Hit]:
    """D4: Recall Rule nodes from Neo4j."""
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []
    tokens = tokenize(query)
    clauses = []
    params = {}
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = tok.lower()
        clauses.append(f"toLower(r.title) CONTAINS $t{i}")
        clauses.append(f"toLower(r.description) CONTAINS $t{i}")
        clauses.append(f"ANY(x IN coalesce(r.triggered_by, []) WHERE toLower(x) CONTAINS $t{i})")
    if not clauses:
        return []
    cypher = f"""
    MATCH (r:Rule)
    WHERE {' OR '.join(clauses)}
    RETURN r.title AS title, r.description AS desc, r.severity AS severity,
           r.triggered_by AS triggers, r.source_path AS spath
    LIMIT $limit
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    hits = []
    with driver.session() as s:
        for r in s.run(cypher, **params, limit=top_k):
            desc = r["desc"] or ""
            severity = r["severity"] or "warning"
            score = 2.5 if severity == "critical" else 1.5
            score += score_text_match(query, tokens, r["title"] or "", desc)
            hits.append(Hit(
                backend="neo4j",
                score=score,
                title=f"🚨 {r['title']}",
                location=r["spath"] or f"rule:{r['title']}",
                snippet=extract_snippet(desc, tokens),
                meta={"node_type": "Rule", "severity": severity, "triggered_by": r["triggers"] or []},
            ))
    driver.close()
    return hits


def recall_journal_episodes(query: str, top_k: int) -> list[Hit]:
    """D4: Recall Journal Episode nodes from Neo4j."""
    try:
        from neo4j import GraphDatabase
    except Exception:
        return []
    tokens = tokenize(query)
    clauses = []
    params = {}
    for i, tok in enumerate(tokens):
        params[f"t{i}"] = tok.lower()
        clauses.append(f"toLower(e.summary) CONTAINS $t{i}")
        clauses.append(f"toLower(e.full_text) CONTAINS $t{i}")
        clauses.append(f"ANY(x IN coalesce(e.topics, []) WHERE toLower(x) CONTAINS $t{i})")
        clauses.append(f"ANY(x IN coalesce(e.entity_names, []) WHERE toLower(x) CONTAINS $t{i})")
    if not clauses:
        return []
    cypher = f"""
    MATCH (e:Episode)
    WHERE e.channel = 'journal' AND ({' OR '.join(clauses)})
    RETURN e.session_id AS sid, e.summary AS summary, e.full_text AS full_text,
           e.topics AS topics, e.journal_date AS jdate, e.section_type AS stype
    ORDER BY e.journal_date DESC
    LIMIT $limit
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    hits = []
    with driver.session() as s:
        for r in s.run(cypher, **params, limit=top_k):
            text = r["full_text"] or ""
            score = 1.5 + score_text_match(query, tokens, r["summary"] or "", text, r["topics"] or []) + recency_boost(r.get("jdate"))
            stype = r.get("stype", "general")
            hits.append(Hit(
                backend="neo4j",
                score=score,
                title=f"📝 [{stype}] {r['summary'] or r['sid']}",
                location=f"journal:{r['sid']}",
                snippet=extract_snippet(text, tokens),
                meta={"node_type": "JournalEpisode", "journal_date": r.get("jdate"), "section_type": stype, "topics": r["topics"] or []},
            ))
    driver.close()
    return hits


def recall_sqlite(query: str, top_k: int) -> list[Hit]:
    if not os.path.exists(SQLITE_DB):
        return []
    tokens = tokenize(query)
    fts_query = " OR ".join(f'"{t}"' if ' ' in t else t for t in tokens)
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    hits = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.path, c.source, c.text,
                   snippet(chunks_fts, 0, '[', ']', ' … ', 20) AS snip,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, top_k),
        )
        for row in cur.fetchall():
            text = row["text"] or ""
            rank = float(row["rank"])
            score = 1.5 + (5.0 - rank) + score_text_match(query, tokens, row["path"], text) + source_adjustment(row["path"], row["path"])
            hits.append(Hit(
                backend="sqlite_fts",
                score=score,
                title=row["path"],
                location=row["path"],
                snippet=row["snip"] or extract_snippet(text, tokens),
                meta={"source": row["source"]},
            ))
    except Exception:
        pass
    finally:
        conn.close()
    return hits


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content (C1 enhancement)."""
    fm = {}
    if not content.startswith('---'):
        return fm
    end = content.find('---', 3)
    if end < 0:
        return fm
    block = content[3:end].strip()
    for line in block.splitlines():
        line = line.strip()
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key in FRONTMATTER_FIELDS:
            if val.startswith('[') and val.endswith(']'):
                fm[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(',') if v.strip()]
            else:
                fm[key] = val
    return fm


def _extract_headings(content: str) -> list[tuple[int, str]]:
    """Extract markdown headings as semantic boundaries (C1 enhancement).
    Returns list of (line_number_0indexed, heading_text)."""
    headings = []
    for m in HEADING_RE.finditer(content):
        level = len(m.group(1))
        title = m.group(2).strip()
        # approximate line number from position
        line_no = content[:m.start()].count('\n')
        headings.append((line_no, title))
    return headings


def _file_context_around_line(lines: list[str], target_idx: int, context: int = 3) -> tuple[str, str]:
    """Get heading context + snippet around a target line (C1 enhancement).
    Returns (nearest_heading, snippet_text)."""
    headings_above = []
    for i in range(target_idx, -1, -1):
        if i < len(lines):
            m = re.match(r'^(#{1,4})\s+(.+)', lines[i])
            if m:
                headings_above.append(m.group(2).strip())
                break
    nearest = headings_above[0] if headings_above else ''
    start = max(0, target_idx - context)
    end = min(len(lines), target_idx + context + 1)
    snippet = ' '.join(lines[start:end]).strip()
    return nearest, snippet


def recall_files(query: str, top_k: int) -> list[Hit]:
    """C1-Enhanced Ripgrep recall: frontmatter parsing, heading extraction,
    200-char snippets, date-weighted recency boost, same-file dedup."""
    tokens = tokenize(query)
    patterns = []
    for t in tokens[:6]:
        patterns.extend(["-e", t])
    search_paths = [os.path.join(WORKSPACE, "memory"), os.path.join(WORKSPACE, "MEMORY.md"), *SESSION_DIRS]
    cmd = [
        "rg", "-n", "-i", "--no-heading", "--max-count", str(top_k * 3),
        "-g", "*.md",
        "-g", "*.jsonl",
        "-g", "!*.checkpoint.*.jsonl",
        "-g", "!*.trajectory.jsonl",
        "-g", "!*.trajectory-path.json",
        *patterns,
        *search_paths,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    except Exception:
        return []

    # Group results by file for C1 enhancements
    file_lines: dict[str, list[tuple[int, str]]] = {}  # path -> [(line_no, text)]
    for line in out.stdout.splitlines()[:top_k * 3]:
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, line_no_str, text = parts[0], parts[1], parts[2]
        try:
            line_no = int(line_no_str)
        except ValueError:
            continue
        file_lines.setdefault(path, []).append((line_no, text))

    hits = []
    file_frontmatter_cache: dict[str, dict] = {}
    file_date_cache: dict[str, float] = {}  # path -> recency_boost

    for path, matches in file_lines.items():
        # Parse frontmatter once per file
        if path not in file_frontmatter_cache:
            fm = {}
            try:
                with open(path, 'r', errors='ignore') as f:
                    first_2k = f.read(2048)
                fm = _parse_frontmatter(first_2k)
                # Extract date from frontmatter or filename
                date_str = fm.get('created') or fm.get('date', '')
                if not date_str:
                    # Try filename pattern: YYYY-MM-DD
                    m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(path))
                    date_str = m.group(1) if m else ''
                file_date_cache[path] = recency_boost(date_str) if date_str else 0.0
            except Exception:
                pass
            file_frontmatter_cache[path] = fm

        fm = file_frontmatter_cache.get(path, {})
        date_boost = file_date_cache.get(path, 0.0)
        fm_tags = fm.get('tags', [])
        fm_title = fm.get('title', '')

        # Same-file dedup: keep top-2 matches per file
        for line_no, text in matches[:2]:
            base_score = 0.6 + score_text_match(query, tokens, os.path.basename(path), text) + source_adjustment(path, os.path.basename(path))

            # Frontmatter tag match bonus
            if fm_tags:
                tag_str = ' '.join(fm_tags).lower()
                for t in tokens:
                    if t.lower() in tag_str:
                        base_score += 0.5

            # Frontmatter title match bonus
            if fm_title and fm_title.lower() in query.lower():
                base_score += 0.8

            # Date recency boost
            base_score += date_boost

            # Generate 200-char snippet around keyword
            snippet = extract_snippet(text, tokens, span=SNIPPET_SPAN)

            # Build enriched title with heading + date
            display_title = os.path.basename(path)
            enriched_meta = {}
            if fm_title:
                display_title = fm_title
                enriched_meta['title'] = fm_title
            if fm.get('created'):
                enriched_meta['created'] = fm['created']
            if fm_tags:
                enriched_meta['tags'] = fm_tags

            hits.append(Hit(
                backend="ripgrep",
                score=base_score,
                title=display_title,
                location=f"{path}#{line_no}",
                snippet=snippet,
                meta=enriched_meta,
            ))

    return hits[:top_k]


def canonical_episode_id(value: str) -> str:
    return re.sub(r'\.checkpoint\.[A-Za-z0-9\-]+$', '', value)


def canonical_key(hit: Hit) -> str:
    if hit.location.startswith('episode:'):
        return 'episode:' + canonical_episode_id(hit.location[len('episode:'):])
    m = re.search(r'episode:([A-Za-z0-9\-\.]+)', hit.snippet)
    if m:
        return 'episode:' + canonical_episode_id(m.group(1))
    return hit.location


def recall_vector(query: str, top_k: int) -> list[Hit]:
    """Vector similarity search via Gemini embedding.

    Active only when GEMINI_API_KEY is set. See ``vector_store`` for details.
    """
    vs = _get_vs()
    if vs is None:
        return []
    
    try:
        hits = vs.search(query, top_k=top_k, min_score=0.4)
    except Exception:
        return []
    
    result = []
    for h in hits:
        result.append(Hit(
            backend="vector",
            score=h["score"],
            title=h["id"],
            location=f"vector:{h['id']}",
            snippet=h["text"][:260],
            meta={"source": h.get("source", "ars")},
        ))
    return result


def dedupe_and_rank(hits: list[Hit], top_k: int) -> list[Hit]:
    """C2: Unified ranking with configurable backend weights."""
    best = {}
    for h in hits:
        # Apply C2 backend weights (replaces old hardcoded backend_bias)
        h.score = h.score * BACKEND_WEIGHTS.get(h.backend, 0.3)
        key = canonical_key(h)
        if key not in best or h.score > best[key].score:
            best[key] = h
    ranked = sorted(best.values(), key=lambda x: x.score, reverse=True)
    return ranked[:top_k]


def recall(query: str, top_k: int = 8, use_neo4j: bool = True, use_sqlite: bool = True, use_files: bool = True,
           use_concepts: bool = True, use_rules: bool = True, use_journal: bool = True,
           use_vector: bool = True) -> list[Hit]:
    """Unified five-path recall: Episode + Concept + Rule + Journal + Vector."""
    hits = []
    if use_neo4j:
        hits.extend(recall_neo4j(query, top_k))
    if use_concepts:
        hits.extend(recall_neo4j_concepts(query, top_k))
    if use_rules:
        hits.extend(recall_neo4j_rules(query, top_k))
    if use_journal:
        hits.extend(recall_journal_episodes(query, top_k))
    if use_vector:
        hits.extend(recall_vector(query, top_k))
    if use_sqlite:
        hits.extend(recall_sqlite(query, top_k))
    if use_files and len(hits) < max(3, top_k // 2):
        hits.extend(recall_files(query, top_k))
    return dedupe_and_rank(hits, top_k)


def format_text(query: str, hits: list[Hit]) -> str:
    if not hits:
        return f"No memory hits for: {query}"
    # Source emoji by backend
    EMOJI = {'neo4j': '🧠', 'vector': '🔍', 'sqlite_fts': '🗃️', 'ripgrep': '📄'}
    lines = [f"Unified Memory Recall · query={query} · hits={len(hits)}\n"]
    for i, h in enumerate(hits, 1):
        emoji = EMOJI.get(h.backend, '❓')
        lines.append(f"{i}. {emoji} [{h.backend}] {h.title}")
        lines.append(f"   at: {h.location}")
        if h.meta:
            lines.append(f"   meta: {json.dumps(h.meta, ensure_ascii=False)}")
        lines.append(f"   {h.snippet[:260]}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-neo4j", action="store_true")
    ap.add_argument("--no-sqlite", action="store_true")
    ap.add_argument("--no-files", action="store_true")
    ap.add_argument("--no-concepts", action="store_true")
    ap.add_argument("--no-rules", action="store_true")
    ap.add_argument("--no-journal", action="store_true")
    ap.add_argument("--no-vector", action="store_true")
    args = ap.parse_args()
    hits = recall(
        args.query,
        args.top_k,
        use_neo4j=not args.no_neo4j,
        use_sqlite=not args.no_sqlite,
        use_files=not args.no_files,
        use_concepts=not args.no_concepts,
        use_rules=not args.no_rules,
        use_journal=not args.no_journal,
        use_vector=not args.no_vector,
    )
    if args.json:
        print(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2))
    else:
        print(format_text(args.query, hits))


if __name__ == "__main__":
    main()
