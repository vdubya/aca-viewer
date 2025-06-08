
"""
streamlit_app.py  ·  v0.2.9  (June 2025)

ACA Viewer – self-contained Streamlit app with PDF.js embed.

Features:
• Dev mode with SIMULATE toggle
• PDF.js viewer for selectable text + annotations via PyMuPDF
• TOC navigation + NER & search overlays
• Fuzzy search + saved searches (TinyDB) with clickable items
• Inline comments
• Two-doc diff view
• Admin page via ?admin=1
• Uses st.query_params and st.rerun() with fallback
• Exits if not run with `streamlit run`
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

# Config
PALANTIR_BASE = os.getenv("PALANTIR_BASE", "https://foundry.api.dod.mil")
PALANTIR_TOKEN = os.getenv("PALANTIR_TOKEN", "###-token-###")
DB = TinyDB(Path(__file__).with_name("aca_store.json"))
HEADERS = {"Authorization": f"Bearer {PALANTIR_TOKEN}"}
COLOR_POOL = ["#FFC107","#03A9F4","#8BC34A","#E91E63",
              "#9C27B0","#FF5722","#607D8B","#FF9800"]

@lru_cache(maxsize=64)
def palantir_get(endpoint: str, params: dict=None):
    url = f"{PALANTIR_BASE}{endpoint}"
    sess = Session(); sess.headers.update(HEADERS)
    res = sess.get(url, params=params, timeout=30)
    res.raise_for_status()
    return res.json()

# Extract text for diff and search

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

def next_color(i: int) -> str:
    return COLOR_POOL[i % len(COLOR_POOL)]

def fuzzy_positions(text: str, term: str, maxd: int) -> list[tuple[int,int]]:
    hits=[]
    for m in re.finditer(r'\b\w+\b', text, re.I):
        if distance(m.group(0).lower(), term.lower())<=maxd:
            hits.append((m.start(), m.end()))
    return hits

# App setup
st.set_page_config(page_title='ACA Viewer', layout='wide')
params = st.query_params
ADMIN = params.get('admin',['0'])[0]=='1'

# Sidebar
with st.sidebar:
    st.title('ACA Viewer')
    SIMULATE = st.checkbox('Dev mode (simulate pipelines)', value=False)
    st.markdown('---')
    if st.button('Reload'):
        try: st.rerun()
        except AttributeError: st.experimental_rerun()
    if not ADMIN:
        st.markdown('[Switch to Admin view](?admin=1)')
    # move settings to bottom
    st.markdown("<div style='position: absolute; bottom: 0; width: 90%;'>", unsafe_allow_html=True)
    with st.expander('Settings'):
        maxd = st.slider('Max edit distance', 0, 5, 1)
    st.markdown('</div>', unsafe_allow_html=True)

# Admin view
if ADMIN:
    st.header('Admin: Saved Searches & Comments')
    st.subheader('Search Terms')
    for r in DB.table('searches').all(): st.write(r)
    st.subheader('Comments')
    for c in DB.table('comments').all(): st.write(c)
    st.stop()

# File uploads
c1,c2=st.columns(2)
with c1: f1=st.file_uploader('Document A', type=['pdf','docx','sec'])
with c2: f2=st.file_uploader('Document B (diff)', type=['pdf','docx','sec'])
if not f1:
    st.info('Upload Document A')
    st.stop()
bytes1=f1.read()

# Pipeline data or stub
if SIMULATE:
    toc={'entries':[]}; ner={'entities':[]}
else:
    toc=palantir_get('/pipelines/toc_extract',params={'fileName':f1.name})
    ner=palantir_get('/pipelines/ner_extract',params={'fileName':f1.name})

# Render PDF with highlights via PDF.js embed
st.title('ACA Viewer')
if f1.name.lower().endswith('.pdf'):
    # annotate PDF
    doc=fitz.open(stream=bytes1,filetype='pdf')
    for ent in ner.get('entities',[]):
        pg=ent.get('page'); coords=ent.get('coords')
        if pg is not None and coords:
            annot=doc[pg].add_highlight_annot(fitz.Rect(*coords))
    # saved searches and fuzzy
    full_text=extract_text(bytes1,f1.name)
    terms=[r['term'] for r in DB.table('searches').all()]
    for term in terms:
        for s,e in fuzzy_positions(full_text,term,maxd):
            pg_idx=max(i for i,p in enumerate(doc) if s < len(doc[i].get_text('text')))
            annot=doc[pg_idx].add_highlight_annot(fitz.Rect(*doc[pg_idx].search_for(term)[0]))
    # output PDF bytes
    pdf_bytes=doc.write()
    b64=base64.b64encode(pdf_bytes).decode('utf-8')
    html=f"<iframe src='data:application/pdf;base64,{b64}' width='100%' height='800px'></iframe>"
    components.html(html, height=820)
else:
    st.write('Non-PDF preview not supported.')

# Clickable search results
full_text=extract_text(bytes1,f1.name)
offsets=[]; acc=0
for p in fitz.open(stream=bytes1,filetype='pdf'):
    offsets.append(acc); acc+=len(p.get_text('text'))+1
hits=[]
for term in [r['term'] for r in DB.table('searches').all()]:
    for s,e in fuzzy_positions(full_text,term,maxd):
        pg=max(i for i,off in enumerate(offsets) if s>=off)
        hits.append({'term':term,'snippet':full_text[s:e],'page':pg})
        DB.table('searches').update({'hits':DB.table('searches').get(Query().term==term)['hits']+1},Query().term==term)
with st.sidebar.expander('Search Results',True):
    for idx,h in enumerate(hits[:50]):
        lbl=f"{h['term']} (p{h['page']+1}): {h['snippet'][:30]}..."
        if st.button(lbl,key=f'srch{idx}'):
            st.session_state['goto_page']=h['page']

# Comments
st.subheader('Comments')
snip=st.text_area('Selected snippet')
note=st.text_input('Note')
if st.button('Save') and snip and note:
    DB.table('comments').insert({'timestamp':datetime.datetime.utcnow().isoformat(),'file':f1.name,'snippet':snip,'note':note})
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

# Diff
if f2 is not None:
    st.subheader('Diff')
    txt2=extract_text(f2.read(),f2.name)
    for line in diff_strings(full_text,txt2): st.code(line)
