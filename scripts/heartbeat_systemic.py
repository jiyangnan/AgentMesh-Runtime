#!/usr/bin/env python3
"""
heartbeat_systemic.py — 系统性心跳自检脚本

参考 ACK Generic Heartbeat：Sense → Think → Act → Report → Remember 五步循环。

检查项：
  1. MEMORY.md 容量
  2. Episodic index 健康（Neo4j Episode 节点计数）
  3. Cron jobs 状态（consecutiveErrors >= 3 标记警告）
  4. context-brief 新鲜度（>48h 未更新）
  5. Sync ledger drift（pending backfill）
  6. Workspace 临时文件

报告输出到 memory/heartbeat-YYYY-MM-DD.md
Critical/Warning 告警推送到 Telegram 群聊

用法：
    python3 heartbeat_systemic.py              # 全量自检 + 生成报告
    python3 heartbeat_systemic.py --critical  # 只检查 critical 项（快速）
    python3 heartbeat_systemic.py --report     # 只读取最新报告
"""

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", str(Path.home() / ".openclaw" / "workspace")))
MEMORY_DIR = WORKSPACE / "memory"
BRIEF_FILE = WORKSPACE / "context-brief.md"
ARS_DIR = Path.home() / "agent-reinforcement-system"
SYNC_LEDGER = ARS_DIR / "state" / "sync-ledger.jsonl"
CHECKPOINT_DIR = ARS_DIR / "state" / "checkpoints"

# Telegram
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")  # 通过环境变量配置

# ==================== Phase 1: Sense (Health Checks) ====================

def check_memory_capacity():
    """检查 MEMORY.md 容量（warn >80KB, critical >105KB）"""
    memory_file = WORKSPACE / "MEMORY.md"
    if not memory_file.exists():
        return "unknown", 0, "文件不存在"

    size_kb = memory_file.stat().st_size / 1024
    warn_threshold_kb = 80
    crit_threshold_kb = 105

    if size_kb > crit_threshold_kb:
        return "critical", size_kb, f"容量 {size_kb:.0f}KB > 105KB (critical)"
    elif size_kb > warn_threshold_kb:
        return "warning", size_kb, f"容量 {size_kb:.0f}KB > 80KB (warning)"
    else:
        return "ok", size_kb, f"容量 {size_kb:.0f}KB（正常）"


def check_episodic_index():
    """检查 episodic index 健康（Neo4j Episode 节点计数）"""
    # 1. 检查 Neo4j bolt 端口连通性
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("127.0.0.1", 7687))
        sock.close()
    except Exception:
        return "critical", 0, "Neo4j bolt 端口不可达（7687）"

    # 2. 查询 Episode 节点数量
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", "password"),
            connection_timeout=5
        )
        with driver.session() as session:
            result = session.run("MATCH (e:Episode) RETURN count(e) as cnt")
            count = result.single()["cnt"]
        driver.close()

        if count == 0:
            return "critical", count, "Neo4j 中无 Episode 节点（index 未初始化）"
        elif count < 100:
            return "warning", count, f"只有 {count} 条 episode（数据量偏低）"
        else:
            return "ok", count, f"{count} 条 Episode 节点（正常）"
    except ImportError:
        return "warning", 0, "neo4j Python 包未安装（无法检查）"
    except Exception as e:
        return "critical", 0, f"Neo4j 查询失败: {str(e)[:60]}"


def check_cron_jobs():
    """检查 cron jobs 状态（找 consecutiveErrors >= 3 的 job）"""
    # openclaw cron list --json 返回 {"jobs": [...]}
    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            jobs = data.get("jobs", data) if isinstance(data, dict) else data
            if isinstance(jobs, list) and jobs:
                failed = [j for j in jobs if j.get("state",{}).get("consecutiveErrors",0) >= 3]
                warn = [j for j in jobs if 0 < j.get("state",{}).get("consecutiveErrors",0) < 3]
                if failed:
                    names = "; ".join([j.get("name","?") for j in failed[:3]])
                    return "critical", len(failed), f"失败: {names}"
                elif warn:
                    names = "; ".join([j.get("name","?") for j in warn[:3]])
                    return "warning", len(warn), f"警告: {names}"
                else:
                    return "ok", len(jobs), f"全部 {len(jobs)} 个 job 正常"
    except FileNotFoundError:
        return "warning", 0, "openclaw CLI 不在 PATH"
    except json.JSONDecodeError:
        return "warning", 0, "cron list JSON 解析失败"
    except Exception as e:
        return "warning", 0, f"cron list 调用失败: {str(e)[:40]}"

    return "warning", 0, "无法获取 cron jobs 状态"


def check_context_brief():
    """检查 context-brief.md 新鲜度（>48h 未更新 = warning）"""
    if not BRIEF_FILE.exists():
        return "warning", 0, "context-brief.md 不存在"

    mtime = BRIEF_FILE.stat().st_mtime
    age_hours = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds() / 3600

    if age_hours > 72:
        return "critical", age_hours, f"超过 72h 未更新（{age_hours:.1f}h）"
    elif age_hours > 48:
        return "warning", age_hours, f"超过 48h 未更新（{age_hours:.1f}h）"
    else:
        return "ok", age_hours, f"新鲜（{age_hours:.1f}h 前更新）"


def check_sync_ledger():
    """检查 sync ledger drift（pending backfill）"""
    if not SYNC_LEDGER.exists():
        return "ok", 0, "sync ledger 不存在（从未同步）"

    try:
        with open(SYNC_LEDGER, "r", encoding="utf-8") as f:
            lines = f.readlines()

        pending = sum(
            1 for line in lines[-50:]
            if "pending_backfill" in line
        )
        total = len(lines)

        if pending > 0:
            return "warning", pending, f"有 {pending}/{total} 条 pending backfill"
        return "ok", total, f"{total} 条 ledger 记录（正常）"
    except Exception as e:
        return "warning", 0, f"ledger 读取失败: {str(e)[:40]}"


def check_temp_files():
    """检查并清理 workspace 临时文件"""
    temp_patterns = ["notion-temp"]
    found = []

    for f in WORKSPACE.glob("*"):
        if f.is_file() and any(p in f.name for p in temp_patterns):
            found.append(f.name)

    bp_dir = WORKSPACE / "builder-pulse"
    if bp_dir.exists():
        for f in bp_dir.glob("notion-temp*"):
            found.append(f"builder-pulse/{f.name}")

    if found:
        return "warning", len(found), f"发现临时文件: {', '.join(found[:5])}"
    return "ok", 0, "无临时文件"


# ==================== Phase 2: Think (Analysis) ====================

def analyze_stale_projects():
    """分析长期未推进的 OODA checkpoint"""
    stale = []
    if not CHECKPOINT_DIR.exists():
        return stale

    for f in CHECKPOINT_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            status = data.get("status", "")
            if status not in ("done", "aborted"):
                iter_num = data.get("iteration", 0)
                max_iter = data.get("max_iterations", 6)
                if iter_num >= max_iter - 1:
                    stale.append({
                        "goal": data.get("goal", f.name),
                        "status": status,
                        "iteration": iter_num,
                        "max": max_iter,
                        "file": f.name,
                    })
        except Exception:
            pass
    return stale


# ==================== Phase 3: Act (Remediation) ====================

def cleanup_temp_files():
    """清理临时文件"""
    cleaned = []
    temp_patterns = ["notion-temp"]
    bp_dir = WORKSPACE / "builder-pulse"

    for f in WORKSPACE.glob("*"):
        if f.is_file() and any(p in f.name for p in temp_patterns):
            try:
                f.unlink()
                cleaned.append(f.name)
            except Exception:
                pass

    if bp_dir.exists():
        for f in bp_dir.glob("notion-temp*"):
            try:
                f.unlink()
                cleaned.append(f"builder-pulse/{f.name}")
            except Exception:
                pass

    return cleaned


# ==================== Phase 4: Report ====================

def generate_report(checks, stale_projects, cleaned_files):
    """生成心跳报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# 🩸 心跳自检报告 — {now}\n")
    lines.append("> 由 heartbeat_systemic.py 自动生成\n")
    lines.append("---\n")

    severity_order = {"critical": 0, "warning": 1, "ok": 2, "unknown": 3}
    sorted_checks = sorted(checks, key=lambda x: severity_order.get(x[1], 3))
    crit = sum(1 for c in checks if c[1] == "critical")
    warn = sum(1 for c in checks if c[1] == "warning")
    ok = len(checks) - crit - warn

    lines.append("## 健康总览\n")
    lines.append(f"| 状态 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| 🔴 Critical | {crit} |")
    lines.append(f"| 🟡 Warning | {warn} |")
    lines.append(f"| ✅ OK | {ok} |")
    lines.append("")

    lines.append("## 检查项详情\n")
    for name, severity, value, detail in sorted_checks:
        icon = {"critical": "🔴", "warning": "🟡", "ok": "✅", "unknown": "❓"}.get(severity, "❓")
        lines.append(f"### {icon} {name}")
        lines.append(f"- **状态**: {severity.upper()} | **值**: {value}")
        lines.append(f"- **详情**: {detail}\n")

    if cleaned_files:
        lines.append("## 治理动作\n")
        lines.append(f"- **清理临时文件**: {', '.join(cleaned_files)}\n")

    if stale_projects:
        lines.append("## ⚠️ 长期未推进项目\n")
        for p in stale_projects:
            lines.append(f"- **{p['goal']}** (`{p['file']}`)")
            lines.append(f"  - 状态: {p['status']} | 迭代: {p['iteration']}/{p['max']}")
        lines.append("")

    if crit > 0:
        push_decision = "**🔴 CRITICAL — 需要立即关注**"
        push_needed = True
    elif warn > 0:
        push_decision = "**🟡 WARNING — 已记录，可后续处理**"
        push_needed = True
    else:
        push_decision = "**✅ ALL OK — 静默存档**"
        push_needed = False

    lines.append("## 推送决策\n")
    lines.append(f"{push_decision}\n")

    return "\n".join(lines), push_needed, crit, warn


def push_to_telegram(report_text):
    """推送报告到 Telegram 群聊（nohup 后台执行）"""
    try:
        summary = report_text[:1500]
        summary += "\n\n_完整报告已存档至 memory/heartbeat-YYYY-MM-DD.md_"
        msg = f"🩸 心跳自检报告\n\n{summary}"

        cmd = [
            "nohup", "openclaw", "agent",
            "--agent", "main",
            "--message", msg,
            "--deliver",
            "--reply-channel", "telegram",
            "--reply-to", TELEGRAM_CHAT,
        ]
        with open("/dev/null", "w") as devnull:
            subprocess.Popen(
                cmd, stdout=devnull, stderr=devnull,
                start_new_session=True
            )
        return True
    except Exception as e:
        print(f"⚠️ Telegram 推送启动失败: {str(e)[:100]}", file=sys.stderr)
        return False


# ==================== Main ====================

def run_health_check(critical_only=False):
    """执行健康检查"""
    checks = [
        ("MEMORY 容量",) + check_memory_capacity(),
        ("episodic index",) + check_episodic_index(),
        ("Cron jobs",) + check_cron_jobs(),
        ("context-brief 新鲜度",) + check_context_brief(),
        ("Sync ledger",) + check_sync_ledger(),
        ("临时文件",) + check_temp_files(),
    ]
    if critical_only:
        return [c for c in checks if c[1] in ("critical", "unknown")]
    return checks


def main():
    import argparse
    parser = argparse.ArgumentParser(description="heartbeat_systemic.py — 系统性心跳自检")
    parser.add_argument("--critical", action="store_true", help="只检查 critical 项（快速）")
    parser.add_argument("--report", action="store_true", help="只读取最新报告")
    args = parser.parse_args()

    print(f"🩸 heartbeat_systemic.py — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.report:
        today = datetime.now().strftime("%Y-%m-%d")
        report_file = MEMORY_DIR / f"heartbeat-{today}.md"
        if report_file.exists():
            print(report_file.read_text())
        else:
            print(f"今日报告不存在: {report_file}")
        return

    # Phase 1: Sense
    print("  [1/5] Sense — 健康检查...")
    checks = run_health_check(critical_only=args.critical)
    print(f"  完成，{len(checks)} 项检查")

    # Phase 2: Think
    print("  [2/5] Think — 分析长期项目...")
    stale = analyze_stale_projects()

    # Phase 3: Act
    print("  [3/5] Act — 清理临时文件...")
    cleaned = cleanup_temp_files()

    # Phase 4: Report
    print("  [4/5] Report — 生成报告...")
    report_text, push_needed, crit_count, warn_count = generate_report(checks, stale, cleaned)

    today = datetime.now().strftime("%Y-%m-%d")
    report_file = MEMORY_DIR / f"heartbeat-{today}.md"
    report_file.write_text(report_text, encoding="utf-8")
    print(f"  报告已写入: {report_file}")

    # Phase 5: Delivery
    if push_needed:
        print("  [5/5] 推送 Telegram...")
        push_to_telegram(report_text)
        print("  Telegram 推送已启动（后台 nohup）")
    else:
        print("  [5/5] 无需推送（静默存档）")

    # 摘要输出
    print(f"\n✅ 自检完成: {len(checks)} 项")
    print(f"   🔴 {crit_count} | 🟡 {warn_count} | ✅ {len(checks) - crit_count - warn_count}")
    if stale:
        print(f"   ⚠️ 长期未推进: {len(stale)} 个")
    if crit_count > 0:
        print("\n🔴 CRITICAL 告警:")
        for name, sev, val, detail in checks:
            if sev == "critical":
                print(f"   - {name}: {detail}")


if __name__ == "__main__":
    main()
