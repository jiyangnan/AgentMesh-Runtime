#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.getenv("ARS_STATE_DIR", str(ROOT / "state")))
LEDGER_PATH = STATE_DIR / "sync-ledger.jsonl"
NEO4J_URI = os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def append_ledger_event(entry: dict[str, Any]) -> dict[str, Any]:
    ensure_state_dir()
    payload = dict(entry)
    payload.setdefault("created_at", now_iso())
    payload["updated_at"] = now_iso()
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def load_ledger_events() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    rows = []
    with LEDGER_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def latest_ledger_entries() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in load_ledger_events():
        event_id = row.get("event_id")
        if not event_id:
            continue
        latest[event_id] = row
    return latest


def pending_ledger_entries(limit: int | None = None) -> list[dict[str, Any]]:
    rows = [r for r in latest_ledger_entries().values() if r.get("needs_backfill")]
    rows.sort(key=lambda x: x.get("updated_at", ""))
    return rows[:limit] if limit else rows


def parse_neo4j_host_port(uri: str) -> tuple[str, int]:
    rest = uri.split("://", 1)[-1]
    host_port = rest.split("/", 1)[0]
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return host, 7687
    return host_port, 7687


def neo4j_is_ready(timeout: float = 2.0) -> bool:
    host, port = parse_neo4j_host_port(NEO4J_URI)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def sync_status_report(sample: int = 5) -> dict[str, Any]:
    latest = latest_ledger_entries()
    pending = [r for r in latest.values() if r.get("needs_backfill")]
    recent_failures = [
        {
            "event_id": r.get("event_id"),
            "session_id": r.get("session_id"),
            "last_error": r.get("last_error"),
            "retry_count": r.get("retry_count", 0),
        }
        for r in latest.values()
        if r.get("last_error")
    ]
    recent_failures = sorted(recent_failures, key=lambda x: str(x.get("event_id")), reverse=True)[:sample]
    sqlite_success = sum(1 for r in latest.values() if r.get("sqlite_ok"))
    neo4j_success = sum(1 for r in latest.values() if r.get("neo4j_ok"))
    return {
        "ledger_path": str(LEDGER_PATH),
        "ledger_entries": len(latest),
        "pending_backfill": len(pending),
        "neo4j_ready": neo4j_is_ready(),
        "sqlite_success_entries": sqlite_success,
        "neo4j_success_entries": neo4j_success,
        "drift_detected": len(pending) > 0 or neo4j_success < sqlite_success,
        "backfill_needed": len(pending) > 0,
        "recommended_action": "xng sync backfill" if len(pending) > 0 else None,
        "pending_sample": [
            {
                "event_id": r.get("event_id"),
                "session_id": r.get("session_id"),
                "kind": r.get("kind"),
                "retry_count": r.get("retry_count", 0),
            }
            for r in pending[:sample]
        ],
        "recent_failures": recent_failures,
    }
