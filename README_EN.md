# Xbench FP Filter

[中文](README.md) | English

## Overview

 Game-localization QA false-positive filter that reads Xbench Excel reports and uses an LLM to classify false positives.

## Key Capabilities

- Evaluates Xbench QA entries one by one.
- Outputs filtered reports and analysis workbooks.
- Targets game-localization QA review workflows.

## Usage

 Prepare the Xbench Excel report, API configuration, and output directory as described below.

## Status

 This repository is maintained or used according to the current README notes.

## Notes

 LLM classifications should be spot-checked by QA/localization staff.

## Command and Configuration Reference

The following code blocks are preserved from the primary README. Commands, paths, and configuration keys are not translated; adjust them for the actual environment.

```
run.bat
```

```
streamlit run ui/app.py
```

```
fp-filter/
├── ui/                  前端模块
│   ├── app.py           Streamlit 页面路由、组件渲染、进度轮询
│   └── backend.py       UI 与后端适配层：RunConfig、ProcessingTask、导出函数、模型管理
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

## Detailed Technical Notes

The primary README keeps the original technical details, history notes, full commands, and file layout. This file maintains the English version of the core documentation; consult the primary README code blocks and paths when exact commands are needed.
