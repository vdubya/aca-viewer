"""
streamlit_app.py  ·  v0.2.8  (June 2025)

ACA Viewer – self-contained Streamlit app.

Features:
• Dev mode with SIMULATE toggle
• PDF text rendering + TOC navigation + NER & search overlays
• Fuzzy search + saved searches (TinyDB) with clickable navigation
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
        return '\n'.join(page.get_text('text') for page in doc)
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


def apply_highlights(text: str, highlights: list[tuple[int,int,str]]) -> str:
    # highlights: list of (start, end, hex_color)
    offsets = []
    for start,end,color in sorted(highlights, key=lambda x: x[0]):
        offsets.append((start, f"<span style='background:{color}33;'>{text[start:end]}</span>"))
    result = ''
    last = 0
    for start, span in offsets:
        end = start + len(re.sub('<[^>]+>', '', span))
        result += text[last:start] + span
        last = end
    result += text[last:]
    return result

# ─── App setup ───────────────────────────────────────────
st.set_page_config(page_title='ACA Viewer', layout='wide')
params = st.query_params
ADMIN = params.get('admin', ['0'])[0] == '1'

# ─── Sidebar Controls ────────────────────────────────────
with st.sidebar:
    st.title('ACA Viewer')
    SIMULATE = st.checkbox('Dev mode (simulate)', value=False)
    with st.expander('Settings', expanded=False):
        maxd = st.slider('Max edit distance', 0, 5, 1)
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
    st.info('Upload Document A')
    st.stop()
bytes1 = f1.read()

# ─── Pipeline Data (or stubs) ───────────────────────────
if SIMULATE:
    toc = {'entries': []}
    ner = {'entities': []}
else:
    toc = palantir_get('/pipelines/toc_extract', params={'fileName': f1.name})
    ner = palantir_get('/pipelines/ner_extract', params={'fileName': f1.name})

# ─── Highlight & navigation controls ────────────────────
st.sidebar.header('Navigation & Results')
# TOC navigation
show_toc = st.sidebar.checkbox('Show TOC', True)
if show_toc:
    for idx, e in enumerate(toc.get('entries', [])):
        if st.sidebar.button(e['title'][:60], key=f'toc-{idx}'):
            st.session_state['goto_page'] = e['page']
# NER labels filters
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

# ─── Render PDF as selectable text with overlays ─────────
st.title('ACA Viewer')
if f1.name.lower().endswith('.pdf'):
    page_no = st.session_state.get('goto_page', 0)
    doc = fitz.open(stream=bytes1, filetype='pdf')
    page = doc[page_no]
    text = page.get_text('text')
    # Collect highlight spans
    highlights = []
    # NER
    for ent in ner.get('entities', []):
        if ent.get('page')==page_no and ent['label'] in active_labels:
            # find all occurrences
            for m in re.finditer(re.escape(ent['text']), text):
                color = next_color(labels.index(ent['label']))
                highlights.append((m.start(), m.end(), color))
    # Saved searches & fuzzy
    for term in active_terms:
        for m in re.finditer(re.escape(term), text, re.I):
            color = next_color(hash(term))
            highlights.append((m.start(), m.end(), color))
        # fuzzy
        for s,e in fuzzy_positions(text, term, maxd):
            color = next_color(hash(term))
            highlights.append((s,e,color))
    # Apply highlights and display
    html = apply_highlights(text, highlights)
    st.markdown(f"<div style='white-space: pre-wrap; font-family: monospace;'>{html}</div>", unsafe_allow_html=True)
else:
    st.write('No PDF preview available.')

# ─── Clickable Search Results ───────────────────────────
# gather all page-text hits
full_text = extract_text(bytes1, f1.name)
offsets = []
acc = 0
for p in fitz.open(stream=bytes1, filetype='pdf'):
    offsets.append(acc)
    acc += len(p.get_text('text')) + 1
hits = []
for term in active_terms:
    for s,e in fuzzy_positions(full_text, term, maxd):
        pg = max(i for i,off in enumerate(offsets) if s>=off)
        snippet = full_text[s:e]
        hits.append({'term':term,'snippet':snippet,'page':pg})
        # update count
        q=Query()
        if tbl.get(q.term==term): tbl.update({'hits':tbl.get(q.term==term)['hits']+1},q.term==term)

with st.sidebar.expander('Search Results',True):
    for idx,h in enumerate(hits[:100]):
        label = f"{h['term']} (p{h['page']+1}): {h['snippet'][:30]}..."
        if st.button(label, key=f'res{idx}'):
            st.session_state['goto_page'] = h['page']

# ─── Comments ───────────────────────────────────────────
st.subheader('Comments')
snip = st.text_area('Selected snippet')
note = st.text_input('Note')
if st.button('Save Comment') and snip and note:
    DB.table('comments').insert({
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'file': f1.name,'snippet':snip,'note':note
    })
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

# ─── Diff View ───────────────────────────────────────────
if f2 is not None:
    st.subheader('Diff View')
    text2 = extract_text(f2.read(),f2.name)
    for line in diff_strings(full_text,text2): st.code(line)
