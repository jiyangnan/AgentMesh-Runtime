from __future__ import annotations

import json
import subprocess
import time
import urllib.error


class FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body


def test_update_check_detects_newer_public_version(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import release_update

    cache = tmp_path / "update-check.json"
    monkeypatch.setattr(release_update, "cache_path", lambda: cache)
    monkeypatch.setattr(
        release_update.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            '[project]\nname = "agentmesh-runtime"\nversion = "0.2.0"\n'
        ),
    )
    monkeypatch.setattr(
        release_update, "upgrade_commands", lambda: ["git pull --ff-only", "uv sync"]
    )

    result = release_update.check_for_update(force=True, current_version="0.1.1")
    assert result["status"] == "update_available"
    assert result["latest_version"] == "0.2.0"
    assert result["next_suggested"] == "git pull --ff-only"
    assert json.loads(cache.read_text(encoding="utf-8"))["latest_version"] == "0.2.0"


def test_update_check_failure_never_blocks_local_cli(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import release_update

    monkeypatch.setattr(release_update, "cache_path", lambda: tmp_path / "missing.json")

    def unavailable(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(release_update.urllib.request, "urlopen", unavailable)
    result = release_update.check_for_update(force=True, current_version="0.1.1")
    assert result["status"] == "unavailable"
    assert "fully usable" in result["message"]


def test_automatic_check_uses_five_minute_cache(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import release_update

    cache = tmp_path / "update-check.json"
    cache.write_text(
        json.dumps({"fetched_at": time.time(), "latest_version": "0.1.1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(release_update, "cache_path", lambda: cache)

    def unexpected(request, timeout):
        raise AssertionError("fresh cache should avoid the network")

    monkeypatch.setattr(release_update.urllib.request, "urlopen", unexpected)
    latest, source = release_update.fetch_latest_version()
    assert latest == "0.1.1"
    assert source == "cache"


def test_corrupt_update_cache_is_ignored(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import release_update

    cache = tmp_path / "update-check.json"
    cache.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(release_update, "cache_path", lambda: cache)
    monkeypatch.setattr(
        release_update.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse('[project]\nversion = "0.1.1"\n'),
    )
    result = release_update.check_for_update(force=False, current_version="0.1.1")
    assert result["status"] == "current"
    assert result["source"] == "network"


def test_update_never_pulls_an_unrelated_enclosing_checkout(
    tmp_path, monkeypatch
) -> None:
    from agentmesh_runtime import release_update

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "consumer-app"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        release_update.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=str(tmp_path), stderr=""
        ),
    )
    assert release_update._source_checkout() is None
    command = release_update.upgrade_commands()[0]
    assert "AgentMesh-Runtime.git" in command
    assert str(tmp_path) not in command
