# Decision Log

本目录保留 AgentMesh Runtime 从「OpenClaw 内部脚手架 `agent-reinforcement-system`」走向「公开开源 runtime」过程中的**核心决策文档**。按时间顺序排列。

## 时间线

| 日期 | 作者 | 文档 | 状态 |
|---|---|---|---|
| 2026-06-18 | Claude Code | [产品化方案](2026-06-18-claude-产品化方案.md) | ⚠️ 已升级 → 2026-06-21 |
| 2026-06-18 | Codex (GPT-5) | [商业化架构分析](2026-06-18-codex-commercialization-analysis.md) | 部分采纳（横向 infra 定位等） |
| 2026-06-18 | Claude Code | [技术尽调与综合结论](2026-06-18-claude-技术尽调与综合结论.md) | ✅ 已成为决策依据 |
| 2026-06-19 | Codex (GPT-5) | [交叉评审综述](2026-06-19-codex-交叉评审综述.md) | 部分采纳（多租户隔离、可观测性等） |
| 2026-06-21 | Claude Code（执笔）+ 用户拍板 | [最终方向决策](2026-06-21-final-direction.md) | ✅ **当前执行依据** |

## 关键转折点（2026-06-21）

用户指出：

> "我的智能体直接使用这一套，它自身就自带 LLM，根本不需要抽象相关的层出来。"

这一观察把整套「两仓 + 私有 server + LLM 智能层 + core 计费」方案**塌缩**为「单仓 Apache 2.0 全开源、不做 server 智能层」。

理由也变硬了：之前与 Codex 的事实裁决（见技术尽调文档）已确认，被列为「server 护城河」的 OODA Policy / Verification / Hybrid Memory hosted quality / Anti-pattern KB 在**当前代码里全部不存在**——是「未来要新建」而不是「现有 IP」。既然不存在，就没有要保护、要藏在 server 后面的算法。

## 阅读顺序建议

如果你只看一篇，看 [2026-06-21-final-direction.md](2026-06-21-final-direction.md)（当前执行方案）。

如果你想理解为什么走到这一步，按时间线读全部 5 篇。

## 跨 agent 协作的方法论

这套文档同时是「**Claude Code 和 Codex 跨模型对话产出决策**」的样本。两个 AI 都不互相奉承、都拿代码 `文件:行号` 作为分歧裁决依据，最终在事实地基上收敛。可作为后续类似多 agent 协作的参考。
