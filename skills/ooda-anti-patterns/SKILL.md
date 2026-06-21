---
name: ooda-anti-patterns
version: 1.0
description: |
  OODA 闭环反模式检测。在 ooda-driver.py 的 generate_prompt() 中实时检测
  三种破坏性模式：blind retry / phantom progress / pivot exhaustion。
  检测结果注入 agent prompt，强制执行终态保护。
trigger: |
  自动集成到 ooda-driver.py，每次生成 prompt 时执行。
  不需要人类触发。
---

# ooda-anti-patterns — OODA 闭环反模式检测

## 三种反模式

### 1. blind_retry（盲目重试）— 🔴 CRITICAL

**定义**：连续两次执行完全相同的 action。

**检测逻辑**：
- 读取 checkpoint 的 `_history` 列表
- 比较 `history[-1].action` 与当前 `selected_action`
- 完全匹配 → 触发 blind_retry

**危害**：第 2 次重复后立即触发 STUCK 终态，闭环终止。

**Agent 响应**：
```
⚠️ 反模式警告 [blind_retry — CRITICAL]
连续两次执行了相同的 action（"执行 git status"...）。
第 2 次重复将直接触发 STUCK 终态。
→ 建议立即切换思路或改变动作
```

---

### 2. phantom_progress（幽灵进展）— 🟡 WARNING

**定义**：最近 3 次 observation 文本高度相似（关键词重叠 > 70%），没有真实进展。

**检测逻辑**：
- 收集 `current_observation` + `history[-2:]` 共 3 条
- 对每对计算关键词重叠率（分词：按空格/标点分割，取 >2 字符的词）
- 连续 2 对重叠率 > 70% → 触发 phantom_progress

**危害**：agent 在执行同样的操作但期望不同结果（第一性原理违反）。

**Agent 响应**：
```
⚠️ 反模式警告 [phantom_progress — WARNING]
最近 3 次观察高度重叠（100%），没有真实进展。
建议 pivot 改变方向。
→ 建议 PIVOT，换一个完全不同的思路或工具组合
```

---

### 3. pivot_exhaustion（枢轴耗尽）— 🔴 CRITICAL

**定义**：2+ 次 pivot（改变方向）但仍无进展，超过耐受极限。

**检测逻辑**：
- 读取 checkpoint 的 `_pivot_count` 字段
- 检查 `history[-pivot_count:]` 中是否有任何 `verification_result == "pass"`
- 2+ 次 pivot 且无 pass → 触发 pivot_exhaustion

**危害**：超过 max_consecutive_failures 限制，闭环终止。

**Agent 响应**：
```
⚠️ 反模式警告 [pivot_exhaustion — CRITICAL]
已 pivot 2 次但无任何进展。超过 pivot 耐受极限。
→ 连续失败 3 次 → 终态 = STUCK，闭环终止
```

---

## 实现位置

`{ARS_ROOT}/scripts/ooda-driver.py` → `detect_anti_patterns()` 函数

## 历史追踪字段

checkpoint 中需要维护的字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `_history` | `list[dict]` | 每次 act 后追加 `{"action", "observation", "verification_result"}` |
| `_pivot_count` | `int` | pivot 次数，每次 pivot +1 |

## 与 ooda-loop Skill 的集成

在 `ooda-loop/SKILL.md` 的 verify 步骤中追加：

```
更新 _history 中最后一条的 verification_result
如果 selected_action 与上次相同 → blind_retry 警告
如果 pivot 后 2 次仍无进展 → pivot_exhaustion 警告
```

## 反模式 vs 正常重试

| 场景 | 类型 | 处理 |
|------|------|------|
| 验证失败重试，但改进了 action | 正常 | 不触发反模式 |
| 验证失败重试，action 完全相同 | blind_retry | CRITICAL → STUCK |
| 连续 3 次 observation 相同 | phantom_progress | WARNING → 建议 PIVOT |
| 2 次 pivot 后仍失败 | pivot_exhaustion | CRITICAL → STUCK |

## 算法细节

### 关键词重叠率

```python
def _keyword_overlap(a: str, b: str) -> float:
    # 1. 分词：正则 r'[^\w]+'，取 >2 字符的词
    words_a = set(w.lower() for w in re.split(r'[^\w]+', a) if len(w) > 2)
    words_b = set(w.lower() for w in re.split(r'[^\w]+', b) if len(w) > 2)
    # 2. Jaccard 相似度
    return len(words_a & words_b) / len(words_a | words_b)
```

**为什么不用向量余弦**：轻量、确定性、无 API 依赖、足够准确。

## 与 ACK loop_engine 的区别

ACK 检测 3 种反模式（blind retry / phantom progress / pivot exhaustion），
ARS 在此基础上增加了：
- 连续失败计数（consecutive_failures）保护
- pivot 计数（_pivot_count）显式追踪
- 每次 prompt 生成时实时检测，不是轮次结束后检测
