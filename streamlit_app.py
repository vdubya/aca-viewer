"""
aca_viewer.py
Streamlit ACA Viewer  ── v0.1.0  (June 2025)

• User A  – uploads 1 or 2 docs (PDF, Word, or UFGS *.SEC XML) and interactively:
    – Toggles table-of-contents (TOC), NER hits, spelling flags, etc.
    – Highlights any selection, steps next/prev, saves searches.
    – Runs a quick 2-doc similarity/“track changes” diff (text only).

• User B  – Domain SME:
    – Views saved User A search sets, tunes rules, tags “verified” queries.

Palantir: assumes you have an authenticated Foundry REST endpoint that already
produces ⊲
    1.  Hierarchy-aware JSON for PDFs (`/pipelines/toc_extract`)
    2.  NER JSON (`/pipelines/ner_extract`)
    3.  XML→JSON for *.SEC (`/pipelines/sec_parse`)
Adapt the PALANTIR_* constants as needed.
"""

# ── STANDARD LIB ──────────────────────────────────────────────
import io, json, os, re, uuid
from functools import lru_cache
from pathlib import Path
# ── THIRD-PARTY ───────────────────────────────────────────────
import streamlit as st
import fitz  # PyMuPDF – fast PDF rendering
import difflib
from requests import Session
# ── CONFIG ────────────────────────────────────────────────────
PALANTIR_BASE   = os.getenv("PALANTIR_BASE",   "https://foundry.api.dod.mil")
PALANTIR_TOKEN  = os.getenv("PALANTIR_TOKEN",  "###-insert-token-###")
HEADERS         = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}

COLOR_POOL = [
    "#FFC107", "#03A9F4", "#8BC34A", "#E91E63",
    "#9C27B0", "#FF5722", "#607D8B", "#FF9800",
]  # material-ish accent colors for rotations


# ══════════════════════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════════════════════
@lru_cache(maxsize=128)
def palantir_get(endpoint: str, params: dict | None = None):
    """Simple cached GET wrapper for Foundry endpoints."""
    url = f"{PALANTIR_BASE}{endpoint}"
    s = Session()
    s.headers.update(HEADERS)
    resp = s.get(url, params=params, timeout=45)
    resp.raise_for_status()
    return resp.json()


def extract_text(file_bytes: bytes, file_name: str) -> str:
    """Return raw text from PDF, Word (.docx), or XML .SEC."""
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        pdf = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text("text") for page in pdf)
    elif suffix in (".docx", ".doc"):
        import docx2txt
        buf = io.BytesIO(file_bytes)
        return docx2txt.process(buf)
    elif suffix == ".sec":
        return file_bytes.decode("utf-8", errors="ignore")
    else:
        raise ValueError("Unsupported file type.")


def diff_strings(a: str, b: str, ctx: int = 3) -> list[str]:
    """Return unified-diff style list of lines."""
    return list(
        difflib.unified_diff(
            a.splitlines(), b.splitlines(),
            lineterm="", n=ctx, fromfile="Doc A", tofile="Doc B")
    )


def next_color(idx: int) -> str:
    return COLOR_POOL[idx % len(COLOR_POOL)]


# ══════════════════════════════════════════════════════════════
#  STREAMLIT APP
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ACA Viewer",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📑  ACA Viewer")
st.caption("Upload a document (or two) and explore TOC, NER hits, spelling issues, "
           "and more — all powered by your Palantir pipelines.")

# 1 — UPLOAD AREA ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
col_up1, col_up2 = st.columns(2)
with col_up1:
    f1 = st.file_uploader("Document A", type=["pdf", "docx", "doc", "sec"], key="docA")
with col_up2:
    f2 = st.file_uploader("Document B (optional for diff)", type=["pdf", "docx", "doc", "sec"], key="docB")

if not f1:
    st.info("Upload at least one file ⬆️")
    st.stop()

# 2 — FETCH PIPELINE DATA ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
with st.spinner("Contacting Palantir pipelines…"):
    toc_data = palantir_get("/pipelines/toc_extract", params={"fileName": f1.name})
    ner_data = palantir_get("/pipelines/ner_extract", params={"fileName": f1.name})
    if f1.name.lower().endswith(".sec"):
        sec_json = palantir_get("/pipelines/sec_parse", params={"fileName": f1.name})
    else:
        sec_json = None

# 3 — SIDEBAR UI  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
st.sidebar.header("🔦  Highlight Controls")

#  TOC section toggles …………………………………………………………………………………
st.sidebar.subheader("Table of Contents")
show_toc = st.sidebar.checkbox("Show TOC cards", value=True)
if show_toc:
    for i, entry in enumerate(toc_data.get("entries", [])):
        preview = entry["title"][:60] + ("…" if len(entry["title"]) > 60 else "")
        if st.sidebar.button(preview, key=f"toc-{i}"):
            st.session_state["scroll_target"] = entry["page"]

#  NER toggles ……………………………………………………………………………………………………
st.sidebar.subheader("Named Entities")
ner_labels = sorted({e["label"] for e in ner_data["entities"]})
label_selection = st.sidebar.multiselect("Entity types:", ner_labels, default=ner_labels[:4])
entity_colors = {lbl: next_color(i) for i, lbl in enumerate(ner_labels)}
visible_ids = set()
for lbl in label_selection:
    ents = [e for e in ner_data["entities"] if e["label"] == lbl]
    with st.sidebar.expander(f"{lbl}  ({len(ents)})", expanded=False):
        for ent in ents[:250]:
            ck = st.checkbox(ent["text"][:40] + ("…" if len(ent["text"]) > 40 else ""),
                             key=f"ent-{ent['id']}", value=True)
            if ck:
                visible_ids.add(ent["id"])

#  SAVED SEARCHES …………………………………………………………………………………………………
st.sidebar.subheader("Saved Searches")
if "saved_searches" not in st.session_state:
    st.session_state.saved_searches = {}
new_search = st.sidebar.text_input("Search term (regex or plain text)")
if st.sidebar.button("Save term"):
    if new_search:
        st.session_state.saved_searches[str(uuid.uuid4())] = new_search
for sid, term in st.session_state.saved_searches.items():
    vis = st.sidebar.checkbox(term, value=True, key=f"ss-{sid}")
    if not vis:
        continue

#  4 — MAIN VIEWER  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
doc_bytes = f1.read()
pdf_doc = fitz.open(stream=doc_bytes, filetype="pdf") if f1.name.lower().endswith(".pdf") else None
html_id = "docViewer"
st.markdown(f"""
<style>
#{html_id} canvas {{ width: 100% !important; height: auto !important; }}
.highlight {{ border-radius: 4px; padding:2px; }}
</style>
""", unsafe_allow_html=True)

def render_page(page_num: int):
    if pdf_doc:
        pix = pdf_doc[page_num].get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
        st.image(pix.tobytes(), use_column_width=True)
        st.write("---")
    else:
        st.warning("Non-PDF rendering is skipped for brevity.")

start_page = st.session_state.get("scroll_target", 0)
render_page(start_page)

#  5 — HIGHLIGHT LAYER  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
st.subheader("🖍️  Highlighted Text (dynamic)")
txt = extract_text(doc_bytes, f1.name)
highlighted = txt
#  apply entity highlights
for e in ner_data["entities"]:
    if e["id"] not in visible_ids:
        continue
    color = entity_colors[e["label"]]
    highlighted = highlighted.replace(
        e["text"],
        f"<span class='highlight' style='background:{color}33;border-bottom:2px solid {color};'>"
        f"{e['text']}</span>"
    )
#  apply saved-search highlights
for sid, term in st.session_state.saved_searches.items():
    if st.session_state.get(f"ss-{sid}", True):
        color = next_color(hash(sid))
        pattern = re.compile(re.escape(term), re.I)
        highlighted = pattern.sub(
            lambda m: f"<span class='highlight' style='background:{color}33;'>{m.group(0)}</span>",
            highlighted
        )
st.markdown(f"<div id='{html_id}'>{highlighted}</div>", unsafe_allow_html=True)

#  6 — COMMENTING  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
st.subheader("💬  Add Comment")
comment_txt = st.text_area("Selected text (copy/paste) and your note:")
if st.button("Save comment"):
    st.success("Comment saved (placeholder – persist however you like)")

#  7 — OPTIONAL DIFF  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
if f2:
    with st.expander("🔍  Diff Viewer (text-only)", expanded=False):
        txtA = extract_text(f1.read(), f1.name)
        txtB = extract_text(f2.read(), f2.name)
        diff_lines = diff_strings(txtA, txtB)
        st.code("\n".join(diff_lines), language="diff")


# ══════════════════════════════════════════════════════════════
#  ROADMAP / TODOS  (tracked in-code for transparency)
# ══════════════════════════════════════════════════════════════
"""
🔜  Near-term improvements
    • Replace naive text-substitution highlighting with rectangle overlays using
      the coordinate data already delivered by Palantir (SEC + PDF pipelines).
    • Persist comments & saved searches to a backend table or Foundry dataset.
    • Add fuzzy/AI search (e.g., via OpenAI embeddings + cosine similarity).
    • Expose a small admin page for User B to review and curate searches.

💡  UI Philosophy
    Hide power features behind “Advanced ▽” expanders; keep default view minimal.
"""

