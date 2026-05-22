# Xbench FP Filter

游戏本地化 QA 误报过滤工具。读取 Xbench 导出的 Excel 质检报告，通过 LLM 逐条判定是否为误报，输出过滤后报告和分析总表。

---

## 快速启动

```
run.bat
```

首次运行自动检测 Python：内嵌版 → 系统 PATH → 自动运行 `setup.bat` 下载。

或手动：

```
streamlit run app.py
```

首次运行前在 Streamlit「参数设置」页填入 API Key 和 Base URL。

---

## 目录结构

```
fp-filter/
├── app.py               Streamlit 页面路由、组件渲染、进度轮询
├── ui_backend.py        UI 与后端适配层：RunConfig、ProcessingTask、导出函数、模型管理
├── run.bat / setup.bat  Windows 一键启动 / 环境初始化（下载嵌入版 Python）
├── config.py / config_template.py  运行时配置及脱敏模板
├── requirements.txt     Python 依赖
│
├── core/                核心 LLM 模块
│   ├── xbench.py        Xbench Excel 解析 + 行过滤
│   └── llm_review.py    LLM 复核：prompt、async 调用、重试、结果解析
│
├── rag/                 向量检索层 ⚠️ 待完善（实验阶段，功能不完整）
│   ├── store.py         案例库（SQLite + FAISS + bge-m3 embedding）
│   ├── search.py        向量检索 + 决策路由
│   └── engine.py        RAGEngine：完整 RAG 流水线统一入口
│
├── scripts/             批量测试与评估
│   ├── run_test.py      RAG 批量测试入口
│   └── data_calculator.py  评估指标计算（精确率、召回率、F1、F2）
│
└── data/
    ├── database/        SQLite 案例库 + FAISS 索引
    ├── raw_data/        解析后的 JSON 缓存
    ├── custom_models.json   用户自定义模型列表（UI 写入）
    ├── report/          历史测试报告
    └── 已导入/           待导入的案例数据
```

**当前 UI 流程：** 解析 → LLM 独立判断，不走向量检索。
**RAG 后端** 代码框架已搭建但仍在完善中，尚未接入 UI 主流程。

---

## 配置

`config.py` 为运行时默认值，Streamlit UI 启动后通过「参数设置」页覆盖（`ui_backend.apply_config`）。

| 参数 | 说明 |
|---|---|
| `LLM_API_KEY` | API 密钥 |
| `LLM_API_BASE` | API Base URL（兼容 OpenAI 格式） |
| `LLM_MODEL` | 模型 ID |
| `LLM_TEMPERATURE` | 采样温度，建议 0.3 |
| `LLM_MAX_TOKENS` | 单次最大输出 token |
| `THRESHOLD_HIGH/LOW` | 向量检索决策阈值（仅 RAG 模式） |
| `SIM_WARN_THRESHOLD` | 向 LLM 提示低相似度参考的阈值 |

---

## RAG 后端接入

```python
from rag.engine import RAGEngine

engine = RAGEngine(
    db_path="data/database/cases.db",
    faiss_path="data/database/cases.faiss",
    llm_api_key="sk-xxx",
    llm_api_base="https://api.xxx/v1",
    llm_model="gemini-3.1-flash-lite",
)

result = engine.judge(
    error_type="术语违规",
    error_description="开封府 | Kaifeng Prefecture | Kaifeng",
    source_text="来人，把此人押回开封府。",
    target_text="Guards, haul him off to Kaifeng.",
)
```

当前 `ui_backend.process_file` 传入 `search_results=[]`，改为实际检索结果即可接回。

---

## 决策路由（RAG 模式）

| 路径 | 触发条件 | 处理 |
|---|---|---|
| `direct_pass` | sim ≥ 0.99 且命中误报案例 | 直接判误报，跳过 LLM |
| `llm_review` | sim ≥ 0.60 | LLM 结合检索案例二次判断 |
| `llm_independent` | sim < 0.60 或无匹配 | LLM 仅依据规则独立判断 |

---

## License

MIT
