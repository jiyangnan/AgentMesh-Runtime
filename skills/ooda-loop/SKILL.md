# OODA+RV Loop — B 版 Cron 驱动闭环

> 将 agent-reinforcement-system 的模块 3/4 接入 OpenClaw Cron，实现**外部强制执行**的自主闭环。

## 概述

A 版（内化规则）的问题：闭环步骤全靠 agent 自觉，Verify 经常被跳过。
B 版的解法：每个闭环步骤由 cron job 触发，agent 读 checkpoint → 执行一步 → 写 checkpoint → 下次 cron 继续推进。

## 核心机制

### 1. 启动闭环

当收到复杂任务时（3+ 步骤、有依赖关系、需要自主推进），agent：

1. 创建 Goal JSON + LoopState JSON 到 checkpoint 目录
2. 创建一个 cron job，`sessionTarget: "isolated"`，`payload.kind: "agentTurn"`
3. Cron prompt 由 `ooda-driver.py next` 动态生成

### 2. Cron Job 模板

```json
{
  "name": "ooda-loop-{goal_id}",
  "schedule": {"kind": "every", "everyMs": 30000},
  "payload": {
    "kind": "agentTurn",
    "message": "(由 ooda-driver.py next 动态生成)",
    "toolsAllow": ["read", "write", "edit", "exec", "web_fetch", "apply_patch", "cron"]
  },
  "sessionTarget": "isolated",
  "delivery": {"mode": "none"},
  "deleteAfterRun": false,
  "enabled": true
}
```

**关键配置说明**：
- `delivery.mode: "none"` — 中间步骤不推消息，避免刷屏。终态由主 session 通过启动恢复钩子发现并报告
- `toolsAllow` 包含 `cron` — 让 isolated agent 能在终态时停掉自己的 cron job
- `deleteAfterRun: false` — 任务没完成时 cron 继续保留

### 3. AgentTurn 执行流程

每次 cron 触发时，isolated agent：

1. **读 checkpoint**：找到 `current_step` 字段
2. **执行该步骤**：
   - `observe` → 读文件/调工具收集事实，更新 `last_observation`，设 `current_step=orient`
   - `orient` → 列出假设和前提，更新 `working_hypotheses`，设 `current_step=decide`
   - `decide` → 选最小动作 + 验证计划，更新 `selected_action` + `verification_plan`，设 `current_step=act`
   - `act` → 调用工具执行动作，更新 `last_observation` 为执行结果，设 `current_step=verify`
   - `verify` → **必须用工具实际检查**，不能凭感觉，更新 `verification_result`，设 `current_step=record` 或回到 `observe`（失败时）
   - `record` → 写记忆 + ledger，判断终态或继续，设 `current_step=observe` + `iteration+1`（继续时）
3. **写回 checkpoint**
4. **如果到终态**：停用 cron job，向主 session 报告结果

### 4. Verify 步骤的强制规则

这是 B 版最关键的改进。Verify 步骤**必须**：

- 执行至少一个工具调用来验证（不能只"想"）
- 每条 `verification_plan` 都要逐条检查
- 记录 `expected` vs `actual`
- 失败时不推进到 record，而是回到 observe

### 5. 终态处理

| 终态 | 条件 | 动作 |
|------|------|------|
| `done` | 所有 success_criteria 验证通过 | 停 cron，向用户报告成功 |
| `blocked` | consecutive_failures >= max | 停 cron，向用户报告阻塞原因 |
| `waiting_human` | needs_human_input=true | 停 cron，等用户回复后手动恢复 |
| `aborted` | iteration >= max_iterations | 停 cron，向用户报告超限 |

### 6. 文件路径

| 文件 | 路径 |
|------|------|
| Driver 脚本 | `scripts/ooda-driver.py` |
| Checkpoint 目录 | `{ARS_ROOT}/state/checkpoints/` |
| Goal JSON | `{goal_id}__goal.json` |
| LoopState JSON | `{goal_id}__{loop_id}.json` |
| Sync Ledger | `{ARS_ROOT}/state/sync-ledger.jsonl` |
| Schema | `schemas/goal_frame.schema.json` + `schemas/loop_state.schema.json` |

## 启动恢复

主 session 启动时，扫描 checkpoint 目录。如果有 status 为 `active`/`initialized`/`blocked`/`waiting_human` 的 goal，向用户报告并询问是否恢复。

## 与 A 版的区别

| 维度 | A 版 | B 版 |
|------|------|------|
| 执行方式 | agent 自觉执行 | cron 外部驱动 |
| Verify | 靠 agent 记得检查 | 不检查不推进 |
| 步骤粒度 | 一次跑完整个循环 | 每次 cron 只执行一步 |
| 状态持久化 | 写了但不强制读 | 必须读 checkpoint 才知道做什么 |
| 失败恢复 | 无 | 自动重试回到 observe |
