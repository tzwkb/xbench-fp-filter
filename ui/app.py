"""
app.py
------
Streamlit UI — False Positive Filter for game localization QA.
Professional Engineering Edition.

Run:
    streamlit run ui/app.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui.backend import (
    RunConfig, default_config_from_module, apply_config,
    process_file, build_filtered_xlsx, build_analysis_xlsx, build_zip_bytes,
    test_api_connection,
    get_all_models, add_custom_model, remove_model, PRESET_MODELS,
    start_processing_task, ProcessingTask,
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Xbench FP Filter",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── UI 微调 (无破坏性隐藏，确保侧边栏功能正常) ──────────────────────────────────
st.markdown("""
<style>
    /* 仅隐藏底部 Streamlit 水印，保留顶部 header 以确保侧边栏按钮正常工作 */
    footer { visibility: hidden; }
    
    /* 优化全局字体，偏向技术风格 */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }

    /* 数据看板卡片规范化 */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetric"] label {
        color: #475569 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #0f172a !important;
        font-size: 1.6rem !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

if "cfg" not in st.session_state:
    _cfg    = default_config_from_module()
    _models = get_all_models()
    if _models and _cfg.model not in _models:
        _cfg.model = _models[0]
    st.session_state.cfg = _cfg
if "sel_model" not in st.session_state:
    _models = get_all_models()
    _m = st.session_state.cfg.model
    st.session_state.sel_model = _m if _m in _models else (_models[0] if _models else "")
if "page"           not in st.session_state:
    st.session_state.page = "filter"
if "results"        not in st.session_state:
    st.session_state.results = []
if "file_bytes_map" not in st.session_state:
    st.session_state.file_bytes_map = {}
if "api_status"     not in st.session_state:
    st.session_state.api_status = None
if "task"           not in st.session_state:
    st.session_state.task = None
if "zip_cache"      not in st.session_state:
    st.session_state.zip_cache = None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Xbench FP Filter")
    st.caption("游戏本地化 QA 误报筛查工具")
    st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)

    nav_items = [
        ("filter",   "🔍 误报筛查"),
        ("settings", "⚙️ 参数设置"),
        ("about",    "📖 使用说明"),
    ]
    for key, label in nav_items:
        if st.button(
            label, key=f"nav_{key}", use_container_width=True,
            type="primary" if st.session_state.page == key else "secondary",
        ):
            st.session_state.page = key
            st.rerun()

    st.markdown("<div style='margin: 1.5rem 0;'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Page: 误报筛查
# ══════════════════════════════════════════════════════════════════════════════

def page_filter():
    st.markdown("### 误报筛查")
    st.caption("上传 Xbench 报告，系统将自动识别并过滤由于排版、变量等引起的误报噪音。")
    st.markdown("<div style='margin: 0.5rem 0;'></div>", unsafe_allow_html=True)

    with st.container(border=True):
        uploaded = st.file_uploader("上传 Xbench 报告 (.xlsx)", type=["xlsx"], accept_multiple_files=True, label_visibility="collapsed")
        
        c_run, c_clear = st.columns([5, 1])
        with c_run:
            run_btn = st.button("▶ 开始筛查", type="primary", disabled=not uploaded, use_container_width=True)
        with c_clear:
            if st.button("🗑️ 清除", use_container_width=True, disabled=not st.session_state.results):
                st.session_state.results = []
                st.session_state.file_bytes_map = {}
                st.session_state.zip_cache = None
                st.rerun()

    if not st.session_state.results and not run_btn:
        st.info("请将需要处理的 Xbench Excel 报告拖拽至上方区域。支持多文件批量处理。")

    if run_btn and uploaded:
        files = [(uf.name, uf.read()) for uf in uploaded]
        st.session_state.file_bytes_map = {n: d for n, d in files}
        st.session_state.task      = start_processing_task(files, st.session_state.cfg)
        st.session_state.results   = []
        st.session_state.zip_cache = None
        st.rerun()

    @st.fragment(run_every=0.5)
    def _task_progress():
        task: ProcessingTask = st.session_state.task
        if task is None:
            return
        if not task.done:
            labels = {"parse": "解析数据", "llm": "大模型复核"}
            st.progress(
                task.current / max(task.total, 1),
                text=f"总进度：{task.current + 1} / {task.total} 个文件",
            )
            if task.stage_total:
                pct = min(1.0, task.stage_done / task.stage_total)
                st.progress(pct)
                st.caption(
                    f"**{task.current_name}**　"
                    f"{labels.get(task.stage, task.stage)} "
                    f"{task.stage_done} / {task.stage_total} 条"
                )
            else:
                st.caption(f"正在初始化：{task.current_name}")
        else:
            st.session_state.results   = task.results
            st.session_state.task      = None
            st.session_state.zip_cache = None
            st.rerun()

    if st.session_state.task is not None:
        _task_progress()

    if st.session_state.results:
        st.markdown("<div style='margin: 1.5rem 0;'></div>", unsafe_allow_html=True)
        
        total_items, total_supp, total_kept = 0, 0, 0
        summary_data = []
        
        for r in st.session_state.results:
            s = r.get("stats", {})
            t_count = s.get("total", 0)
            s_count = s.get("suppressed", 0)
            k_count = s.get("kept", 0)
            
            total_items += t_count
            total_supp += s_count
            total_kept += k_count
            
            summary_data.append({
                "filename": r["filename"],
                "total": t_count,
                "suppressed": s_count,
                "kept": k_count,
                "rate": f"{s_count / t_count * 100:.1f}%" if t_count else "—",
                "status": "异常" if r.get("error") else "正常"
            })
            
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("处理文件数", f"{len(st.session_state.results)}")
        m2.metric("报错总条数", f"{total_items}")
        m3.metric("拦截误报数", f"{total_supp}")
        m4.metric("平均过滤率", f"{total_supp / total_items * 100:.1f}%" if total_items else "0.0%")
        
        st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)
        
        st.dataframe(
            summary_data, use_container_width=True, hide_index=True,
            column_config={
                "filename": st.column_config.TextColumn("文件名", width="large"),
                "total": st.column_config.NumberColumn("总行数"),
                "suppressed": st.column_config.NumberColumn("过滤误报"),
                "kept": st.column_config.NumberColumn("保留错漏"),
                "rate": st.column_config.TextColumn("过滤率"),
                "status": st.column_config.TextColumn("处理状态")
            }
        )

        st.divider()

        st.markdown("#### 数据导出")
        
        valid_results = [r for r in st.session_state.results if r.get("rows") and not r.get("error")]
        
        if valid_results:
            if st.session_state.zip_cache is None:
                st.session_state.zip_cache = build_zip_bytes(st.session_state.results, st.session_state.file_bytes_map)
            st.download_button("📦 批量下载全部结果 (.ZIP)", data=st.session_state.zip_cache, file_name="Xbench_Filtered_Results.zip", mime="application/zip", use_container_width=True)
            st.markdown("<div style='margin: 0.5rem 0;'></div>", unsafe_allow_html=True)
            
            selected_file = st.selectbox("单文件导出：", [r["filename"] for r in valid_results], label_visibility="collapsed")
            
            if selected_file:
                r_item = next((x for x in valid_results if x["filename"] == selected_file), None)
                if not r_item:
                    st.rerun()
                orig_bytes = st.session_state.file_bytes_map.get(selected_file)
                stem = os.path.splitext(selected_file)[0]
                
                c_dl_left, c_dl_right = st.columns(2)
                with c_dl_left:
                    with st.container(border=True):
                        st.markdown("**1. 过滤后报告**")
                        st.caption("仅保留有效错漏，用于下发执行修正。")
                        if orig_bytes:
                            st.download_button(f"下载 {stem}_filtered.xlsx", data=build_filtered_xlsx(orig_bytes, r_item["rows"]), file_name=f"{stem}_filtered.xlsx", use_container_width=True)
                with c_dl_right:
                    with st.container(border=True):
                        st.markdown("**2. 分析总表**")
                        st.caption("包含完整行数据与模型复核依据，用于复盘。")
                        st.download_button(f"下载 {stem}_analysis.xlsx", data=build_analysis_xlsx(r_item["rows"]), file_name=f"{stem}_analysis.xlsx", use_container_width=True)

        st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)
        with st.expander("在线数据明细", expanded=False):
            sel_preview = st.selectbox("选择文件", [r["filename"] for r in st.session_state.results], key="detail_sel", label_visibility="collapsed")
            if sel_preview:
                r_prev = next((x for x in st.session_state.results if x["filename"] == sel_preview), None)
                if not r_prev:
                    st.rerun()
                
                # 数据安全处理，防止 None 值导致渲染报错
                rows_display = [{
                    "Verdict": row.verdict or "—",
                    "Source": str(row.source_text) if row.source_text else "—",
                    "Target": str(row.target_text) if row.target_text else "—",
                    "Error": str(row.error_description) if row.error_description else "—",
                    "Reason": str(row.llm_analysis) if row.llm_analysis else "—",
                } for row in (r_prev.get("rows") or [])]
                
                if rows_display:
                    st.dataframe(
                        rows_display, use_container_width=True, height=350,
                        column_config={
                            "Verdict": st.column_config.TextColumn("系统判定", width="small"),
                            "Source": st.column_config.TextColumn("原文", width="medium"),
                            "Target": st.column_config.TextColumn("译文", width="medium"),
                            "Error": st.column_config.TextColumn("报错类别", width="small"),
                            "Reason": st.column_config.TextColumn("复核依据", width="large")
                        }
                    )


# ══════════════════════════════════════════════════════════════════════════════
# Page: 参数设置
# ══════════════════════════════════════════════════════════════════════════════

def page_settings():
    st.markdown("### 参数设置")
    st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)
    
    cfg = st.session_state.cfg
    
    with st.container(border=True):
        st.markdown("**API 接口配置**")
        api_key = st.text_input("API Key", value=cfg.api_key, type="password")
        api_base = st.text_input("Base URL", value=cfg.api_base)
        
        st.markdown("<div style='margin: 1.5rem 0;'></div>", unsafe_allow_html=True)
        st.markdown("**模型选择**")
        
        all_models = get_all_models()
        if "sel_model" not in st.session_state or st.session_state.sel_model not in all_models:
            if all_models:
                st.session_state.sel_model = cfg.model if cfg.model in all_models else all_models[0]
            else:
                st.session_state.sel_model = ""

        for m in all_models:
            is_sel = (m == st.session_state.sel_model)
            c1, c2, c3 = st.columns([1.5, 7, 1])
            if c1.button("● 当前启用" if is_sel else "○ 选择", key=f"sel_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state.sel_model = m
                st.rerun()

            c2.markdown(f"<div style='padding:0.25rem 0;'><code>{m}</code></div>", unsafe_allow_html=True)

            if m not in PRESET_MODELS:
                if c3.button("✕", key=f"rm_{m}", use_container_width=True, disabled=len(all_models) <= 1):
                    remove_model(m)
                    remaining = [x for x in all_models if x != m]
                    st.session_state.sel_model = remaining[0] if remaining else ""
                    st.rerun()
            else:
                c3.write("")

        c_in, c_btn = st.columns([7.5, 1])
        new_model = c_in.text_input("自定义模型", placeholder="输入 Model ID...", label_visibility="collapsed")
        if c_btn.button("添加", use_container_width=True) and new_model.strip():
            add_custom_model(new_model.strip())
            st.session_state.sel_model = new_model.strip()
            st.rerun()

    with st.container(border=True):
        st.markdown("**引擎执行参数**")
        c_temp, c_work = st.columns(2)
        with c_temp:
            temperature = st.slider("Temperature (建议维持在 0.3 左右以保证判断稳定性)", 0.0, 1.0, cfg.temperature, 0.05)
        with c_work:
            max_workers = st.number_input("并发线程数 (受限于 API 并发配额)", 1, 64, cfg.max_workers)
        max_tokens = cfg.max_tokens

    effective_model = st.session_state.sel_model or (all_models[0] if all_models else cfg.model)
    new_cfg = RunConfig(
        api_key=api_key, api_base=api_base, model=effective_model,
        temperature=temperature, max_tokens=max_tokens, max_workers=max_workers,
    )
    st.session_state.cfg = new_cfg
    try:
        apply_config(new_cfg)
    except Exception:
        pass

    st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)
    if st.button("测试连接", use_container_width=True):
        with st.spinner("连接中..."):
            ok, msg = test_api_connection(new_cfg)
        st.session_state.api_status = (ok, msg)
        if ok: st.success("连接正常")
        else: st.error(f"连接异常：{msg}")


# ══════════════════════════════════════════════════════════════════════════════
# Page: 使用说明
# ══════════════════════════════════════════════════════════════════════════════

def page_about():
    st.markdown("### 使用说明")
    st.markdown("<div style='margin: 1rem 0;'></div>", unsafe_allow_html=True)
    
    with st.container(border=True):
        st.markdown("""
        **操作流程：**
        
        1. **环境准备**：在「参数设置」页配置大模型 API Key。建议点击“测试连接”确认网络畅通。
        2. **数据处理**：在「误报筛查」页上传 Xbench 导出的原始 `.xlsx` 报错报告，点击“开始筛查”。系统支持多文件并发处理。
        3. **获取产出物**：
           * **过滤后报告**：直接剔除大模型判断为误报的行，保留真实的质量问题，供 QA/翻译人员处理。
           * **分析总表**：包含原始数据的全部行及大模型的复核依据，用于流程复盘和规则追溯。
           
        *注：若处理过程中频繁出现接口限流错误 (Rate Limit)，请在参数设置中适当调低“并发线程数”。*
        """)

# ── Router ────────────────────────────────────────────────────────────────────

{
    "filter":   page_filter,
    "settings": page_settings,
    "about":    page_about,
}.get(st.session_state.page, page_filter)()

# ── Sidebar status (rendered after page fn updates cfg) ───────────────────────

with st.sidebar:
    cfg = st.session_state.cfg
    with st.container(border=True):
        st.markdown("**运行环境状态**")
        st.markdown(f"- 模型: `{cfg.model}`")
        st.markdown(f"- 并发: `{cfg.max_workers}` 线程")

        status = st.session_state.api_status
        if status is None:
            st.markdown("- API: `🔘 未测试`")
        elif status[0]:
            st.markdown("- API: `🟢 正常`")
        else:
            st.markdown("- API: `🔴 异常`")