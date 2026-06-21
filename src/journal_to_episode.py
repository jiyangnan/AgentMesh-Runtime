#!/usr/bin/env python3
"""
Journal → Episode Parser (D2)

Parses daily journal files (memory/YYYY-MM-DD.md) into Neo4j Episode nodes.
Extracts structured information: decisions, lessons, events, entities.

Usage:
  journal_to_episode.py [--dry-run] [--since YYYY-MM-DD] [--batch-size N]
"""

import argparse, json, os, re, sys
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

WORKSPACE = os.getenv("ARS_WORKSPACE", os.path.expanduser("~/.openclaw/workspace"))
MEMORY_DIR = os.path.join(WORKSPACE, "memory")
NEO4J_URI = os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("ARS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("ARS_NEO4J_PASSWORD", "password")

# Known entity patterns for extraction
KNOWN_ENTITIES = {
    # --- 用户个性化实体，请根据实际情况修改 ---
    # "你的名字": "person",
    # "AI助手名字": "agent",
    "Neo4j": "technology", "OpenClaw": "technology", "Claude Code": "tool",
    "Codex": "tool", "Telegram": "channel", "Discord": "channel", "Feishu": "channel",
    "BotLearn": "product", "Ollama": "technology",
    "MEMORY.md": "file", "SOUL.md": "file", "AGENTS.md": "file",
}

# Topic keywords (shared with episode_ingest)
TOPIC_KEYWORDS = {
    "neo4j": "neo4j", "向量": "vector-index", "memory": "memory",
    "episodic": "episodic-memory", "discord": "discord", "telegram": "telegram",
    "feishu": "feishu", "cron": "cron", "skill": "skill", "写作": "writing",
    "公众号": "wechat", "twitter": "twitter", "产品": "product",
    "独立开发": "indie-dev", "openclaw": "openclaw", "agent": "agent",
    "claude": "claude", "gemini": "gemini", "embedding": "embedding",
}


@dataclass
class JournalEpisode:
    """A parsed journal episode segment."""
    journal_date: str
    heading: str
    section_type: str  # "decision", "lesson", "event", "summary", "general"
    content: str
    entities: list[dict]
    topics: list[str]


def extract_date_from_filename(fname: str) -> str | None:
    """Extract YYYY-MM-DD from filename."""
    m = re.match(r'(\d{4}-\d{2}-\d{2})', fname)
    return m.group(1) if m else None


def extract_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter."""
    fm = {}
    if not content.startswith('---'):
        return fm
    end = content.find('---', 3)
    if end < 0:
        return fm
    for line in content[3:end].strip().splitlines():
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def classify_section(heading: str, content: str) -> str:
    """Classify section type based on heading and content patterns."""
    h_lower = heading.lower()
    decision_kw = ['决策', '决定', 'decision', '选择']
    lesson_kw = ['教训', '经验', 'lesson', '踩坑', '翻车', '铁律', '注意', '规则']
    summary_kw = ['总结', 'summary', '复盘', '要点', '基本']

    for kw in decision_kw:
        if kw in h_lower:
            return "decision"
    for kw in lesson_kw:
        if kw in h_lower:
            return "lesson"
    for kw in summary_kw:
        if kw in h_lower:
            return "summary"
    return "general"


def extract_entities(text: str) -> list[dict]:
    """Extract known entities from text."""
    found = {}
    text_lower = text.lower()
    for name, etype in KNOWN_ENTITIES.items():
        if name.lower() in text_lower:
            found[name] = etype

    # File references: `filename.ext` or filename.md
    for m in re.finditer(r'`?([A-Za-z0-9_\-]+\.(?:md|py|json|jsonl|yaml|sh))`?', text):
        fname = m.group(1)
        if len(fname) > 3:
            found.setdefault(fname, "file")

    # Project paths
    home = os.getenv("HOME", "/home/user")
    for m in re.finditer(re.escape(home) + r'/([A-Za-z0-9_\-]+)', text):
        proj = m.group(1)
        if proj not in ('.openclaw', 'Library', 'Desktop'):
            found.setdefault(proj, "project")

    return [{"name": k, "entity_type": v} for k, v in sorted(found.items())]


def extract_topics(text: str) -> list[str]:
    """Extract topics from text."""
    combined = text.lower()
    topics = []
    for kw, topic in TOPIC_KEYWORDS.items():
        if kw in combined and topic not in topics:
            topics.append(topic)
    return topics


def parse_journal(fpath: str) -> list[JournalEpisode]:
    """Parse a single journal file into episodes."""
    fname = os.path.basename(fpath)
    journal_date = extract_date_from_filename(fname)
    if not journal_date:
        return []

    with open(fpath, 'r', errors='ignore') as f:
        content = f.read()

    if len(content.strip()) < 50:
        return []

    frontmatter = extract_frontmatter(content)
    # Skip frontmatter
    body = content
    if content.startswith('---'):
        end = content.find('---', 3)
        if end > 0:
            body = content[end + 3:]

    # Split by ## headings
    sections = []
    current_heading = "Overview"
    current_lines = []

    for line in body.splitlines():
        m = re.match(r'^(#{1,3})\s+(.+)', line)
        if m:
            if current_lines:
                sections.append((current_heading, '\n'.join(current_lines)))
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, '\n'.join(current_lines)))

    episodes = []
    for heading, section_text in sections:
        section_text = section_text.strip()
        if len(section_text) < 30:
            continue

        section_type = classify_section(heading, section_text)
        entities = extract_entities(section_text)
        topics = extract_topics(section_text)

        # Add frontmatter tags to topics
        if frontmatter.get('tags'):
            for tag in frontmatter['tags']:
                if tag not in topics:
                    topics.append(tag)

        episodes.append(JournalEpisode(
            journal_date=journal_date,
            heading=heading,
            section_type=section_type,
            content=section_text[:4000],
            entities=entities,
            topics=topics,
        ))

    # If no sections parsed, create one from full body
    if not episodes and len(body.strip()) > 50:
        entities = extract_entities(body)
        topics = extract_topics(body)
        episodes.append(JournalEpisode(
            journal_date=journal_date,
            heading="Full Day",
            section_type="general",
            content=body.strip()[:4000],
            entities=entities,
            topics=topics,
        ))

    return episodes


def write_episode_to_neo4j(episode: JournalEpisode) -> bool:
    """Write a journal episode to Neo4j."""
    try:
        from neo4j import GraphDatabase
        session_id = f"journal:{episode.journal_date}:{episode.heading[:30]}"
        summary = f"[{episode.section_type}] {episode.heading} ({episode.journal_date})"
        full_text = episode.content
        topics = episode.topics
        entity_names = [e['name'] for e in episode.entities]
        ts = f"{episode.journal_date}T00:00:00Z"

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as s:
            s.run("""
                MERGE (e:Episode {session_id: $sid})
                SET e.channel = 'journal',
                    e.summary = $sum,
                    e.topics = $topics,
                    e.entity_names = $entity_names,
                    e.first_timestamp = $fts,
                    e.last_timestamp = $fts,
                    e.message_count = 1,
                    e.full_text = $ft,
                    e.section_type = $stype,
                    e.journal_date = $jdate,
                    e.updated_at = datetime()
            """, sid=session_id, sum=summary, topics=topics,
               entity_names=entity_names, fts=ts, ft=full_text,
               stype=episode.section_type, jdate=episode.journal_date)

            # Clear and recreate relationships
            s.run("""
                MATCH (e:Episode {session_id: $sid})-[r:TAGGED|MENTIONS]->()
                DELETE r
            """, sid=session_id)

            for t in topics:
                s.run("""
                    MERGE (t:Topic {name: $name})
                    WITH t
                    MATCH (e:Episode {session_id: $sid})
                    MERGE (e)-[:TAGGED]->(t)
                """, name=t, sid=session_id)

            for ent in episode.entities:
                s.run("""
                    MERGE (n:Entity {name: $name, entity_type: $etype})
                    WITH n
                    MATCH (e:Episode {session_id: $sid})
                    MERGE (e)-[:MENTIONS]->(n)
                """, name=ent['name'], etype=ent['entity_type'], sid=session_id)

            # Link to same-day episodes
            s.run("""
                MATCH (prev:Episode {journal_date: $jdate})
                WHERE prev.session_id <> $sid
                WITH prev
                ORDER BY prev.first_timestamp DESC
                LIMIT 1
                MATCH (e:Episode {session_id: $sid})
                MERGE (prev)-[:SAME_DAY]->(e)
            """, sid=session_id, jdate=episode.journal_date)

        driver.close()
        return True
    except Exception as e:
        try:
            driver.close()
        except:
            pass
        print(f"  ❌ Neo4j write failed: {e}")
        return False


def batch_process(since: str | None = None, dry_run: bool = False, batch_size: int = 500):
    """Process all journal files."""
    since_ts = None
    if since:
        try:
            since_ts = datetime.strptime(since, "%Y-%m-%d")
        except ValueError:
            print(f"Invalid --since date: {since}")
            return

    # Load ledger
    ledger_path = os.path.join(os.path.dirname(__file__), ".journal_ledger.json")
    ledger = {}
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path) as f:
                ledger = json.load(f)
        except Exception:
            pass

    files = sorted([f for f in os.listdir(MEMORY_DIR) if f.endswith('.md')])
    total_files = 0
    total_episodes = 0
    total_neo4j_ok = 0
    total_skipped = 0

    for fname in files:
        if total_files >= batch_size:
            break

        fpath = os.path.join(MEMORY_DIR, fname)
        date_str = extract_date_from_filename(fname)
        if not date_str:
            continue

        if since_ts:
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date < since_ts:
                    continue
            except ValueError:
                continue

        # Checksum dedup
        import hashlib
        with open(fpath, 'rb') as f:
            chk = hashlib.md5(f.read()).hexdigest()
        if fname in ledger and ledger[fname] == chk:
            total_skipped += 1
            continue

        total_files += 1
        episodes = parse_journal(fpath)
        if not episodes:
            continue

        for ep in episodes:
            total_episodes += 1
            if dry_run:
                print(f"  [DRY] {ep.journal_date} | {ep.section_type} | {ep.heading[:50]} | entities={len(ep.entities)} topics={len(ep.topics)}")
                continue
            ok = write_episode_to_neo4j(ep)
            if ok:
                total_neo4j_ok += 1

        # Update ledger
        ledger[fname] = chk

    # Save ledger
    with open(ledger_path, 'w') as f:
        json.dump(ledger, f)

    print(f"\n=== Journal → Episode Complete ===")
    print(f"Files: {total_files}  Episodes: {total_episodes}  Neo4j OK: {total_neo4j_ok}")
    print(f"Skipped (checksum): {total_skipped}")
    print(f"Ledger: {len(ledger)} entries")


def main():
    ap = argparse.ArgumentParser(description="Journal → Episode Parser (D2)")
    ap.add_argument("--dry-run", action="store_true", help="Parse only, don't write to Neo4j")
    ap.add_argument("--since", type=str, help="Only process journals since YYYY-MM-DD")
    ap.add_argument("--batch-size", type=int, default=500, help="Max files to process")
    args = ap.parse_args()
    batch_process(since=args.since, dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
