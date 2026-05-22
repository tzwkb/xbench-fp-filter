# 2026-04-29 变更日志

## 归档清单

### 数据文件（data/raw_data/20260429/）

| 文件 | 轮次 | 说明 |
|------|------|------|
| test_20260429b_llm.json | 0429b | BCE Reranker 集成测试 |
| test_20260429b_vector.json | 0429b | 向量检索结果 |
| test_20260429c_llm.json | 0429c | Prompt 大幅放宽 |
| test_20260429c_vector.json | 0429c | 向量检索结果 |
| test_20260429d_llm.json | 0429d | Prompt 收紧平衡 |
| test_20260429d_vector.json | 0429d | 向量检索结果 |
| test_20260429e_llm.json | 0429e | st+tt 入向量（旧 GT 最佳） |
| test_20260429e_vector.json | 0429e | 向量检索结果 |
| test_20260429f_vector.json | 0429f | 向量检索结果（无 llm） |
| test_20260429g_llm.json | 0429g | st+tt + reranker 组合 |
| test_20260429g_vector.json | 0429g | 向量检索结果 |
| test_20260429h_llm.json | 0429h | 场景分类 prompt（已回滚） |
| test_20260429h_vector.json | 0429h | 向量检索结果 |
| test_20260429i_llm.json | 0429i | 0428f prompt + 新 GT |
| test_20260429i_vector.json | 0429i | 向量检索结果 |
| test_20260429j_llm.json | 0429j | 固定 few-shot + 放宽 A/B |
| test_20260429j_vector.json | 0429j | 向量检索结果 |
| test_20260429k_llm.json | 0429k | 固定 few-shot 最后 + A/B 一律可接受 |
| test_20260429k_vector.json | 0429k | 向量检索结果 |

### 报告文件（data/report/20260429/）

| 文件 | 轮次 | 说明 |
|------|------|------|
| test_20260429b_report.md | 0429b | Reranker 报告 |
| test_20260429b_result.xlsx | 0429b | 逐条明细 |
| test_20260429c_report.md | 0429c | Prompt 放宽报告 |
| test_20260429c_result.xlsx | 0429c | 逐条明细 |
| test_20260429d_report.md | 0429d | Prompt 收紧报告 |
| test_20260429d_result.xlsx | 0429d | 逐条明细 |
| test_20260429e_report.md | 0429e | st+tt 报告 |
| test_20260429e_result.xlsx | 0429e | 逐条明细 |
| test_20260429g_report.md | 0429g | st+tt+reranker 报告 |
| test_20260429g_result.xlsx | 0429g | 逐条明细 |
| test_20260429h_report.md | 0429h | 场景分类报告 |
| test_20260429h_result.xlsx | 0429h | 逐条明细 |
| test_20260429i_report.md | 0429i | 回滚+新 GT 报告 |
| test_20260429i_result.xlsx | 0429i | 逐条明细 |
| test_20260429j_report.md | 0429j | 固定 few-shot 报告 |
| test_20260429j_result.xlsx | 0429j | 逐条明细 |
| test_20260429k_report.md | 0429k | few-shot 最后 + A/B 一律报告 |
| test_20260429k_result.xlsx | 0429k | 逐条明细 |
| review_annotation_0429.xlsx | — | 实习生标注包 |

---

## 代码变更

### llm_review.py

| 变更 | 说明 |
|------|------|
| 固定 few-shot（8 条） | 覆盖代词替代、泛指替代、语境意译、同义替换四种误报模式 |
| 固定 few-shot 位置 | 从 prompt 顶部 → 移到复核步骤之前 |
| 动态 few-shot 弱化 | "系统自动检索，可能存在标签冲突，仅供参考" |
| A 规则放宽 | "上下文能明确指代" → "只要不影响理解即可接受" |
| B 规则放宽 | "语义清晰时可接受" → "一律可接受" |
| LLM 重试机制 | `_MAX_RETRIES = 5`，`timeout = 90s`，间隔 2 秒 |
| 复核步骤 | "固定案例优先级高于动态检索案例" |

---

## 今日里程碑

| 里程碑 | 数值 | 轮次 |
|--------|------|------|
| **F2 首次突破 0.80** | **0.830** | 0429k |
| **FA 首次突破 85%** | **88.1%** | 0429k |
| TE 最高 | 93.2% | 0429i |
| 准确率最高 | 85.5% | 0429k |
| 重试机制上线 | 5 次/90s | 0429k |

---

## 关键结论

1. **固定 few-shot 是有效策略**：将代表性误报案例作为固定参考，直接让 FA 从 52% → 88%（+36%）
2. **位置至关重要**：固定 few-shot 放在 prompt 末尾（LLM 记忆最新）比放在顶部更有效
3. **prompt 调优天花板已触**：0429c/d/h 反复证明跷跷板效应
4. **数据质量是 binding constraint**：47 条真实数据仅 47.6%，LLM 生成数据与真实场景存在鸿沟

---

## 下一步

- **0429l**：在 0429j（TE 88%, FA 76%）和 0429k（TE 84.6%, FA 88.1%）之间找平衡
- 目标：TE ≥85%, FA ≥75%, F2 ≥0.80 同时达标
