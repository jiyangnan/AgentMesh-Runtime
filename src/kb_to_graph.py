#!/usr/bin/env python3
"""
KB → Graph Migration (D3)

Migrates 记忆库/语义知识/ → Concept nodes
Migrates 记忆库/强制规则/ → Rule nodes
to Neo4j for graph-based recall.

Usage:
  kb_to_graph.py [--dry-run]
"""

import argparse, json, os, re, sys
from datetime import datetime, timezone

WORKSPACE = os.getenv("ARS_WORKSPACE", os.path.expanduser("~/.openclaw/workspace"))
KB_BASE = os.path.join(WORKSPACE, "memory", "记忆库")
SEMANTIC_DIR = os.path.join(KB_BASE, "语义知识")
RULES_DIR = os.path.join(KB_BASE, "强制规则")

NEO4J_URI = os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("ARS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("ARS_NEO4J_PASSWORD", "password")


def extract_frontmatter(content: str) -> dict:
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


def extract_severity(content: str, filename: str) -> str:
    """Determine severity from content or filename."""
    if filename.startswith('00-') or '铁律' in filename or '铁律' in content[:200]:
        return "critical"
    if any(kw in content[:200] for kw in ['必须', '禁止', '绝不', '红线']):
        return "critical"
    return "warning"


def extract_triggered_by(content: str) -> list[str]:
    """Heuristic: what triggers this rule."""
    triggers = []
    if any(kw in content for kw in ['发布', '发送', '推文', '公众号']):
        triggers.append("publishing")
    if any(kw in content for kw in ['代码', 'coding', 'skill', '编程']):
        triggers.append("coding")
    if any(kw in content for kw in ['记忆', 'memory', '写入']):
        triggers.append("memory")
    if any(kw in content for kw in ['文件', 'config', '配置']):
        triggers.append("config")
    if not triggers:
        triggers.append("general")
    return triggers


def process_concepts(dry_run: bool = False) -> int:
    """Process 语义知识/ → Concept nodes."""
    if not os.path.exists(SEMANTIC_DIR):
        print(f"Directory not found: {SEMANTIC_DIR}")
        return 0

    count = 0
    for fname in sorted(os.listdir(SEMANTIC_DIR)):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(SEMANTIC_DIR, fname)
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()

        title = fname.replace('.md', '')
        fm = extract_frontmatter(content)
        if fm.get('title'):
            title = fm['title']

        description = content[:800].strip()
        tags = fm.get('tags', []) if isinstance(fm.get('tags'), list) else []

        if dry_run:
            print(f"  [DRY] Concept: {title} | desc_len={len(description)} | tags={tags}")
            count += 1
            continue

        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            with driver.session() as s:
                s.run("""
                    MERGE (c:Concept {title: $title})
                    SET c.description = $desc,
                        c.source_path = $spath,
                        c.tags = $tags,
                        c.updated_at = datetime()
                """, title=title, desc=description, spath=fpath, tags=tags)

                # Link to topics
                for tag in tags:
                    s.run("""
                        MERGE (t:Topic {name: $name})
                        WITH t
                        MATCH (c:Concept {title: $title})
                        MERGE (c)-[:TAGGED]->(t)
                    """, name=tag, title=title)

                # Link to related entities from content
                for known_name, etype in {
                    # --- 用户个性化实体，请根据实际情况修改 ---
                    "Neo4j": "technology", "OpenClaw": "technology", "Claude Code": "tool", "Codex": "tool",
                }.items():
                    if known_name.lower() in content.lower():
                        s.run("""
                            MERGE (e:Entity {name: $name, entity_type: $etype})
                            WITH e
                            MATCH (c:Concept {title: $title})
                            MERGE (c)-[:MENTIONS]->(e)
                        """, name=known_name, etype=etype, title=title)
            driver.close()
            count += 1
        except Exception as e:
            print(f"  ❌ Concept write failed ({title}): {e}")

    return count


def process_rules(dry_run: bool = False) -> int:
    """Process 强制规则/ → Rule nodes."""
    if not os.path.exists(RULES_DIR):
        print(f"Directory not found: {RULES_DIR}")
        return 0

    count = 0
    for fname in sorted(os.listdir(RULES_DIR)):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(RULES_DIR, fname)
        with open(fpath, 'r', errors='ignore') as f:
            content = f.read()

        title = fname.replace('.md', '')
        fm = extract_frontmatter(content)
        if fm.get('title'):
            title = fm['title']

        description = content[:1000].strip()
        severity = extract_severity(content, fname)
        triggered_by = extract_triggered_by(content)

        if dry_run:
            print(f"  [DRY] Rule: {title} | severity={severity} | triggers={triggered_by}")
            count += 1
            continue

        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            with driver.session() as s:
                s.run("""
                    MERGE (r:Rule {title: $title})
                    SET r.description = $desc,
                        r.source_path = $spath,
                        r.triggered_by = $triggers,
                        r.severity = $severity,
                        r.updated_at = datetime()
                """, title=title, desc=description, spath=fpath,
                     triggers=triggered_by, severity=severity)

                # Link rules to each other (related rules)
                s.run("""
                    MATCH (r:Rule {title: $title})
                    MATCH (other:Rule)
                    WHERE other.title <> $title
                    MERGE (r)-[:RELATED_RULE]->(other)
                """, title=title)
            driver.close()
            count += 1
        except Exception as e:
            print(f"  ❌ Rule write failed ({title}): {e}")

    return count


def main():
    ap = argparse.ArgumentParser(description="KB → Graph Migration (D3)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=== D3: KB → Graph Migration ===\n")

    print("Processing 语义知识/ → Concept nodes...")
    concept_count = process_concepts(dry_run=args.dry_run)
    print(f"  Concepts created: {concept_count}\n")

    print("Processing 强制规则/ → Rule nodes...")
    rule_count = process_rules(dry_run=args.dry_run)
    print(f"  Rules created: {rule_count}\n")

    print(f"=== Migration Complete: {concept_count} concepts + {rule_count} rules ===")


if __name__ == "__main__":
    main()
