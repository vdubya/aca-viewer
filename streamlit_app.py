"""
streamlit_app.py  ·  v0.2.4  (June 2025)

ACA Viewer – self-contained Streamlit app.

Features:
• SIMULATE_PALANTIR flag / sidebar toggle
• Levenshtein fuzzy search
• Rectangle overlays via PDF coords
• TinyDB persistence for comments & saved searches
• Admin page for User B via ?admin=1
• Uses st.query_params and st.rerun() (with fallback)
• Exits cleanly if run with “streamlit run”
"""

# ── stdlib ───────────────────────────────────────────────
import io, os, re, sys, datetime
from functools import lru_cache
from pathlib import Path

# ── third-party ──────────────────────────────────────────
import streamlit as st
import fitz                          # PyMuPDF
from Levenshtein import distance     # fuzzy
from tinydb import TinyDB, Query      # JSON DB
from requests import Session

# ── CONFIG ───────────────────────────────────────────────
PALANTIR_BASE  = os.getenv("PALANTIR_BASE",  "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
SIMULATE       = False  # default; controlled by sidebar
DB             = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS        = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}

COLOR_POOL = [
    "#FFC107","#03A9F4","#8BC34A","#E91E63",
    "#9C27B0","#FF5722","#607D8B","#FF9800",
]

# guard: must run via streamlit
if not hasattr(st, "runtime") or not hasattr(st.runtime, "scriptrunner_utils"):
    print("Run with: streamlit run streamlit_app.py")
    sys.exit(1)

# ══════════ PALANTIR HELPER ══════════
@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict=None):
    """Fetch from Foundry REST."""
    url = f"{PALANTIR_BASE}{endpoint}"
    s = Session(); s.headers.update(HEADERS)
    resp = s.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

# ══════════ UTILITIES ══════════
def extract_text(data: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        pdf = fitz.open(stream=data, filetype="pdf")
        return "\n".join(p.get_text("text") for p in pdf)
    if ext in {".doc",".docx"}:
        import docx2txt, tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data); tmp.flush()
            return docx2txt.process(tmp.name)
    if ext == ".sec":
        return data.decode("utf-8","ignore")
    raise ValueError("Unsupported file type")

def next_color(i): return COLOR_POOL[i%len(COLOR_POOL)]

def fuzzy_positions(txt, term, maxd):
    out=[]
    for m in re.finditer(r'\b\w+\b', txt, re.I):
        if distance(m.group(0).lower(), term.lower())<=maxd:
            out.append((m.start(), m.end()))
    return out

# ══════════ APP ══════════
st.set_page_config(page_title="ACA Viewer",layout="wide")
params=st.query_params
ADMIN=params.get("admin",["0"])[0]=="1"

# Sidebar
with st.sidebar:
    st.title("ACA Viewer 🌐")
    SIMULATE=st.checkbox("Dev mode (simulate)",value=False)
    st.markdown("---")
    if st.button("Reload"):
        try: st.rerun()
        except: st.experimental_rerun()
    if not ADMIN:
        st.markdown("[Admin view](?admin=1)")

if ADMIN:
    st.header("Admin – saved searches & comments")
    # show DB tables
    st.subheader("Searches")
    for r in DB.table("searches").all(): st.write(r)
    st.subheader("Comments")
    for c in DB.table("comments").all(): st.write(c)
    st.stop()

# Uploads
c1,c2=st.columns(2)
with c1: f1=st.file_uploader("Document A", type=["pdf","docx","sec"])
with c2: f2=st.file_uploader("Document B (diff)", type=["pdf","docx","sec"])
if not f1:
    st.info("Upload Document A")
    st.stop()

# Read bytes
doc_bytes=f1.read()

# Pipelines (stub if simulate)
if SIMULATE:
    toc={"entries":[]}  
    ner={"entities":[]}
else:
    with st.spinner("Fetching pipelines…"):
        toc=palantir_get("/pipelines/toc_extract",params={"fileName":f1.name})
        ner=palantir_get("/pipelines/ner_extract",params={"fileName":f1.name})
        sec_json=palantir_get("/pipelines/sec_parse",params={"fileName":f1.name}) if f1.name.lower().endswith(".sec") else None

# Sidebar highlight
st.sidebar.header("Highlights 🔦")
show_toc=st.sidebar.checkbox("TOC Cards",True)
if show_toc:
    for i,e in enumerate(toc.get("entries",[])):
        if st.sidebar.button(e["title"][:50],key=i): st.session_state["pg"]=e["page"]
labels=sorted({x["label"] for x in ner.get("entities",[])})
active_lbl=st.sidebar.multiselect("Entities",labels,default=labels[:3])
# Saved searches
tbl=DB.table("searches")
ps=[r["term"] for r in tbl.all()]
sel=st.sidebar.multiselect("Search terms",ps,default=ps)
ns=st.sidebar.text_input("New term")
if st.sidebar.button("Add term") and ns:
    tbl.insert({"term":ns,"hits":0});st.experimental_rerun()
# Fuzzy
dmax=st.sidebar.slider("Max edit",0,5,1)

# Render PDF
st.title("ACA Viewer")
if f1.name.lower().endswith(".pdf"):
    pg=st.session_state.get("pg",0)
    doc=fitz.open(stream=doc_bytes,filetype="pdf")
    p=doc[pg]
    # draw entities
    for ent in ner.get("entities",[]):
        if ent["label"] in active_lbl and ent.get("coords") and ent.get("page")==pg:
            r=fitz.Rect(*ent["coords"])
            c=next_color(labels.index(ent["label"]))
            p.draw_rect(r,color=fitz.utils.getColor(c),fill=fitz.utils.getColor(c+"55"))
    st.image(p.get_pixmap().tobytes(),use_column_width=True)
else:
    st.write("Non-PDF view")

# Text matches
txt=extract_text(doc_bytes,f1.name)
st.subheader("Matches")
hits=[]
for t in sel:
    for s,e in fuzzy_positions(txt,t,dmax):
        hits.append(f"{t}: {txt[s:e]}")
DB.table("searches").update(lambda r: {"hits":r["hits"]+len([1 for _ in fuzzy_positions(txt,r["term"],dmax)])},Query().term_test=lambda v: True)
for m in hits[:50]: st.write(m)

# Comments
st.subheader("Comments 💬")
cs=st.text_area("Selected text")
note=st.text_input("Note")
if st.button("Save") and cs and note:
    DB.table("comments").insert({"time":datetime.datetime.utcnow().isoformat(),"file":f1.name,"snippet":cs,"note":note});st.experimental_rerun()

# Diff
if f2:
    st.subheader("Diff 🔍")
    ot=extract_text(f2.read(),f2.name)
    for line in diff_strings(txt,ot): st.code(line)
