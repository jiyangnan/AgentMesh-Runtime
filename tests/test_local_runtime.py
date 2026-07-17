from __future__ import annotations

import json
import socket
import stat


def test_empty_sqlite_database_is_initialized_and_searchable(
    tmp_path, monkeypatch
) -> None:
    from agentmesh_runtime import episode_ingest, sync_state, unified_memory_recall
    from agentmesh_runtime.sqlite_store import connect_memory_db

    database = tmp_path / "memory" / "main.sqlite"
    state = tmp_path / "state"
    monkeypatch.setattr(episode_ingest, "MEMORY_DB", str(database))
    monkeypatch.setattr(sync_state, "STATE_DIR", state)
    monkeypatch.setattr(sync_state, "LEDGER_PATH", state / "sync-ledger.jsonl")
    monkeypatch.setattr(sync_state, "neo4j_is_ready", lambda timeout=2.0: False)
    monkeypatch.setattr(episode_ingest, "neo4j_write", lambda *args, **kwargs: False)

    conn = connect_memory_db(database)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    conn.close()
    assert {"chunks", "files", "chunks_fts", "agentmesh_runtime_meta"} <= tables
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700

    result = episode_ingest.ingest_event(
        "standalone-1",
        "Standalone memory",
        "AgentMesh Runtime standalone SQLite recall works",
        channel="test",
    )
    assert result["sqlite_ok"] is True
    assert result["neo4j_ok"] is False
    assert result["ledger"]["needs_backfill"] is True
    assert result["ledger"]["retry_count"] == 0

    monkeypatch.setattr(unified_memory_recall, "SQLITE_DB", str(database))
    hits = unified_memory_recall.recall_sqlite("standalone SQLite", top_k=5)
    assert hits
    assert hits[0].location == "episode:standalone-1"

    health = sync_state.sync_status_report()
    assert health["pending_backfill"] == 1
    assert health["backfill_needed"] is True
    assert health["healthy"] is False


def test_primary_sqlite_failure_is_reported_unhealthy(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import sync_state

    state = tmp_path / "state"
    monkeypatch.setattr(sync_state, "STATE_DIR", state)
    monkeypatch.setattr(sync_state, "LEDGER_PATH", state / "sync-ledger.jsonl")
    monkeypatch.setattr(sync_state, "neo4j_is_ready", lambda timeout=2.0: False)
    sync_state.append_ledger_event(
        {
            "event_id": "failed-primary",
            "session_id": "failed-primary",
            "sqlite_ok": False,
            "neo4j_ok": False,
            "needs_backfill": False,
            "last_error": "sqlite_write_failed",
        }
    )

    health = sync_state.sync_status_report()
    assert health["primary_write_failures"] == 1
    assert health["healthy"] is False
    assert "SQLite" in health["recommended_action"]


def test_doctor_initializes_user_state_before_reporting(
    tmp_path, monkeypatch, capsys
) -> None:
    from agentmesh_runtime import checkpoint_store, cli, sync_state

    state = tmp_path / "state"
    memory = tmp_path / "memory.sqlite"
    monkeypatch.setattr(cli, "state_dir", lambda: state)
    monkeypatch.setattr(cli, "memory_db_path", lambda: memory)
    monkeypatch.setattr(
        cli,
        "ensure_runtime_state_dir",
        lambda: state.mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(checkpoint_store, "STATE_DIR", state)
    monkeypatch.setattr(checkpoint_store, "CHECKPOINT_DIR", state / "checkpoints")
    monkeypatch.setattr(checkpoint_store, "ensure_runtime_state_dir", lambda: state)
    monkeypatch.setattr(sync_state, "STATE_DIR", state)
    monkeypatch.setattr(sync_state, "LEDGER_PATH", state / "sync-ledger.jsonl")
    monkeypatch.setattr(sync_state, "ensure_runtime_state_dir", lambda: state)
    monkeypatch.setattr(sync_state, "neo4j_is_ready", lambda timeout=2.0: False)

    def unavailable(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(socket, "create_connection", unavailable)
    assert cli.cmd_doctor(None) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["state_dir"] == "ok"
    assert report["checks"]["sqlite"].startswith("ok:")


def test_no_neo4j_disables_every_graph_recall_path(monkeypatch) -> None:
    from agentmesh_runtime import unified_memory_recall as recall_module

    def unexpected(*args, **kwargs):
        raise AssertionError("Neo4j path should not be called")

    monkeypatch.setattr(recall_module, "recall_neo4j", unexpected)
    monkeypatch.setattr(recall_module, "recall_neo4j_concepts", unexpected)
    monkeypatch.setattr(recall_module, "recall_neo4j_rules", unexpected)
    monkeypatch.setattr(recall_module, "recall_journal_episodes", unexpected)

    hits = recall_module.recall(
        "offline",
        use_neo4j=False,
        use_sqlite=False,
        use_files=False,
        use_vector=False,
    )
    assert hits == []


def test_checkpoint_contains_complete_resumable_state(tmp_path, monkeypatch) -> None:
    from agentmesh_runtime import checkpoint_store
    from agentmesh_runtime.autonomous_loop import AutonomousLoop, GoalFrame, LoopState

    monkeypatch.setattr(checkpoint_store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(checkpoint_store, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    goal = GoalFrame(
        goal_id="resume-test",
        name="Resume test",
        goal="Persist all loop state",
        success_criteria=["checkpoint can resume"],
        constraints=[],
    )
    state = LoopState(
        loop_id="loop-1",
        goal_id=goal.goal_id,
        status="waiting_human",
        iteration=2,
        last_observation="observed evidence",
        verification_plan=["check evidence"],
        consecutive_failures=1,
    )
    loop = AutonomousLoop(goal, state=state)
    loop._save_checkpoint()

    path = checkpoint_store.checkpoint_path(goal.goal_id, state.loop_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["checkpoint_schema_version"] == 2
    assert payload["goal_frame"]["goal"] == goal.goal
    assert payload["loop_state"]["iteration"] == 2
    assert payload["loop_state"]["last_observation"] == "observed evidence"

    resumed = AutonomousLoop.from_checkpoint(str(path))
    assert resumed.goal.goal_id == goal.goal_id
    assert resumed.state.verification_plan == ["check evidence"]
    resumed.resume()
    assert resumed.state.status == "active"


def test_default_policy_never_claims_simulated_action_succeeded(
    tmp_path, monkeypatch
) -> None:
    from agentmesh_runtime.autonomous_loop import (
        AutonomousLoop,
        GoalFrame,
        HAMemoryAdapter,
        IntegratedPolicy,
    )

    class Memory(HAMemoryAdapter):
        def recall(self, query: str) -> list[dict]:
            return []

        def record(self, item: dict) -> dict:
            return {"recorded": True}

    goal = GoalFrame(
        goal_id="fail-closed",
        name="Fail closed",
        goal="Require a real external executor",
        success_criteria=["real evidence exists"],
        constraints=[],
    )
    monkeypatch.setattr(
        "agentmesh_runtime.autonomous_loop.save_checkpoint",
        lambda payload: str(tmp_path / "checkpoint.json"),
    )
    loop = AutonomousLoop(goal, policy=IntegratedPolicy(memory=Memory()))
    result = loop.run()
    assert result.status == "waiting_human"
    assert result.verification_result == "unknown"
    assert result.needs_human_input is True
    assert "external executor required" in result.blockers[0]


def test_legacy_package_state_migration_skips_bundled_demo(
    tmp_path, monkeypatch
) -> None:
    from agentmesh_runtime import config

    legacy = tmp_path / "legacy"
    destination = tmp_path / "destination"
    (legacy / "checkpoints").mkdir(parents=True)
    (legacy / "checkpoints" / "demo.json").write_text(
        json.dumps({"goal_id": "ars-demo-001"}), encoding="utf-8"
    )
    (legacy / "checkpoints" / "real.json").write_text(
        json.dumps({"goal_id": "real-goal"}), encoding="utf-8"
    )
    (legacy / "sync-ledger.jsonl").write_text(
        json.dumps({"event_id": "demo", "summary": "Loop ars-demo-001 iteration 1"})
        + "\n"
        + json.dumps({"event_id": "real", "summary": "User event"})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "state_dir", lambda: destination)
    monkeypatch.setattr(config, "_legacy_package_state_dir", lambda: legacy)

    config.ensure_runtime_state_dir()
    assert not (destination / "checkpoints" / "demo.json").exists()
    assert (destination / "checkpoints" / "real.json").exists()
    ledger = (destination / "sync-ledger.jsonl").read_text(encoding="utf-8")
    assert '"event_id": "real"' in ledger
    assert '"event_id": "demo"' not in ledger
