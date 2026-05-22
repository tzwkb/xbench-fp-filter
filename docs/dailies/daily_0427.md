# 工作日报 — 2026/04/27

---

## 今日完成

### 1. 字段规范化（对齐行业标准）

参考 MQM 2.0 / DQF / LQA 游戏本地化行业标准，重新设计字段规范，输出 `field_standard.md`，核心变更：
- `error_type`：改为单值枚举，对齐 MQM 维度
- `error_description`：精简为结构化三元组（`{原文术语} | {规定译名} | {实际译文}`），仅用于向量检索
- `severity`：新增，对应 MQM Critical/Major/Minor/Neutral 四级
- `false_alarm_reason` → `reason`：改名并扩展，覆盖误报和真错误两种判定理由，详细描述供 LLM 参考
- `reason`（原 LLM 输出字段）→ `llm_analysis`：改名避免冲突

### 2. 代码实现（Step 1 + Step 2）

**Step 1：字段变更（4 个文件）**

| 文件 | 主要改动 |
|---|---|
| `store.py` | Case 加 severity/reason 字段；`build_vector_text` 改为 `{error_type} {error_description}`；insert 逻辑同步更新 |
| `search.py` | SearchResult 加 severity/reason；`to_llm_context` 去掉 error_description，改展示 severity + review_label + reason |
| `llm_review.py` | prompt 加 severity；输出字段 reason → llm_analysis；ReviewResult 同步改名 |
| `run_test.py` | 传 severity 给 LLM；结果写 llm_analysis |

**Step 2：数据库迁移**
- 现有 cases 表加 severity（默认 Minor）和 reason 两列
- 60 条有 false_alarm_reason 的案例数据已复制到 reason

### 3. 准备数据转换文件

筛出案例库中 64 条术语类案例，连同转换 prompt 一起写入 `data/raw_data/terminology_cases_to_convert.json`，供明日用 LLM 批量翻新格式。

---

## 明日计划

1. 用 LLM 转换 64 条术语案例（新 error_description + severity + reason 格式），人工抽检后入库重建索引
2. 用 LLM 生成入库案例（约 60 条）和查询案例（约 80 条，真错误 ≥40 条）

---

## 当前系统状态

| 项目 | 状态 |
|---|---|
| 代码字段变更 | ✅ 完成 |
| 数据库迁移 | ✅ 完成 |
| 案例库转换 | ⏳ 待执行（JSON 已准备好） |
| 新测试数据生成 | ⏳ 待执行 |
| 推荐部署版本 | 第七轮配置（误报识别率 74.7%，真错误保护率 90.9%） |
