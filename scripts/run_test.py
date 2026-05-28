"""
run_test.py
-----------
RAG 测试入口。

Usage:
    python run_test.py real
    python run_test.py real --queries data/real_test_query_cases.json --date 20260417
    python run_test.py real --skip-llm
"""
import sys, io, json, argparse, os, asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _ROOT)

BASE_DIR  = _ROOT
DATA_DIR  = os.path.join(BASE_DIR, "data")
RAW_DIR   = os.path.join(DATA_DIR, "raw_data")
REPORT_DIR = os.path.join(DATA_DIR, "report")


def pct(n, d): return f"{n}/{d}（{100*n/d:.1f}%）" if d else "N/A"


# ══════════════════════════════════════════════════════════════════════════════
# 子命令：real
# ══════════════════════════════════════════════════════════════════════════════

def cmd_real(args):
    from rag.search import search_by_term, decide, serialize_search_result
    from core.llm_review import llm_secondary_review
    import config

    DATE        = args.date
    VECTOR_PATH = os.path.join(RAW_DIR,    f"test_{DATE}_vector.json")
    LLM_PATH    = os.path.join(RAW_DIR,    f"test_{DATE}_llm.json")
    REPORT_PATH = os.path.join(REPORT_DIR, f"test_{DATE}_report.md")
    EXCEL_PATH  = os.path.join(REPORT_DIR, f"test_{DATE}_result.xlsx")

    with open(args.queries, encoding="utf-8") as f:
        queries = json.load(f)

    # ── Step 1: 向量检索 ──────────────────────────────────────────────────────
    print(f"Step 1: 向量检索 ({len(queries)} 条)...")
    vector_records  = []
    step1_results   = []   # 保留原始 SearchResult，供 Step 2 直接使用
    for i, q in enumerate(queries):
        print(f"  [{i+1}/{len(queries)}]", end="\r")
        gt = q.get("ground_truth", "")
        if isinstance(gt, int):
            gt = "真错误" if gt == 1 else "误报"
        try:
            results  = search_by_term(
                error_description=q["error_description"],
                error_type=q["error_type"],
                source_text=q.get("source_text", ""),
                target_text=q.get("target_text", ""),
            )
            decision = decide(results)
            rec = serialize_search_result(q, results, decision, ground_truth=gt)
            rec["idx"] = i
        except Exception as e:
            results = []
            rec = {
                "idx": i, "ground_truth": gt,
                "error_type": q["error_type"], "error_description": q["error_description"],
                "source_text": q.get("source_text", ""), "target_text": q.get("target_text", ""),
                "decision": None, "top_similarity": None, "top_case_id": None,
                "ref_cases": [], "error": str(e),
            }
        vector_records.append(rec)
        step1_results.append(results)

    print()
    with open(VECTOR_PATH, "w", encoding="utf-8") as f:
        json.dump(vector_records, f, ensure_ascii=False, indent=2)
    print(f"Vector → {VECTOR_PATH}")

    if args.skip_llm:
        print("--skip-llm 已指定，跳过 LLM 复核。")
        return

    # ── Step 2: LLM 复核 ──────────────────────────────────────────────────────
    print(f"\nStep 2: LLM 复核（并发）...")
    llm_records = [None] * len(queries)
    completed_count = [0]

    def _review_one(idx, q, vrec, search_results):
        if vrec.get("error"):
            return idx, {**vrec, "final_label": None, "llm_analysis": None, "llm_raw_response": None}

        decision = vrec.get("decision")

        if decision == "direct_pass":
            rec = dict(vrec)
            rec["final_label"] = "误报"
            rec["llm_analysis"] = f"高置信度匹配历史误报案例（case_id={vrec['top_case_id']}, sim={vrec['top_similarity']:.3f}）"
            rec["llm_raw_response"] = None
            return idx, rec

        try:
            review = asyncio.run(llm_secondary_review(
                error_type=q["error_type"],
                error_description=q["error_description"],
                source_text=q.get("source_text", ""),
                target_text=q.get("target_text", ""),
                search_results=search_results,
                severity=q.get("severity", "Minor"),
                note=q.get("note", ""),
            ))
            rec = dict(vrec)
            rec["final_label"] = review.final_label
            rec["llm_analysis"] = review.llm_analysis
            rec["llm_raw_response"] = review.raw_response
            return idx, rec
        except Exception as e:
            return idx, {**vrec, "final_label": None, "llm_analysis": None, "llm_raw_response": None, "error": str(e)}

    with ThreadPoolExecutor(max_workers=24) as executor:
        futures = {
            executor.submit(_review_one, i, q, vrec, step1_results[i]): i
            for i, (q, vrec) in enumerate(zip(queries, vector_records))
        }
        for future in as_completed(futures):
            idx, rec = future.result()
            llm_records[idx] = rec
            completed_count[0] += 1
            print(f"  [{completed_count[0]}/{len(queries)}]", end="\r")

    print()
    with open(LLM_PATH, "w", encoding="utf-8") as f:
        json.dump(llm_records, f, ensure_ascii=False, indent=2)
    print(f"LLM    → {LLM_PATH}")

    # ── Step 3: 生成报告 ──────────────────────────────────────────────────────
    import data_calculator
    data_calculator.generate_report_from_files(
        LLM_PATH, REPORT_PATH, queries_path=args.queries, date=DATE, model_name=config.LLM_MODEL
    )
    _write_excel(llm_records, EXCEL_PATH)





def _write_excel(raw, excel_path):
    import openpyxl
    headers = [
        "序号", "原文", "译文", "错误类型", "错误描述",
        "系统决策", "系统判断", "是否正确",
        "判断理由", "最高相似度",
    ]
    for n in range(1, 4):
        headers += [f"命中案例{n}"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for i, x in enumerate(raw):
        pred = x.get("final_label") or ""
        gt   = x.get("ground_truth") or ""
        if pred and gt:
            correct = "✓" if pred == gt else "✗"
        else:
            correct = ""
        row = [
            i + 1,
            x.get("source_text", ""),
            x.get("target_text", ""),
            x.get("error_type", ""),
            x.get("error_description", ""),
            x.get("decision", ""),
            pred,
            correct,
            x.get("llm_analysis", ""),
            x.get("top_similarity", ""),
        ]
        for n in range(3):
            ref = x["ref_cases"][n] if x.get("ref_cases") and len(x["ref_cases"]) > n else None
            if ref:
                desc = f'[{ref.get("review_label", "")}] {ref.get("error_description", "")} | {ref.get("source_text", "")} → {ref.get("target_text", "")} | {ref.get("reason", "")}'
            else:
                desc = ""
            row += [desc]
        ws.append(row)
    wb.save(excel_path)
    print(f"Excel  → {excel_path}")


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(prog="run_test.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_real = sub.add_parser("real", help="真实数据全流程测试")
    p_real.add_argument("--queries",  default=os.path.join(RAW_DIR, "real_test_query_cases.json"))
    p_real.add_argument("--date",     default=datetime.now().strftime("%Y%m%d"))
    p_real.add_argument("--skip-llm", action="store_true", dest="skip_llm")

    args = parser.parse_args()
    cmd_real(args)


if __name__ == "__main__":
    main()
