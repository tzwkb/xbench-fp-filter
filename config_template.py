"""
config_template.py
------------------
使用说明：
1. 复制本文件为 config.py
2. 把 LLM_API_KEY 改成你的真实密钥
3. config.py 已被 .gitignore 忽略，不会泄露到 Git
"""

LLM_API_KEY     = "your-api-key-here"
LLM_API_BASE    = "https://api.vectorengine.ai/v1"
LLM_MODEL       = "gemini-3.1-flash-lite"
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS  = 2048

# 向量检索决策阈值（仅 RAG 模式使用）
THRESHOLD_HIGH     = 0.99
THRESHOLD_LOW      = 0.60
SIM_WARN_THRESHOLD = 0.65
