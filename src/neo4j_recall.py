#!/usr/bin/env python3
"""
neo4j-recall — Cypher-powered episodic memory retrieval.

Fallback when OpenAI embedding is unavailable.
Uses keyword + CONTAINS search on Episode.full_text and Episode.summary.

Usage:
    python3 neo4j-recall.py "第一性原理"
    python3 neo4j-recall.py "neo4j 图数据库" --top-k 5
    python3 neo4j-recall.py "白羊武士 项目" --json
"""

import sys, json, re
from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password"


def neo4j_recall(query: str, top_k: int = 5, verbose: bool = False) -> list[dict]:
    """
    Search episodes using keyword + CONTAINS across summary and full_text.
    Returns list of dicts with session_id, summary, topics, timestamps.
    """
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    # Build CONTAINS clauses for each token
    tokens = re.findall(r'[\w]+', query.lower())
    contains_clauses = " OR ".join(
        f"(e.summary CONTAINS '{t}' OR e.full_text CONTAINS '{t}')" for t in tokens
    )

    cypher = f"""
        MATCH (e:Episode)
        WHERE {contains_clauses}
        RETURN e.session_id as session_id,
               e.summary as summary,
               e.topics as topics,
               e.first_timestamp as first_ts,
               e.last_timestamp as last_ts,
               e.message_count as msg_count,
               e.channel as channel,
               e.full_text as full_text
        ORDER BY e.first_timestamp DESC
        LIMIT {top_k}
    """

    results = []
    with driver.session() as s:
        for record in s.run(cypher):
            full_text = record["full_text"] or ""
            # Extract relevant snippet around matches
            snippet = _extract_snippet(full_text, tokens)
            results.append({
                "session_id": record["session_id"],
                "summary": record["summary"],
                "topics": record["topics"] or [],
                "first_ts": record["first_ts"],
                "last_ts": record["last_ts"],
                "msg_count": record["msg_count"],
                "channel": record["channel"] or "unknown",
                "snippet": snippet,
            })

    driver.close()
    return results


def _extract_snippet(text: str, tokens: list[str], context_chars: int = 150) -> str:
    """Extract snippet around first match."""
    text_lower = text.lower()
    for t in tokens:
        idx = text_lower.find(t)
        if idx >= 0:
            start = max(0, idx - context_chars)
            end = min(len(text), idx + context_chars + len(t))
            snippet = text[start:end].replace("\n", " ").strip()
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            return f"{prefix}{snippet}{suffix}"
    return text[:context_chars * 2].replace("\n", " ").strip()[:300]


def format_results(results: list[dict], query: str) -> str:
    if not results:
        return f"⚠️ Neo4j 检索无结果（查询：「{query}」）\n提示：数据在 Neo4j（{len(results)} 条 episode），但关键词未匹配到。"

    lines = [f"🧠 **Neo4j Episodic Memory 检索结果**（共 {len(results)} 条）\n"]
    for i, r in enumerate(results, 1):
        ts = r["first_ts"][:16] if r["first_ts"] else "?"
        topics = ", ".join(r["topics"][:5]) if r["topics"] else "无标签"
        snippet = r["snippet"][:200] if r["snippet"] else r["summary"][:200]
        lines.append(
            f"**{i}. [{ts}]** `{r['channel']}` "
            f"({r['msg_count']}条消息)\n"
            f"   标签: {topics}\n"
            f"   {snippet}\n"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Neo4j episodic memory recall")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    results = neo4j_recall(args.query, top_k=args.top_k, verbose=args.verbose)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results, args.query))
