
"""
streamlit_app.py  ·  v0.2.3  (June 2025)

ACA Viewer – complete, self-contained Streamlit app.

Features:
• SIMULATE_PALANTIR flag / sidebar toggle
• Levenshtein fuzzy search
• Rectangle overlays via PDF coords
• TinyDB persistence for comments & saved searches
• Admin page for User B via ?admin=1
• Uses st.query_params and st.rerun() (with fallback)
• Exits cleanly if run with “python” instead of “streamlit run”
"""

# ── stdlib ───────────────────────────────────────────────
import io
import os
import re
import sys
import datetime
from functools import lru_cache
from pathlib import Path

# ── third-party ──────────────────────────────────────────
import streamlit as st
import fitz                          # PyMuPDF
from Levenshtein import distance     # fuzzy search
from tinydb import TinyDB, Query      # JSON DB
from requests import Session

# ── CONFIG ───────────────────────────────────────────────
PALANTIR_BASE  = os.getenv("PALANTIR_BASE",  "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
SIMULATE       = bool(int(os.getenv("SIMULATE_PALANTIR", "0")))
DB             = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS        = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}

COLOR_POOL = [
    "#FFC107", "#03A9F4", "#8BC34A", "#E91E63",
    "#9C27B0", "#FF5722", "#607D8B", "#FF9800",
]

# ── guard: must run via `streamlit run` ─────────────────
if not hasattr(st, "runtime") or not hasattr(st.runtime, "scriptrunner_utils"):
    print("\n⚠️  Please start this app with:\n\n    streamlit run streamlit_app.py\n")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
#  PALANTIR helper (live or simulated)
# ══════════════════════════════════════════════════════════════
@lru_cache(maxsize=128)
def palantir_get(endpoint: str, params: dict | None = None):
    """Fetch from Foundry or return mock JSON when SIMULATE."""
    if SIMULATE:
        if "toc_extract" in endpoint:
            return {"entries": [
                {"title": "CHAPTER 1 INTRODUCTION", "page": 0},
                {"title": "1-1 Purpose",            "page": 1},
            ]}
        if "ner_extract" in endpoint:
            return {"entities": [
                {"id": "e1", "text": "Department of Defense", "label": "ORG",
                 "page": 0, "coords": [50, 100, 320, 118]},
                {"id": "e2", "text": "United States",         "label": "LOC",
                 "page": 0, "coords": [50, 180, 250, 198]},
            ]}
        if "sec_parse" in endpoint:
            return {"section": "dummy-sec-json"}
        return {}
    url = f"{PALANTIR_BASE}{endpoint}"
    s = Session()
    s.headers.update(HEADERS)
    resp = s.get(url, params=params, timeout=45)
    resp.raise_for_status()
    return resp.json()

# ══════════════════════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════════════════════
def extract_text(data: bytes, name: str) -> str:
    suf = Path(name).suffix.lower()
    if suf == ".pdf":
        pdf = fitz.open(stream=data, filetype="pdf")
        return "\n".join(page.get_text("text") for page in pdf)
    elif suf in {".doc", ".docx"}:
        import docx2txt, tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            return docx2txt.process(tmp.name)
    elif suf == ".sec":
        return data.decode("utf-8", "ignore")
    else:
        raise ValueError("Unsupported file type")


def next_color(idx: int) -> str:
    return COLOR_POOL[idx % len(COLOR_POOL)]


def fuzzy_positions(text: str, term: str, max_dist: int) -> list[tuple[int,int]]:
    matches = []
    for m in re.finditer(r'\b\w+\b', text, re.I):
        w = m.group(0)
        if distance(w.lower(), term.lower()) <= max_dist:
            matches.append((m.start(), m.end()))
    return matches


def diff_strings(a: str, b: str, ctx: int = 3) -> list[str]:
    import difflib
    return list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), lineterm="", n=ctx,
        fromfile="Doc A", tofile="Doc B"
    ))

# ══════════════════════════════════════════════════════════════
#  STREAMLIT APP
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="ACA Viewer", page_icon="📑", layout="wide")
params = st.query_params
ADMIN_VIEW = params.get("admin", ["0"])[0] == "1"

# Sidebar controls
with st.sidebar:
    st.title("ACA ⚙️")
    if "simulate" not in st.session_state:
        st.session_state.simulate = SIMULATE
    SIMULATE = st.checkbox("🛠 Dev mode (simulate Palantir)", value=st.session_state.simulate)
    st.session_state.simulate = SIMULATE
    if st.button("Reload page"):
        try: st.rerun()
        except AttributeError: st.experimental_rerun()
    if not ADMIN_VIEW:
        st.markdown("[Switch to Admin view](?admin=1)")

if ADMIN_VIEW:
    st.header("👩‍🔧 Admin – saved searches & comments")
    searches = DB.table("searches").all()
    comments = DB.table("comments").all()
    st.subheader(f"🔍 Saved searches ({len(searches)})")
    for r in searches:
        st.write(f"- **{r['term']}** · used {r['hits']}× · id `{r.doc_id}`")
    st.subheader(f"💬 Comments ({len(comments)})")
    for c in comments:
        st.write(f"• *{c['snippet']}* — {c['note']} _(on {c['file']})_")
    sys.exit(0)

# Upload area
c1, c2 = st.columns(2)
with c1:
    f1 = st.file_uploader("Document A", type=["pdf","docx","doc","sec"], key="A")
with c2:
    f2 = st.file_uploader("Document B (optional diff)", type=["pdf","docx","doc","sec"], key="B")

# Fallback sample
if not f1:
    if SIMULATE:
        sample = os.getenv("SIM_SAMPLE_PATH", "./sample.pdf")
        if Path(sample).exists():
            f1 = open(sample, "rb")
            st.warning(f"🔧 Using sample: {sample}")
        else:
            st.error(f"Sample not found: {sample}")
            st.stop()
    else:
        st.info("Upload at least one file ⬆️")
        st.stop()

# Read file bytes once
doc_bytes = f1.read()

# Fetch Palantir data
with st.spinner("Fetching Palantir data…"):
    toc = palantir_get("/pipelines/toc_extract", {"fileName": f1.name})
    ner = palantir_get("/pipelines/ner_extract", {"fileName": f1.name})
    sec_json = palantir_get("/pipelines/sec_parse", {"fileName": f1.name}) if f1.name.lower().endswith(".sec") else None

# Highlight controls
st.sidebar.header("🔦 Highlight controls")
show_toc = st.sidebar.checkbox("Show TOC cards", True)
if show_toc:
    for i, entry in enumerate(toc.get("entries", [])):
        if st.sidebar.button(entry["title"], key=f"toc-{i}"):
            st.session_state["goto_page"] = entry["page"]

st.sidebar.subheader("NER labels")
all_labels = sorted({e["label"] for e in ner.get("entities", [])})
active_labels = st.sidebar.multiselect("Show labels:", all_labels, default=all_labels)

st.sidebar.subheader("🔍 Saved searches")
SearchTbl = DB.table("searches")
def incr_hit(term):
    q = Query(); cur = SearchTbl.get(q.term == term)
    if cur:
        SearchTbl.update({"hits": cur["hits"] + 1}, doc_ids=[cur.doc_id])
    else:
        SearchTbl.insert({"term": term, "hits": 1})

saved_terms = [r["term"] for r in SearchTbl.all()]
active_terms = st.sidebar.multiselect("Activate terms:", saved_terms, default=saved_terms)
new_term = st.sidebar.text_input("New term")
if st.sidebar.button("Save term") and new_term.strip():
    SearchTbl.insert({"term": new_term.strip(), "hits": 0})
    try: st.rerun()
    except: st.experimental_rerun()

st.sidebar.subheader("Fuzzy search")
max_dist = st.sidebar.slider("Max edit distance", 0, 5, 1)

# Main viewer
st.title("📑 ACA Viewer")
pdf = fitz.open(stream=doc_bytes, filetype="pdf") if f1.name.lower().endswith(".pdf") else None
page_no = st.session_state.get("goto_page", 0)
if pdf:
    page = pdf[page_no]
    for ent in ner.get("entities", []):
        if ent.get("label") in active_labels and ent.get("page")==page_no and ent.get("coords"):
            rect = fitz.Rect(*ent["coords"])
            col = next_color(all_labels.index(ent["label"]))
            page.draw_rect(rect, color=fitz.utils.getColor(col), fill=fitz.utils.getColor(col+"55"))
    st.image(page.get_pixmap().tobytes(), use_column_width=True)
else:
    st.warning("Non-PDF rendering placeholder.")

text = extract_text(doc_bytes, f1.name)
st.subheader("Matches")
hits = []
for term in active_terms:
    for s, e in fuzzy_positions(text, term, max_dist):
        snippet = text[max(0, s-30):e+30].replace("\n", " ")
        hits.append({"term": term, "snippet": snippet})
    incr_hit(term)
st.write(f"Found {len(hits)} matches.")
for h in hits[:250]: st.write(f"• **{h['term']}** …{h['snippet']}…")

# Commenting
st.subheader("💬 Add comment")
snippet_sel = st.text_input("Snippet (copy/paste)")
note = st.text_area("Your note")
if st.button("Save comment") and snippet_sel.strip() and note.strip():
    DB.table("comments").insert({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "file": f1.name,
        "snippet": snippet_sel.strip(),
        "note": note.strip()
    })
    try: st.rerun()
    except: st.experimental_rerun()

# Diff viewer
if f2:
    st.subheader("🔍 Diff Viewer")
    other_text = extract_text(f2.read(), f2.name)
    diff = diff_strings(text, other_text)
    st.code("\n".join(diff), language="diff")

