#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from checkpoint_store import list_checkpoints, list_open_checkpoints
from sync_state import STATE_DIR, sync_status_report
from unified_memory_recall import recall

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHYDRATE_PATH = Path(STATE_DIR) / "rehydrate-snapshot.json"
DEFAULT_BOOTSTRAP_PATH = Path(STATE_DIR) / "startup-context.txt"


def collect_recent_repo_changes(limit: int = 5) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    try:
        out = subprocess.run(["git", "log", "--oneline", f"-{limit}"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split(" ", 1)
            changes.append({"commit": parts[0], "title": parts[1] if len(parts) > 1 else ""})
    except Exception:
        return []
    return changes


def collect_recent_memory_hits(open_checkpoints: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    queries = []
    for cp in open_checkpoints[:3]:
        q = " ".join(filter(None, [cp.get("goal_id"), cp.get("title"), cp.get("next_step"), cp.get("latest_decision")]))
        if q.strip():
            queries.append(q.strip())
    if not queries:
        return []
    seen = set()
    hits_out = []
    for q in queries:
        try:
            hits = recall(q, top_k=top_k)
        except Exception:
            hits = []
        for h in hits:
            if h.location in seen:
                continue
            seen.add(h.location)
            hits_out.append({
                "backend": h.backend,
                "location": h.location,
                "title": h.title,
                "snippet": h.snippet,
                "score": h.score,
            })
            if len(hits_out) >= top_k:
                return hits_out
    return hits_out


def build_rehydrate_snapshot() -> dict[str, Any]:
    open_checkpoints = list_open_checkpoints()
    all_checkpoints = list_checkpoints(include_done=True)
    memory_hits = collect_recent_memory_hits(open_checkpoints)
    repo_changes = collect_recent_repo_changes()
    sync = sync_status_report()
    suggested = None
    if sync.get("backfill_needed"):
        suggested = "Run xng sync backfill before relying on graph recall."
    elif open_checkpoints:
        cp = open_checkpoints[0]
        suggested = cp.get("next_step") or cp.get("next_iteration_hint") or cp.get("latest_decision")
    elif all_checkpoints:
        suggested = "No open checkpoints. Review the most recent completed checkpoint and choose the next goal."
    else:
        suggested = "No checkpoints found. Start a goal or ingest recent sessions first."
    return {
        "active_goals": [
            {
                "goal_id": cp.get("goal_id"),
                "title": cp.get("title"),
                "status": cp.get("status"),
                "current_phase": cp.get("current_phase"),
                "next_step": cp.get("next_step"),
                "blockers": cp.get("blockers", []),
                "updated_at": cp.get("updated_at"),
            }
            for cp in open_checkpoints
        ],
        "recent_checkpoints": [
            {
                "goal_id": cp.get("goal_id"),
                "loop_id": cp.get("loop_id"),
                "title": cp.get("title"),
                "status": cp.get("status"),
                "current_phase": cp.get("current_phase"),
                "next_step": cp.get("next_step"),
                "updated_at": cp.get("updated_at"),
            }
            for cp in all_checkpoints[:5]
        ],
        "open_loops": [
            {
                "loop_id": cp.get("loop_id"),
                "goal_id": cp.get("goal_id"),
                "status": cp.get("status"),
                "next_iteration_hint": cp.get("next_iteration_hint"),
            }
            for cp in open_checkpoints
        ],
        "recent_memory_hits": memory_hits,
        "recent_repo_changes": repo_changes,
        "sync_health": sync,
        "suggested_next_focus": suggested,
    }


def render_bootstrap_text(snapshot: dict[str, Any]) -> str:
    lines = ["Startup Rehydrate Snapshot", ""]
    sync = snapshot.get("sync_health", {})
    if sync.get("backfill_needed"):
        lines.append(f"- Sync warning: pending_backfill={sync.get('pending_backfill')} (run xng sync backfill)")
    else:
        lines.append("- Sync health: no pending backfill")

    active = snapshot.get("active_goals", [])
    if active:
        lines.append("- Active goals:")
        for goal in active[:3]:
            lines.append(f"  - {goal.get('goal_id')}: {goal.get('title')} | status={goal.get('status')} | next={goal.get('next_step')}")
    else:
        lines.append("- Active goals: none")

    recent = snapshot.get("recent_checkpoints", [])
    if recent:
        lines.append("- Recent checkpoints:")
        for cp in recent[:3]:
            lines.append(f"  - {cp.get('goal_id')} / {cp.get('status')} / phase={cp.get('current_phase')} / next={cp.get('next_step')}")

    memory_hits = snapshot.get("recent_memory_hits", [])
    if memory_hits:
        lines.append("- Relevant memory hits:")
        for hit in memory_hits[:3]:
            lines.append(f"  - [{hit.get('backend')}] {hit.get('title')} @ {hit.get('location')}")

    repo_changes = snapshot.get("recent_repo_changes", [])
    if repo_changes:
        lines.append("- Recent repo changes:")
        for item in repo_changes[:3]:
            lines.append(f"  - {item.get('commit')}: {item.get('title')}")

    lines.append("")
    lines.append(f"Suggested next focus: {snapshot.get('suggested_next_focus')}")
    return "\n".join(lines).strip() + "\n"


def default_output_path(fmt: str) -> Path:
    return DEFAULT_REHYDRATE_PATH if fmt == "json" else DEFAULT_BOOTSTRAP_PATH


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a startup recovery snapshot")
    ap.add_argument("--format", choices=["json", "bootstrap"], default="json")
    ap.add_argument("--out", help="write output to a file instead of stdout")
    ap.add_argument("--write-default", action="store_true", help="write to the standard startup recovery path for this format")
    ap.add_argument("--print-path", action="store_true", help="print the resolved output path after writing")
    args = ap.parse_args()

    snapshot = build_rehydrate_snapshot()
    rendered = json.dumps(snapshot, ensure_ascii=False, indent=2) if args.format == "json" else render_bootstrap_text(snapshot)

    out_path = None
    if args.out:
        out_path = Path(args.out)
    elif args.write_default:
        out_path = default_output_path(args.format)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")
        if args.print_path:
            print(str(out_path))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
