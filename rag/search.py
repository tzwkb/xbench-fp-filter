"""
search.py
---------
Case retrieval module.
Implements:
  - Pure vector search (vector_only mode, default) — error_type as semantic signal
  - SQL hard filter + vector search (sql_filter mode, legacy)
  - Result formatting for human inspection or LLM context construction

Usage (as a module):
    from search import search_similar
    results = search_similar(error_description, error_type, top_k=3)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rag.store import embed, embed_with_cache, save_query_history, get_faiss_index, build_vector_text, Case, SEARCH_MODE, get_connection


# --------------------------------------------------------------------------
# Result structure
# --------------------------------------------------------------------------
@dataclass
class SearchResult:
    case_id:            int
    similarity:         float
    error_type:         str
    error_description:  str
    source_text:        str
    target_text:        str
    review_label:       str
    false_alarm_reason: str  # 保留兼容旧数据
    annotator:          str
    annotated_at:       str
    severity:           str = "Minor"
    reason:             str = ""

    def is_false_alarm(self) -> bool:
        return self.review_label == "误报"

    @staticmethod
    def _clean_reason(text: str) -> str:
        import re
        text = re.sub(r'[，,]?\s*(真错误|误报)\s*[，,]?\s*', ' ', text)
        return re.sub(r'\s{2,}', ' ', text).strip(' ，、')

    def to_llm_context(self, mask_label: bool = False) -> str:
        reason = self._clean_reason(self.reason or self.false_alarm_reason or '')
        if mask_label:
            lines = [f"案例ID: {self.case_id}"]
            if reason:
                lines.append(f"判定依据: {reason}")
            return "\n".join(lines)
        lines = [
            f"案例ID: {self.case_id} | 相似度: {self.similarity:.3f}",
            f"严重程度: {self.severity}",
            f"人工标签: {self.review_label}",
        ]
        if reason:
            lines.append(f"判定依据: {reason}")
        return "\n".join(lines)

    def to_display(self) -> str:
        label_marker = "✓ 误报" if self.is_false_alarm() else (
            "✗ 真错误" if self.review_label == "真错误" else "? 待复核"
        )
        return (
            f"  [{label_marker}] 相似度={self.similarity:.4f}  case_id={self.case_id}\n"
            f"  错误描述  : {self.error_description}\n"
            f"  误报原因  : {self.false_alarm_reason or '（无）'}\n"
        )

import config as _cfg

# --------------------------------------------------------------------------
# Similarity thresholds（从 config.py 读取，方便统一管理）
# --------------------------------------------------------------------------
THRESHOLD_HIGH  = _cfg.THRESHOLD_HIGH
THRESHOLD_LOW   = _cfg.THRESHOLD_LOW

# --------------------------------------------------------------------------
# Core search function
# --------------------------------------------------------------------------
def search_similar(
    error_description:  str,
    error_type:         str,
    top_k:              int = 1,
    search_multiplier:  int = 5,
    source_text:        str = "",
    target_text:        str = "",
    ground_truth:       str = "",
) -> list[SearchResult]:
    index = get_faiss_index()

    if index.ntotal == 0:
        print("[search] FAISS index is empty. Please insert cases first.")
        return []

    query_case = Case(error_type=error_type, error_description=error_description, source_text=source_text, target_text=target_text)
    query_vector = embed_with_cache([build_vector_text(query_case)])

    save_query_history(
        error_type=error_type,
        error_description=error_description,
        source_text=source_text,
        target_text=target_text,
        ground_truth=ground_truth,
        vector=query_vector[0],
    )

    fetch_k = min(top_k * search_multiplier, index.ntotal)
    similarities, candidate_ids = index.search(query_vector, fetch_k)

    if SEARCH_MODE == "vector_only":
        filtered = _filter_vector_only(similarities, candidate_ids, top_k)
    else:
        filtered = _filter_sql(similarities, candidate_ids, error_type, top_k)

    if not filtered:
        print("[search] No similar cases found (mode=%s)" % SEARCH_MODE)
        return []

    return _fetch_results(filtered)


def _filter_vector_only(
    similarities: np.ndarray,
    candidate_ids: np.ndarray,
    top_k: int,
) -> list[tuple[float, int]]:
    candidates = [(float(sim), int(cid))
                  for sim, cid in zip(similarities[0], candidate_ids[0])
                  if cid != -1]
    if not candidates:
        return []

    id_list = [cid for _, cid in candidates]
    placeholders = ",".join("?" * len(id_list))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT id FROM cases WHERE id IN ({placeholders}) AND review_label != '待复核'",
        id_list,
    )
    valid_ids = set(row["id"] for row in cursor.fetchall())
    conn.close()

    filtered = []
    for sim, cid in candidates:
        if cid in valid_ids:
            filtered.append((sim, cid))
        if len(filtered) >= top_k:
            break
    return filtered


def _filter_sql(
    similarities: np.ndarray,
    candidate_ids: np.ndarray,
    error_type: str,
    top_k: int,
) -> list[tuple[float, int]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM cases WHERE error_type = ? AND review_label != '待复核'",
        (error_type,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    valid_ids = set(row["id"] for row in rows)

    filtered = []
    for sim, cid in zip(similarities[0], candidate_ids[0]):
        if cid == -1:
            continue
        if cid in valid_ids:
            filtered.append((float(sim), int(cid)))
        if len(filtered) >= top_k:
            break

    return filtered


def _fetch_results(filtered: list[tuple[float, int]]) -> list[SearchResult]:
    sim_by_id = {cid: sim for sim, cid in filtered}
    placeholders = ",".join("?" * len(sim_by_id))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM cases WHERE id IN ({placeholders})", list(sim_by_id))
    rows = {row["id"]: row for row in cursor.fetchall()}
    conn.close()

    results = []
    for sim, cid in filtered:
        row = rows.get(cid)
        if row:
            results.append(SearchResult(
                case_id=row["id"],
                similarity=sim,
                error_type=row["error_type"],
                error_description=row["error_description"],
                source_text=row["source_text"],
                target_text=row["target_text"],
                review_label=row["review_label"],
                false_alarm_reason=row["false_alarm_reason"],
                annotator=row["annotator"],
                annotated_at=row["annotated_at"],
                severity=row["severity"] if "severity" in row.keys() else "Minor",
                reason=row["reason"] if "reason" in row.keys() else "",
            ))
    return results


# --------------------------------------------------------------------------
# Decision helper (for future integration with main QA pipeline)
# --------------------------------------------------------------------------
def decide(results: list[SearchResult]) -> str:
    if not results:
        return "llm_independent"

    top = results[0]

    if top.similarity >= THRESHOLD_LOW:
        return "llm_review"
    return "llm_independent"


# --------------------------------------------------------------------------
# Serialization helper
# --------------------------------------------------------------------------
def serialize_search_result(
    query: dict,
    results: list[SearchResult],
    decision: str,
    ground_truth: str = "",
) -> dict:
    return {
        "ground_truth":      ground_truth,
        "error_type":        query.get("error_type", ""),
        "error_description": query.get("error_description", ""),
        "source_text":       query.get("source_text", ""),
        "target_text":       query.get("target_text", ""),
        "decision":          decision,
        "top_similarity":    round(results[0].similarity, 4) if results else 0.0,
        "top_case_id":       results[0].case_id if results else None,
        "ref_cases": [
            {
                "case_id":           hit.case_id,
                "similarity":        round(hit.similarity, 4),
                "error_type":        hit.error_type,
                "error_description": hit.error_description,
                "source_text":       hit.source_text,
                "target_text":       hit.target_text,
                "review_label":      hit.review_label,
                "severity":          hit.severity,
                "reason":            hit.reason or hit.false_alarm_reason,
            }
            for hit in results
        ],
    }
