# 开发计划 — 2026/04/28

**本轮范围：** 仅术语违规类型，其余 error_type 暂时搁置

---

## 一、数据结构变更

### 1.1 字段变更总览

| 字段 | 变更 | 说明 |
|---|---|---|
| `error_type` | 本轮只保留"术语违规" | 其他类型暂不测试 |
| `error_description` | 精简格式，仅用于向量检索 | 不进入 LLM prompt |
| `severity` | 新增 | 查询案例和入库案例都有，进入 LLM prompt |
| `false_alarm_reason` | 改名为 `reason` | 同时覆盖误报和真错误，详细描述，进入 LLM prompt |
| `reason`（原 LLM 输出字段） | 改名为 `llm_analysis` | 避免与新 reason 字段冲突 |

---

### 1.2 error_description（向量检索专用）

**只做向量化匹配，不进入 LLM prompt。**

格式固定为三元组，仅保留术语名、规定译名、实际译文：

```
{原文术语} | {规定译名} | {实际译文}
```

示例：
```
开封府 | Kaifeng Prefecture | Kaifeng
内力 | Internal Force | Internal Power
不羡仙 | Blissful Retreat | this place
```

**设计原则：** 语义密度高、噪音低，让 bge-m3 专注于匹配"同类术语错误模式"，不被冗长描述干扰。

---

### 1.3 severity（可选新增字段）

对应 MQM 2.0 四级标准，查询案例和入库案例都必须填，**进入 LLM prompt 作为判断参考**。

| 值 | MQM 对应 | 游戏本地化含义 |
|---|---|---|
| `Critical` | Critical | 角色名/核心剧情术语错误，玩家无法理解 |
| `Major` | Major | 重要 NPC 对话、关键地名/机构名错误 |
| `Minor` | Minor | 普通术语不一致，不影响游戏进行 |
| `Neutral` | Neutral | 冠词差异、轻微拼写变体 |

---

### 1.4 reason（原 false_alarm_reason 改名扩展）

**覆盖误报和真错误两种情况，详细描述判定依据，进入 LLM prompt。**

- 误报时：说明为什么不是错误（对应 A-G 规则）
- 真错误时：说明为什么是错误（对应 T1-T4 规则）

格式：`[规则] {规则编号}，{判定逻辑}`

示例：

```
# 误报
[规则] A，NPC 对玩家的角色称呼在英文口语中惯用 you/someone 替代，指代清晰，不构成术语漏译。

# 真错误
[规则] T2，开封府为官方司法机构，术语表规定译名 Kaifeng Prefecture，译文简称 Kaifeng 丢失机构属性，不属于合理简称豁免。
```

---

### 1.5 llm_analysis（原 reason 字段改名）

LLM 每次调用后输出的推理过程，仅用于日志和调试，不入案例库，不参与向量化。

---

### 1.6 数据库 Schema 变更

```sql
-- 新增 severity 字段
ALTER TABLE cases ADD COLUMN severity TEXT DEFAULT 'Minor';

-- 将 false_alarm_reason 数据迁移到 reason（新建列）
ALTER TABLE cases ADD COLUMN reason TEXT DEFAULT '';
UPDATE cases SET reason = false_alarm_reason;

-- 保留 false_alarm_reason 列做兼容，后续版本再删除
```

查询集 JSON 新增字段：

```json
{
  "error_type": "术语违规",
  "error_description": "开封府 | Kaifeng Prefecture | Kaifeng",
  "severity": "Major",
  "source_text": "来人，把此人押回开封府。",
  "target_text": "Guards, haul him off to Kaifeng.",
  "ground_truth": "真错误"
}
```

入库案例 JSON 新增字段：

```json
{
  "error_type": "术语违规",
  "error_description": "开封府 | Kaifeng Prefecture | Kaifeng",
  "severity": "Major",
  "source_text": "来人，把此人押回开封府。",
  "target_text": "Guards, haul him off to Kaifeng.",
  "review_label": "真错误",
  "reason": "[规则] 开封府为官方司法机构，译文简称丢失机构属性，不属于合理简称豁免。",
  "annotator": "产品组"
}
```

---

### 1.7 LLM Prompt 字段调整

| 字段 | 来源 | 是否进入 prompt |
|---|---|---|
| error_type | 查询案例 | ✓ |
| error_description | 查询案例 | ✓（让 LLM 知道当前错误是什么） |
| severity | 查询案例 | ✓ |
| source_text | 查询案例 | ✓ |
| target_text | 查询案例 | ✓ |
| error_description | 入库案例 | ✗ |
| severity | 入库案例 | ✓ |
| reason | 入库案例 | ✓（核心 Few-shot 依据） |
| review_label | 入库案例 | ✓ |

---

## 二、存量数据处理

### 2.1 从现有案例库提取术语类案例

从 110 条案例中筛出 error_type 包含"术语"的条目，用 LLM 按新格式翻新：

```python
import sqlite3

conn = sqlite3.connect("data/database/cases.db")
rows = conn.execute("""
    SELECT id, error_type, error_description, false_alarm_reason,
           source_text, target_text, review_label
    FROM cases
    WHERE error_type LIKE '%术语%'
""").fetchall()
conn.close()

print(f"找到 {len(rows)} 条术语类案例")
```

翻新内容（用 LLM 批量处理）：
1. `error_description` → 改为 `{原文术语} | {规定译名} | {实际译文}` 格式
2. `severity` → 根据原文内容判断填入 Critical/Major/Minor/Neutral
3. `reason` → 在原 false_alarm_reason 基础上补充规则编号，真错误案例补写 reason

---

## 三、生成测试数据

### 3.1 生成入库案例（案例库）

用 LLM 生成约 **60 条**术语违规案例入库，覆盖：
- 误报场景、真错误场景

每条包含完整字段：error_description、severity、source_text、target_text、review_label、reason。

### 3.2 生成查询案例（测试集）

用 LLM 独立生成约 **80 条**查询案例，与入库案例不重叠：
- 误报约 65 条，真错误约 15 条（保证真错误样本 ≥ 40 条的目标）
- 每条包含 ground_truth 标签，用于计算指标

**生成原则：**
- 入库案例和查询案例使用不同的游戏文本片段，避免检索时直接命中自身
- 真错误案例覆盖 T1-T4 四种规则，各至少 3 条
- severity 分布：Critical 10%，Major 40%，Minor 40%，Neutral 10%

---

## 四、代码改动范围

| 文件 | 改动内容 |
|---|---|
| `store.py` | 新增 severity 字段的 insert/query 逻辑；false_alarm_reason → reason 兼容处理 |
| `search.py` | 返回结果加入 severity、reason 字段；去掉 error_description 的返回（不传给 LLM） |
| `llm_review.py` | prompt 模板加入 severity；入库案例只展示 review_label + severity + reason；原 reason 输出字段改名为 llm_analysis |
| `run_test.py` | 查询集读取加 severity 字段；结果写入加 llm_analysis 字段 |
| `build_vector_text()` | 格式改为 `{error_type} {原文术语} | {规定译名} | {实际译文}` |

---

## 五、执行顺序

```
第一步  修改 store.py / search.py / llm_review.py / run_test.py（字段变更）
第二步  数据库迁移脚本（加 severity 列，false_alarm_reason → reason）
第三步  筛出存量术语案例，用 LLM 翻新格式，重建 FAISS 索引
第四步  用 LLM 生成入库案例（60 条）+ 查询案例（80 条）
第五步  跑测试，验证指标
```

> **注意：** 按顺序推进，数据准备和数据结构重构完成后再开始测试。测试过程中根据实际结果持续调试 prompt。

---

## 六、暂缓事项

| 事项 | 原因 |
|---|---|
| 其他 error_type（错译、漏译等） | 本轮聚焦术语，验证新数据结构后再扩展 |
| 数据库主-从结构重构 | 新结构验证后再决定是否值得投入 |
