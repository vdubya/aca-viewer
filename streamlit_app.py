"""
aca_viewer.py  ·  v0.2.0  (June 2025)

Changes vs v0.1.0
──────────────────
✓ SIMULATE_PALANTIR flag / sidebar toggle.
✓ Levenshtein-based fuzzy search.
✓ Rectangle overlay highlights using coordinates.
✓ TinyDB persistence for comments + saved searches.
✓ Simple Admin view for User B.

Run:
    export SIMULATE_PALANTIR=1   # optional
    streamlit run aca_viewer.py
"""
# ── stdlib ───────────────────────────────────────────────
import io, json, os, re, uuid, datetime
from functools import lru_cache
from pathlib import Path
# ── third-party ──────────────────────────────────────────
import streamlit as st
import fitz                          # PyMuPDF
from Levenshtein import distance     # fuzzy
from tinydb import TinyDB, Query      # persistence
from requests import Session

# ── config ───────────────────────────────────────────────
PALANTIR_BASE   = os.getenv("PALANTIR_BASE",   "https://foundry.api.dod.mil")
PALANTIR_TOKEN  = os.getenv("PALANTIR_TOKEN",  "###-token-###")
SIMULATE        = bool(int(os.getenv("SIMULATE_PALANTIR", "0")))
DB              = TinyDB(Path(__file__).with_name("aca_store.json"))

HEADERS         = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}

COLOR_POOL = [
    "#FFC107", "#03A9F4", "#8BC34A", "#E91E63",
    "#9C27B0", "#FF5722", "#607D8B", "#FF9800",
]

# ═════════════════ Palantir helper ═══════════════════════
@lru_cache(maxsize=128)
def palantir_get(endpoint: str, params: dict | None = None):
    """Live call or mock depending on SIMULATE flag."""
    if SIMULATE:
        # — minimal stub —
        if "toc_extract" in endpoint:
            return {"entries": [
                {"title": "CHAPTER 1 INTRODUCTION", "page": 0},
                {"title": "1-1 Purpose",            "page": 1},
            ]}
        if "ner_extract" in endpoint:
            return {"entities": [
                {"id": "e1", "text": "Department of Defense", "label": "ORG",
                 "page": 0, "coords": [50, 100, 320, 118]},
                {"id": "e2", "text": "United States", "label": "LOC",
                 "page": 0, "coords": [50, 180, 250, 198]},
            ]}
        if "sec_parse" in endpoint:
            return {"section": "dummy-sec-json"}
        return {}
    # — real call —
    url = f"{PALANTIR_BASE}{endpoint}"
    s = Session(); s.headers.update(HEADERS)
    resp = s.get(url, params=params, timeout=45)
    resp.raise_for_status()
    return resp.json()

# ═════════════════ misc utils ════════════════════════════
def extract_text(data: bytes, name: str) -> str:
    """Return plain text."""
    suf = Path(name).suffix.lower()
    if suf == ".pdf":
        pdf = fitz.open(stream=data, filetype="pdf")
        return "\n".join(p.get_text("text") for p in pdf)
    elif suf in {".doc", ".docx"}:
        import docx2txt, tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            return docx2txt.process(tmp.name)
    elif suf == ".sec":
        return data.decode("utf-8", "ignore")
    raise ValueError("Unsupported filetype")

def next_color(i: int) -> str: return COLOR_POOL[i % len(COLOR_POOL)]

def fuzzy_positions(text: str, term: str, max_dist: int) -> list[tuple[int,int]]:
    """Return [(start,end), …] of fuzzy matches <= max_dist."""
    out, tlen = [], len(term)
    for m in re.finditer(r'\b\w+\b', text, re.I):
        piece = m.group(0)
        if distance(piece.lower(), term.lower()) <= max_dist:
            out.append((m.start(), m.end()))
    return out

# ═════════════════ Streamlit UI ═══════════════════════════
st.set_page_config(page_title="ACA Viewer", page_icon="📑", layout="wide")
params = st.experimental_get_query_params()
ADMIN_VIEW = "admin" in params or params.get("admin", ["0"])[0] == "1"

with st.sidebar:
    st.title("ACA ⚙️")
    SIMULATE = st.checkbox("🛠 Dev mode (simulate Palantir)", value=SIMULATE)
    if st.button("Reload page"): st.experimental_rerun()
    if not ADMIN_VIEW:
        st.markdown("[Admin view](?admin=1)")

if ADMIN_VIEW:
    st.header("👩‍🔧 Admin – curated searches & comments")
    searches = DB.table("searches").all()
    comments = DB.table("comments").all()
    st.subheader(f"Saved search terms ({len(searches)})")
    for row in searches:
        st.write(f"- **{row['term']}** · used {row['hits']}× · id `{row.doc_id}`")
    st.subheader(f"Comments ({len(comments)})")
    for c in comments:
        st.write(f"• *{c['snippet']}* — {c['note']}  _(on {c['file']})_")
    st.stop()

# ─── Uploads ─────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1: f1 = st.file_uploader("Document A", type=["pdf","docx","doc","sec"], key="A")
with c2: f2 = st.file_uploader("Document B (optional diff)", type=["pdf","docx","doc","sec"], key="B")
if not f1: st.info("Upload at least one file"); st.stop()

# ─── Fetch pipeline JSON (or mock) ───────────────────────
with st.spinner("Fetching Palantir data…"):
    toc_data = palantir_get("/pipelines/toc_extract", {"fileName": f1.name})
    ner_data = palantir_get("/pipelines/ner_extract", {"fileName": f1.name})

# ─── Sidebar controls ────────────────────────────────────
st.sidebar.header("Highlight controls")

# → TOC
show_toc = st.sidebar.checkbox("Show TOC cards", True)
if show_toc:
    for i,e in enumerate(toc_data.get("entries", [])):
        if st.sidebar.button(e["title"][:60], key=f"toc{i}"):
            st.session_state["goto_page"] = e["page"]

# → NER
st.sidebar.subheader("NER labels")
labels = sorted({e["label"] for e in ner_data["entities"]})
active_labels = st.sidebar.multiselect("Show labels:", labels, default=labels)

# → Saved searches (TinyDB)
st.sidebar.subheader("Saved searches")
SearchTbl = DB.table("searches")
def incr_hit(term):
    q=Query(); cur=SearchTbl.get(q.term==term)
    if cur: SearchTbl.update({"hits":cur["hits"]+1}, doc_ids=[cur.doc_id])
    else:   SearchTbl.insert({"term":term,"hits":1})
saved_terms = [r["term"] for r in SearchTbl.all()]
active_terms = st.sidebar.multiselect("Activate:", saved_terms, default=saved_terms)
new_term = st.sidebar.text_input("Add term")
if st.sidebar.button("Save term"):
    if new_term.strip():
        SearchTbl.insert({"term":new_term.strip(),"hits":0})
        st.experimental_rerun()

# → Fuzzy slider
st.sidebar.subheader("Fuzzy search")
max_dist = st.sidebar.slider("Levenshtein max distance", 0, 5, 1)

# ─── Render document page by page ────────────────────────
pdf = fitz.open(stream=f1.read(), filetype="pdf") if f1.name.lower().endswith(".pdf") else None
goto = st.session_state.get("goto_page", 0)
for page_num in range(goto, min(goto+1, (pdf.page_count if pdf else 1))):
    if pdf:
        page = pdf[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(1,1), alpha=False)
        img = pix.pil()

        # rectangle overlays for entities with coords
        draw = fitz.Rect
        for e in ner_data["entities"]:
            if e["label"] not in active_labels or e.get("page")!=page_num: continue
            if "coords" in e:       # [x0,y0,x1,y1]
                r = e["coords"];    # Palantir gives PDF-space coords
                rect = fitz.Rect(*r)
                page.draw_rect(rect, color=fitz.utils.getColor(next_color(labels.index(e["label"]))),
                               fill=fitz.utils.getColor(next_color(labels.index(e["label"]))+"55"))

        # re-render page with rectangles
        pix = page.get_pixmap(matrix=fitz.Matrix(1,1), alpha=False)
        st.image(pix.tobytes(), use_column_width=True)
    else:
        st.warning("Non-PDF rendering placeholder (extend as needed).")

txt = extract_text(f1.read(), f1.name)  # re-read for text

# ─── Fuzzy + saved-term highlighting list ────────────────
st.subheader("Matches")
hits = []
for t in active_terms:
    pos = fuzzy_positions(txt, t, max_dist)
    for s,e in pos: hits.append({"term":t,"snippet":txt[max(0,s-30):e+30]})
    incr_hit(t)
st.write(f"Found {len(hits)} hits across active terms.")
for h in hits[:250]:
    st.write(f"• **{h['term']}** …{h['snippet']}…")

# ─── Commenting ──────────────────────────────────────────
st.subheader("💬 Comment")
sel = st.text_input("Copy/paste snippet")
note = st.text_area("Your note")
if st.button("Save comment"):
    if sel.strip() and note.strip():
        DB.table("comments").insert({
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "file": f1.name, "snippet": sel.strip(), "note": note.strip()
        })
        st.success("Saved!") ; st.experimental_rerun()

# ─── Diff view (optional) ────────────────────────────────
if f2:
    import difflib
    st.subheader("🔍 Text diff (unified)")
    t1 = txt
    t2 = extract_text(f2.read(), f2.name)
    diff = difflib.unified_diff(t1.splitlines(), t2.splitlines(),
                                fromfile=f1.name, tofile=f2.name, n=3, lineterm="")
    st.code("\n".join(diff), language="diff")
