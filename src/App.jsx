import { useEffect, useMemo, useState } from 'react';
import { LexicalComposer } from '@lexical/react/LexicalComposer';
import { RichTextPlugin } from '@lexical/react/LexicalRichTextPlugin';
import { ContentEditable } from '@lexical/react/LexicalContentEditable';
import { HistoryPlugin } from '@lexical/react/LexicalHistoryPlugin';
import { OnChangePlugin } from '@lexical/react/LexicalOnChangePlugin';
import { ListPlugin } from '@lexical/react/LexicalListPlugin';
import { LinkPlugin } from '@lexical/react/LexicalLinkPlugin';
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext';
import { ListNode, ListItemNode } from '@lexical/list';
import { LinkNode } from '@lexical/link';
import { $getRoot, $createParagraphNode, $createTextNode } from 'lexical';

const STORAGE_KEY = 'specs-saas-state-v1';

const seed = {
  organizations: [
    { id: 'org-acme', name: 'ACME Federal Design', plan: 'enterprise' },
    { id: 'org-atlas', name: 'Atlas Engineering', plan: 'pro' }
  ],
  users: [
    { id: 'u1', name: 'Avery Admin', email: 'admin@acme.mil', role: 'admin', orgId: 'org-acme' },
    { id: 'u2', name: 'Elliot Editor', email: 'editor@acme.mil', role: 'editor', orgId: 'org-acme' },
    { id: 'u3', name: 'Riley Reviewer', email: 'reviewer@atlas.com', role: 'reviewer', orgId: 'org-atlas' }
  ],
  projects: [
    { id: 'p1', orgId: 'org-acme', number: 'MIL-26-104', name: 'Facility Modernization FY26' }
  ],
  clauses: [
    {
      id: 'c1',
      orgId: 'org-acme',
      title: 'Quality Control Reports',
      body: 'Submit weekly QC reports documenting testing, deficiencies, and corrective actions.',
      tags: ['submittal', 'qc']
    }
  ],
  sections: [
    {
      id: 's1',
      projectId: 'p1',
      sectionNo: '03 30 00',
      title: 'Cast-in-Place Concrete',
      status: 'draft',
      discipline: 'civil',
      body: 'PART 1 - GENERAL\n1.1 SUMMARY\nA. Section includes cast-in-place concrete.\n\nPART 2 - PRODUCTS\n2.1 CEMENT\nA. ASTM C150 Type I/II.\n\nPART 3 - EXECUTION\n3.1 INSTALLATION\nA. Comply with ACI 301.',
      updatedAt: new Date().toISOString()
    }
  ],
  versions: [
    {
      sectionId: 's1',
      version: 1,
      body: 'PART 1 - GENERAL\n1.1 SUMMARY\nA. Section includes cast-in-place concrete.\n\nPART 2 - PRODUCTS\n2.1 CEMENT\nA. ASTM C150 Type I/II.\n\nPART 3 - EXECUTION\n3.1 INSTALLATION\nA. Comply with ACI 301.',
      summary: 'Initial seed',
      changedAt: new Date().toISOString(),
      changedBy: 'admin@acme.mil'
    }
  ],
  audit: []
};

const editorTheme = {
  paragraph: 'editor-paragraph'
};

function buildSuggestions(text) {
  const out = [];
  const lc = text.toLowerCase();
  if (!lc.includes('warranty')) out.push('Add a warranty requirement for closeout compliance.');
  if (!lc.includes('submittal') && !lc.includes('submit')) out.push('Add a submittal paragraph for product data, samples, and certificates.');
  if (!text.includes('ASTM')) out.push('Reference applicable ASTM standards for technical compliance.');
  if (!text.includes('PART 3')) out.push('Add PART 3 - EXECUTION requirements.');
  return out;
}

function extractSubmittals(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && /submit|submittal/i.test(line));
}

function quickDiff(a, b) {
  const aa = a.split('\n');
  const bb = b.split('\n');
  const max = Math.max(aa.length, bb.length);
  const result = [];
  for (let i = 0; i < max; i += 1) {
    if (aa[i] !== bb[i]) {
      if (aa[i] !== undefined) result.push(`- ${aa[i]}`);
      if (bb[i] !== undefined) result.push(`+ ${bb[i]}`);
    }
  }
  return result.length ? result.join('\n') : 'No textual difference.';
}

function Toolbar({ onInsertClause }) {
  const [editor] = useLexicalComposerContext();

  const appendLine = (line) => {
    editor.update(() => {
      const root = $getRoot();
      const p = $createParagraphNode();
      p.append($createTextNode(line));
      root.append(p);
    });
  };

  return (
    <div className="toolbar">
      <button type="button" onClick={() => appendLine('PART 1 - GENERAL')}>Insert PART 1</button>
      <button type="button" onClick={() => appendLine('PART 2 - PRODUCTS')}>Insert PART 2</button>
      <button type="button" onClick={() => appendLine('PART 3 - EXECUTION')}>Insert PART 3</button>
      <button type="button" onClick={onInsertClause}>Insert Selected Clause</button>
    </div>
  );
}

function SpecsEditor({ text, onTextChange, onInsertClause }) {
  const initialConfig = {
    namespace: 'specs-editor',
    editable: true,
    nodes: [ListNode, ListItemNode, LinkNode],
    theme: editorTheme,
    editorState: () => {
      const root = $getRoot();
      root.clear();
      const lines = text.split('\n');
      lines.forEach((line) => {
        const p = $createParagraphNode();
        p.append($createTextNode(line));
        root.append(p);
      });
    },
    onError: (error) => {
      throw error;
    }
  };

  return (
    <LexicalComposer initialConfig={initialConfig}>
      <div className="editor-shell">
        <Toolbar onInsertClause={onInsertClause} />
        <RichTextPlugin
          contentEditable={<ContentEditable className="editor-input" />}
          placeholder={<div className="editor-placeholder">Start editing section content...</div>}
          ErrorBoundary={({ children }) => <>{children}</>}
        />
        <HistoryPlugin />
        <ListPlugin />
        <LinkPlugin />
        <OnChangePlugin
          onChange={(editorState) => {
            editorState.read(() => {
              const next = $getRoot().getTextContent();
              onTextChange(next);
            });
          }}
        />
      </div>
    </LexicalComposer>
  );
}

export default function App() {
  const [state, setState] = useState(seed);
  const [userId, setUserId] = useState('u1');
  const [projectId, setProjectId] = useState('p1');
  const [sectionId, setSectionId] = useState('s1');
  const [editorText, setEditorText] = useState(seed.sections[0].body);
  const [revisionSummary, setRevisionSummary] = useState('');
  const [clauseToInsert, setClauseToInsert] = useState('');
  const [activeTab, setActiveTab] = useState('editor');

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      setState(parsed);
      setEditorText(parsed.sections[0]?.body ?? '');
      setProjectId(parsed.projects[0]?.id ?? '');
      setSectionId(parsed.sections[0]?.id ?? '');
      setUserId(parsed.users[0]?.id ?? '');
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const user = state.users.find((u) => u.id === userId) ?? state.users[0];
  const projects = useMemo(() => state.projects.filter((p) => p.orgId === user.orgId), [state, user]);
  const sections = useMemo(() => state.sections.filter((s) => s.projectId === projectId), [state, projectId]);
  const section = sections.find((s) => s.id === sectionId) ?? sections[0];
  const sectionVersions = state.versions.filter((v) => v.sectionId === section?.id).sort((a, b) => b.version - a.version);
  const orgClauses = state.clauses.filter((c) => c.orgId === user.orgId);

  useEffect(() => {
    if (section) {
      setEditorText(section.body);
    }
  }, [section?.id]);

  const updateState = (fn) => setState((prev) => fn(structuredClone(prev)));

  const saveRevision = () => {
    if (!section) return;
    updateState((draft) => {
      const s = draft.sections.find((item) => item.id === section.id);
      s.body = editorText;
      s.updatedAt = new Date().toISOString();

      const versions = draft.versions.filter((v) => v.sectionId === section.id);
      const nextVersion = versions.length ? Math.max(...versions.map((v) => v.version)) + 1 : 1;
      draft.versions.push({
        sectionId: section.id,
        version: nextVersion,
        body: editorText,
        summary: revisionSummary || 'Update',
        changedAt: new Date().toISOString(),
        changedBy: user.email
      });
      draft.audit.push({
        event: 'save_revision',
        at: new Date().toISOString(),
        actor: user.email,
        target: section.id
      });
    });
    setRevisionSummary('');
  };

  const addSection = () => {
    const sectionNo = prompt('Section number (e.g. 09 90 00)');
    const title = prompt('Section title');
    if (!sectionNo || !title) return;

    const id = `s${Date.now()}`;
    const body = 'PART 1 - GENERAL\n1.1 DESCRIPTION\nA. ';
    updateState((draft) => {
      draft.sections.push({
        id,
        projectId,
        sectionNo,
        title,
        status: 'draft',
        discipline: 'general',
        body,
        updatedAt: new Date().toISOString()
      });
      draft.versions.push({
        sectionId: id,
        version: 1,
        body,
        summary: 'Initial creation',
        changedAt: new Date().toISOString(),
        changedBy: user.email
      });
      draft.audit.push({ event: 'create_section', at: new Date().toISOString(), actor: user.email, target: id });
    });
    setSectionId(id);
  };

  const insertClause = () => {
    if (!clauseToInsert) return;
    const clause = orgClauses.find((c) => c.id === clauseToInsert);
    if (!clause) return;
    setEditorText((prev) => `${prev}\n${clause.body}`);
  };

  const addClause = () => {
    const title = prompt('Clause title');
    const body = prompt('Clause text');
    if (!title || !body) return;
    updateState((draft) => {
      draft.clauses.push({
        id: `c${Date.now()}`,
        orgId: user.orgId,
        title,
        body,
        tags: []
      });
      draft.audit.push({ event: 'add_clause', at: new Date().toISOString(), actor: user.email, target: title });
    });
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <h2>Specs SaaS</h2>
        <label>User</label>
        <select value={userId} onChange={(e) => setUserId(e.target.value)}>
          {state.users.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
        </select>

        <label>Project</label>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.number} — {p.name}</option>)}
        </select>

        <label>Section</label>
        <select value={section?.id ?? ''} onChange={(e) => setSectionId(e.target.value)}>
          {sections.map((s) => <option key={s.id} value={s.id}>{s.sectionNo} {s.title}</option>)}
        </select>

        <button type="button" onClick={addSection} disabled={user.role === 'reviewer'}>New Section</button>

        <div className="meta">
          <div>Role: <strong>{user.role}</strong></div>
          <div>Org: <strong>{user.orgId}</strong></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>SpecsIntact SaaS Editor Replacement (Lexical)</h1>
          <nav>
            {['editor', 'library', 'submittals', 'admin'].map((tab) => (
              <button key={tab} type="button" className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)}>
                {tab}
              </button>
            ))}
          </nav>
        </header>

        {activeTab === 'editor' && section && (
          <section>
            <h3>{section.sectionNo} — {section.title}</h3>
            <div className="meta-grid">
              <label>Status
                <select
                  value={section.status}
                  onChange={(e) => updateState((draft) => {
                    const target = draft.sections.find((s) => s.id === section.id);
                    target.status = e.target.value;
                  })}
                >
                  <option value="draft">draft</option>
                  <option value="in_review">in_review</option>
                  <option value="approved">approved</option>
                </select>
              </label>

              <label>Discipline
                <select
                  value={section.discipline}
                  onChange={(e) => updateState((draft) => {
                    const target = draft.sections.find((s) => s.id === section.id);
                    target.discipline = e.target.value;
                  })}
                >
                  <option value="general">general</option>
                  <option value="civil">civil</option>
                  <option value="mechanical">mechanical</option>
                  <option value="electrical">electrical</option>
                </select>
              </label>

              <label>Clause to insert
                <select value={clauseToInsert} onChange={(e) => setClauseToInsert(e.target.value)}>
                  <option value="">-- select clause --</option>
                  {orgClauses.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
                </select>
              </label>
            </div>

            <SpecsEditor text={editorText} onTextChange={setEditorText} onInsertClause={insertClause} />
            <label>Revision Summary
              <input value={revisionSummary} onChange={(e) => setRevisionSummary(e.target.value)} placeholder="Updated execution tolerances" />
            </label>
            <button type="button" onClick={saveRevision} disabled={user.role === 'reviewer'}>Save Revision</button>

            <h4>AI Drafting Assistant</h4>
            <ul>
              {buildSuggestions(editorText).map((s) => <li key={s}>{s}</li>)}
            </ul>

            <h4>Version History</h4>
            {sectionVersions.map((v) => (
              <div key={`${v.sectionId}-${v.version}`} className="version-row">
                <strong>v{v.version}</strong> · {new Date(v.changedAt).toLocaleString()} · {v.changedBy}
                <p>{v.summary}</p>
              </div>
            ))}
            {sectionVersions.length >= 2 && (
              <pre>{quickDiff(sectionVersions[1].body, sectionVersions[0].body)}</pre>
            )}
          </section>
        )}

        {activeTab === 'library' && (
          <section>
            <h3>Clause Library</h3>
            <button type="button" onClick={addClause} disabled={user.role === 'reviewer'}>Add Clause</button>
            {orgClauses.map((c) => (
              <article key={c.id} className="card">
                <h4>{c.title}</h4>
                <p>{c.body}</p>
                <small>Tags: {c.tags.join(', ') || 'none'}</small>
              </article>
            ))}
          </section>
        )}

        {activeTab === 'submittals' && (
          <section>
            <h3>Submittal Register</h3>
            <table>
              <thead>
                <tr><th>Section</th><th>Title</th><th>Requirement</th><th>Status</th></tr>
              </thead>
              <tbody>
                {sections.flatMap((s) => extractSubmittals(s.body).map((req, idx) => (
                  <tr key={`${s.id}-${idx}`}>
                    <td>{s.sectionNo}</td>
                    <td>{s.title}</td>
                    <td>{req}</td>
                    <td>Open</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </section>
        )}

        {activeTab === 'admin' && (
          <section>
            <h3>Admin Dashboard</h3>
            {user.role !== 'admin' ? <p>Admin access required.</p> : (
              <>
                <div className="metrics">
                  <div className="metric"><span>Organizations</span><strong>{state.organizations.length}</strong></div>
                  <div className="metric"><span>Projects</span><strong>{state.projects.length}</strong></div>
                  <div className="metric"><span>Sections</span><strong>{state.sections.length}</strong></div>
                </div>
                <h4>Audit Log</h4>
                <pre>{JSON.stringify(state.audit.slice(-20).reverse(), null, 2)}</pre>
              </>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
