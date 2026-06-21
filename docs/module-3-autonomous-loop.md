# Module 3 — Autonomous-Loop

## Design trigger
`--compile-procedural-skill "Autonomous-Loop"`

## Position in the 3-module system
- **Module 1** solves: how the agent should think
- **Module 2** solves: how the agent should remember
- **Module 3** solves: how the agent should keep acting until the job reaches a terminal state

This module is the execution reinforcement layer.

---

## 1. Goal

Turn the agent from a one-turn responder into a bounded autonomous executor.

The module must let an agent:
1. hold a goal across multiple steps
2. inspect real state before acting
3. choose the smallest valid next action
4. verify whether the action worked
5. record useful experience
6. continue, pause, escalate, or stop cleanly

---

## 2. Core definition

> **Autonomous-Loop** is a procedural execution loop that repeatedly runs:
>
> **Observe → Orient → Decide → Act → Verify → Record → Loop/Exit**
>
> until it reaches one of four terminal states:
> - `done`
> - `blocked`
> - `waiting_human`
> - `aborted`

---

## 3. Design principles

### 3.1 Bounded autonomy
Autonomy is allowed only inside explicit task boundaries.

### 3.2 Verification before success claims
No action counts as complete until a concrete verification step passes.

### 3.3 Hypothesis revision over blind retry
Repeated failure must trigger reasoning revision, not infinite repetition.

### 3.4 Human escalation at irreversible boundaries
Public posting, deletion, money movement, credentials, or external side effects require escalation or explicit prior authorization.

### 3.5 Memory is part of execution
The loop must write useful episodes, not just outputs.

---

## 4. Loop lifecycle

```text
Goal Frame
   ↓
Observe
   ↓
Orient
   ↓
Decide
   ↓
Act
   ↓
Verify
   ↓
Record
   ↓
[done | blocked | waiting_human | aborted | next iteration]
```

---

## 5. State machine

## States
- `initialized`
- `active`
- `waiting_human`
- `blocked`
- `done`
- `aborted`

## Transitions
- `initialized -> active`
- `active -> active` (next iteration)
- `active -> waiting_human`
- `active -> blocked`
- `active -> done`
- `active -> aborted`
- `waiting_human -> active`
- `blocked -> active`
- `blocked -> aborted`

---

## 6. Goal Frame schema

```yaml
goal_id: string
name: string
goal: string
success_criteria:
  - string
constraints:
  - string
non_goals:
  - string
risk_level: low | medium | high
external_side_effects: true | false
escalation_points:
  - string
abort_conditions:
  - string
max_iterations: integer
max_consecutive_failures: integer
owner: user | agent
created_at: iso8601
```

### Example
```yaml
goal_id: ars-demo-001
name: Publish first two modules as standalone repo
goal: Create a clean public repository containing module 1 and module 2 docs and code.
success_criteria:
  - repository exists on GitHub
  - README explains both modules
  - code compiles
constraints:
  - do not modify unrelated repositories
  - ask before irreversible publication if not already authorized
non_goals:
  - marketing launch
risk_level: medium
external_side_effects: true
escalation_points:
  - final public release
abort_conditions:
  - missing GitHub auth
max_iterations: 20
max_consecutive_failures: 3
owner: user
created_at: 2026-04-29T00:00:00Z
```

---

## 7. Loop State schema

```yaml
loop_id: string
goal_id: string
status: initialized | active | waiting_human | blocked | done | aborted
iteration: integer
current_step: observe | orient | decide | act | verify | record
last_observation: string
working_hypotheses:
  - string
selected_action: string
verification_plan:
  - string
verification_result: pass | fail | unknown
blockers:
  - string
open_questions:
  - string
needs_human_input: true | false
consecutive_failures: integer
last_error: string | null
memory_write_required: true | false
next_iteration_hint: string | null
updated_at: iso8601
```

---

## 8. Step contract

### 8.1 Observe
Purpose: inspect live state, not assumed state.

Required output:
- current facts
- missing facts
- evidence source

Failure mode:
- if critical state is unknown, do not continue to act

### 8.2 Orient
Purpose: interpret the observation using Module 1 (First-Principles Runtime).

Required output:
- explicit assumptions
- causal explanation
- top hypotheses ranked by likelihood

Failure mode:
- if the explanation depends on convention without evidence, revise

### 8.3 Decide
Purpose: choose the smallest meaningful next move.

Required output:
- chosen action
- why this action dominates alternatives
- risk check

Failure mode:
- if action is irreversible and not pre-authorized, escalate

### 8.4 Act
Purpose: perform the selected action.

Required output:
- action performed
- action result
- raw evidence or result handle

Failure mode:
- if tool execution fails, capture error and move to verify/record

### 8.5 Verify
Purpose: determine whether the action actually changed the world as intended.

Required output:
- verification method
- expected result
- actual result
- pass/fail decision

Failure mode:
- no success claim without a real check

### 8.6 Record
Purpose: persist durable learning into Module 2 memory.

Required output:
- what to remember
- why it matters
- whether it is episodic, semantic, or procedural

Failure mode:
- do not store transient noise as durable memory

### 8.7 Loop/Exit
Purpose: decide whether to continue.

Valid outcomes:
- `continue`
- `done`
- `waiting_human`
- `blocked`
- `aborted`

---

## 9. Retry / revise / escalate policy

### Retry
Allowed when:
- failure is likely transient
- the hypothesis remains intact
- retry count is below threshold

### Revise hypothesis
Required when:
- the same action fails repeatedly
- verification disproves the current explanation
- the environment differs from the assumed model

### Escalate to human
Required when:
- irreversible action is next
- the goal frame is ambiguous
- conflicting success criteria exist
- authorization is required

### Abort
Required when:
- abort condition is met
- safety boundary is hit
- repeated failure exceeds maximum without a better hypothesis

---

## 10. Interface with Module 1

Autonomous-Loop must call Module 1 during **Orient** and **Decide**.

### Required constraints inherited from Module 1
- decompose to atomic claims
- verify target object and necessary conditions
- reject unsupported jumps
- treat mutable facts as requiring live checks

---

## 11. Interface with Module 2

Autonomous-Loop must call Module 2 during **Observe** and **Record**.

### Observe-side usage
- recall prior similar episodes
- pull previous failures / decisions / context

### Record-side usage
- write successful patterns
- write failed hypotheses
- write blockers and escalation context

### Memory categories
- episodic: what happened in this run
- semantic: reusable lesson or rule
- procedural: loop pattern worth compiling into a reusable skill

---

## 12. Procedural skill compilation

The module must support promoting repeated loops into reusable procedural skills.

## Promotion trigger
Compile a procedural skill when all are true:
1. same goal pattern appears at least 3 times
2. stable step ordering emerges
3. verification criteria are repeatable
4. failure modes are known enough to encode

## Compiled skill output
```yaml
skill_name: string
trigger_pattern: string
inputs:
  - name: string
    type: string
steps:
  - observe
  - orient
  - decide
  - act
  - verify
stop_conditions:
  - string
escalation_rules:
  - string
verification_rules:
  - string
memory_rules:
  - string
```

---

## 13. Minimal JSON runtime example

```json
{
  "goal_id": "goal-003",
  "name": "Repair memory failover path",
  "goal": "Make local memory recall work when embedding provider is down.",
  "success_criteria": [
    "Neo4j recall returns results",
    "SQLite fallback works",
    "single-entry recall script exists"
  ],
  "constraints": [
    "prefer local backends",
    "do not break existing memory files"
  ],
  "risk_level": "medium",
  "external_side_effects": false,
  "max_iterations": 12,
  "max_consecutive_failures": 3
}
```

---

## 14. Reference implementation targets

A practical implementation should eventually include:
- `autonomous_loop.py` execution engine
- `goal_frame.schema.json`
- `loop_state.schema.json`
- `procedural_skill.schema.json`
- adapters for:
  - memory recall
  - memory write
  - tool execution
  - verification assertions

---

## 15. Why this module matters

Without Module 3:
- the agent may think well
- the agent may remember well
- but it still behaves like a clever one-turn assistant

With Module 3:
- the agent can persistently push work forward
- know when to stop
- know when to ask
- and convert repeated execution patterns into reusable skills

That is what turns intelligence + memory into an actual operating system for work.
