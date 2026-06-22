# Changelog

## 0.1.0 — Unreleased

First public release as **AgentMesh Runtime** — a productized fork of the internal `agent-reinforcement-system` runtime that originally lived inside the author's OpenClaw agent.

### Why it exists
This release does not add new runtime capabilities. It strips the previous codebase of operator-specific identifiers, generalizes hard-coded paths, aligns the toolchain with the rest of the AgentMesh ecosystem, and reframes the public surface as honest scaffolding — not a "runtime AI."

### Changed (breaking vs. internal predecessor)
- **Repo**: forked snapshot of `agent-reinforcement-system @ 5081a98`; no upstream coupling. Future iteration happens here.
- **License**: MIT → **Apache 2.0**.
- **Package**: flat `src/*.py` modules → proper `src/agentmesh_runtime/` package with relative imports.
- **Build / toolchain**: `pip + setuptools + requirements.txt` → **`uv + hatchling`** with locked `uv.lock`.
- **CLI**: `xng` → **`agentmesh-runtime`** (primary) + **`amr`** (short alias). `xng` is preserved as a deprecated alias for one release.
- **Sanitization**: removed hard-coded operator entities (people, projects, agent rosters), per-episode downweighting hacks, and brand-specific DNS bypass defaults. The DoH fallback in `vector_store.py` now only activates when `AGENTMESH_RUNTIME_DOH_BYPASS=1` is set explicitly.
- **Agent roster**: previously hard-coded `["main", "growth", "invest"]` → auto-discovery of `<SESSION_BASE>/<agent>/sessions/` subdirectories.

### Marketing / framing
- Removed the "first-principles runtime" claim from headline messaging — the code did not implement a runtime distinct from the system prompt template, so the claim was unhonest.
- OODA loop is now framed as **scaffolding** — the `decide()` and `verify()` steps are intentionally minimal stubs, and the README + AGENTS.md say so explicitly. Real reasoning is expected to come from the caller agent.

### Not in this release
- No hosted service.
- No multi-tenant Server, no credit/billing, no LLM-backed decision/verify layer. See `docs/decisions/2026-06-21-final-direction.md` for why this was a deliberate scope cut.

### Cross-agent decision record
The discovery and disagreement process that produced this product shape is preserved in [`docs/decisions/`](docs/decisions/README.md), including Codex's two analyses and Claude Code's facts-based synthesis.
