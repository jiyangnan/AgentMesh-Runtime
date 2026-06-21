#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


class RichHelpFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def run_py(script: str, args: list[str]) -> int:
    cmd = [sys.executable, str(SRC / script), *args]
    return subprocess.call(cmd, cwd=ROOT)


def cmd_memory(ns: argparse.Namespace) -> int:
    if ns.memory_cmd == "recall":
        args = [ns.query, "--top-k", str(ns.top_k)]
        if ns.json:
            args.append("--json")
        if ns.no_neo4j:
            args.append("--no-neo4j")
        if ns.no_sqlite:
            args.append("--no-sqlite")
        if ns.no_files:
            args.append("--no-files")
        return run_py("unified_memory_recall.py", args)
    if ns.memory_cmd == "ingest-file":
        return run_py("episode_ingest.py", ["ingest-file", ns.path, ns.channel])
    if ns.memory_cmd == "ingest-session":
        return run_py("episode_ingest.py", ["ingest", ns.session_id, ns.channel])
    print("unknown memory command", file=sys.stderr)
    return 2


def cmd_loop(ns: argparse.Namespace) -> int:
    args = [ns.goal]
    if ns.state:
        args += ["--state", ns.state]
    if ns.out:
        args += ["--out", ns.out]
    args += ["--mode", ns.loop_cmd]
    return run_py("autonomous_loop.py", args)


def cmd_doctor(_: argparse.Namespace) -> int:
    report = {
        "cwd": str(ROOT),
        "neo4j_uri": os.getenv("ARS_NEO4J_URI", "bolt://localhost:7687"),
        "session_base": os.getenv("ARS_SESSION_BASE", os.path.expanduser("~/.openclaw/agents")),
        "memory_db": os.getenv("ARS_MEMORY_DB", os.path.expanduser("~/.openclaw/memory/main.sqlite")),
        "workspace": os.getenv("ARS_WORKSPACE", str(ROOT)),
        "checks": {},
    }
    import socket, sqlite3
    from sync_state import STATE_DIR, sync_status_report
    from checkpoint_store import checkpoint_summary

    host, port = "localhost", 7687
    try:
        with socket.create_connection((host, port), timeout=2):
            report["checks"]["neo4j_port_7687"] = "ok"
    except Exception as e:
        report["checks"]["neo4j_port_7687"] = f"fail: {e}"
    db = Path(report["memory_db"]).expanduser()
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            cur.execute("select count(*) from sqlite_master where type='table'")
            report["checks"]["sqlite"] = f"ok: {cur.fetchone()[0]} tables"
            conn.close()
        except Exception as e:
            report["checks"]["sqlite"] = f"fail: {e}"
    else:
        report["checks"]["sqlite"] = "missing"
    report["checks"]["state_dir"] = "ok" if Path(STATE_DIR).exists() else "missing"
    report["memory_health"] = sync_status_report()
    report["checkpoint_health"] = checkpoint_summary()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_sync(ns: argparse.Namespace) -> int:
    if ns.sync_cmd == "status":
        return run_py("sync_backfill.py", ["status"])
    if ns.sync_cmd == "backfill":
        args = ["backfill"]
        if ns.limit is not None:
            args.append(str(ns.limit))
        return run_py("sync_backfill.py", args)
    print("unknown sync command", file=sys.stderr)
    return 2


def cmd_rehydrate(ns: argparse.Namespace) -> int:
    args = ["--format", ns.format]
    if ns.out:
        args += ["--out", ns.out]
    if ns.write_default:
        args.append("--write-default")
    if ns.print_path:
        args.append("--print-path")
    return run_py("startup_rehydrate.py", args)


def cmd_bootstrap(ns: argparse.Namespace) -> int:
    args = ["--format", "bootstrap"]
    if ns.out:
        args += ["--out", ns.out]
    elif not ns.stdout:
        args.append("--write-default")
        args.append("--print-path")
    if ns.stdout:
        pass
    return run_py("startup_rehydrate.py", args)


def cmd_demo(_: argparse.Namespace) -> int:
    goal = str(ROOT / "examples" / "goal_frame.example.json")
    return run_py("autonomous_loop.py", [goal, "--mode", "run"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xng",
        description="xiaonangua CLI — first-principles reasoning, HA memory, and bounded autonomy.",
        epilog=(
            "Examples:\n"
            "  xng doctor\n"
            "  xng memory recall \"First-Principles-Only\"\n"
            "  xng memory ingest-file /path/to/session.jsonl discord\n"
            "  xng loop run examples/goal_frame.example.json\n"
            "  xng sync status\n"
            "  xng rehydrate --write-default --print-path\n"
            "  xng bootstrap\n"
            "  xng demo"
        ),
        formatter_class=RichHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    m = sub.add_parser(
        "memory",
        help="recall or ingest memory",
        description="Memory operations: recall indexed memory or ingest new session/runtime material.",
        formatter_class=RichHelpFormatter,
    )
    msub = m.add_subparsers(dest="memory_cmd", required=True, metavar="MEMORY_COMMAND")

    mr = msub.add_parser(
        "recall",
        help="search memory across Neo4j / SQLite / files",
        description="Recall memory with automatic backend failover and merged ranking.",
        epilog=(
            "Examples:\n"
            "  xng memory recall \"First-Principles-Only\"\n"
            "  xng memory recall \"ars-demo-001\" --top-k 5\n"
            "  xng memory recall \"neo4j memory\" --json --no-files"
        ),
        formatter_class=RichHelpFormatter,
    )
    mr.add_argument("query", help="query text to search for")
    mr.add_argument("--top-k", type=int, default=8, help="maximum number of hits to return")
    mr.add_argument("--json", action="store_true", help="emit JSON output when supported")
    mr.add_argument("--no-neo4j", action="store_true", help="skip Neo4j recall")
    mr.add_argument("--no-sqlite", action="store_true", help="skip SQLite FTS recall")
    mr.add_argument("--no-files", action="store_true", help="skip raw file/session grep fallback")
    mr.set_defaults(func=cmd_memory)

    mif = msub.add_parser(
        "ingest-file",
        help="ingest a transcript file into the memory index",
        description="Ingest a session transcript JSONL file into SQLite and Neo4j memory backends.",
        epilog="Example:\n  xng memory ingest-file /path/to/session.jsonl discord",
        formatter_class=RichHelpFormatter,
    )
    mif.add_argument("path", help="path to a session transcript file")
    mif.add_argument("channel", nargs="?", default="discord", help="source channel label")
    mif.set_defaults(func=cmd_memory)

    mis = msub.add_parser(
        "ingest-session",
        help="ingest a visible session by id",
        description="Ingest a session by session id using the configured session base directory.",
        epilog="Example:\n  xng memory ingest-session 26e731ba-64b2-4f40-b34f-f58ab8a03987 discord",
        formatter_class=RichHelpFormatter,
    )
    mis.add_argument("session_id", help="session id to ingest")
    mis.add_argument("channel", nargs="?", default="discord", help="source channel label")
    mis.set_defaults(func=cmd_memory)

    l = sub.add_parser(
        "loop",
        help="run the bounded autonomous loop",
        description="Autonomous-Loop operations for goal execution.",
        formatter_class=RichHelpFormatter,
    )
    lsub = l.add_subparsers(dest="loop_cmd", required=True, metavar="LOOP_COMMAND")
    for mode in ("run", "step"):
        lp = lsub.add_parser(
            mode,
            help=f"{mode} a goal frame through the loop",
            description=f"{mode.capitalize()} an autonomous loop from a goal frame JSON file.",
            epilog=(
                f"Examples:\n"
                f"  xng loop {mode} examples/goal_frame.example.json\n"
                f"  xng loop {mode} examples/goal_frame.example.json --out loop_state.json"
            ),
            formatter_class=RichHelpFormatter,
        )
        lp.add_argument("goal", help="path to goal frame JSON")
        lp.add_argument("--state", help="path to an existing loop state JSON")
        lp.add_argument("--out", help="write resulting loop state to this path")
        lp.set_defaults(func=cmd_loop)

    s = sub.add_parser(
        "sync",
        help="inspect or reconcile SQLite → Neo4j sync state",
        description="Sync operations for pending backfill, consistency status, and Neo4j recovery handling.",
        formatter_class=RichHelpFormatter,
    )
    ssub = s.add_subparsers(dest="sync_cmd", required=True, metavar="SYNC_COMMAND")

    ss = ssub.add_parser(
        "status",
        help="show pending backfill and drift status",
        description="Show ledger status, pending backfill count, and whether Neo4j is ready.",
        epilog="Example:\n  xng sync status",
        formatter_class=RichHelpFormatter,
    )
    ss.set_defaults(func=cmd_sync)

    sb = ssub.add_parser(
        "backfill",
        help="replay pending SQLite entries into Neo4j",
        description="Replay pending sync ledger entries into Neo4j after the graph backend recovers.",
        epilog="Examples:\n  xng sync backfill\n  xng sync backfill --limit 10",
        formatter_class=RichHelpFormatter,
    )
    sb.add_argument("--limit", type=int, help="maximum number of pending entries to backfill")
    sb.set_defaults(func=cmd_sync)

    d = sub.add_parser(
        "doctor",
        help="check runtime environment and memory consistency health",
        description="Check environment dependencies plus pending SQLite → Neo4j sync drift and checkpoint state.",
        epilog="Example:\n  xng doctor",
        formatter_class=RichHelpFormatter,
    )
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser(
        "rehydrate",
        help="restore current working state after restart",
        description="Build a startup recovery snapshot from checkpoints, memory recall, repo state, and sync health.",
        epilog="Examples:\n  xng rehydrate\n  xng rehydrate --format bootstrap\n  xng rehydrate --write-default --print-path",
        formatter_class=RichHelpFormatter,
    )
    r.add_argument("--format", choices=["json", "bootstrap"], default="json", help="output format")
    r.add_argument("--out", help="write output to a file")
    r.add_argument("--write-default", action="store_true", help="write to the standard recovery path under state/")
    r.add_argument("--print-path", action="store_true", help="print the resolved output path after writing")
    r.set_defaults(func=cmd_rehydrate)

    b = sub.add_parser(
        "bootstrap",
        help="emit startup-ready text context for a new session",
        description="Render a concise startup context block suitable for injecting into a new session bootstrap flow.",
        epilog="Examples:\n  xng bootstrap\n  xng bootstrap --stdout\n  xng bootstrap --out /tmp/startup-context.txt",
        formatter_class=RichHelpFormatter,
    )
    b.add_argument("--out", help="write bootstrap text to a file")
    b.add_argument("--stdout", action="store_true", help="print bootstrap text instead of writing the standard startup file")
    b.set_defaults(func=cmd_bootstrap)

    demo = sub.add_parser(
        "demo",
        help="run the bundled integrated demo",
        description="Run the bundled goal frame demo that exercises memory recall and the autonomy loop.",
        epilog="Example:\n  xng demo",
        formatter_class=RichHelpFormatter,
    )
    demo.set_defaults(func=cmd_demo)
    return p


def main() -> int:
    parser = build_parser()
    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
