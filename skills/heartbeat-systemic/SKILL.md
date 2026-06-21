---
name: heartbeat-systemic
version: 1.0
description: |
  系统性心跳自检脚本。每 6 小时执行 Sense→Think→Act→Report→Remember 五步循环，
  检查 MEMORY/episodic/Cron/context-brief/sync/temp 六项健康指标。
  Critical 告警推送到配置的通知渠道。
trigger: |
  使用 heartbeat_systemic.py cron job 执行。
  不需要人类触发，是完全自治的维护循环。
---

# heartbeat-systemic — 系统性心跳自检

## 概念

参考 ACK Generic Heartbeat 的 Sense→Think→Act→Report→Remember 五步循环，但：
- 更频繁（每 6 小时 vs ACK 的每周日）
- 面向项目健康而非 Agent 自我维持
- 直接修复能力（清理临时文件）

## 五步循环

```
┌─────────────────────────────────────────────────────────┐
│              HEARTBEAT SYSTEMIC CYCLE                   │
│                                                        │
│  1. SENSE    — 执行 6 项健康检查                        │
│     • MEMORY.md 容量                                    │
│     • Episodic index (Neo4j Episode 节点)                │
│     • Cron jobs 状态（consecutiveErrors >= 3）           │
│     • context-brief.md 新鲜度                            │
│     • Sync ledger drift                                 │
│     • Workspace 临时文件                                │
│                                                        │
│  2. THINK    — 分析模式                                │
│     • 识别长期未推进的 OODA checkpoint                  │
│                                                        │
│  3. ACT      — 执行治理                                │
│     • 清理 notion-temp*.sh 等临时文件                   │
│                                                        │
│  4. REPORT   — 生成报告                                │
│     • 写入 memory/heartbeat-YYYY-MM-DD.md              │
│     • Critical/Warning → 推送到 Telegram 群聊            │
│                                                        │
│  5. REMEMBER — 记录                                     │
│     • 报告已存档，计入审计跟踪                          │
└─────────────────────────────────────────────────────────┘
```

## 检查项详情

| # | 检查项 | OK | Warning | Critical |
|---|--------|----|---------|----------|
| 1 | MEMORY.md 容量 | < 80KB | 80-105KB | > 105KB |
| 2 | Neo4j Episode 节点 | ≥ 100 | 10-99 | < 10 或不可达 |
| 3 | Cron jobs | 无失败 | 1-2 次错误 | ≥3 次连续错误 |
| 4 | context-brief 新鲜度 | < 48h | 48-72h | > 72h |
| 5 | Sync ledger | 无 pending | 有 pending | — |
| 6 | 临时文件 | 无 | 有 | — |

## 核心脚本

**路径**：`{WORKSPACE}/scripts/heartbeat_systemic.py`

```bash
# 全量自检（每 6 小时 cron 触发）
python3 heartbeat_systemic.py

# 只检查 critical 项（快速）
python3 heartbeat_systemic.py --critical

# 只读最新报告
python3 heartbeat_systemic.py --report
```

## Cron Job 配置

```json
{
  "name": "🩸 心跳自检（系统性）",
  "schedule": {"kind": "cron", "expr": "0 */6 * * *", "tz": "Asia/Shanghai"},
  "payload": {"kind": "agentTurn", "message": "执行系统性心跳自检..."},
  "sessionTarget": "isolated",
  "delivery": {"mode": "announce", "channel": "telegram", "to": "$TELEGRAM_CHAT_ID"}
}
```

## 报告输出路径

- 存档：`{WORKSPACE}/memory/heartbeat-YYYY-MM-DD.md`
- Telegram：自动推送摘要到配置的群聊

## 报告格式

```markdown
## 健康总览
| 🔴 Critical | 🟡 Warning | ✅ OK |

## 检查项详情
### 🔴 [检查项名]
- 状态: CRITICAL | 值: ...
- 详情: ...

## 治理动作
- [执行的操作]

## ⚠️ 长期未推进项目
- [项目名] (状态: ... | 迭代: X/Y)
```

## 与 ACK Generic Heartbeat 的区别

| 维度 | ACK | ARS heartbeat-systemic |
|------|-----|----------------------|
| 频率 | 每周日 | 每 6 小时 |
| 推送 | Discord | Telegram 群聊 |
| Cron jobs 检查 | ✅ | ✅ |
| Neo4j Episodic | ✅ (通过 episodic_index) | ✅ (直接查 Episode 节点) |
| MEMORY 容量 | ✅ | ✅ |
| 临时文件清理 | ❌ | ✅ |
| OODA checkpoint 分析 | ❌ | ✅ |

## 依赖

- Neo4j 运行中（bolt://localhost:7687）
- openclaw cron list CLI（检查 jobs 状态）
- `GEMINI_API_KEY`（向量检索，可选，不影响心跳）
