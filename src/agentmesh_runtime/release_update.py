"""Fail-open update checks for the fully local AgentMesh Runtime CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .config import ensure_runtime_state_dir


DEFAULT_VERSION_URL = (
    "https://raw.githubusercontent.com/jiyangnan/AgentMesh-Runtime/main/pyproject.toml"
)
REPOSITORY_URL = "https://github.com/jiyangnan/AgentMesh-Runtime"
CACHE_TTL_SECONDS = 5 * 60
STALE_CACHE_SECONDS = 7 * 24 * 60 * 60


def cache_path() -> Path:
    return ensure_runtime_state_dir() / "update-check.json"


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"invalid stable semantic version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _project_version(pyproject_text: str) -> str:
    in_project = False
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project:
            match = re.fullmatch(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
            if match:
                value = match.group(1)
                _version(value)
                return value
    raise ValueError("project.version not found")


def _is_runtime_project(pyproject_text: str) -> bool:
    in_project = False
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project and re.fullmatch(
            r'name\s*=\s*["\']agentmesh-runtime["\']', stripped
        ):
            return True
    return False


def _load_cache() -> dict[str, Any] | None:
    try:
        payload = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(
        payload.get("latest_version"), str
    ):
        return None
    try:
        _version(payload["latest_version"])
        float(payload.get("fetched_at", 0))
    except (TypeError, ValueError):
        return None
    return payload


def _save_cache(latest_version: str) -> None:
    path = cache_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"fetched_at": time.time(), "latest_version": latest_version},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def fetch_latest_version(*, force: bool = False) -> tuple[str | None, str]:
    cached = _load_cache()
    now = time.time()
    if cached and not force and now - float(cached["fetched_at"]) < CACHE_TTL_SECONDS:
        return str(cached["latest_version"]), "cache"

    request = urllib.request.Request(
        os.getenv("AGENTMESH_RUNTIME_UPDATE_URL", DEFAULT_VERSION_URL),
        headers={
            "Accept": "text/plain",
            "User-Agent": f"agentmesh-runtime/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            latest = _project_version(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        ValueError,
        urllib.error.URLError,
    ):
        if cached and now - float(cached["fetched_at"]) <= STALE_CACHE_SECONDS:
            return str(cached["latest_version"]), "stale-cache"
        return None, "unavailable"
    _save_cache(latest)
    return latest, "network"


def _source_checkout() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    root = Path(result.stdout.strip())
    try:
        pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    return root if _is_runtime_project(pyproject_text) else None


def upgrade_commands() -> list[str]:
    checkout = _source_checkout()
    if checkout:
        quoted = f'"{checkout}"'
        return [
            f"git -C {quoted} pull --ff-only",
            f"cd {quoted} && uv sync",
        ]
    return [f'"{sys.executable}" -m pip install --upgrade "git+{REPOSITORY_URL}.git"']


def check_for_update(
    *, force: bool = False, current_version: str | None = None
) -> dict[str, Any]:
    current = current_version or __version__
    latest, source = fetch_latest_version(force=force)
    if latest is None:
        return {
            "status": "unavailable",
            "current_version": current,
            "source": source,
            "message": "Update check unavailable; local commands remain fully usable.",
        }
    status = "update_available" if _version(latest) > _version(current) else "current"
    result: dict[str, Any] = {
        "status": status,
        "current_version": current,
        "latest_version": latest,
        "source": source,
        "release_url": REPOSITORY_URL,
    }
    if status == "update_available":
        result["upgrade_commands"] = upgrade_commands()
        result["next_suggested"] = result["upgrade_commands"][0]
    return result


def maybe_print_update_notice() -> None:
    if os.getenv("AGENTMESH_RUNTIME_SKIP_UPDATE") == "1":
        return
    try:
        result = check_for_update()
    except Exception:
        return
    if result.get("status") != "update_available":
        return
    print(
        f"AgentMesh Runtime {result['latest_version']} is available "
        f"(current {result['current_version']}).",
        file=sys.stderr,
    )
    for command in result.get("upgrade_commands", []):
        print(f"  {command}", file=sys.stderr)
