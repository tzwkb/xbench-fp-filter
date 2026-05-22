# 工作日报 — 2026/04/28

---

## 今日完成

### 1. 项目接手与文档梳理

- 阅读全部文档：handoff_0428、dev_guide_0424、metrics_guide、field_standard
- 识别核心问题：LLM 生成数据存在标签冲突，direct_pass 机制放大检索层错误
- 创建 `docs/test_log_0428.md`，同步更新 `README.md`（完整项目介绍）

### 2. 代码修复与模块化

- **禁用 direct_pass**：修改 `search.py` `decide()`，所有命中走 `llm_review`
- **Prompt T1 补充**：`llm_review.py` 增加"技能/属性/道具名属于强制统一术语，不适用规则 E 豁免"
- **修复 Excel KeyError**：`run_test.py` `_write_excel` 用 `.get()` 替代直接访问
- **提取 data_calculator**：将报告生成逻辑从 `run_test.py` 拆分为独立模块

### 3. 数据层修正（两轮）

**Query set GT 修正（23 条）**：
- 将 23 个 query 从"误报"改为"真错误"
- 典型：特定术语被代词/泛指替代（如"不羡仙→here"、"秦川→those lands"）
- Query set 分布从 63/96 变为 40/119

**Case library 标签修正（Batch1 + Batch2，共 22 条）**：
- Batch1（5 条）：case_id=88/66/77 改标签，81/70 改 description
- Batch2（17 条）：case_id=92,48,87,70,90,94,96,93,68,91,89,71,57,81,99,82,86 从误报改为真错误
- 效果：TE 从 58.3% → 95.8%，是今日最有效的干预

### 4. 八轮测试（0428a ~ 0428h）

| 轮次 | 改动 | TE | FA | 结论 |
|------|------|-----|-----|------|
| 0428a | 原始基线 | 58.3% | **88.9%** | direct_pass 误压 40 条真错误 |
| 0428b | 禁用 direct_pass + T1 补充 | 81.2% | 74.6% | 止损有效，但 FA 下滑 |
| 0428c | batch1 修正 + temp=0.3 | 89.6% | 60.3% | TE 接近 90%，FA 骤降 |
| 0428d | 23 query GT 修正 | 81.5% | **95.0%** | GT 修正后 query 更真实 |
| 0428e | batch2 修正（17 条） | **95.8%** | 42.5% | 数据修正效果最大 |
| **0428f** | **隐藏标签 + 条件 direct_pass** | **94.1%** | **60.0%** | ✅ **当前最佳基线** |
| 0428g | Prompt 加 A/B/E 覆盖 T1 | 88.2% | 67.5% | TE 跌破 90%，不可取 |
| 0428h | 入库 15 个误报案例 | 72.3% | 97.5% | ❌ 已回退（TE 暴跌） |

**关键发现：**
1. 数据修正（case library + query GT）比 prompt 调优有效 10 倍以上
2. 高相似度区间（≥0.80）比中低区间更危险（FA 识别率 53.8% vs 94.7%）
3. 隐藏标签/相似度可切断 LLM 跟票，但无法解决 LLM 对"强制术语"理解过宽的问题
4. **不能同时存在语义相近但标签相反的案例入库**——0428h 灾难性结果已验证

### 5. 文档输出

- `docs/test_log_0428.md`：八轮完整测试记录 + 跨轮深度分析
- `docs/devplan_0429.md`：明日开发计划（P0 数据 review + P1 Reranker）
- `README.md`：面向实习生的项目介绍
- `data/raw_data/cases_export_0428.json`：案例库 JSON 导出

---

## 当前系统状态

| 项目 | 状态 |
|---|---|
| 案例库规模 | **124 条**（0428h 入库的 15 条已回退） |
| 查询集规模 | 159 条（真错误 119 / 误报 40） |
| 最佳基线 | **0428f**：TE 94.1%, FA 60.0% |
| 代码状态 | search.py / llm_review.py / run_test.py / data_calculator.py 已更新 |
| 待复核率 | 3.8%（6/159，主要是 LLM 429/超时） |

---

## 明日计划（详见 devplan_0429.md）

### P0：数据层人工 Review（上午）
- Review 15 个被错杀的误报 + 7 个被漏杀的真错误
- 确认 GT 标签是否正确，修正 case library 中高频案例的 reason
- 跑 0429a 测试，看数据修正后基线

### P1：Reranker 集成（下午）
- 下载 `BCE Reranker Base v1`
- 开发 `rerank.py`，改造 `search.py` 召回逻辑
- 跑 0429b 测试，对比数据修正 vs 数据修正+Reranker

### P2：稳定性优化（间隙）
- Temperature 回退 0.3→0 测试
- 如需，实现 LLM 重试机制

---

## 注意事项

1. **当前 case library 已回退到 124 条**，FAISS 124 向量
2. **不要同时入库语义相近但标签相反的案例**
3. **Prompt 工程天花板已现**，继续调规则豁免会牺牲 TE
4. 备份：`cases.db.bak_0427`（原始）、`cases.db.bak_0428b`（batch1 后）、`cases.db.bak_0428d`（GT 修正后）
