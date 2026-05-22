"""
data_calculator.py
------------------
RAG 测试报告生成器。
从 LLM 复核结果（JSON）计算全部指标，输出 Markdown 测试报告。

可被 run_test.py 自动调用，也可独立运行：
    python data_calculator.py --date 20260428b --queries data/raw_data/query_cases_0428.json
"""

import json
import sys
import os
import argparse
from collections import Counter

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPTS_DIR)


def pct(n, d):
    return f"{n}/{d}（{100*n/d:.1f}%）" if d else "N/A"


def generate_report(raw, queries_path="", date="", model_name="gemini"):
    """
    从原始记录列表生成完整 Markdown 报告。

    Parameters
    ----------
    raw : list[dict]
        LLM 复核后的记录列表，每条包含 ground_truth, final_label, decision,
        top_similarity, ref_cases, error_description, source_text, target_text 等字段。
    queries_path : str
        查询集文件路径，仅用于在报告中显示文件名。
    date : str
        测试日期标识，如 "20260428a"。
    model_name : str
        LLM 模型名称，用于报告头部。

    Returns
    -------
    str
        Markdown 格式的完整报告文本。
    """
    def pred(x):
        return x.get("final_label")

    def correct(x):
        return pred(x) == x.get("ground_truth")

    direct = [x for x in raw if x.get("decision") == "direct_pass"]
    llm_rev = [x for x in raw if x.get("decision") == "llm_review"]
    keep = [x for x in raw if x.get("decision") == "llm_independent"]

    fa_all = [x for x in raw if x.get("ground_truth") == "误报"]
    te_all = [x for x in raw if x.get("ground_truth") == "真错误"]
    intervened = [x for x in raw if pred(x) in ("误报", "真错误")]
    n_correct = sum(1 for x in intervened if correct(x))
    fa_hit = [x for x in fa_all if pred(x) == "误报"]
    te_safe = [x for x in te_all if pred(x) != "误报"]
    te_bad = [x for x in te_all if pred(x) == "误报"]

    def would_mock(x):
        refs = x.get("ref_cases", [])
        if not refs:
            return "待复核"
        top = refs[0]
        if top.get("review_label") == "误报" and top.get("similarity", 0) >= 0.70:
            return "误报"
        if top.get("review_label") == "真错误":
            return "真错误"
        return "待复核"

    flipped = [x for x in llm_rev if pred(x) and pred(x) != would_mock(x)]
    flipped_correct = [x for x in flipped if correct(x)]
    flipped_wrong = [x for x in flipped if not correct(x)]
    not_flipped = [x for x in llm_rev if pred(x) and pred(x) == would_mock(x)]
    not_flipped_correct = [x for x in not_flipped if correct(x)]

    pending = [x for x in raw if pred(x) == "待复核" or not pred(x)]
    suppressed = [x for x in raw if pred(x) == "误报"]
    human_q = len(raw) - len(suppressed)
    sims = [x["top_similarity"] for x in raw if x.get("top_similarity") is not None]
    avg_sim = sum(sims) / len(sims) if sims else 0

    precision = len(fa_hit) / len(suppressed) if suppressed else 0
    recall = len(fa_hit) / len(fa_all) if fa_all else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    beta = 2
    f2 = (1 + beta**2) * precision * recall / (beta**2 * precision + recall) if (beta**2 * precision + recall) else 0

    lines = []
    A = lines.append

    # ------------------------------------------------------------------
    # 头部
    # ------------------------------------------------------------------
    date_str = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) >= 8 else date
    A(f"# RAG + LLM 质检复核系统测试报告")
    A(f"")
    A(f"**测试日期：** {date_str}")
    if queries_path:
        A(f"**查询数据：** `{os.path.basename(queries_path)}`（{len(raw)} 条）")
    else:
        A(f"**查询数据：** {len(raw)} 条")
    A(f"**模型：** {model_name}（向量检索：bge-m3）")
    A(f"")
    if intervened:
        A(f"> **核心指标摘要：** 系统整体准确率 {100*n_correct/len(intervened):.1f}%，误报识别率 {pct(len(fa_hit), len(fa_all))}，真错误保护率 {pct(len(te_safe), len(te_all))}，F2={f2:.3f}。")
    A(f"")
    A(f"---")
    A(f"")

    # ------------------------------------------------------------------
    # 一、名词说明
    # ------------------------------------------------------------------
    A(f"## 一、名词说明")
    A(f"")
    A(f"| 术语 | 含义 |")
    A(f"|---|---|")
    A(f"| 误报 | AI 初检报了错误，但人工确认实际上没有问题 |")
    A(f"| 真错误 | AI 初检报了错误，人工确认确实是翻译错误 |")
    A(f"| direct_pass | 向量相似度极高（≥0.80）且命中误报案例，系统直接压制，不调用 LLM |")
    A(f"| llm_review | 向量相似度中等（0.60~0.80），或高相似度命中真错误，交由 LLM 二次判断 |")
    A(f"| llm_independent | 无强匹配（相似度<0.60），转 LLM 独立判断（无参考案例） |")
    A(f"| 翻转 | LLM 的判断与向量检索命中案例的标签不同 |")
    A(f"")
    A(f"---")
    A(f"")

    # ------------------------------------------------------------------
    # 二、核心指标
    # ------------------------------------------------------------------
    A(f"## 二、核心指标")
    A(f"")
    A(f"| 指标 | 数值 | 说明 |")
    A(f"|---|---|---|")
    if intervened:
        A(f"| 整体准确率 | **{100*n_correct/len(intervened):.1f}%**（{n_correct}/{len(intervened)}） | 系统判断与人工标注一致的比例 |")
    A(f"| 误报识别率（Recall） | **{pct(len(fa_hit), len(fa_all))}** | {len(fa_all)} 条误报中被正确压制的比例 |")
    A(f"| 精确率（Precision） | **{precision:.3f}** | 系统压制的条目中真正是误报的比例 |")
    A(f"| F1 | **{f1:.3f}** | 误报识别率与精确率的调和平均 |")
    A(f"| F2 (β=2) | **{f2:.3f}** | 更重视召回率的调和平均 |")
    A(f"| 真错误保护率 | **{pct(len(te_safe), len(te_all))}** | {len(te_all)} 条真错误中未被误压制的比例 |")
    A(f"| 待复核率 | **{100*len(pending)/len(raw):.1f}%**（{len(pending)}/{len(raw)}） | 系统弃权、未给出明确判断的比例 |")
    A(f"| 人工队列压缩率 | **{100*(1-human_q/len(raw)):.1f}%** | 系统压制后人工需审核条目的减少比例 |")
    if human_q:
        A(f"| 审核精度 | **{100*len(te_safe)/human_q:.1f}%**（{len(te_safe)}/{human_q}） | 人工队列中真错误占比（越高越省力） |")
    A(f"| 平均检索相似度 | **{avg_sim:.3f}** | 所有查询 top-1 相似度均值，反映检索质量 |")
    A(f"| LLM 翻转率 | **{pct(len(flipped), len(llm_rev))}** | 其中正确翻转 {len(flipped_correct)} 条，错误翻转 {len(flipped_wrong)} 条 |")
    if flipped:
        A(f"| LLM 翻转准确率 | **{100*len(flipped_correct)/len(flipped):.1f}%** | 翻转时判断正确的比例 |")
    if not_flipped:
        A(f"| LLM 不翻转准确率 | **{100*len(not_flipped_correct)/len(not_flipped):.1f}%** | 跟随检索建议时判断正确的比例 |")
    A(f"")

    # ------------------------------------------------------------------
    # 决策分布
    # ------------------------------------------------------------------
    A(f"### 决策分布")
    A(f"")
    A(f"| 决策 | 条数 | 占比 |")
    A(f"|---|---|---|")
    A(f"| direct_pass（直接压制） | {len(direct)} | {100*len(direct)/len(raw):.1f}% |")
    A(f"| llm_review（LLM 二次审） | {len(llm_rev)} | {100*len(llm_rev)/len(raw):.1f}% |")
    A(f"| llm_independent（LLM 独立判断） | {len(keep)} | {100*len(keep)/len(raw):.1f}% |")
    A(f"")

    # ------------------------------------------------------------------
    # 分组准确率
    # ------------------------------------------------------------------
    A(f"### 分组准确率（含 GT 拆分）")
    A(f"")
    A(f"| 组别 | 总条数 | 整体准确率 | 误报准确率 | 真错误准确率 |")
    A(f"|---|---|---|---|---|")
    for gname, group in [("direct_pass", direct), ("llm_review", llm_rev), ("llm_independent", keep)]:
        gi = [x for x in group if pred(x) in ("误报", "真错误")]
        gc = sum(1 for x in gi if correct(x))
        fa_g = [x for x in group if x.get("ground_truth") == "误报" and pred(x) in ("误报", "真错误")]
        te_g = [x for x in group if x.get("ground_truth") == "真错误" and pred(x) in ("误报", "真错误")]
        fa_acc = f"{100*sum(1 for x in fa_g if correct(x))/len(fa_g):.1f}%" if fa_g else "—"
        te_acc = f"{100*sum(1 for x in te_g if correct(x))/len(te_g):.1f}%" if te_g else "—"
        overall = f"{100*gc/len(gi):.1f}%" if gi else "—"
        A(f"| {gname} | {len(group)} | {overall} | {fa_acc} | {te_acc} |")
    A(f"")

    # ------------------------------------------------------------------
    # 相似度区间分布
    # ------------------------------------------------------------------
    A(f"### 相似度区间分布")
    A(f"")
    A(f"| 区间 | 条数 | 占比 |")
    A(f"|---|---|---|")
    bins = [("≥0.80", 0.80, 2.0), ("0.75~0.80", 0.75, 0.80), ("0.70~0.75", 0.70, 0.75),
            ("0.65~0.70", 0.65, 0.70), ("0.60~0.65", 0.60, 0.65), ("<0.60", None, 0.60)]
    for label, lo, hi in bins:
        if lo is None:
            cnt = sum(1 for x in raw if (x.get("top_similarity") or 0) < hi)
        elif hi == 2.0:
            cnt = sum(1 for x in raw if (x.get("top_similarity") or 0) >= lo)
        else:
            cnt = sum(1 for x in raw if lo <= (x.get("top_similarity") or 0) < hi)
        A(f"| {label} | {cnt} | {100*cnt/len(raw):.1f}% |")
    A(f"")

    # ------------------------------------------------------------------
    # 误报 vs 真错误相似度分布
    # ------------------------------------------------------------------
    A(f"### 误报 vs 真错误相似度分布")
    A(f"")
    fa_sims = [x["top_similarity"] for x in raw if x.get("ground_truth") == "误报" and x.get("top_similarity") is not None]
    te_sims = [x["top_similarity"] for x in raw if x.get("ground_truth") == "真错误" and x.get("top_similarity") is not None]
    A(f"| 类别 | 条数 | 均值 | 最高 | 最低 |")
    A(f"|---|---|---|---|---|")
    if fa_sims:
        A(f"| 误报 | {len(fa_sims)} | {sum(fa_sims)/len(fa_sims):.3f} | {max(fa_sims):.3f} | {min(fa_sims):.3f} |")
    if te_sims:
        A(f"| 真错误 | {len(te_sims)} | {sum(te_sims)/len(te_sims):.3f} | {max(te_sims):.3f} | {min(te_sims):.3f} |")
    A(f"")

    # ------------------------------------------------------------------
    # 案例库命中频率
    # ------------------------------------------------------------------
    A(f"### 案例库命中频率（Top-10）")
    A(f"")
    hit_counter = Counter(x.get("top_case_id") for x in raw if x.get("top_case_id"))
    total_hits = sum(hit_counter.values())
    unique_hit = len(hit_counter)
    A(f"激活案例数：{unique_hit} 条（共 {len(raw)} 次命中）")
    A(f"")
    A(f"| 排名 | case_id | 命中次数 | 占比 |")
    A(f"|---|---|---|---|")
    top10_sum = 0
    for rank, (cid, cnt) in enumerate(hit_counter.most_common(10), 1):
        top10_sum += cnt
        A(f"| {rank} | {cid} | {cnt} | {100*cnt/total_hits:.1f}% |")
    A(f"| Top-10 合计 | — | {top10_sum} | {100*top10_sum/total_hits:.1f}% |")
    A(f"")

    # ------------------------------------------------------------------
    # 错误翻转错误类型分布
    # ------------------------------------------------------------------
    A(f"### 错误翻转错误类型分布")
    A(f"")
    wrong_flips = [x for x in llm_rev if pred(x) and pred(x) != would_mock(x) and not correct(x)]
    if wrong_flips:
        wf_counter = Counter(x.get("error_type", "未知") for x in wrong_flips)
        A(f"错误翻转总数：{len(wrong_flips)} 条")
        A(f"")
        A(f"| 错误类型 | 次数 | 占比 |")
        A(f"|---|---|---|")
        for et, cnt in wf_counter.most_common():
            A(f"| {et} | {cnt} | {100*cnt/len(wrong_flips):.1f}% |")
    else:
        A(f"本轮无错误翻转。")
    A(f"")

    # ------------------------------------------------------------------
    # 错误类型分布
    # ------------------------------------------------------------------
    A(f"### 错误类型分布")
    A(f"")
    A(f"| 错误类型 | 总条数 | 误报 | 真错误 | 误报识别率 | 真错误保护率 |")
    A(f"|---|---|---|---|---|---|")
    error_types = sorted(set(x.get("error_type", "未知") for x in raw))
    for et in error_types:
        et_all = [x for x in raw if x.get("error_type") == et]
        et_fa = [x for x in et_all if x.get("ground_truth") == "误报"]
        et_te = [x for x in et_all if x.get("ground_truth") == "真错误"]
        et_fa_hit = sum(1 for x in et_fa if pred(x) == "误报")
        et_te_safe = sum(1 for x in et_te if pred(x) != "误报")
        fa_rate = f"{et_fa_hit}/{len(et_fa)}（{100*et_fa_hit/len(et_fa):.0f}%）" if et_fa else "—"
        te_rate = f"{et_te_safe}/{len(et_te)}（{100*et_te_safe/len(et_te):.0f}%）" if et_te else "—"
        A(f"| {et} | {len(et_all)} | {len(et_fa)} | {len(et_te)} | {fa_rate} | {te_rate} |")
    A(f"")
    A(f"---")
    A(f"")

    # ------------------------------------------------------------------
    # 三、被误压制的真错误
    # ------------------------------------------------------------------
    A(f"## 三、被误压制的真错误（需关注）")
    A(f"")
    if te_bad:
        for x in te_bad:
            top = x.get("ref_cases", [None])[0]
            A(f"**[{x.get('idx', 0)+1:02d}]**")
            A(f"- 原文：{x.get('source_text', '')}")
            A(f"- 译文：{x.get('target_text', '')}")
            A(f"- 错误描述：{x.get('error_description', '')}")
            A(f"- 系统判断：{pred(x)}（{x.get('decision', '')}，sim={x.get('top_similarity', '')}）")
            A(f"- 判断理由：{x.get('llm_analysis', '') or x.get('reason', '')}")
            if top:
                A(f"- 命中案例：case_id={top.get('case_id')}，标签={top.get('review_label', '')}")
            A(f"")
    else:
        A(f"无。所有真错误均未被误压制。")
    A(f"")
    A(f"---")
    A(f"")

    # ------------------------------------------------------------------
    # 四、未被识别的误报
    # ------------------------------------------------------------------
    A(f"## 四、未被识别的误报")
    A(f"")
    fa_missed = [x for x in fa_all if pred(x) != "误报"]
    if fa_missed:
        for x in fa_missed:
            A(f"**[{x.get('idx', 0)+1:02d}]**")
            A(f"- 原文：{x.get('source_text', '')}")
            A(f"- 译文：{x.get('target_text', '')}")
            A(f"- 错误描述：{x.get('error_description', '')}")
            A(f"- 系统判断：{pred(x) or '未干预'}（{x.get('decision', '')}，sim={x.get('top_similarity', '')}）")
            A(f"- 判断理由：{x.get('llm_analysis', '') or x.get('reason', '')}")
            A(f"")
    else:
        A(f"无。所有误报均被正确识别。")
    A(f"")
    A(f"---")
    A(f"")

    # ------------------------------------------------------------------
    # 五、逐条明细
    # ------------------------------------------------------------------
    A(f"## 五、逐条明细")
    A(f"")
    A(f"图例：✓ 判断正确　✗ 判断错误　△ 未干预")
    A(f"")
    for x in raw:
        p = pred(x) or "未干预"
        ok = "✓" if correct(x) else ("△" if p == "未干预" else "✗")
        top_ref = (x.get("ref_cases") or [None])[0]
        A(f"### [{x.get('idx', 0)+1:02d}] {ok} GT={x.get('ground_truth', '')} → 系统={p}")
        A(f"")
        A(f"| 字段 | 内容 |")
        A(f"|---|---|")
        A(f"| 错误类型 | {x.get('error_type', '')} |")
        A(f"| 错误描述 | {x.get('error_description', '')} |")
        A(f"| 原文 | {x.get('source_text') or '—'} |")
        A(f"| 译文 | {x.get('target_text') or '—'} |")
        A(f"| 决策 | {x.get('decision', '')} |")
        A(f"| 最高相似度 | {x.get('top_similarity', '')} |")
        if top_ref:
            reason_text = top_ref.get('reason') or top_ref.get('false_alarm_reason') or '无'
            A(f"| 命中案例 | case_id={top_ref.get('case_id')}，sim={top_ref.get('similarity')}，标签={top_ref.get('review_label')}，判定依据={reason_text} |")
        A(f"| 最终判断 | {p} |")
        A(f"| 判断理由 | {x.get('llm_analysis') or x.get('reason') or '—'} |")
        A(f"")

    return "\n".join(lines)


def write_report(report_text, report_path):
    """将报告写入文件，并打印摘要。"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"Report → {report_path}")


def generate_report_from_files(llm_path, report_path, queries_path="", date="", model_name="gemini"):
    """从 LLM JSON 文件读取数据，生成报告并写入文件。"""
    raw = json.load(open(llm_path, encoding="utf-8"))
    report = generate_report(raw, queries_path=queries_path, date=date, model_name=model_name)
    write_report(report, report_path)

    # 打印核心指标摘要
    def pred(x): return x.get("final_label")
    def correct(x): return pred(x) == x.get("ground_truth")
    fa_all = [x for x in raw if x.get("ground_truth") == "误报"]
    te_all = [x for x in raw if x.get("ground_truth") == "真错误"]
    intervened = [x for x in raw if pred(x) in ("误报", "真错误")]
    n_correct = sum(1 for x in intervened if correct(x))
    fa_hit = [x for x in fa_all if pred(x) == "误报"]
    te_safe = [x for x in te_all if pred(x) != "误报"]
    if intervened:
        print(f"\n准确率: {100*n_correct/len(intervened):.1f}%  误报识别率: {pct(len(fa_hit), len(fa_all))}  真错误保护率: {pct(len(te_safe), len(te_all))}")


def main():
    parser = argparse.ArgumentParser(description="RAG 测试报告生成器")
    parser.add_argument("--date", required=True, help="测试日期标识，如 20260428a")
    parser.add_argument("--queries", default="", help="查询集文件路径")
    parser.add_argument("--model", default="gemini", help="LLM 模型名称")
    parser.add_argument("--llm-path", default="", help="LLM JSON 文件路径（默认按日期规则推导）")
    parser.add_argument("--report-path", default="", help="报告输出路径（默认按日期规则推导）")
    parser.add_argument("--root", default=_ROOT, help="项目根目录（默认自动检测）")
    args = parser.parse_args()

    date = args.date
    queries_path = args.queries
    model_name = args.model
    root = args.root

    llm_path = args.llm_path or os.path.join(root, "data", "raw_data", f"test_{date}_llm.json")
    report_path = args.report_path or os.path.join(root, "data", "report", f"test_{date}_report.md")

    generate_report_from_files(llm_path, report_path, queries_path=queries_path, date=date, model_name=model_name)


if __name__ == "__main__":
    main()
