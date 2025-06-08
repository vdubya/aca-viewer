"""
AI Criteria Assistant – Streamlit app with PDF.js viewer and dynamic highlights.

Features:
• PDF.js viewer via streamlit-pdf-viewer for selectable text + overlay highlights
• TOC navigation + NER & search overlays
• Saved & fuzzy searches (TinyDB) with clickable navigation
• Inline comments
• Compare two documents via diff
• Admin page via ?admin=1
• Doc A uploader on main panel; Doc B (for compare) in Advanced sidebar
• Sample PDF load button for quick testing
• Settings (incl. Dev mode & fuzzy distance) in bottom expander
"""

import os
import re
import datetime
from functools import lru_cache
from pathlib import Path

import streamlit as st
import requests
import fitz  # PyMuPDF
from Levenshtein import distance
from tinydb import TinyDB
from requests import Session
from streamlit_pdf_viewer import pdf_viewer

# ─── Config ─────────────────────────────────────────────
PALANTIR_BASE = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107", "#03A9F4", "#8BC34A", "#E91E63",
              "#9C27B0", "#FF5722", "#607D8B", "#FF9800"]
SIMULATE_DEFAULT = bool(int(os.getenv("SIMULATE_PALANTIR", "0")))

@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict | None = None):
    if st.session_state.get("simulate", SIMULATE_DEFAULT):
        if "toc_extract" in endpoint:
            return {"entries": []}
        if "ner_extract" in endpoint:
            return {"entities": []}
        if "sec_parse" in endpoint:
            return {"section": ""}
        return {}
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
st.set_page_config(page_title='AI Criteria Assistant', layout='wide')
params = st.query_params
ADMIN = params.get('admin',['0'])[0] == '1'

# ─── Sidebar ─────────────────────────────────────────────
with st.sidebar:
    st.title('AI Criteria Assistant')
    # Advanced section for Document B
    with st.expander('Advanced', expanded=False):
        f2 = st.file_uploader('Document (for compare)', type=['pdf','docx','sec'])

    st.subheader('🔎 Search Terms')
    if 'new_term' not in st.session_state:
        st.session_state.new_term = ''
    st.session_state.new_term = st.text_input('Add term:', st.session_state.new_term)
    if st.button('Save term'):
        term = st.session_state.new_term.strip()
        if term:
            S = DB.table('searches')
            S.insert({'term': term, 'hits': 0})
            st.session_state.new_term = ''
            st.experimental_rerun()

    S = DB.table('searches')
    saved_terms = [r['term'] for r in S.all()]
    st.subheader('Saved Terms')
    active_terms = st.multiselect('Activate:', saved_terms, default=saved_terms)

    st.subheader('Navigation & Highlights')
    # TOC
    toc = st.session_state.get('toc_data', {}).get('entries', [])
    if st.checkbox('Show TOC', value=True):
        for i, entry in enumerate(toc):
            if st.button(entry['title'][:50], key=f'toc-{i}'):
                st.session_state['goto_page'] = entry['page']
    # NER labels
    labels = st.session_state.get('ner_labels', [])
    active_labels = st.multiselect('NER Labels', labels, default=labels)
    # Clickable results
    with st.expander('Search Results', expanded=False):
        hits = st.session_state.get('search_hits', [])
        for idx, h in enumerate(hits[:50]):
            lbl = f"{h['term']} (p{h['page']+1}): {h['snippet'][:30]}..."
            if st.button(lbl, key=f'srch{idx}'):
                st.session_state['goto_page'] = h['page']
    st.markdown('---')
    # Settings at bottom
    st.markdown("<div style='position:absolute; bottom:0; width:90%;'>", unsafe_allow_html=True)
    with st.expander('Settings', expanded=False):
        if 'simulate' not in st.session_state:
            st.session_state.simulate = SIMULATE_DEFAULT
        st.session_state.simulate = st.checkbox('Dev mode (simulate pipelines)',
                                               value=st.session_state.simulate)
        if 'max_dist' not in st.session_state:
            st.session_state.max_dist = 1
        st.session_state.max_dist = st.slider('Max edit distance', 0, 5,
                                             st.session_state.max_dist,
                                             key='max_dist')
    st.markdown('</div>', unsafe_allow_html=True)

# ─── Admin View ──────────────────────────────────────────
if ADMIN:
    st.header('Admin: Saved Searches & Comments')
    st.subheader('Search Terms')
    for r in DB.table('searches').all(): st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all(): st.write(c)
    st.stop()

# ─── Main Panel: Document A upload & sample button ───────
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
# document name for pipelines and diff fallback
doc_name = f1.name if f1 else sample_url.split('/')[-1]

# ─── Pipeline Data or stub ───────────────────────────────
if st.session_state.get('simulate', SIMULATE_DEFAULT):
    toc_data, ner_data = {'entries':[]}, {'entities':[]}
else:
    toc_data = palantir_get('/pipelines/toc_extract', params={'fileName':doc_name})
    ner_data = palantir_get('/pipelines/ner_extract', params={'fileName':doc_name})
# cache for sidebar
st.session_state['toc_data'] = toc_data
st.session_state['ner_labels'] = sorted({e['label'] for e in ner_data.get('entities', [])})

# ─── Compute Annotations ─────────────────────────────────
doc = fitz.open(stream=viewer_bytes, filetype='pdf')
annotations = []
# NER annotations
for ent in ner_data.get('entities', []):
    pg = ent.get('page'); coords = ent.get('coords')
    if pg is not None and coords:
        annotations.append({'page':pg,'coords':coords,'color':next_color(hash(ent['label']))})
# Search annotations
txt_all = extract_text(viewer_bytes, doc_name)
search_hits = []
for term in active_terms:
    # exact
    for m in re.finditer(re.escape(term), txt_all, re.I):
        pg_idx = next((i for i,p in enumerate(doc) if m.start()<len(p.get_text('text'))),0)
        rects = doc[pg_idx].search_for(term)
        if rects:
            annotations.append({'page':pg_idx,'coords':[rects[0].x0,rects[0].y0,rects[0].x1,rects[0].y1],'color':next_color(hash(term))})
            snippet = txt_all[m.start():m.end()]
            search_hits.append({'term':term,'snippet':snippet,'page':pg_idx})
    # fuzzy
    for s, e in fuzzy_positions(txt_all, term,
                                st.session_state.get('max_dist', 1)):
        snippet = txt_all[s:e]
        for i in range(len(doc)):
            rects = doc[i].search_for(snippet)
            if rects:
                annotations.append({'page':i,'coords':[rects[0].x0,rects[0].y0,rects[0].x1,rects[0].y1],'color':next_color(hash(term))})
                search_hits.append({'term':term,'snippet':snippet,'page':i})
                break
# cache search_hits for sidebar
st.session_state['search_hits'] = search_hits

# ─── Render PDF via streamlit-pdf-viewer ────────────────
st.title('AI Criteria Assistant')
pdf_viewer(viewer_bytes, height=800, annotations=annotations)

# ─── Comments & Diff ─────────────────────────────────────
# Comments
st.subheader('Comments')
snip = st.text_area('Selected snippet')
note = st.text_input('Note')
if st.button('Save Comment') and snip and note:
    DB.table('comments').insert({'timestamp': datetime.datetime.utcnow().isoformat(), 'file': doc_name, 'snippet': snip, 'note': note})
    try: st.rerun()
    except AttributeError: st.experimental_rerun()
# Diff
if f2:
    st.subheader('Compare Documents')
    text2 = extract_text(f2.read(), f2.name)
    for line in diff_strings(txt_all, text2):
        st.code(line)
=======
if __name__ == "__main__":
    run()
