#!/usr/bin/env python3
"""
Autonomous Loop runtime for agent-reinforcement-system.

Integrated version:
- Module 1: First-Principles Runtime
- Module 2: HA Episodic Memory
- Module 3: Autonomous Loop

Observe -> Orient -> Decide -> Act -> Verify -> Record -> Loop/Exit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unified_memory_recall import recall as memory_recall
from episode_ingest import ingest_event
from checkpoint_store import save_checkpoint

VALID_STATUSES = {"initialized", "active", "waiting_human", "blocked", "done", "aborted"}
VALID_STEPS = ["observe", "orient", "decide", "act", "verify", "record"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(text: str, n: int = 240) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "..."


@dataclass
class GoalFrame:
    goal_id: str
    name: str
    goal: str
    success_criteria: list[str]
    constraints: list[str]
    non_goals: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    external_side_effects: bool = False
    escalation_points: list[str] = field(default_factory=list)
    abort_conditions: list[str] = field(default_factory=list)
    max_iterations: int = 12
    max_consecutive_failures: int = 3
    owner: str = "user"
    created_at: str = field(default_factory=now_iso)


@dataclass
class LoopState:
    loop_id: str
    goal_id: str
    status: str = "initialized"
    iteration: int = 0
    current_step: str = "observe"
    last_observation: str = ""
    working_hypotheses: list[str] = field(default_factory=list)
    selected_action: str = ""
    verification_plan: list[str] = field(default_factory=list)
    verification_result: str = "unknown"
    blockers: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    needs_human_input: bool = False
    consecutive_failures: int = 0
    last_error: str | None = None
    memory_write_required: bool = False
    next_iteration_hint: str | None = None
    updated_at: str = field(default_factory=now_iso)


class AutonomousLoopError(RuntimeError):
    pass


class HAMemoryAdapter:
    def __init__(self, top_k: int = 5, log_path: str | None = None, channel: str = "runtime"):
        self.top_k = top_k
        self.log_path = Path(log_path or os.getenv("ARS_LOOP_MEMORY_LOG", "./runtime/loop_memory.jsonl"))
        self.channel = channel

    def recall(self, query: str) -> list[dict[str, Any]]:
        hits = memory_recall(query, self.top_k)
        return [asdict(h) for h in hits]

    def record(self, item: dict[str, Any]) -> dict[str, Any]:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        session_id = f"loop:{item['loop_id']}:{item['iteration']}"
        summary = f"Loop {item['goal_id']} iteration {item['iteration']}"
        full_text = json.dumps(item, ensure_ascii=False)
        ingest = ingest_event(
            session_id=session_id,
            summary=summary,
            full_text=full_text,
            channel=self.channel,
            kind="loop_record",
            event_id=f"loop:{item['loop_id']}:{item['iteration']}",
        )
        return ingest


class FirstPrinciplesEngine:
    """Small reasoning helper for Orient/Decide."""

    def orient(self, goal: GoalFrame, state: LoopState, observation: dict[str, Any]) -> dict[str, Any]:
        premises = [
            f"goal={goal.goal}",
            f"success_criteria={len(goal.success_criteria)}",
            f"constraints={len(goal.constraints)}",
            f"memory_hits={len(observation.get('memory_hits', []))}",
        ]
        needed_conditions = [f"must satisfy: {x}" for x in goal.success_criteria]
        hypotheses = []
        if observation.get("memory_hits"):
            hypotheses.append("Historical memory contains similar context that can reduce uncertainty.")
        hypotheses.append("The next action should be the smallest move that reduces uncertainty or verifies one success criterion.")
        if goal.external_side_effects:
            hypotheses.append("External side effects increase risk and may require human approval before action.")
        explanation = {
            "premises": premises,
            "needed_conditions": needed_conditions,
            "hypotheses": hypotheses,
            "explanation": "Rebuilt from goal constraints, observable context, and required success conditions instead of habit.",
        }
        return explanation

    def decide(self, goal: GoalFrame, state: LoopState, orientation: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        memory_hits = observation.get("memory_hits", [])
        top_memory = memory_hits[0] if memory_hits else None
        action = "produce_minimal_plan"
        rationale = "No narrower executable action was preconfigured, so the loop should first produce a minimal verified next-step plan."

        if top_memory:
            action = f"reuse_or_compare_memory:{top_memory.get('location','unknown')}"
            rationale = "Closest prior episode should be compared before acting from scratch."

        needs_human_input = False
        if goal.external_side_effects and goal.risk_level in {"medium", "high"}:
            needs_human_input = True
            action = "ask_human_for_authorization"
            rationale = "External side effects under medium/high risk require bounded escalation."

        verification_plan = [
            "confirm the chosen action advances at least one success criterion",
            "confirm no stated constraint is violated",
        ]
        return {
            "action": action,
            "rationale": rationale,
            "verification_plan": verification_plan,
            "needs_human_input": needs_human_input,
        }


class IntegratedPolicy:
    """Policy that actually connects Module 1 + Module 2 into Module 3."""

    def __init__(self, memory: HAMemoryAdapter | None = None, fp: FirstPrinciplesEngine | None = None):
        self.memory = memory or HAMemoryAdapter()
        self.fp = fp or FirstPrinciplesEngine()

    def observe(self, goal: GoalFrame, state: LoopState) -> dict[str, Any]:
        query = f"{goal.name} {goal.goal} {' '.join(goal.success_criteria[:3])}".strip()
        memory_hits = self.memory.recall(query)
        summary = f"Observed goal + {len(memory_hits)} memory hits"
        evidence = [truncate(hit.get("snippet", ""), 180) for hit in memory_hits[:3]]
        return {
            "observation": summary,
            "query": query,
            "memory_hits": memory_hits,
            "evidence": evidence,
        }

    def orient(self, goal: GoalFrame, state: LoopState, observation: dict[str, Any]) -> dict[str, Any]:
        return self.fp.orient(goal, state, observation)

    def decide(self, goal: GoalFrame, state: LoopState, orientation: dict[str, Any]) -> dict[str, Any]:
        observation = {"memory_hits": [], "observation": state.last_observation}
        # state.last_observation is string, but current iteration's memory hit count is not preserved there.
        # recover from hint if present; the decision engine mainly needs the memory hits count / top hit.
        if hasattr(state, "_observation_cache"):
            observation = getattr(state, "_observation_cache")
        return self.fp.decide(goal, state, orientation, observation)

    def act(self, goal: GoalFrame, state: LoopState, decision: dict[str, Any]) -> dict[str, Any]:
        if decision.get("needs_human_input"):
            return {"performed": False, "result": decision.get("rationale", "waiting for human input")}
        action = decision.get("action", "")
        return {
            "performed": True,
            "result": f"simulated execution: {action}",
            "rationale": decision.get("rationale", ""),
        }

    def verify(self, goal: GoalFrame, state: LoopState, action_result: dict[str, Any]) -> dict[str, Any]:
        if not action_result.get("performed"):
            return {"result": "unknown", "reason": action_result.get("result", "not performed")}
        if state.selected_action.startswith("reuse_or_compare_memory:"):
            return {"result": "pass", "reason": "Historical context successfully retrieved and used as the next-step anchor."}
        if state.selected_action == "produce_minimal_plan":
            return {"result": "pass", "reason": "A bounded next-step plan was produced without violating constraints."}
        return {"result": "pass", "reason": action_result.get("result", "ok")}

    def record(self, goal: GoalFrame, state: LoopState, verification: dict[str, Any]) -> dict[str, Any]:
        item = {
            "ts": now_iso(),
            "goal_id": goal.goal_id,
            "loop_id": state.loop_id,
            "iteration": state.iteration,
            "status": state.status,
            "step": state.current_step,
            "selected_action": state.selected_action,
            "verification_result": state.verification_result,
            "reason": verification.get("reason", ""),
            "hypotheses": state.working_hypotheses,
        }
        ingest = self.memory.record(item)
        return {"memory_items": [item], "ingest": ingest}


class AutonomousLoop:
    def __init__(self, goal: GoalFrame, state: LoopState | None = None, policy: Any | None = None):
        self.goal = goal
        self.state = state or LoopState(loop_id=str(uuid.uuid4()), goal_id=goal.goal_id)
        self.policy = policy or IntegratedPolicy()
        self._validate_goal()
        self._validate_state()

    def _validate_goal(self) -> None:
        if not self.goal.goal_id or not self.goal.goal:
            raise AutonomousLoopError("GoalFrame missing required content")
        if self.goal.risk_level not in {"low", "medium", "high"}:
            raise AutonomousLoopError("Invalid risk_level")
        if self.goal.owner not in {"user", "agent"}:
            raise AutonomousLoopError("Invalid owner")
        if self.goal.max_iterations < 1 or self.goal.max_consecutive_failures < 1:
            raise AutonomousLoopError("Invalid loop limits")

    def _validate_state(self) -> None:
        if self.state.status not in VALID_STATUSES:
            raise AutonomousLoopError(f"Invalid status: {self.state.status}")
        if self.state.current_step not in VALID_STEPS:
            raise AutonomousLoopError(f"Invalid step: {self.state.current_step}")

    def _touch(self) -> None:
        self.state.updated_at = now_iso()

    def _checkpoint_payload(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal.goal_id,
            "loop_id": self.state.loop_id,
            "title": self.goal.name,
            "goal": self.goal.goal,
            "status": self.state.status,
            "current_phase": self.state.current_step,
            "latest_decision": self.state.selected_action,
            "blockers": self.state.blockers,
            "open_questions": self.state.open_questions,
            "next_step": self.state.next_iteration_hint,
            "next_iteration_hint": self.state.next_iteration_hint,
            "verification_result": self.state.verification_result,
            "needs_human_input": self.state.needs_human_input,
            "last_error": self.state.last_error,
            "updated_at": self.state.updated_at,
        }

    def _save_checkpoint(self) -> None:
        save_checkpoint(self._checkpoint_payload())

    def step(self) -> LoopState:
        if self.state.status in {"done", "blocked", "waiting_human", "aborted"}:
            self._save_checkpoint()
            return self.state

        if self.state.iteration >= self.goal.max_iterations:
            self.state.status = "aborted"
            self.state.last_error = "max_iterations_exceeded"
            self._touch()
            self._save_checkpoint()
            return self.state

        self.state.status = "active"
        self.state.iteration += 1

        observation = self._run_observe()
        orientation = self._run_orient(observation)
        decision = self._run_decide(orientation)

        if decision.get("needs_human_input"):
            self.state.status = "waiting_human"
            self.state.needs_human_input = True
            self.state.next_iteration_hint = "await human approval or decision"
            self._touch()
            self._save_checkpoint()
            return self.state

        action_result = self._run_act(decision)
        verification = self._run_verify(action_result)
        self._run_record(verification)
        self._resolve_terminal_state(verification)
        self._touch()
        self._save_checkpoint()
        return self.state

    def run(self) -> LoopState:
        while self.state.status == "initialized" or self.state.status == "active":
            self.step()
        return self.state

    def _run_observe(self) -> dict[str, Any]:
        self.state.current_step = "observe"
        obs = self.policy.observe(self.goal, self.state)
        self.state.last_observation = obs.get("observation", "")
        setattr(self.state, "_observation_cache", obs)
        return obs

    def _run_orient(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.state.current_step = "orient"
        orient = self.policy.orient(self.goal, self.state, observation)
        self.state.working_hypotheses = orient.get("hypotheses", [])
        return orient

    def _run_decide(self, orientation: dict[str, Any]) -> dict[str, Any]:
        self.state.current_step = "decide"
        decision = self.policy.decide(self.goal, self.state, orientation)
        self.state.selected_action = decision.get("action", "")
        self.state.verification_plan = decision.get("verification_plan", [])
        self.state.needs_human_input = bool(decision.get("needs_human_input", False))
        return decision

    def _run_act(self, decision: dict[str, Any]) -> dict[str, Any]:
        self.state.current_step = "act"
        return self.policy.act(self.goal, self.state, decision)

    def _run_verify(self, action_result: dict[str, Any]) -> dict[str, Any]:
        self.state.current_step = "verify"
        verification = self.policy.verify(self.goal, self.state, action_result)
        result = verification.get("result", "unknown")
        if result not in {"pass", "fail", "unknown"}:
            raise AutonomousLoopError(f"Invalid verification result: {result}")
        self.state.verification_result = result
        if result == "fail":
            self.state.consecutive_failures += 1
        elif result == "pass":
            self.state.consecutive_failures = 0
        return verification

    def _run_record(self, verification: dict[str, Any]) -> dict[str, Any]:
        self.state.current_step = "record"
        self.state.memory_write_required = True
        record = self.policy.record(self.goal, self.state, verification)
        self.state.memory_write_required = False
        return record

    def _resolve_terminal_state(self, verification: dict[str, Any]) -> None:
        if self.state.consecutive_failures >= self.goal.max_consecutive_failures:
            self.state.status = "blocked"
            self.state.last_error = "max_consecutive_failures_exceeded"
            self.state.next_iteration_hint = "revise hypothesis or escalate"
            return

        if verification.get("result") == "pass":
            self.state.status = "done"
            self.state.next_iteration_hint = "goal verified complete"
            return

        if verification.get("result") == "unknown":
            self.state.status = "waiting_human" if self.state.needs_human_input else "active"
            self.state.next_iteration_hint = "need verification or authorization"
            return

        self.state.status = "active"
        self.state.next_iteration_hint = "retry with revised hypothesis"

    @staticmethod
    def from_files(goal_path: str, state_path: str | None = None) -> "AutonomousLoop":
        with open(goal_path, encoding="utf-8") as f:
            goal = GoalFrame(**json.load(f))
        state = None
        if state_path and os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                state = LoopState(**json.load(f))
        return AutonomousLoop(goal, state)

    def save_state(self, path: str) -> None:
        payload = asdict(self.state)
        payload.pop("_observation_cache", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous Loop runtime")
    parser.add_argument("goal", help="Path to goal frame JSON")
    parser.add_argument("--state", help="Path to existing loop state JSON")
    parser.add_argument("--out", help="Write resulting loop state to file")
    parser.add_argument("--mode", choices=["step", "run"], default="run")
    args = parser.parse_args()

    loop = AutonomousLoop.from_files(args.goal, args.state)
    result = loop.step() if args.mode == "step" else loop.run()

    payload = asdict(result)
    payload.pop("_observation_cache", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out:
        loop.save_state(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
