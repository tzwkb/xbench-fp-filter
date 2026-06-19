"""
make_dist.py
------------
Build a distributable zip of Xbench FP Filter on the Desktop.

Excludes secrets and customer/generated data:
  - config.py (real API key)            -> replaced by a placeholder generated from config_template.py
  - data/ (customer files + 66M RAG DB; UI does not read it)
  - __pycache__, *.pyc/*.pyo, *.bak*, *.xlsx/*.xls/*.faiss/*.db
  - docs/dailies, docs/annotation_requirements (internal)
  - .git, venv, embedded python runtime (setup.bat downloads it)

Run:  python scripts/make_dist.py
"""

import os
import shutil
import zipfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "xbench-fp-filter"
STAMP = "20260618"
DESKTOP = os.path.expanduser("~/Desktop")
STAGE_ROOT = os.path.join("/tmp", "xbench_dist_stage")
STAGE = os.path.join(STAGE_ROOT, NAME)
ZIP_PATH = os.path.join(DESKTOP, f"{NAME}_dist_{STAMP}.zip")

EXCLUDE_DIRS = {"__pycache__", ".git", "venv", ".venv", "env", "python",
                "data", "dailies", "annotation_requirements", ".streamlit_cache"}
EXCLUDE_FILES = {"config.py"}
EXCLUDE_EXT = {".pyc", ".pyo", ".xlsx", ".xls", ".faiss", ".db"}


def _ignore(dirpath, names):
    drop = set()
    for n in names:
        full = os.path.join(dirpath, n)
        if os.path.isdir(full):
            if n in EXCLUDE_DIRS:
                drop.add(n)
        else:
            if n in EXCLUDE_FILES:
                drop.add(n)
            elif os.path.splitext(n)[1].lower() in EXCLUDE_EXT:
                drop.add(n)
            elif ".bak" in n:
                drop.add(n)
    return drop


def build():
    if os.path.exists(STAGE_ROOT):
        shutil.rmtree(STAGE_ROOT)
    shutil.copytree(PROJ, STAGE, ignore=_ignore)

    # generate a placeholder config.py from the template so the app launches out-of-box
    tpl = os.path.join(STAGE, "config_template.py")
    cfg = os.path.join(STAGE, "config.py")
    if os.path.exists(tpl) and not os.path.exists(cfg):
        shutil.copy(tpl, cfg)

    # ---- Windows launchers must be CRLF (cmd.exe misparses LF-only .bat) ----
    for root, _, files in os.walk(STAGE):
        for f in files:
            if f.lower().endswith((".bat", ".cmd")):
                p = os.path.join(root, f)
                b = open(p, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                open(p, "wb").write(b)

    # ---- safety asserts: no secret, no customer data ----
    assert not os.path.isdir(os.path.join(STAGE, "data")), "data/ leaked into dist!"
    # read the real key from the source config.py at runtime (never hardcode it here)
    real_key = ""
    src_cfg = os.path.join(PROJ, "config.py")
    if os.path.exists(src_cfg):
        import re
        m = re.search(r'LLM_API_KEY\s*=\s*["\']([^"\']{12,})["\']',
                      open(src_cfg, encoding="utf-8").read())
        if m:
            real_key = m.group(1)
    leaks = []
    if real_key:
        for root, _, files in os.walk(STAGE):
            for f in files:
                p = os.path.join(root, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                        if real_key in fh.read():
                            leaks.append(os.path.relpath(p, STAGE))
                except Exception:
                    pass
    assert not leaks, f"REAL API KEY found in dist files: {leaks}"

    # ---- zip (Python zipfile sets UTF-8 flag for non-ascii names automatically) ----
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(STAGE):
            for f in files:
                p = os.path.join(root, f)
                arc = os.path.join(NAME, os.path.relpath(p, STAGE))
                zf.write(p, arc)
                count += 1

    size_mb = os.path.getsize(ZIP_PATH) / 1024 / 1024
    print(f"OK  {ZIP_PATH}")
    print(f"    {count} files, {size_mb:.2f} MB")
    print("--- top-level entries in dist ---")
    for n in sorted(os.listdir(STAGE)):
        tag = "/" if os.path.isdir(os.path.join(STAGE, n)) else ""
        print(f"    {n}{tag}")
    shutil.rmtree(STAGE_ROOT)


if __name__ == "__main__":
    build()
