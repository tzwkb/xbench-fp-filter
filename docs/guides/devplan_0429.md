# 开发计划 — 2026/04/29

## 一、目标

基于 0428f 基线（TE 94.1%, FA 60.0%），通过**数据质量提升 + Reranker 精排**，将误报识别率提升至 **75%+**，同时保持真错误保护率 **≥90%**。

---

## 二、任务清单

### P0：数据层人工 Review（预计 2-3 小时，ROI 最高）

**背景**：当前 15 个误报被错杀 + 7 个真错误被漏杀，根本原因是 query set 和 case library 的标注标准不一致。今天已证明：调 prompt 和入库案例都无法在不牺牲 TE 的前提下大幅提升 FA。

**具体工作**：
1. **Review 15 个被错杀的误报**（0428f 报告第四章）
   - 确认这些 query 的 GT 标签是否确实应为"误报"
   - 特别关注：人物称谓代词化（大人→My lord/you）、地名口语省略（不羡仙→here）、通用概念意译（真气→vital energy）
   - 输出：确认无误的保留，GT 标错的修正

2. **Review 7 个被漏杀的真错误**（0428f 报告第三章）
   - 开封府→Kaifeng Court / the authorities
   - 孤云→Guyun Pavilion / that group
   - 芥子庐→[Missing]
   - 驿站→Station
   - 玄元教首领→him
   - 确认这些是否确实是真错误，还是 GT 标严了

3. **Review case library 中高频激活案例**（Top-10）
   - case_id 115（孤云）、101（秦川）、107（开封府）等被频繁命中
   - 检查这些案例的 reason 是否过于宽泛，导致不同语境的 query 被错误匹配
   - 必要时细化 reason（如注明"此规则仅适用于门派/角色名语境"）

**验收标准**：
- 修正后的 query set 重新跑 0429a 测试，对比 0428f 的 TE/FA 变化
- 若 FA 提升 ≥10% 且 TE 保持 ≥90%，视为有效

---

### P1：Reranker 集成与验证（预计 4-6 小时）

**背景**：用户提议使用 `BCE Reranker Base v1` 在向量检索后做精排。该模型基于 Cross-Encoder，能理解 query 与 case 的细微语境差异。

**具体工作**：
1. **环境准备**
   - 下载 `BCE Reranker Base v1`（百度开源，约 300MB）
   - 验证本地运行（PyTorch / transformers）

2. **模块开发：rerank.py**
   - 封装 Reranker 接口：`rerank(query_text, candidates) -> reranked_list`
   - 输入：query 的 error_description + source_text + target_text
   - 输入：case 的 error_description + reason + source_text + target_text
   - 输出：重排序后的 case 列表 + 新的相关性分数

3. **改造 search.py**
   - `search_similar()`：召回从 top-5 扩大到 top-10（给 Reranker 更多候选）
   - 召回后调用 `rerank()` 取 top-3
   - `decide()` 使用 Reranker 分数替代原始 FAISS 相似度
   - 注意：需要重新标定阈值（Reranker 分数分布与余弦相似度不同）

4. **阈值调优**
   - 先跑 `--skip-llm` 模式，只看检索质量
   - 对比：原始 top-1 相似度 vs Reranker top-1 分数
   - 观察 Reranker 是否能将"相反标签高相似度"的案例压下去

5. **全流程测试**
   - 跑 0429b 测试（带 Reranker）
   - 对比 0429a（数据修正后）和 0429b（数据修正 + Reranker）

**验收标准**：
- Reranker 集成后系统能正常运行，无报错
- 0429b 的 TE ≥ 90% 且 FA ≥ 65%（比 0428f 的 60% 有提升）
- 若 FA 无提升或 TE 下降，记录 Reranker 的局限性，决定是否保留

---

### P2：稳定性优化（预计 1 小时，间隙做）

**背景**：0428f 有 6 个待复核（3.8%），主要是 LLM 429 / 超时。当前 `LLM_TEMPERATURE = 0.3`。

**具体工作**：
1. **Temperature 回退测试**
   - 将 `LLM_TEMPERATURE` 从 0.3 改回 0
   - 跑 0429c 测试（仅改 temperature，其他不变）
   - 对比超时率和结果一致性

2. **如果 429 错误频繁**
   - 在 `llm_review.py` 中加入指数退避重试（retry with backoff）
   - 或加入请求速率限制（rate limiter）

**验收标准**：
- 待复核率从 3.8% 降到 ≤2%
- 结果稳定性提升（同一 query 多次运行结果一致）

---

### P3：Case Library 结构化（可选，预计 2 小时）

**背景**：当前 case library 只有 error_type + error_description + reason，缺少"适用场景"信息。

**具体工作**：
1. **评估是否需要新增字段**
   - `context_type`：UI / 对话 / 叙述 / 技能描述
   - `term_category`：专有名词（门派/角色/地名）/ 通用概念 / 场所通称
   
2. **如果加字段**
   - 修改 `store.py` 的 Case dataclass 和数据库表结构
   - 给高频案例（Top-10）手动标注 context_type
   - 在 `search.py` 中加入按 context_type 过滤逻辑

**验收标准**：
- 仅在 Reranker 效果不佳时启动，作为备选方案

---

## 三、执行顺序

```
上午：P0 数据层 Review
      ↓
中午：跑 0429a 测试（数据修正后基线）
      ↓
下午：P1 Reranker 集成
      ↓
傍晚：跑 0429b 测试（数据 + Reranker）
      ↓
晚上：对比 0429a vs 0429b，决定保留/回退 Reranker
      ↓
间隙：P2 Temperature 回退测试（如果 P1 顺利）
```

---

## 四、决策树

```
0429a（数据修正后）结果如何？
├── FA ≥ 75% 且 TE ≥ 90%
│   └── ✅ 目标达成，P1 Reranker 作为锦上添花验证
├── FA 有提升（65-75%）但不够
│   └── 继续 P1 Reranker，看能否补足到 75%
└── FA 无提升或 TE 下降
    └── 说明 GT 标签本身有系统性偏差，需要更深入的数据清洗

0429b（+Reranker）结果如何？
├── FA 提升 ≥5% 且 TE 保持
│   └── ✅ 保留 Reranker，作为系统标配
├── FA 无提升
│   └── Reranker 在当前数据上效果有限，记录结论后回退代码
└── TE 下降
    └── ❌ Reranker 引入了新问题，回退代码，专注 P0+P2
```

---

## 五、风险与备案

| 风险 | 概率 | 备案 |
|------|------|------|
| Reranker 推理太慢（Cross-Encoder 比 Bi-Encoder 慢 5-10 倍） | 中 | 只给 top-5 做 rerank，不是 top-10；或换更小的模型 |
| Reranker 无法区分标签冲突案例 | 高 | 这是预期内的，Reranker 不是万能药，效果不好就回退 |
| 数据 Review 发现大量 GT 错误 | 中 | 这是好事，修正后系统指标会更真实 |
| Temperature 回退后超时更多 | 低 | 保持 0.3，或实现重试机制 |

---

## 六、今日基线（0428f）

| 指标 | 数值 | 目标（0429 结束） |
|------|------|-----------------|
| 真错误保护率 | 94.1% | ≥ 90% |
| 误报识别率 | 60.0% | ≥ 75% |
| 待复核率 | 3.8% | ≤ 2% |
| 人工队列压缩率 | 19.5% | — |
| 平均检索相似度 | 0.856 | — |
