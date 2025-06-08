```python
"""
streamlit_app.py  ·  v0.2.13  (June 2025)

ACA Viewer – self-contained Streamlit app with enhanced PDF loading.

Features:
• Dev mode with SIMULATE toggle
• PDF.js viewer via streamlit-pdf-viewer for selectable text + overlay highlights
• TOC navigation + NER & search overlays
• Saved & fuzzy searches (TinyDB) with clickable navigation
• Inline comments
• Two-doc diff view
• Admin page via ?admin=1
• Uses st.query_params and st.rerun() with fallback
• Doc A uploader on main panel; Doc B in Advanced sidebar
• Sample PDF load button for quick testing
"""
import os, re, datetime
from functools import lru_cache
from pathlib import Path

import streamlit as st
import requests
import fitz  # PyMuPDF
from Levenshtein import distance
from tinydb import TinyDB, Query
from requests import Session
from streamlit_pdf_viewer import pdf_viewer  # PDF.js component

# ─── Config ─────────────────────────────────────────────
PALANTIR_BASE  = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107","#03A9F4","#8BC34A","#E91E63",
              "#9C27B0","#FF5722","#607D8B","#FF9800"]

@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict=None):
    url = f"{PALANTIR_BASE}{endpoint}"
    sess = Session(); sess.headers.update(HEADERS)
    res = sess.get(url, params=params or {}, timeout=30)
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


def diff_strings(a: str, b: str, ctx: int=3) -> list[str]:
    import difflib
    return list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), lineterm='', n=ctx,
        fromfile='Doc A', tofile='Doc B'
    ))


def next_color(idx: int) -> str:
    return COLOR_POOL[idx % len(COLOR_POOL)]


def fuzzy_positions(text: str, term: str, maxd: int) -> list[tuple[int,int]]:
    hits=[]
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
    with st.expander('Advanced', expanded=False):
        f2 = st.file_uploader('Document B (diff)', type=['pdf','docx','sec'])
    if st.button('Reload'):
        try: st.rerun()
        except AttributeError: st.experimental_rerun()
    if not ADMIN:
        st.markdown('[Switch to Admin view](?admin=1)')
    # Settings at bottom
    st.markdown("<div style='position:absolute; bottom:0; width:90%;'>", unsafe_allow_html=True)
    with st.expander('Settings', expanded=False):
        maxd = st.slider('Max edit distance', 0, 5, 1)
    st.markdown('</div>', unsafe_allow_html=True)

# ─── Admin View ──────────────────────────────────────────
if ADMIN:
    st.header('Admin: Saved Searches & Comments')
    st.subheader('Search Terms')
    for r in DB.table('searches').all(): st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all(): st.write(c)
    st.stop()

# ─── Main Panel: Document A upload & sample button ───────┐
st.header('Document A')
viewer_bytes = None
f1 = st.file_uploader('Upload Document A', type=['pdf','docx','sec'], key='mainA')
if st.button('Load Sample PDF'):
    sample_url = 'https://www.wbdg.org/FFC/DOD/UFC/ufc_1_300_01_2021.pdf'
    try:
        resp = requests.get(sample_url)
        resp.raise_for_status()
        viewer_bytes = resp.content
        st.success('Loaded sample PDF')
    except Exception as e:
        st.error(f"Error loading sample PDF: {e}")
if f1:
    viewer_bytes = f1.read()
if not viewer_bytes:
    st.info('Please upload Document A or click Load Sample')
    st.stop()
# document name for extract_text fallback
doc_name = f1.name if f1 else sample_url.split('/')[-1]

# ─── Pipeline Data (or stub) ────────────────────────────
if SIMULATE:
    toc, ner = {'entries':[]}, {'entities':[]}
else:
    toc = palantir_get('/pipelines/toc_extract', params={'fileName': doc_name})
    ner = palantir_get('/pipelines/ner_extract', params={'fileName': doc_name})

# ─── Compute Annotations ─────────────────────────────────
doc = fitz.open(stream=viewer_bytes, filetype='pdf')
annotations = []
# NER annotations
for ent in ner.get('entities', []):
    pg = ent.get('page'); coords = ent.get('coords')
    if pg is not None and coords:
        annotations.append({'page':pg,'coords':coords,'color':next_color(hash(ent['label']))})
# Search annotations
txt_all = extract_text(viewer_bytes, doc_name)
for term in [r['term'] for r in DB.table('searches').all()]:
    for m in re.finditer(re.escape(term), txt_all, re.I):
        pg_idx = next((i for i,p in enumerate(doc) if m.start()<len(p.get_text('text'))),0)
        rects = doc[pg_idx].search_for(term)
        if rects: annotations.append({'page':pg_idx,'coords':[rects[0].x0,rects[0].y0,rects[0].x1,rects[0].y1],'color':next_color(hash(term))})
    for s,e in fuzzy_positions(txt_all, term, maxd):
        snippet = txt_all[s:e]
        for i in range(len(doc)):
            rects = doc[i].search_for(snippet)
            if rects: annotations.append({'page':i,'coords':[rects[0].x0,rects[0].y0,rects[0].x1,rects[0].y1],'color':next_color(hash(term))}); break

# ─── Render PDF via streamlit-pdf-viewer ────────────────
st.title('ACA Viewer')
pdf_viewer(viewer_bytes, height=800, annotations=annotations)

# ─── Clickable Search Results ───────────────────────────
offsets=[]; acc=0
for p in doc: offsets.append(acc); acc += len(p.get_text('text'))+1
hits=[]
for term in [r['term'] for r in DB.table('searches').all()]:
    for s,e in fuzzy_positions(txt_all, term, maxd):
        pg = max(i for i, off in enumerate(offsets) if s >= off)
        hits.append({'term':term,'snippet':txt_all[s:e],'page':pg})
        q=Query(); T=DB.table('searches')
        if T.get(q.term==term): T.update({'hits':T.get(q.term==term)['hits']+1},q.term==term)
with st.sidebar.expander('Search Results',expanded=True):
    for idx,h in enumerate(hits[:50]):
        lbl=f"{h['term']} (p{h['page']+1}): {h['snippet'][:30]}..."
        if st.button(lbl, key=f'srch{idx}'): st.session_state['goto_page']=h['page']

# ─── Comments ───────────────────────────────────────────
st.subheader('Comments')
snip = st.text_area('Selected snippet')
note = st.text_input('Note')
if st.button('Save Comment') and snip and note:
    DB.table('comments').insert({'timestamp':datetime.datetime.utcnow().isoformat(),'file':doc_name,'snippet':snip,'note':note});
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

# ─── Diff View ───────────────────────────────────────────
if 'f2' in locals() and f2:
    st.subheader('Diff')
    txt2 = extract_text(f2.read(), f2.name)
    for line in diff_strings(txt_all, txt2): st.code(line)
```
