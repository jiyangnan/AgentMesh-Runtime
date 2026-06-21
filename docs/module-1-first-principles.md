# Module 1 — First-Principles Runtime

## Goal
Force the agent to reason from explicit premises instead of inherited habits.

## What was implemented in the source system
- a durable “First-Principles-Only” mode
- system-level reasoning discipline, not a temporary prompt trick
- explicit requirements to:
  - decompose problems
  - verify assumptions
  - ask one clarifying question when ambiguity blocks correctness
  - avoid unexplained jumps
  - prefer live checks over stale memory

## Use cases
- product and architecture decisions
- debugging and root-cause analysis
- high-stakes reasoning where explainability matters
- reducing hallucinated certainty

## Value
- more auditable outputs
- fewer “sounds right” but ungrounded answers
- better failure diagnosis
- lower randomness in decision quality

## Minimal implementation surface
This module does not require code first. It requires a strong runtime rule layer and consistent enforcement.

## Recommended rollout
1. install as a system/runtime rule
2. attach to every engineering/debugging task
3. require evidence-backed answers when facts are mutable
4. treat ambiguity resolution as part of correctness
