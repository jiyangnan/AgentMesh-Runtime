"""
Smoke tests — fast, no external services required.

These are intentionally tiny. They protect against three regressions:

1. Package wiring (relative imports) breaking.
2. Recall scoring weights silently changing.
3. CLI entry point disappearing.

Anything that needs Neo4j / SQLite data / Gemini lives elsewhere.
"""
from __future__ import annotations


def test_package_imports() -> None:
    """All twelve modules import without side effects raising."""
    from agentmesh_runtime import (
        autonomous_loop,
        checkpoint_store,
        cli,
        episode_ingest,
        journal_to_episode,
        kb_to_graph,
        neo4j_recall,
        startup_rehydrate,
        sync_backfill,
        sync_state,
        unified_memory_recall,
        vector_store,
    )

    modules = [
        autonomous_loop, checkpoint_store, cli, episode_ingest,
        journal_to_episode, kb_to_graph, neo4j_recall,
        startup_rehydrate, sync_backfill, sync_state,
        unified_memory_recall, vector_store,
    ]
    assert len(modules) == 12


def test_recall_scoring_weights_locked() -> None:
    """If you change a backend weight on purpose, update this test.

    The point is to make accidental weight drift loud — recall ranking
    quality depends on these and they're easy to nudge by mistake.
    """
    from agentmesh_runtime.unified_memory_recall import BACKEND_WEIGHTS

    assert BACKEND_WEIGHTS == {
        "neo4j": 1.0,
        "vector": 1.5,
        "sqlite_fts": 0.6,
        "ripgrep": 0.3,
    }


def test_cli_main_callable() -> None:
    """The CLI entry point exists and is callable."""
    from agentmesh_runtime.cli import main

    assert callable(main)


def test_score_text_match_is_deterministic_and_positive() -> None:
    """score_text_match is the heart of recall ranking; make sure it
    still returns something positive on an obvious match.
    """
    from agentmesh_runtime.unified_memory_recall import (
        score_text_match,
        tokenize,
    )

    query = "Neo4j memory recall"
    tokens = tokenize(query)
    summary = "An overview of Neo4j memory recall and how it ranks hits."
    text = "Neo4j memory recall combines graph and text signals."

    score = score_text_match(query, tokens, summary, text)
    assert score > 0
    assert score_text_match(query, tokens, summary, text) == score


def test_localized_pages_use_the_runtime_product_mark_as_favicon() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    favicon = (root / "site/favicon.svg").read_text()

    assert "#2E5BCE" in favicon
    assert "AgentMesh Runtime" in favicon
    for relative in ("index.html", "en/index.html", "ja/index.html", "ko/index.html"):
        page = (root / "site" / relative).read_text()
        assert (
            '<link rel="icon" type="image/svg+xml" '
            'href="/favicon.svg?v=product-mark-v1" />'
        ) in page
        assert "data:image/svg+xml" not in page
