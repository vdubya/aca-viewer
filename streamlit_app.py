
"""
streamlit_app.py  ·  v0.2.7  (June 2025)

ACA Viewer – self-contained Streamlit app.

Features:
• Dev mode with SIMULATE toggle
• PDF rendering + TOC navigation + NER overlays
• Fuzzy search + saved searches (TinyDB) with clickable results
• Inline comments
• Two‑doc diff view
• Admin page via ?admin=1
• Uses st.query_params and st.rerun() with fallback
• Exits if not run with `streamlit run`
"""

import os
import re
import sys
import datetime
from functools import lru_cache
from pathlib import Path

import streamlit as st
import fitz  # PyMuPDF
from Levenshtein import distance
from tinydb import TinyDB, Query
from requests import Session

# ─── Config ─────────────────────────────────────────────
PALANTIR_BASE = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107","#03A9F4","#8BC34A","#E91E63",
              "#9C27B0","#FF5722","#607D8B","#FF9800"]

# Ensure run via Streamlit
if not hasattr(st, 'runtime') or not hasattr(st.runtime, 'scriptrunner_utils'):
    print("⚠️ Run with: streamlit run streamlit_app.py")
    sys.exit(1)

# ─── Palantir helper ─────────────────────────────────────
@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict = None):
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
        return data.decode('utf-8', 'ignore')
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

# ─── App setup ───────────────────────────────────────────
st.set_page_config(page_title='ACA Viewer', layout='wide')
params = st.query_params
ADMIN = params.get('admin', ['0'])[0] == '1'

# ─── Sidebar ─────────────────────────────────────────────
with st.sidebar:
    st.title('ACA Viewer')
    SIMULATE = st.checkbox('Dev mode (simulate pipelines)', value=False)
    st.markdown('---')
    if st.button('Reload'):
        try: st.rerun()
        except AttributeError: st.experimental_rerun()
    if not ADMIN:
        st.markdown('[Switch to Admin view](?admin=1)')

# ─── Admin page ──────────────────────────────────────────
if ADMIN:
    st.header('Admin: Saved Searches & Comments')
    st.subheader('Search Terms')
    for r in DB.table('searches').all(): st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all(): st.write(c)
    st.stop()

# ─── File uploads ────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    f1 = st.file_uploader('Document A', type=['pdf','docx','sec'])
with col2:
    f2 = st.file_uploader('Document B (diff)', type=['pdf','docx','sec'])
if not f1:
    st.info('Upload at least Document A')
    st.stop()
bytes1 = f1.read()

# ─── Pipelines or stubs ─────────────────────────────────
if SIMULATE:
    toc = {'entries': []}
    ner = {'entities': []}
else:
    toc = palantir_get('/pipelines/toc_extract', params={'fileName': f1.name})
    ner = palantir_get('/pipelines/ner_extract', params={'fileName': f1.name})

# ─── Highlight & navigation controls ────────────────────
st.sidebar.header('Highlights & Results')
# TOC navigation
show_toc = st.sidebar.checkbox('Show TOC', True)
if show_toc:
    for idx, e in enumerate(toc.get('entries', [])):
        if st.sidebar.button(e['title'][:60], key=f'toc-{idx}'):
            st.session_state['goto_page'] = e['page']
# NER labels
labels = sorted({x['label'] for x in ner.get('entities', [])})
active_labels = st.sidebar.multiselect('NER Labels', labels, default=labels)
# Saved searches
tbl = DB.table('searches')
terms = [r['term'] for r in tbl.all()]
active_terms = st.sidebar.multiselect('Search Terms', terms, default=terms)
new_term = st.sidebar.text_input('New Search Term')
if st.sidebar.button('Add') and new_term:
    tbl.insert({'term': new_term.strip(), 'hits':0})
    try: st.rerun()
    except AttributeError: st.experimental_rerun()
# Fuzzy slider
maxd = st.sidebar.slider('Max edit distance', 0, 5, 1)

# ─── Render PDF ─────────────────────────────────────────
st.title('ACA Viewer')
# Open PDF
if f1.name.lower().endswith('.pdf'):
    pg = st.session_state.get('goto_page', 0)
    doc = fitz.open(stream=bytes1, filetype='pdf')
    # Precompute page texts & offsets
    pages_text = [p.get_text('text') for p in doc]
    offsets = []
    off = 0
    for txt in pages_text:
        offsets.append(off)
        off += len(txt) + 1
    # Draw page
    page = doc[pg]
    for ent in ner.get('entities', []):
        if ent.get('page')==pg and ent['label'] in active_labels and ent.get('coords'):
            r = fitz.Rect(*ent['coords'])
            c = next_color(labels.index(ent['label']))
            page.draw_rect(r, color=fitz.utils.getColor(c), fill=fitz.utils.getColor(c+'55'))
    st.image(page.get_pixmap().tobytes(), use_container_width=True)
else:
    st.write('No PDF preview available.')

# ─── Compute and display clickable search results ────────
full_text = extract_text(bytes1, f1.name)
# Gather hits with page mapping
hits = []
for term in active_terms:
    for s,e in fuzzy_positions(full_text, term, maxd):
        # determine page index
        pg_idx = len(offsets)-1
        for i, start in enumerate(offsets):
            if s < start:
                pg_idx = max(0, i-1)
                break
        snippet = full_text[max(0, s-30):e+30].replace('\n',' ')
        hits.append({'term': term, 'snippet': snippet, 'page': pg_idx})
        # update hit count
        q = Query()
        if tbl.get(q.term==term):
            tbl.update({'hits': tbl.get(q.term==term)['hits']+1}, q.term==term)
# Display in sidebar
with st.sidebar.expander('Search Results', expanded=True):
    for idx, h in enumerate(hits[:100]):
        title = f"{h['term']} (p{h['page']+1}): {h['snippet'][:40]}..."
        if st.button(title, key=f'res-{idx}'):
            st.session_state['goto_page'] = h['page']

# ─── Comments ───────────────────────────────────────────
st.subheader('Comments')
snip = st.text_area('Selected snippet')
note = st.text_input('Note')
if st.button('Save Comment') and snip and note:
    DB.table('comments').insert({
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'file': f1.name, 'snippet': snip, 'note': note
    })
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

# ─── Diff View ───────────────────────────────────────────
if f2 is not None:
    st.subheader('Diff View')
    bytes2 = f2.read()
    text2 = extract_text(bytes2, f2.name)
    for line in diff_strings(full_text, text2):
        st.code(line)
