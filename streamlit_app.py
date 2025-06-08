
"""
streamlit_app.py  ·  v0.2.10  (June 2025)

ACA Viewer – self-contained Streamlit app with PDF.js viewer.

Features:
• Dev mode with SIMULATE toggle
• PDF.js viewer for selectable text + PyMuPDF annotations
• TOC navigation + NER & search overlays
• Saved & fuzzy searches (TinyDB) with clickable navigation
• Inline comments
• Two-doc diff view
• Admin page via ?admin=1
• Uses st.query_params and st.rerun() with fallback
• Guarded to run only via `streamlit run`
"""
import os, re, sys, datetime, base64
from functools import lru_cache
from pathlib import Path

import streamlit as st
import fitz  # PyMuPDF
from Levenshtein import distance
from tinydb import TinyDB, Query
from requests import Session
import streamlit.components.v1 as components

# ─── Config ─────────────────────────────────────────────
PALANTIR_BASE = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107","#03A9F4","#8BC34A","#E91E63",
              "#9C27B0","#FF5722","#607D8B","#FF9800"]

# Ensure app is run with Streamlit
if not hasattr(st, 'runtime') or not hasattr(st.runtime, 'scriptrunner_utils'):
    print("⚠️  Please run with: streamlit run streamlit_app.py")
    sys.exit(1)

@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict = None):
    """Fetch JSON from Foundry endpoint."""
    url = f"{PALANTIR_BASE}{endpoint}"
    sess = Session(); sess.headers.update(HEADERS)
    res = sess.get(url, params=params, timeout=30)
    res.raise_for_status()
    return res.json()

# ─── Utilities ───────────────────────────────────────────
def extract_text(data: bytes, name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == '.pdf':
        doc = fitz.open(stream=data, filetype='pdf')
        return '\n'.join(p.get_text('text') for p in doc)
    if ext in ('.doc', '.docx'):
        import docx2txt, tempfile
        with tempfile.NamedTemporaryFile(delete=False) as t:
            t.write(data); t.flush()
            return docx2txt.process(t.name)
    if ext == '.sec':
        return data.decode('utf-8','ignore')
    raise ValueError('Unsupported file type')


def diff_strings(a: str, b: str, ctx: int = 3) -> list[str]:
    import difflib
    return list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), lineterm='', n=ctx,
        fromfile='Doc A', tofile='Doc B'
    ))

def next_color(i: int) -> str:
    return COLOR_POOL[i % len(COLOR_POOL)]


def fuzzy_positions(text: str, term: str, maxd: int) -> list[tuple[int,int]]:
    hits = []
    for m in re.finditer(r'\b\w+\b', text, re.I):
        if distance(m.group(0).lower(), term.lower()) <= maxd:
            hits.append((m.start(), m.end()))
    return hits

# ─── App Setup ───────────────────────────────────────────
st.set_page_config(page_title='ACA Viewer', layout='wide')
params = st.query_params
ADMIN = params.get('admin',['0'])[0] == '1'

# ─── Sidebar ─────────────────────────────────────────────
with st.sidebar:
    st.title('ACA Viewer')
    SIMULATE = st.checkbox('Dev mode (simulate pipelines)', value=False)
    st.markdown('---')
    if st.button('Reload'):
        try:
            st.rerun()
        except AttributeError:
            st.experimental_rerun()
    if not ADMIN:
        st.markdown('[Switch to Admin view](?admin=1)')
    # Settings at bottom
    st.markdown("<div style='position:absolute; bottom:0; width:90%;'>", unsafe_allow_html=True)
    with st.expander('Settings', expanded=False):
        maxd = st.slider('Max edit distance', min_value=0, max_value=5, value=1)
    st.markdown('</div>', unsafe_allow_html=True)

# ─── Admin View ──────────────────────────────────────────
if ADMIN:
    st.header('Admin: Saved Searches & Comments')
    st.subheader('Search Terms')
    for r in DB.table('searches').all():
        st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all():
        st.write(c)
    st.stop()

# ─── File Uploads ────────────────────────────────────────
# Document A
f1 = st.sidebar.file_uploader('Document A', type=['pdf','docx','sec'])
if not f1:
    st.info('Please upload Document A to proceed')
    st.stop()
bytes1 = f1.read()
# Document B (diff) under Advanced
with st.sidebar.expander('Advanced', expanded=False):
    f2 = st.file_uploader('Document B (diff)', type=['pdf','docx','sec'])

# ─── Pipeline Data (or stub) ────────────────────────────
if SIMULATE:
    toc = {'entries': []}
    ner = {'entities': []}
else:
    toc = palantir_get('/pipelines/toc_extract', params={'fileName': f1.name})
    ner = palantir_get('/pipelines/ner_extract', params={'fileName': f1.name})

# ─── Render PDF with PyMuPDF annotations via iframe ─────
st.title('ACA Viewer')
if f1.name.lower().endswith('.pdf'):
    doc = fitz.open(stream=bytes1, filetype='pdf')
    # Highlight NER
    for ent in ner.get('entities', []):
        pg = ent.get('page'); coords = ent.get('coords')
        if pg is not None and coords:
            doc[pg].add_highlight_annot(fitz.Rect(*coords))
    # Highlight saved searches & fuzzy
    full_text = extract_text(bytes1, f1.name)
    for term in [r['term'] for r in DB.table('searches').all()]:
        # exact matches
        for m in re.finditer(re.escape(term), full_text, re.I):
            pg_idx = next((i for i, p in enumerate(doc) if m.start() < len(p.get_text('text'))), 0)
            coords_list = doc[pg_idx].search_for(term)
            if coords_list:
                doc[pg_idx].add_highlight_annot(fitz.Rect(*coords_list[0]))
        # fuzzy
        for s,e in fuzzy_positions(full_text, term, maxd):
            pg_idx = next((i for i, p in enumerate(doc) if s < len(p.get_text('text'))), 0)
            coords_list = doc[pg_idx].search_for(full_text[s:e])
            if coords_list:
                doc[pg_idx].add_highlight_annot(fitz.Rect(*coords_list[0]))
    # Serve annotated PDF in iframe
    pdf_bytes = doc.write()
    b64 = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_url = f"data:application/pdf;base64,{b64}"
    components.iframe(pdf_url, width='100%', height=800, scrolling=True)
else:
    st.write('Non-PDF preview not supported.')

# ─── Clickable Search Results ───────────────────────────
full_text = extract_text(bytes1, f1.name)
offsets = []
acc = 0
for p in fitz.open(stream=bytes1, filetype='pdf'):
    offsets.append(acc)
    acc += len(p.get_text('text')) + 1
hits = []
for term in [r['term'] for r in DB.table('searches').all()]:
    for s,e in fuzzy_positions(full_text, term, maxd):
        pg = max(i for i, off in enumerate(offsets) if s >= off)
        snippet = full_text[s:e]
        hits.append({'term': term, 'snippet': snippet, 'page': pg})
        # increment count
        q = Query()
        T = DB.table('searches')
        if T.get(q.term == term):
            T.update({'hits': T.get(q.term == term)['hits'] + 1}, q.term == term)
with st.sidebar.expander('Search Results', expanded=True):
    for idx, h in enumerate(hits[:50]):
        label = f"{h['term']} (p{h['page']+1}): {h['snippet'][:30]}..."
        if st.button(label, key=f'srch{idx}'):
            st.session_state['goto_page'] = h['page']

# ─── Comments ───────────────────────────────────────────
st.subheader('Comments')
snip = st.text_area('Selected snippet')
note = st.text_input('Note')
if st.button('Save Comment') and snip and note:
    DB.table('comments').insert({
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'file': f1.name,
        'snippet': snip,
        'note': note
    })
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

# ─── Diff View ───────────────────────────────────────────
if f2:
    st.subheader('Diff')
    text2 = extract_text(f2.read(), f2.name)
    for line in diff_strings(full_text, text2):
        st.code(line)
