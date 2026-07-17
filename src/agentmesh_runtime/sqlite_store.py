"""SQLite schema and connection helpers for standalone local memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import memory_db_path


SCHEMA_VERSION = 1


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal OpenClaw-compatible memory and FTS schema."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          id TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'memory',
          start_line INTEGER NOT NULL,
          end_line INTEGER NOT NULL,
          hash TEXT NOT NULL,
          model TEXT NOT NULL,
          text TEXT NOT NULL,
          embedding TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY,
          source TEXT NOT NULL DEFAULT 'memory',
          hash TEXT NOT NULL,
          mtime INTEGER NOT NULL,
          size INTEGER NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          text,
          id UNINDEXED,
          path UNINDEXED,
          source UNINDEXED,
          model UNINDEXED,
          start_line UNINDEXED,
          end_line UNINDEXED
        );

        CREATE TABLE IF NOT EXISTS agentmesh_runtime_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO agentmesh_runtime_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def connect_memory_db(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path).expanduser() if path else memory_db_path()
    parent_existed = target.parent.exists()
    database_existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        try:
            target.parent.chmod(0o700)
        except OSError:
            pass
    conn = sqlite3.connect(str(target), timeout=30)
    try:
        if not database_existed:
            try:
                target.chmod(0o600)
            except OSError:
                pass
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        initialize_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn
