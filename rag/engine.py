"""
engine.py
---------
RAG engine — single entry point for the QA review pipeline.

Usage:
    from engine import RAGEngine

    engine = RAGEngine(
        db_path="data/database/cases.db",
        faiss_path="data/database/cases.faiss",
        llm_api_key="sk-xxx",
        llm_api_base="https://api.xxx/v1",
        llm_model="gemini-3.1-pro-preview",
    )

    result = engine.judge(
        error_type="术语违规",
        error_description="区域 | Region",
        source_text="长按，在黄色区域松开",
        target_text="Hold and release in the yellow area",
    )
    # → {"final_label": "误报", "decision": "direct_pass", "reason": "...", ...}

    # 批量：调用方自己循环
    results = [engine.judge(**item) for item in items]
"""

import os
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EngineConfig:
    db_path:       str = ""
    faiss_path:    str = ""
    llm_api_key:   str = ""
    llm_api_base:  str = "https://api.vectorengine.ai/v1"
    llm_model:     str = "gemini-3.1-pro-preview"
    llm_temperature: float = 0.3
    llm_max_tokens:  int = 2048
    threshold_high:  float = 0.80
    threshold_low:   float = 0.60
    sim_warn:        float = 0.65
    embedding_model: str = "BAAI/bge-m3"


# ══════════════════════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════════════════════

class RAGEngine:
    """Single entry for the RAG QA review pipeline.

    All external dependencies (DB paths, LLM keys, thresholds) are injected
    at construction. No global config, no hardcoded paths.
    """

    def __init__(self, config: EngineConfig):
        self.cfg = config
        self._model = None               # lazy-loaded embedding model
        self._faiss_index = None
        self._llm_client = None
        self._db_conn = None

    # ── public ────────────────────────────────────────────────────────────

    def judge(self, error_type: str = "", error_description: str = "",
              source_text: str = "", target_text: str = "") -> dict:
        """Judge a single QA item. Returns verdict dict.

        All fields are positional or keyword; no wrapping dict needed.
        """
        hits = self._search(error_description, error_type, source_text, target_text)
        decision = self._decide(hits)

        if decision == "direct_pass":
            return self._verdict("误报", decision,
                                 f"高置信度匹配历史误报案例 (sim={hits[0]['similarity']:.3f})",
                                 hits)

        if decision == "llm_review":
            final, reason = self._llm_review(error_type, error_description,
                                             source_text, target_text, hits)
            return self._verdict(final, decision, reason, hits)

        # llm_independent
        final, reason = self._llm_review(error_type, error_description,
                                         source_text, target_text, [])
        return self._verdict(final, decision, reason, [])

    def judge_all(self, items: list[dict], *,
                  on_progress=None,
                  status_path: str = "",
                  ) -> list[dict]:
        """Judge a list of items with progress tracking.

        Each item: {error_type, error_description, source_text?, target_text?}
        Returns list of verdict dicts in same order.

        on_progress(done, total, item, result) — called after each item.
        status_path — if set, writes progress JSON here for external polling.
        """
        import time, json as _json

        total = len(items)
        llm_done = 0
        llm_errors = 0
        need_llm = list(enumerate(items))
        results = [None] * total
        t0 = time.time()

        def _write_status():
            if not status_path:
                return
            elapsed = time.time() - t0
            eta = (elapsed / max(llm_done, 1)) * (len(need_llm) - llm_done) if need_llm and llm_done > 0 else 0
            with open(status_path, "w", encoding="utf-8") as f:
                _json.dump({
                    "total": total,
                    "need_llm": len(need_llm), "llm_done": llm_done,
                    "llm_errors": llm_errors,
                    "progress_pct": round(100 * llm_done / total, 1) if total else 0,
                    "elapsed_s": round(elapsed), "eta_s": round(eta),
                }, f, ensure_ascii=False)

        # LLM review (concurrent)
        if need_llm:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _llm_one(idx, item):
                r = self.judge(
                    error_type=item.get("error_type", ""),
                    error_description=item.get("error_description", ""),
                    source_text=item.get("source_text", ""),
                    target_text=item.get("target_text", ""),
                )
                return idx, r

            with ThreadPoolExecutor(max_workers=24) as ex:
                futures = {ex.submit(_llm_one, i, item): i for i, item in need_llm}
                for fut in as_completed(futures):
                    idx, r = fut.result()
                    results[idx] = r
                    llm_done += 1
                    if r.get("final_label") is None:
                        llm_errors += 1
                    if on_progress:
                        on_progress(llm_done, total, items[idx], r)
                    _write_status()

        if status_path:
            try:
                os.remove(status_path)
            except OSError:
                pass

        return results

    def import_case(self, error_type: str, error_description: str,
                    source_text: str = "", target_text: str = "",
                    review_label: str = "", reason: str = "",
                    annotator: str = "", severity: str = "Minor") -> int:
        """Import a single case into the library. Returns case_id."""
        from rag.store import Case
        case = Case(error_type=error_type, error_description=error_description,
                    source_text=source_text, target_text=target_text,
                    review_label=review_label, reason=reason,
                    annotator=annotator, severity=severity)
        return self._insert_case(case)

    def import_cases_batch(self, cases: list[dict]) -> list[int]:
        """Import multiple cases. Each dict maps to Case fields."""
        from rag.store import Case
        objs = [Case(**c) for c in cases]
        return self._insert_cases_batch(objs)

    def case_count(self) -> int:
        """Return number of cases in library."""
        self._ensure_db()
        return self._faiss_index.ntotal

    # ── internals ─────────────────────────────────────────────────────────

    def _ensure_db(self):
        import rag.store as store
        if self._faiss_index is not None and store.DB_PATH == self.cfg.db_path:
            return
        store.DB_PATH = self.cfg.db_path
        store.FAISS_PATH = self.cfg.faiss_path
        os.makedirs(os.path.dirname(self.cfg.db_path), exist_ok=True)
        store.init_db()

        # Load FAISS
        import faiss
        if os.path.exists(self.cfg.faiss_path):
            self._faiss_index = faiss.read_index(self.cfg.faiss_path)
        else:
            self._faiss_index = faiss.IndexIDMap(faiss.IndexFlatIP(1024))

        # Load embedding model
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.cfg.embedding_model)

        # Wire into store module
        store._model = self._model
        store._faiss_index = self._faiss_index

    def _ensure_llm(self):
        if self._llm_client is not None:
            return
        from openai import OpenAI
        self._llm_client = OpenAI(api_key=self.cfg.llm_api_key,
                                  base_url=self.cfg.llm_api_base)

    def _search(self, error_description, error_type, source_text, target_text):
        self._ensure_db()
        from rag.search import search_by_term
        return [self._hit_to_dict(h) for h in
                search_by_term(error_description, error_type, 3,
                               source_text=source_text, target_text=target_text)]

    def _decide(self, hits):
        return "llm_review" if hits else "llm_independent"

    def _llm_review(self, error_type, error_description, source_text, target_text, hits):
        self._ensure_llm()
        from core.llm_review import REVIEW_PROMPT, _parse

        # Build cases block
        if hits:
            cases_parts = []
            for i, h in enumerate(hits[:3]):
                cases_parts.append(
                    f"--- 案例 {i+1} ---\n"
                    f"案例ID: {h['case_id']}\n"
                    f"相似度: {h['similarity']:.3f}\n"
                    f"人工标签: {h['review_label']}\n"
                    f"判定依据: {h['reason'] or '（无）'}"
                )
            cases_block = "\n\n".join(cases_parts)

            # Consensus
            labels = [h["review_label"] for h in hits[:3]]
            if len(labels) >= 2 and all(l == labels[0] for l in labels):
                cases_block = (
                    f"【案例共识】检索到的 {len(labels)} 条案例标签一致，均判定为「{labels[0]}」。"
                    f"请优先参考此共识，除非有明确理由推翻。\n\n"
                    + cases_block
                )
            elif len(set(labels)) > 1:
                cases_block = "【注意】检索案例标签存在冲突，请结合规则独立判断。\n\n" + cases_block

            similar_cases_block = f"【历史相似案例】\n{cases_block}"
        else:
            similar_cases_block = "【历史相似案例】\n（无匹配的历史案例，请完全依据规则独立判断）"

        prompt = REVIEW_PROMPT.format(
            error_type=error_type,
            error_description=error_description,
            severity="Minor",
            source_text=source_text or "（无）",
            target_text=target_text or "（无）",
            note_block="\n",
            similar_cases_block=similar_cases_block,
        )

        raw = self._llm_client.chat.completions.create(
            model=self.cfg.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.cfg.llm_temperature,
            max_tokens=self.cfg.llm_max_tokens,
            timeout=90,
        ).choices[0].message.content

        parsed = _parse(raw)
        return parsed["final_label"], parsed.get("llm_analysis", "")

    def _insert_case(self, case) -> int:
        self._ensure_db()
        import rag.store as store
        return store.insert_case(case)

    def _insert_cases_batch(self, cases) -> list[int]:
        self._ensure_db()
        import rag.store as store
        return store.insert_cases_batch(cases)

    @staticmethod
    def _verdict(final_label, decision, reason, hits) -> dict:
        return {
            "final_label":    final_label,
            "decision":       decision,
            "reason":         reason,
            "top_similarity": hits[0]["similarity"] if hits else 0.0,
            "top_case_id":    hits[0]["case_id"] if hits else None,
            "ref_cases":      hits[:3],
        }

    @staticmethod
    def _hit_to_dict(hit) -> dict:
        return {
            "case_id":      hit.case_id,
            "similarity":   round(hit.similarity, 4),
            "error_type":   hit.error_type,
            "review_label": hit.review_label,
            "reason":       hit.reason or hit.false_alarm_reason,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Quick-start helper
# ══════════════════════════════════════════════════════════════════════════════

def create_engine(
    db_path:      str = "",
    faiss_path:   str = "",
    llm_api_key:  str = "",
    llm_api_base: str = "https://api.vectorengine.ai/v1",
    llm_model:    str = "gemini-3.1-pro-preview",
) -> RAGEngine:
    """Factory: create engine with explicit paths. No config.py needed."""
    return RAGEngine(EngineConfig(
        db_path=db_path, faiss_path=faiss_path,
        llm_api_key=llm_api_key, llm_api_base=llm_api_base, llm_model=llm_model,
    ))
