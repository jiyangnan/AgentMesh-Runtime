#!/usr/bin/env python3
"""
context-brief 自动更新脚本

触发时机：复杂任务（>3 步 OODA 闭环）完成后由 agent 调用。
功能：扫描最近的 memory/ 日志、OODA checkpoint、cron 状态，
      生成结构化上下文摘要写入 context-brief.md。

用法：
    python3 update_context_brief.py                    # 全量扫描更新
    python3 update_context_brief.py --task "完成了XXX"  # 追加任务完成记录
    python3 update_context_brief.py --status           # 只输出当前状态 JSON
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
BRIEF_FILE = WORKSPACE / "context-brief.md"
MEMORY_DIR = WORKSPACE / "memory"
CHECKPOINT_DIR = Path.home() / "agent-reinforcement-system" / "state" / "checkpoints"

# ==================== Data Collection ====================

def collect_recent_memory(days=3):
    """收集最近 N 天的 memory 日志标题"""
    entries = []
    today = datetime.now()
    for i in range(days):
        date = today - timedelta(days=i)
        fname = f"{date.strftime('%Y-%m-%d')}.md"
        fpath = MEMORY_DIR / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding='utf-8')
                # 提取每条记录的第一行（通常是标题或时间戳）
                lines = content.strip().split('\n')
                for line in lines[:20]:  # 只看前 20 行
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('---'):
                        # 提取有意义的内容摘要
                        summary = line[:100]
                        if summary:
                            entries.append({
                                "date": fname.replace('.md', ''),
                                "summary": summary
                            })
                            break
            except Exception:
                pass
    return entries


def collect_active_checkpoints():
    """扫描 OODA checkpoint，找到活跃的 goal"""
    active = []
    if not CHECKPOINT_DIR.exists():
        return active

    for f in CHECKPOINT_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            status = data.get("status", "")
            if status not in ("done", "aborted"):
                active.append({
                    "file": f.name,
                    "goal": data.get("goal", f.name),
                    "status": status,
                    "step": data.get("current_step", "?"),
                    "iteration": data.get("iteration", 0),
                    "max_iterations": data.get("max_iterations", "?")
                })
        except Exception:
            pass
    return active


def collect_known_issues():
    """从 memory/ 日志中提取已知问题"""
    issues = []
    issue_keywords = ["❌", "⚠️", "ERROR", "失败", "不可用", "broken", "挂了", "限流"]

    today = datetime.now()
    for i in range(7):  # 扫描最近 7 天
        date = today - timedelta(days=i)
        fname = f"{date.strftime('%Y-%m-%d')}.md"
        fpath = MEMORY_DIR / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding='utf-8')
                for line in content.split('\n'):
                    for kw in issue_keywords:
                        if kw in line:
                            line = line.strip()
                            if len(line) > 10 and len(line) < 200:
                                issues.append({
                                    "date": fname.replace('.md', ''),
                                    "issue": line[:150]
                                })
                                break
            except Exception:
                pass

    # 去重（按 issue 文本）
    seen = set()
    unique = []
    for iss in issues:
        key = iss["issue"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(iss)
    return unique[:10]  # 最多 10 条


def collect_recent_completions(task_note=None):
    """收集近期完成的任务"""
    completions = []

    # 如果有传入的任务备注，加到最前
    if task_note:
        completions.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "task": task_note
        })

    # 从 memory 日志提取 ✅ 标记的完成项
    today = datetime.now()
    for i in range(3):
        date = today - timedelta(days=i)
        fname = f"{date.strftime('%Y-%m-%d')}.md"
        fpath = MEMORY_DIR / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding='utf-8')
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith("✅") and len(line) > 5:
                        # 避免重复
                        text = line[:120]
                        if not any(c["task"][:30] in text for c in completions):
                            completions.append({
                                "date": fname.replace('.md', ''),
                                "task": text
                            })
            except Exception:
                pass

    return completions[:5]


def collect_decisions():
    """从 memory 日志提取决策记录"""
    decisions = []
    decision_markers = ["决策", "决定", "确认了", "选择了", "→"]

    today = datetime.now()
    for i in range(7):
        date = today - timedelta(days=i)
        fname = f"{date.strftime('%Y-%m-%d')}.md"
        fpath = MEMORY_DIR / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding='utf-8')
                for line in content.split('\n'):
                    line = line.strip()
                    if any(m in line for m in decision_markers) and len(line) > 10:
                        decisions.append({
                            "date": fname.replace('.md', ''),
                            "decision": line[:150]
                        })
            except Exception:
                pass

    return decisions[-5:]  # 最近 5 条


# ==================== Output Generation ====================

def generate_brief(task_note=None):
    """生成 context-brief.md 内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    active = collect_active_checkpoints()
    completions = collect_recent_completions(task_note)
    issues = collect_known_issues()
    decisions = collect_decisions()

    lines = []
    lines.append("# 📋 Context Brief — 近期工作上下文\n")
    lines.append(f"> 最后更新：{now} · 复杂任务完成后自动更新")
    lines.append("> ⚠️ 不要手动编辑此文件，由 update_context_brief.py 自动维护\n")
    lines.append("---\n")

    # 进行中
    lines.append("## 🔨 进行中\n")
    if active:
        for cp in active:
            lines.append(f"### {cp['goal']}")
            lines.append(f"- **状态**：{cp['status']} (step: {cp['step']}, iteration: {cp['iteration']}/{cp['max_iterations']})")
            lines.append(f"- **文件**：`{cp['file']}`\n")
    else:
        lines.append("（当前无活跃的 OODA 闭环任务）\n")

    # 近期完成
    lines.append("## ✅ 近期完成（最近 3 次会话）\n")
    if completions:
        for c in completions:
            lines.append(f"- **{c['date']}**: {c['task']}")
    else:
        lines.append("（暂无记录）")
    lines.append("")

    # 决策记录
    lines.append("## 📋 重要决策记录\n")
    if decisions:
        for d in decisions:
            lines.append(f"- **{d['date']}**: {d['decision']}")
    else:
        lines.append("（暂无记录）")
    lines.append("")

    # 已知问题
    lines.append("## ⚠️ 已知问题\n")
    if issues:
        for iss in issues:
            lines.append(f"- {iss['issue']} ({iss['date']})")
    else:
        lines.append("（暂无已知问题）")
    lines.append("")

    # 计划提醒（从 active checkpoint 提取）
    lines.append("## 📅 计划提醒\n")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if active:
        for cp in active:
            lines.append(f"- **{tomorrow}**: 继续 {cp['goal']} — step: {cp['step']}")
    else:
        lines.append("（暂无待办）")
    lines.append("")

    return "\n".join(lines)


def get_status_json():
    """输出状态 JSON（供 agent 程序化读取）"""
    return json.dumps({
        "active_checkpoints": len(collect_active_checkpoints()),
        "recent_completions": len(collect_recent_completions()),
        "known_issues": len(collect_known_issues()),
        "recent_decisions": len(collect_decisions()),
        "brief_exists": BRIEF_FILE.exists(),
        "brief_size": BRIEF_FILE.stat().st_size if BRIEF_FILE.exists() else 0,
        "last_updated": datetime.fromtimestamp(BRIEF_FILE.stat().st_mtime).isoformat() if BRIEF_FILE.exists() else None
    }, indent=2, ensure_ascii=False)


# ==================== Main ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="context-brief 自动更新")
    parser.add_argument("--task", type=str, default=None, help="追加任务完成记录")
    parser.add_argument("--status", action="store_true", help="只输出状态 JSON")
    args = parser.parse_args()

    if args.status:
        print(get_status_json())
    else:
        content = generate_brief(args.task)
        BRIEF_FILE.write_text(content, encoding='utf-8')
        print(f"✅ context-brief.md 已更新 ({len(content)} bytes)")
        print(f"   路径：{BRIEF_FILE}")
