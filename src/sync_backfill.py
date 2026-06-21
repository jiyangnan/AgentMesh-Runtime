#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any

from episode_ingest import MEMORY_DB, _clean_text, extract_entities, neo4j_write, TOPIC_KEYWORDS
from sync_state import append_ledger_event, neo4j_is_ready, pending_ledger_entries, sync_status_report


def fetch_sqlite_event(session_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(MEMORY_DB)
    cur = conn.cursor()
    try:
        cur.execute("select path, source, text from chunks where path = ? limit 1", (f"episode:{session_id}",))
        row = cur.fetchone()
        if not row:
            return None
        return {"path": row[0], "source": row[1], "text": row[2]}
    finally:
        conn.close()


def derive_topics(text: str) -> list[str]:
    combined = (text or "").lower()
    topics = []
    for kw, topic in TOPIC_KEYWORDS.items():
        if kw in combined and topic not in topics:
            topics.append(topic)
    return topics


def backfill_one(entry: dict[str, Any]) -> dict[str, Any]:
    retry_count = int(entry.get("retry_count", 0)) + 1
    if not neo4j_is_ready():
        return append_ledger_event({
            **entry,
            "retry_count": retry_count,
            "needs_backfill": True,
            "neo4j_ok": False,
            "last_error": "neo4j_not_ready",
        })

    session_id = entry.get("session_id")
    sqlite_row = fetch_sqlite_event(session_id)
    if not sqlite_row:
        return append_ledger_event({
            **entry,
            "retry_count": retry_count,
            "needs_backfill": True,
            "neo4j_ok": False,
            "last_error": "sqlite_source_missing",
        })

    full_text = _clean_text(sqlite_row.get("text", ""))
    summary = entry.get("summary") or full_text[:160]
    topics = entry.get("topics") or derive_topics(full_text)
    entities = entry.get("entities") or extract_entities([
        {"role": "assistant", "text": full_text, "timestamp": entry.get("first_ts") or entry.get("created_at")}
    ], full_text)
    ok = neo4j_write(
        session_id=session_id,
        summary=summary,
        full_text=full_text,
        channel=entry.get("channel") or sqlite_row.get("source") or "runtime",
        topics=topics,
        entities=entities,
        first_ts=entry.get("first_ts") or entry.get("created_at"),
        last_ts=entry.get("last_ts") or entry.get("updated_at"),
        msg_count=int(entry.get("msg_count") or 1),
    )
    if ok:
        return append_ledger_event({
            **entry,
            "topics": topics,
            "entities": entities,
            "retry_count": retry_count,
            "neo4j_ok": True,
            "needs_backfill": False,
            "last_error": None,
        })
    return append_ledger_event({
        **entry,
        "topics": topics,
        "entities": entities,
        "retry_count": retry_count,
        "neo4j_ok": False,
        "needs_backfill": True,
        "last_error": "neo4j_backfill_failed",
    })


def run_backfill(limit: int | None = None) -> dict[str, Any]:
    pending = pending_ledger_entries(limit=limit)
    result = {
        "neo4j_ready": neo4j_is_ready(),
        "scanned": len(pending),
        "backfilled": 0,
        "failed": 0,
        "details": [],
    }
    if not result["neo4j_ready"]:
        result["error"] = "neo4j_not_ready"
        return result
    for entry in pending:
        updated = backfill_one(entry)
        detail = {
            "event_id": updated.get("event_id"),
            "session_id": updated.get("session_id"),
            "neo4j_ok": updated.get("neo4j_ok"),
            "needs_backfill": updated.get("needs_backfill"),
            "retry_count": updated.get("retry_count", 0),
            "last_error": updated.get("last_error"),
        }
        result["details"].append(detail)
        if updated.get("neo4j_ok") and not updated.get("needs_backfill"):
            result["backfilled"] += 1
        else:
            result["failed"] += 1
    return result


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(sync_status_report(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "backfill":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(run_backfill(limit=limit), ensure_ascii=False, indent=2))
        return 0
    print("Usage: sync_backfill.py [status|backfill [limit]]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
