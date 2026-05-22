"""
store.py
--------
Case insertion module.
Handles:
  - Loading the bge-m3 embedding model (local, cached after first load)
  - Generating and normalizing vectors
  - Inserting a case into SQLite + FAISS index
  - Saving/loading the FAISS index to disk

Usage (as a module):
    from store import insert_case, load_index
    insert_case(case_dict)
"""

from __future__ import annotations

import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Optional

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH    = os.path.join(DATA_DIR, "database", "cases.db")
FAISS_PATH = os.path.join(DATA_DIR, "database", "cases.faiss")
os.makedirs(os.path.join(DATA_DIR, "database"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "raw_data"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "report"),   exist_ok=True)

# --------------------------------------------------------------------------
# Allowed values for review_label (core to decision logic, not extensible)
# --------------------------------------------------------------------------
REVIEW_LABELS = ["真错误", "误报", "待复核"]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.cursor().executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            annotator       TEXT    NOT NULL DEFAULT '',
            annotated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            error_type          TEXT NOT NULL,
            error_description   TEXT NOT NULL,
            source_text         TEXT NOT NULL DEFAULT '',
            target_text         TEXT NOT NULL DEFAULT '',
            review_label        TEXT NOT NULL DEFAULT '',
            false_alarm_reason  TEXT NOT NULL DEFAULT '',
            severity            TEXT NOT NULL DEFAULT 'Minor',
            reason              TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_error_type   ON cases(error_type);
        CREATE INDEX IF NOT EXISTS idx_review_label ON cases(review_label);
        CREATE TABLE IF NOT EXISTS query_history (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            queried_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            error_type        TEXT NOT NULL DEFAULT '',
            error_description TEXT NOT NULL DEFAULT '',
            source_text       TEXT NOT NULL DEFAULT '',
            target_text       TEXT NOT NULL DEFAULT '',
            ground_truth      TEXT NOT NULL DEFAULT '',
            query_key         TEXT NOT NULL DEFAULT '',
            vector            BLOB
        );
        CREATE INDEX IF NOT EXISTS idx_qh_queried_at  ON query_history(queried_at);
        CREATE INDEX IF NOT EXISTS idx_qh_error_type  ON query_history(error_type);
        CREATE INDEX IF NOT EXISTS idx_qh_query_key   ON query_history(query_key);
    """)
    conn.commit()
    conn.close()
    # 对已存在的旧表，补加新列（幂等）
    conn = get_connection()
    for col, default in [("severity", "'Minor'"), ("reason", "''")]:
        try:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
            conn.commit()
        except Exception:
            pass  # 列已存在
    conn.close()
    print(f"[store] Database initialized at: {DB_PATH}")

# --------------------------------------------------------------------------
# Search mode
# --------------------------------------------------------------------------
SEARCH_MODE = os.environ.get("RAG_SEARCH_MODE", "vector_only")

# --------------------------------------------------------------------------
# Embedding model (lazy-loaded singleton)
# --------------------------------------------------------------------------
_model = None

def get_embedding_model():
    global _model
    if _model is None:
        print("[store] Loading embedding model BAAI/bge-m3 ...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-m3")
        print("[store] Model loaded.")
    return _model


def embed(texts: list[str]) -> np.ndarray:
    import numpy as np
    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.astype(np.float32)


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_with_cache(texts: list[str]) -> np.ndarray:
    import numpy as np
    keys = [_cache_key(t) for t in texts]
    conn = get_connection()
    placeholders = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT query_key, vector FROM query_history WHERE query_key IN ({placeholders}) GROUP BY query_key",
        keys
    ).fetchall()
    conn.close()
    cached = {row["query_key"]: np.frombuffer(row["vector"], dtype=np.float32) for row in rows}

    result = np.zeros((len(texts), VECTOR_DIM), dtype=np.float32)
    miss_indices, miss_texts = [], []

    for i, (text, key) in enumerate(zip(texts, keys)):
        if key in cached:
            result[i] = cached[key]
        else:
            miss_indices.append(i)
            miss_texts.append(text)

    if miss_texts:
        new_vecs = embed(miss_texts)
        for idx, vec in zip(miss_indices, new_vecs):
            result[idx] = vec
        print(f"[store] embed_with_cache: {len(miss_texts)} new, {len(texts)-len(miss_texts)} cached")

    return result


def save_query_history(
    error_type: str,
    error_description: str,
    source_text: str,
    target_text: str,
    ground_truth: str,
    vector: np.ndarray,
) -> None:
    key = _cache_key(build_vector_text(Case(
        error_type=error_type,
        error_description=error_description,
        source_text=source_text,
        target_text=target_text,
    )))
    conn = get_connection()
    conn.execute(
        """INSERT INTO query_history
           (error_type, error_description, source_text, target_text, ground_truth, query_key, vector)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (error_type, error_description, source_text, target_text, ground_truth,
         key, vector.tobytes())
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# FAISS index management
# --------------------------------------------------------------------------
_faiss_index: Optional[faiss.IndexIDMap] = None

VECTOR_DIM = 1024  # bge-m3 output dimension


def get_faiss_index() -> faiss.IndexIDMap:
    import faiss
    global _faiss_index
    if _faiss_index is not None:
        return _faiss_index

    if os.path.exists(FAISS_PATH):
        print(f"[store] Loading FAISS index from {FAISS_PATH}")
        _faiss_index = faiss.read_index(FAISS_PATH)
    else:
        print("[store] Creating new FAISS index (IndexIDMap + IndexFlatIP)")
        base_index  = faiss.IndexFlatIP(VECTOR_DIM)
        _faiss_index = faiss.IndexIDMap(base_index)

    return _faiss_index


def save_faiss_index() -> None:
    import faiss
    index = get_faiss_index()
    faiss.write_index(index, FAISS_PATH)
    print(f"[store] FAISS index saved to {FAISS_PATH} ({index.ntotal} vectors)")


# --------------------------------------------------------------------------
# Case data structure
# --------------------------------------------------------------------------
@dataclass
class Case:
    error_type:         str
    error_description:  str
    source_text:        str = ""
    target_text:        str = ""
    review_label:       str = ""
    false_alarm_reason: str = ""  # 保留兼容旧数据
    annotator:          str = ""
    severity:           str = "Minor"
    reason:             str = ""  # 替代 false_alarm_reason，覆盖误报和真错误


def validate_case(case: Case) -> None:
    if not case.error_type.strip():
        raise ValueError("error_type must not be empty.")
    if case.review_label and case.review_label not in REVIEW_LABELS:
        raise ValueError(
            f"Invalid review_label: '{case.review_label}'\n"
            f"Allowed values: {REVIEW_LABELS}"
        )
    if not case.error_description.strip():
        raise ValueError("error_description must not be empty.")


def build_vector_text(case: Case) -> str:
    if case.error_type == "Key Term Mismatch":
        return f"{case.error_type} | {case.error_description}"
    parts = [case.error_type, case.error_description]
    if getattr(case, "source_text", ""):
        parts.append(f"Source: {case.source_text}")
    if getattr(case, "target_text", ""):
        parts.append(f"Target: {case.target_text}")
    return " | ".join(parts)


# --------------------------------------------------------------------------
# Insertion
# --------------------------------------------------------------------------
def insert_case(case: Case) -> int:
    import numpy as np
    validate_case(case)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cases (
            error_type, error_description,
            source_text, target_text,
            review_label, false_alarm_reason,
            annotator, severity, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        case.error_type, case.error_description,
        case.source_text, case.target_text,
        case.review_label, case.false_alarm_reason,
        case.annotator, case.severity, case.reason,
    ))
    case_id = cursor.lastrowid
    conn.commit()
    conn.close()

    vector = embed([build_vector_text(case)])
    index = get_faiss_index()
    index.add_with_ids(vector, np.array([case_id], dtype=np.int64))
    save_faiss_index()

    print(f"[store] Case inserted: id={case_id}, type={case.error_type}, label={case.review_label}")
    return case_id


def import_library(json_path: str) -> list[int]:
    import json
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    cases = [
        Case(
            error_type=item["error_type"],
            error_description=item["error_description"],
            source_text=item.get("source_text", ""),
            target_text=item.get("target_text", ""),
            review_label=item.get("review_label", ""),
            false_alarm_reason=item.get("false_alarm_reason", ""),
            annotator=item.get("annotator", ""),
            severity=item.get("severity", "Minor"),
            reason=item.get("reason", item.get("false_alarm_reason", "")),
        )
        for item in data
    ]
    return insert_cases_batch(cases)


def insert_cases_batch(cases: list[Case]) -> list[int]:
    import numpy as np
    if not cases:
        return []

    for case in cases:
        validate_case(case)

    conn = get_connection()
    cursor = conn.cursor()
    case_ids = []
    for case in cases:
        cursor.execute("""
            INSERT INTO cases (
                error_type, error_description,
                source_text, target_text,
                review_label, false_alarm_reason,
                annotator, severity, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case.error_type, case.error_description,
            case.source_text, case.target_text,
            case.review_label, case.false_alarm_reason,
            case.annotator, case.severity, case.reason,
        ))
        case_ids.append(cursor.lastrowid)
    conn.commit()
    conn.close()

    vectors = embed([build_vector_text(c) for c in cases])
    index = get_faiss_index()
    index.add_with_ids(vectors, np.array(case_ids, dtype=np.int64))
    save_faiss_index()

    print(f"[store] Batch inserted {len(cases)} cases. IDs: {case_ids}")
    return case_ids
