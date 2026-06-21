#!/usr/bin/env python3
"""
OODA+RV Driver — B 版 cron 驱动的闭环执行器。

功能：
1. 扫描 checkpoint 目录，找到需要推进的 goal
2. 根据 current_step 生成 agentTurn 的 prompt
3. 输出 JSON 供 cron job 使用

用法：
  python3 ooda-driver.py next          # 找到下一个待推进的 checkpoint，输出 prompt
  python3 ooda-driver.py list          # 列出所有 open checkpoint
  python3 ooda-driver.py init <goal_json> <loop_json>  # 初始化新 goal
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ARS_ROOT = Path(os.getenv("ARS_ROOT", str(Path.home() / "agent-reinforcement-system")))
STATE_DIR = ARS_ROOT / "state"
CHECKPOINT_DIR = STATE_DIR / "checkpoints"
LEDGER_PATH = STATE_DIR / "sync-ledger.jsonl"

VALID_STEPS = ["observe", "orient", "decide", "act", "verify", "record"]
TERMINAL_STATUSES = {"done", "blocked", "aborted"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_open_checkpoints():
    """找出所有非终止状态的 checkpoint"""
    if not CHECKPOINT_DIR.exists():
        return []
    results = []
    for p in sorted(CHECKPOINT_DIR.glob("*__*.json")):
        # Skip goal files (pattern: {goal_id}__goal.json)
        if p.name.endswith("__goal.json"):
            continue
        data = load_json(p)
        if data and data.get("status") not in TERMINAL_STATUSES and data.get("loop_id"):
            # Also load the goal
            goal_path = CHECKPOINT_DIR / f"{data['goal_id']}__goal.json"
            goal = load_json(goal_path) or {}
            results.append({"loop": data, "goal": goal, "path": str(p)})
    return results


# ==================== Anti-Pattern Detection ====================

def _keyword_overlap(a: str, b: str) -> float:
    """计算两个文本的关键词重叠率（0.0-1.0）。用于 phantom progress 检测。"""
    if not a or not b:
        return 0.0
    # 简单分词：按空格和标点分割，取 >2 字符的词
    import re
    words_a = set(w.lower() for w in re.split(r'[^\w]+', a) if len(w) > 2)
    words_b = set(w.lower() for w in re.split(r'[^\w]+', b) if len(w) > 2)
    if not words_a or not words_b:
        return 0.0
    overlap = words_a & words_b
    union = words_a | words_b
    return len(overlap) / len(union) if union else 0.0


def detect_anti_patterns(loop_state, goal_frame) -> list[dict]:
    """检测三种反模式，返回警告列表。"""
    warnings = []
    iteration = loop_state.get("iteration", 0)
    max_consec = goal_frame.get("max_consecutive_failures", 3)

    # 历史记录
    history = loop_state.get("_history", [])

    current_action = loop_state.get("selected_action", "")
    current_obs = loop_state.get("last_observation", "")

    # ── 1. blind retry：连续两次相同 action ──────────────────────
    if len(history) >= 1:
        prev_action = history[-1].get("action", "")
        if prev_action and current_action == prev_action:
            warnings.append({
                'type': 'blind_retry',
                'severity': 'critical',
                'message': f"⚠️ 反模式警告 [blind retry]：连续两次执行了相同的 action（{current_action[:60]}...）。第 2 次重复将直接触发 STUCK 终态。",
                'action': '建议立即切换思路或改变动作'
            })

    # ── 2. phantom progress：最近 3 次 observation 高度相似 ──────
    recent_obs = [h.get("observation", "") for h in history[-3:] if h.get("observation")]
    if current_obs:
        recent_obs.insert(0, current_obs)
    if len(recent_obs) >= 3:
        overlaps = [
            _keyword_overlap(recent_obs[i], recent_obs[i + 1])
            for i in range(len(recent_obs) - 1)
        ]
        if all(o > 0.7 for o in overlaps[-2:]):  # 最近 2 对都 > 70%
            warnings.append({
                'type': 'phantom_progress',
                'severity': 'warning',
                'message': f"⚠️ 反模式警告 [phantom progress]：最近 {len(recent_obs)} 次观察高度重叠（{overlaps[-1]:.0%}），没有真实进展。建议 pivot 改变方向。",
                'action': '建议 PIVOT，换一个完全不同的思路或工具组合'
            })

    # ── 3. pivot exhaustion：2+ 次 pivot 无进展 ──────────────────
    pivot_count = loop_state.get("_pivot_count", 0)
    if pivot_count >= 2:
        has_progress = any(
            h.get("verification_result") == "pass"
            for h in history[-pivot_count:]
        )
        if not has_progress:
            warnings.append({
                'type': 'pivot_exhaustion',
                'severity': 'critical',
                'message': f"⚠️ 反模式警告 [pivot exhaustion]：已 pivot {pivot_count} 次但无任何进展。超过 pivot 耐受极限。",
                'action': f'连续失败 {max_consec} 次 → 终态 = STUCK，闭环终止'
            })

    return warnings


def generate_prompt(loop_state, goal_frame):
    """根据 current_step 生成 agentTurn 的 prompt（含反模式检测）"""
    step = loop_state.get("current_step", "observe")
    iteration = loop_state.get("iteration", 0)
    max_iter = goal_frame.get("max_iterations", 12)
    goal_id = loop_state.get("goal_id", "unknown")

    # ── 反模式检测 ──
    anti_patterns = detect_anti_patterns(loop_state, goal_frame)
    ap_section = ""
    if anti_patterns:
        ap_lines = ["## 🔴 反模式警告（必须立即处理）"]
        for ap in anti_patterns:
            ap_lines.append(f"\n**【{ap['type'].upper()} — {ap['severity'].upper()}】**")
            ap_lines.append(f"{ap['message']}")
            ap_lines.append(f"→ 建议动作：{ap['action']}")
        ap_section = "\n" + "\n".join(ap_lines) + "\n\n"

    # ── 连续失败计数 ──
    consec_fail = loop_state.get("consecutive_failures", 0)
    max_consec = goal_frame.get("max_consecutive_failures", 3)
    fail_section = ""
    if consec_fail >= max_consec - 1:
        fail_section = f"\n🔴 警告：consecutive_failures={consec_fail}/{max_consec}（下一步失败将触发 STUCK 终态）\n"

    header = f"""你正在执行 OODA+RV 自主闭环任务。

任务: {goal_frame.get('name', '')}
目标: {goal_frame.get('goal', '')}
迭代: {iteration}/{max_iter}
当前步骤: {step}
上次观察: {loop_state.get('last_observation', '无')}
当前假设: {json.dumps(loop_state.get('working_hypotheses', []), ensure_ascii=False)}
选定动作: {loop_state.get('selected_action', '无')}
验证结果: {loop_state.get('verification_result', 'unknown')}
连续失败: {consec_fail}/{max_consec}{fail_section}成功标准:
{chr(10).join(f'  - {c}' for c in goal_frame.get('success_criteria', []))}

约束:
{chr(10).join(f'  - {c}' for c in goal_frame.get('constraints', []))}
{ap_section}⚠️ 终态保护：如果 checkpoint 的 status 是 done/blocked/aborted，立即输出 NO_REPLY 并退出，不要做任何操作。

Checkpoint 路径: {CHECKPOINT_DIR}/{goal_id}__goal.json
Ledger 路径: {LEDGER_PATH}
"""

    step_instructions = {
        "observe": """## 你的任务: OBSERVE（观察）

收集当前真实状态，不要假设。

必须做：
1. 读取相关文件、调用工具、搜索记忆
2. 记录你观察到的**事实**，不是推测
3. 列出缺失的信息

输出格式（完成后写回 checkpoint）：
- last_observation: 你观察到什么
- current_step: 改为 "orient"
- status: 保持 "active"
""",
        "orient": """## 你的任务: ORIENT（分析）

基于观察结果，用第一性原理分析。

必须做：
1. 列出明确的前提和假设
2. 列出必要条件
3. 排列假设，按可能性排序

输出格式（完成后写回 checkpoint）：
- working_hypotheses: 假设列表
- current_step: 改为 "decide"
""",
        "decide": """## 你的任务: DECIDE（决策）

选**最小可行动作**。

必须做：
1. 从假设中选一个最可能正确的
2. 确定下一步具体做什么
3. 列出验证计划：执行后怎么确认做对了
4. 检查是否需要人工确认（高风险操作）
5. **判断是否 pivot**：如果上一个动作连续失败或 observation 没有变化，主动换一个完全不同的思路 → 在 checkpoint 里 `_pivot_count += 1`

输出格式（完成后写回 checkpoint）：
- selected_action: 选定的动作
- verification_plan: 验证计划列表
- needs_human_input: true/false
- current_step: 改为 "act"
""",
        "act": """## 你的任务: ACT（执行）

执行 selected_action 中定义的动作。

必须做：
1. 调用工具执行动作
2. 记录执行结果（成功/失败/错误信息）
3. 保留原始证据（命令输出、文件内容等）

关键：**执行完不要自己判断是否成功**，留给 Verify 步骤。

输出格式（完成后写回 checkpoint）：
- current_step: 改为 "verify"
- 更新 last_observation 为执行结果摘要
- 追加到 _history：[{{"action": selected_action, "observation": 执行结果摘要, "verification_result": "unknown"}}]
""",
        "verify": """## 你的任务: VERIFY（验证）

用 verification_plan 中的断言验证执行结果。

必须做：
1. 逐条检查 verification_plan
2. 每条断言给出 pass/fail
3. 如果全部 pass → verification_result = "pass"
4. 如果任一 fail → verification_result = "fail"，consecutive_failures +1

**这是最关键的步骤。不允许跳过。不允许凭感觉判断。**
必须用工具实际检查：读文件、运行命令、验证输出。

输出格式（完成后写回 checkpoint）：
- verification_result: "pass" 或 "fail"
- consecutive_failures: 更新失败计数
- 更新 _history 中最后一条的 verification_result
- current_step: 改为 "record"（如果 pass）或 "observe"（如果 fail，重新观察）
""",
        "record": """## 你的任务: RECORD（记录）

持久化本次迭代的经验。

必须做：
1. 写 checkpoint 文件（更新 loop state）
2. 追加 sync ledger 条目
3. 判断是否继续：
   - 所有 success_criteria 验证通过 → status = "done"
   - 连续失败 >= max_consecutive_failures → status = "blocked"
   - 需要人工确认 → status = "waiting_human"
   - 否则 → status = "active", iteration +1, current_step = "observe"

⚠️ 如果 status 变为终态（done/blocked/aborted/waiting_human）：
   你必须调用 cron 工具将当前 cron job 设为 enabled=false 来停止自己。
   cron job name 包含 "ooda-loop-" 前缀。

输出格式（完成后写回 checkpoint）：
- status: 终态或 "active"
- iteration: 递增（如果继续）
- current_step: "observe"（如果继续）
- memory_write_required: false（已完成写入）
""",
    }

    return header + step_instructions.get(step, "")


def cmd_next():
    """找到下一个待推进的 checkpoint，输出 prompt"""
    open_cps = list_open_checkpoints()
    if not open_cps:
        print(json.dumps({"action": "none", "reason": "no open checkpoints"}))
        return 0

    # Pick the first one, but double-check it's truly not terminal
    cp = open_cps[0]
    loop = cp["loop"]
    if loop.get("status") in TERMINAL_STATUSES:
        print(json.dumps({"action": "none", "reason": f"goal already in terminal state: {loop['status']}"}))
        return 0
    loop = cp["loop"]
    goal = cp["goal"]

    prompt = generate_prompt(loop, goal)

    # Output as JSON for the cron job to use
    result = {
        "action": "run",
        "goal_id": loop["goal_id"],
        "loop_id": loop.get("loop_id", ""),
        "current_step": loop.get("current_step", "observe"),
        "status": loop.get("status", "initialized"),
        "iteration": loop.get("iteration", 0),
        "prompt": prompt,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_list():
    """列出所有 open checkpoint"""
    open_cps = list_open_checkpoints()
    for cp in open_cps:
        loop = cp["loop"]
        goal = cp["goal"]
        print(f"  {loop['goal_id']} | step={loop.get('current_step','?')} | iter={loop.get('iteration',0)}/{goal.get('max_iterations','?')} | status={loop.get('status','?')}")
    if not open_cps:
        print("  (no open checkpoints)")
    return 0


def cmd_init(goal_json_path, loop_json_path):
    """注册新 goal（文件已经写好的情况下只做初始化检查）"""
    goal = load_json(goal_json_path)
    loop = load_json(loop_json_path)
    if not goal or not loop:
        print("ERROR: could not load goal or loop json", file=sys.stderr)
        return 1

    # Validate
    required_goal = ["goal_id", "name", "goal", "success_criteria", "constraints"]
    for f in required_goal:
        if f not in goal:
            print(f"ERROR: goal missing field: {f}", file=sys.stderr)
            return 1

    if loop.get("status") != "initialized":
        loop["status"] = "initialized"
        save_json(loop_json_path, loop)

    print(f"OK: goal_id={goal['goal_id']} status=initialized")
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: ooda-driver.py [next|list|init <goal.json> <loop.json>]")
        return 1

    cmd = sys.argv[1]
    if cmd == "next":
        return cmd_next()
    elif cmd == "list":
        return cmd_list()
    elif cmd == "init" and len(sys.argv) >= 4:
        return cmd_init(sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
