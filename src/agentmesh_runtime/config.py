"""Local-first configuration and filesystem locations.

The public runtime must remain usable without OpenClaw and must never write
state into the installed Python package.  New ``AGENTMESH_RUNTIME_*`` names
are preferred; the historical ``ARS_*`` variables remain supported.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _env_path(primary: str, legacy: str | None = None) -> Path | None:
    value = os.getenv(primary) or (os.getenv(legacy) if legacy else None)
    return Path(value).expanduser() if value else None


def runtime_home() -> Path:
    return _env_path("AGENTMESH_RUNTIME_HOME") or Path.home() / ".agentmesh" / "runtime"


def state_dir() -> Path:
    return (
        _env_path("AGENTMESH_RUNTIME_STATE_DIR", "ARS_STATE_DIR")
        or runtime_home() / "state"
    )


def memory_db_path() -> Path:
    configured = _env_path("AGENTMESH_RUNTIME_MEMORY_DB", "ARS_MEMORY_DB")
    if configured:
        return configured
    legacy = Path.home() / ".openclaw" / "memory" / "main.sqlite"
    return legacy if legacy.exists() else runtime_home() / "memory.sqlite"


def vector_db_path() -> Path:
    return _env_path("AGENTMESH_RUNTIME_VECTOR_DB") or runtime_home() / "vectors.sqlite"


def workspace_path() -> Path:
    configured = _env_path("AGENTMESH_RUNTIME_WORKSPACE", "ARS_WORKSPACE")
    if configured:
        return configured
    legacy = Path.home() / ".openclaw" / "workspace"
    return legacy if legacy.exists() else Path.cwd()


def session_base_path() -> Path:
    configured = _env_path("AGENTMESH_RUNTIME_SESSION_BASE", "ARS_SESSION_BASE")
    if configured:
        return configured
    legacy = Path.home() / ".openclaw" / "agents"
    return legacy if legacy.exists() else runtime_home() / "agents"


def neo4j_uri() -> str:
    return os.getenv("AGENTMESH_RUNTIME_NEO4J_URI") or os.getenv(
        "ARS_NEO4J_URI", "bolt://localhost:7687"
    )


def neo4j_user() -> str:
    return os.getenv("AGENTMESH_RUNTIME_NEO4J_USER") or os.getenv(
        "ARS_NEO4J_USER", "neo4j"
    )


def neo4j_password() -> str:
    return os.getenv("AGENTMESH_RUNTIME_NEO4J_PASSWORD") or os.getenv(
        "ARS_NEO4J_PASSWORD", "password"
    )


def _legacy_package_state_dir() -> Path:
    # Before 0.1.1, parent.parent resolved to ``src/`` and runtime data was
    # accidentally written under ``src/state`` (or site-packages/state).
    return Path(__file__).resolve().parent.parent / "state"


def _is_bundled_demo_checkpoint(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("goal_id") == "ars-demo-001"


def _copy_legacy_ledger(source: Path, destination: Path) -> int:
    copied = 0
    lines: list[str] = []
    try:
        raw_lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in raw_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)
            copied += 1
            continue
        if str(payload.get("summary", "")).startswith("Loop ars-demo-001"):
            continue
        lines.append(json.dumps(payload, ensure_ascii=False))
        copied += 1
    if lines and not destination.exists():
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        destination.chmod(0o600)
    return copied


def ensure_runtime_state_dir() -> Path:
    """Create the user-owned state directory and migrate genuine old state.

    The demo artifacts that were accidentally committed in 0.1.0 are skipped;
    user-created checkpoints and ledger entries are preserved.  Migration is
    idempotent because existing destination files are never overwritten.
    """

    destination = state_dir()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        destination.chmod(0o700)
    except OSError:
        pass

    marker = destination / ".package-state-migration-v1"
    legacy = _legacy_package_state_dir()
    if (
        marker.exists()
        or not legacy.exists()
        or legacy.resolve() == destination.resolve()
    ):
        return destination

    checkpoints = destination / "checkpoints"
    source_checkpoints = legacy / "checkpoints"
    if source_checkpoints.exists():
        checkpoints.mkdir(parents=True, exist_ok=True)
        for source in source_checkpoints.glob("*.json"):
            if _is_bundled_demo_checkpoint(source):
                continue
            target = checkpoints / source.name
            if not target.exists():
                shutil.copy2(source, target)

    _copy_legacy_ledger(legacy / "sync-ledger.jsonl", destination / "sync-ledger.jsonl")
    marker.write_text("migrated\n", encoding="utf-8")
    return destination
