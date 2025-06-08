"""
streamlit_app.py  ·  v0.2.5  (June 2025)

ACA Viewer – self-contained Streamlit app (stable).

Features:
• Dev mode with SIMULATE toggle
• PDF rendering + TOC navigation
• NER rectangle overlays
• Fuzzy search + saved searches
• Inline comments (TinyDB)
• Two‑doc diff view
• Admin page via ?admin=1
• Uses st.query_params, st.rerun()
"""

import os, re, sys, datetime
from functools import lru_cache
from pathlib import Path
import streamlit as st
import fitz  # PyMuPDF
from Levenshtein import distance
from tinydb import TinyDB, Query
from requests import Session

# Config
PALANTIR_BASE = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107","#03A9F4","#8BC34A","#E91E63",
              "#9C27B0","#FF5722","#607D8B","#FF9800"]

# Must run with Streamlit
if not hasattr(st, 'runtime') or not hasattr(st.runtime, 'scriptrunner_utils'):
    print("⚠️  Run with: streamlit run streamlit_app.py")
    sys.exit(1)

@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict = None):
    """Fetch JSON from Foundry endpoint."""
    url = f"{PALANTIR_BASE}{endpoint}"
    sess = Session(); sess.headers.update(HEADERS)
    res = sess.get(url, params=params, timeout=30)
    res.raise_for_status()
    return res.json()

# Utilities

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
    raise ValueError('Unsupported type')


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

# App setup
st.set_page_config(page_title='ACA Viewer', layout='wide')
params = st.query_params
ADMIN = params.get('admin', ['0'])[0] == '1'

# Sidebar
with st.sidebar:
    st.title('ACA Viewer')
    SIMULATE = st.checkbox('Dev mode (simulate pipelines)', value=False)
    st.markdown('---')
    if st.button('Reload'):
        try: st.rerun()
        except: st.experimental_rerun()
    if not ADMIN:
        st.markdown('[Switch to Admin view](?admin=1)')

# Admin page
if ADMIN:
    st.header('Admin – saved searches & comments')
    st.subheader('Search terms')
    for r in DB.table('searches').all(): st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all(): st.write(c)
    st.stop()

# File upload
col1, col2 = st.columns(2)
with col1:
    f1 = st.file_uploader('Document A', type=['pdf','docx','sec'])
with col2:
    f2 = st.file_uploader('Document B (diff)', type=['pdf','docx','sec'])
if not f1:
    st.info('Upload Document A')
    st.stop()
bytes1 = f1.read()

# Fetch or stub pipelines
if SIMULATE:
    toc = {'entries': []}
    ner = {'entities': []}
else:
    toc = palantir_get('/pipelines/toc_extract', params={'fileName': f1.name})
    ner = palantir_get('/pipelines/ner_extract', params={'fileName': f1.name})

# Sidebar controls
st.sidebar.header('Highlights 🔦')
show_toc = st.sidebar.checkbox('Show TOC', True)
if show_toc:
    for idx, e in enumerate(toc.get('entries', [])):
        if st.sidebar.button(e['title'][:60], key=idx):
            st.session_state['goto_page'] = e['page']
labels = sorted({x['label'] for x in ner.get('entities', [])})
active_labels = st.sidebar.multiselect('NER labels', labels, default=labels)
# Saved searches
S = DB.table('searches')
terms = [r['term'] for r in S.all()]
active_terms = st.sidebar.multiselect('Search terms', terms, default=terms)
new_term = st.sidebar.text_input('New search term')
if st.sidebar.button('Add term') and new_term.strip():
    S.insert({'term': new_term.strip(), 'hits': 0})
    try: st.rerun()
    except: st.experimental_rerun()
# Fuzzy slider
maxd = st.sidebar.slider('Levenshtein max distance', 0, 5, 1)

# Render PDF
st.title('ACA Viewer')
if f1.name.lower().endswith('.pdf'):
    page_no = st.session_state.get('goto_page', 0)
    doc = fitz.open(stream=bytes1, filetype='pdf')
    page = doc[page_no]
    for ent in ner.get('entities', []):
        if ent.get('page') == page_no and ent['label'] in active_labels and ent.get('coords'):
            rect = fitz.Rect(*ent['coords'])
            col = next_color(labels.index(ent['label']))
            page.draw_rect(rect, color=fitz.utils.getColor(col), fill=fitz.utils.getColor(col+'55'))
    st.image(page.get_pixmap().tobytes(), use_column_width=True)
else:
    st.write('Preview not available for this file type.')

# Text matches
text = extract_text(bytes1, f1.name)
st.subheader('Matches')
hits = []
for t in active_terms:
    for s,e in fuzzy_positions(text, t, maxd):
        hits.append(f"{t}: {text[s:e]}")
    # increment hits
    q = Query()
    if S.get(q.term == t):
        S.update({'hits': S.get(q.term == t)['hits']+len(fuzzy_positions(text, t, maxd))}, q.term == t)
for m in hits[:50]: st.write(m)

# Comments
st.subheader('Comments 💬')
snip = st.text_area('Selected snippet')
note = st.text_input('Comment')
if st.button('Save comment') and snip and note:
    DB.table('comments').insert({
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'file': f1.name, 'snippet': snip, 'note': note
    })
    try: st.rerun()
    except: st.experimental_rerun()

# Diff view
if f2 is not None:
    st.subheader('Diff 🔍')
    bytes2 = f2.read()
    text2 = extract_text(bytes2, f2.name)
    for line in diff_strings(text, text2):
        st.code(line)
