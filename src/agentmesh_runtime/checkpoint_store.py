#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.getenv("ARS_STATE_DIR", str(ROOT / "state")))
CHECKPOINT_DIR = STATE_DIR / "checkpoints"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_checkpoint_dir() -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def checkpoint_path(goal_id: str, loop_id: str | None = None) -> Path:
    safe_goal = goal_id.replace("/", "_")
    safe_loop = (loop_id or "current").replace("/", "_")
    return CHECKPOINT_DIR / f"{safe_goal}__{safe_loop}.json"


def save_checkpoint(payload: dict[str, Any]) -> str:
    ensure_checkpoint_dir()
    body = dict(payload)
    body.setdefault("updated_at", now_iso())
    path = checkpoint_path(body["goal_id"], body.get("loop_id"))
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_checkpoint(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_checkpoints(include_done: bool = True) -> list[dict[str, Any]]:
    if not CHECKPOINT_DIR.exists():
        return []
    rows = []
    for p in sorted(CHECKPOINT_DIR.glob("*.json")):
        row = load_checkpoint(p)
        if not row:
            continue
        row["_path"] = str(p)
        if not include_done and row.get("status") == "done":
            continue
        rows.append(row)
    rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return rows


def list_open_checkpoints() -> list[dict[str, Any]]:
    return [r for r in list_checkpoints(include_done=True) if r.get("status") in {"active", "blocked", "waiting_human", "initialized"}]


def checkpoint_summary() -> dict[str, Any]:
    rows = list_checkpoints(include_done=True)
    open_rows = [r for r in rows if r.get("status") in {"active", "blocked", "waiting_human", "initialized"}]
    return {
        "checkpoint_dir": str(CHECKPOINT_DIR),
        "checkpoint_count": len(rows),
        "open_checkpoint_count": len(open_rows),
        "open_sample": [
            {
                "goal_id": r.get("goal_id"),
                "loop_id": r.get("loop_id"),
                "status": r.get("status"),
                "next_step": r.get("next_step"),
            }
            for r in open_rows[:5]
        ],
    }
