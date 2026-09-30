'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Upload, Search, Save, Check, Download, RotateCcw, Trash2, X, Eye, FileText, ListTree, ArchiveX, Files } from 'lucide-react';
import { adminRequest, diagnosticNames, statusNames } from './api';
import Modal from './modal';

type Metadata = { title: string; author: string; date: string; category: string; tags: string[]; language: string; version: string; visibility: string };
type Version = { id: string; number: number; status: string; metadata: Metadata; revision_id: string | null; reviewed_at: number | null; original_sha256: string; original_name: string; format: string; diagnostics: string[] };
type Document = { id: string; title: string; versions: Version[]; active_version_id: string | null; deletion_requested: boolean };
type Locator = { page: number | null; section_path: string[]; line_start: number; line_end: number; origin: string };
type Revision = { id: string; number: number; created_at: number; edited: boolean };

export default function DocumentsView({ csrf }: { csrf: string }) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState({ category: '', tag: '', visibility: '', status: '' });
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [versionId, setVersionId] = useState('');
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [tagText, setTagText] = useState('');
  const [classification, setClassification] = useState({ category: '', tags: '', visibility: 'usuarios' });
  const [markdown, setMarkdown] = useState('');
  const [provenance, setProvenance] = useState<Locator[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [revisionId, setRevisionId] = useState('');
  const [mode, setMode] = useState<'editor' | 'preview' | 'provenance'>('editor');
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const uploadInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const doc = documents.find(item => item.id === selected);
  const version = doc?.versions.find(item => item.id === versionId) || doc?.versions[0];
  const current = revisionId === version?.revision_id;
  const editable = version?.status === 'requiere_revision' && current && !doc?.deletion_requested;
  const canDelete = !!doc && !doc.deletion_requested && !doc.active_version_id && doc.versions.every(v => !['procesando', 'indexando'].includes(v.status));

  function markDirty() { setDirty(true); dirtyRef.current = true; setNotice(''); }
  function clearDirty() { setDirty(false); dirtyRef.current = false; }
  const refresh = useCallback(async () => {
    const data = await adminRequest(`documents?q=${encodeURIComponent(query)}&offset=${offset}&${new URLSearchParams(filters)}`, csrf);
    setDocuments(data.items); setMore(data.has_more);
  }, [csrf, query, offset, filters]);
  useEffect(() => {
    let active = true;
    const update = () => refresh().catch((e: Error) => { if (active) setError(e.message); });
    update(); const timer = setInterval(update, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!version) return;
    setMetadata(version.metadata);
    setClassification({ category: version.metadata.category, tags: version.metadata.tags.join(', '), visibility: version.metadata.visibility });
    setTagText(version.metadata.tags.join(', '));
    setRevisionId(version.revision_id || '');
    setMarkdown(''); setProvenance([]); setRevisions([]); clearDirty();
  }, [version?.id]); // Each selected version owns its own editor state.
  useEffect(() => {
    if (!version?.revision_id || dirtyRef.current) return;
    const requestedVersion = version.id;
    let active = true;
    Promise.all([
      adminRequest(`versions/${requestedVersion}/normalized`, csrf),
      adminRequest(`versions/${requestedVersion}/revisions`, csrf)
    ]).then(([data, history]) => {
      if (!active || dirtyRef.current) return;
      setMarkdown(data.markdown); setProvenance(data.provenance); setRevisionId(data.revision_id);
      setRevisions(history.items); setMetadata(data.metadata); setTagText(data.metadata.tags.join(', '));
    }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [version?.id, version?.revision_id, csrf]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirtyRef.current) { event.preventDefault(); } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, []);

  async function action(operation: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await operation(); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function changeSelection(id: string, nextVersion = '') {
    if (dirtyRef.current && !window.confirm('Descartar los cambios sin guardar?')) return;
    clearDirty(); setSelected(id); setVersionId(nextVersion); setError(''); setNotice('');
  }
  async function upload(file: File | undefined, replacement = false) {
    if (!file || (replacement && !doc)) return;
    await action(async () => {
      const body = new FormData(); body.set('file', file);
      const result = await adminRequest(replacement ? `documents/${doc!.id}/versions` : 'documents', csrf, 'POST', body, crypto.randomUUID());
      clearDirty(); setSelected(result.document.id); setVersionId(result.document.versions[0].id);
      setNotice('Original guardado. Conversion en cola.');
    });
  }
  async function historical(id: string) {
    if (!version || (dirtyRef.current && !window.confirm('Descartar los cambios sin guardar?'))) return;
    await action(async () => {
      const data = await adminRequest(`versions/${version.id}/normalized?revision_id=${id}`, csrf);
      clearDirty(); setRevisionId(data.revision_id); setMarkdown(data.markdown); setProvenance(data.provenance);
      setMetadata(data.metadata); setTagText(data.metadata.tags.join(', '));
    });
  }
  const field = (name: keyof Metadata, value: string) => {
    if (!metadata) return;
    if (name === 'tags') setTagText(value);
    markDirty(); setMetadata({ ...metadata, [name]: name === 'tags' ? value.split(',').map(v => v.trim()).filter(Boolean) : value });
  };

  return <section className="documents-section">
    <div className="document-toolbar"><div className="search-field"><Search size={17} aria-hidden="true"/><input aria-label="Buscar documentos" placeholder="Buscar documentos" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }}/></div>
      <button className="upload-button" disabled={busy} onClick={() => uploadInput.current?.click()}><Upload size={17}/>Cargar documento</button>
      <input ref={uploadInput} type="file" accept=".md,.txt,.pdf,.docx" hidden onChange={e => { upload(e.target.files?.[0]); e.target.value = ''; }}/></div>
    <div className="document-filters"><label>Filtrar categoria<input value={filters.category} onChange={e => { setFilters({ ...filters, category: e.target.value }); setOffset(0); }}/></label><label>Filtrar etiqueta<input value={filters.tag} onChange={e => { setFilters({ ...filters, tag: e.target.value }); setOffset(0); }}/></label><label>Filtrar visibilidad<select value={filters.visibility} onChange={e => { setFilters({ ...filters, visibility: e.target.value }); setOffset(0); }}><option value="">Todas</option><option value="usuarios">Usuarios</option><option value="admin">Administradores</option></select></label><label>Filtrar estado<select value={filters.status} onChange={e => { setFilters({ ...filters, status: e.target.value }); setOffset(0); }}><option value="">Todos</option>{['subido', 'procesando', 'requiere_revision', 'indexando', 'publicado', 'retirado', 'error'].map(s => <option key={s} value={s}>{statusNames[s]}</option>)}</select></label></div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className={`document-layout ${doc ? 'selected-document' : ''}`}>
      <section className="document-list" aria-label="Lista de documentos">
        {documents.length ? <div className="table-wrap"><table><thead><tr><th>Documento</th><th>Estado</th>{!doc && <><th>Formato</th><th>Version</th></>}</tr></thead><tbody>
          {documents.map(item => <tr key={item.id} className={selected === item.id ? 'selected-row' : ''}><td><button className="row-button" onClick={() => changeSelection(item.id)}>{item.title}</button></td>
            <td><span className={`status ${item.versions[0]?.status === 'error' ? 'bad' : ''}`}>{item.deletion_requested ? 'Eliminando' : statusNames[item.versions[0]?.status]}</span></td>
            {!doc && <><td>{item.versions[0]?.format.toUpperCase()}</td><td>{item.versions[0]?.number}</td></>}</tr>)}
        </tbody></table></div> : <div className="empty-state"><Files size={36} strokeWidth={1.4}/><h2>No hay documentos</h2></div>}
        <div className="pagination"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 50))}>Anterior</button><span>{offset + 1} - {offset + documents.length}</span><button disabled={!more || busy} onClick={() => setOffset(offset + 50)}>Siguiente</button></div>
      </section>
      {doc && version && <section className="document-review" aria-label="Revision documental">
        <div className="review-heading"><h2>{doc.title}</h2><button className="icon-button" aria-label="Cerrar documento" title="Cerrar documento" onClick={() => { if (!dirty || window.confirm('Descartar cambios sin guardar?')) { clearDirty(); setSelected(null); } }}><X size={18}/></button></div>
        <div className="review-tools"><label className="inline-label">Version<select aria-label="Version documental" value={version.id} onChange={e => changeSelection(doc.id, e.target.value)}>{doc.versions.map(v => <option key={v.id} value={v.id}>{v.number} - {statusNames[v.status]}</option>)}</select></label>
          <a className="icon-button tool-link" title="Descargar original" aria-label="Descargar original" href={`/api/admin/versions/${version.id}/original`}><Download size={18}/></a>
          <button className="icon-button" disabled={busy || dirty || doc.deletion_requested} title="Sustituir original" aria-label="Sustituir original" onClick={() => replaceInput.current?.click()}><Upload size={18}/></button>
          <input ref={replaceInput} type="file" accept=".md,.txt,.pdf,.docx" hidden onChange={e => { upload(e.target.files?.[0], true); e.target.value = ''; }}/>
          <button className="icon-button" title="Reconvertir original" aria-label="Reconvertir original" disabled={busy || dirty || !['subido', 'requiere_revision', 'error'].includes(version.status)} onClick={() => action(async () => { await adminRequest(`versions/${version.id}/convert`, csrf, 'POST'); setNotice('Conversion en cola.'); })}><RotateCcw size={18}/></button>
          <button className="icon-button" title="Retirar version publicada" aria-label="Retirar version publicada" disabled={busy || !doc.active_version_id} onClick={() => action(() => adminRequest(`documents/${doc.id}/withdraw`, csrf, 'POST'))}><ArchiveX size={18}/></button>
          <button className="icon-button danger-button" title="Eliminar documento" aria-label="Eliminar documento" disabled={busy || !canDelete} onClick={() => { setConfirmation(''); setDeleting(true); }}><Trash2 size={18}/></button></div>
        {version.status === 'publicado' && <form className="retrieval-card" onSubmit={e => { e.preventDefault(); action(async () => { await adminRequest(`versions/${version.id}/classification`, csrf, 'PATCH', { expected_revision_id: version.revision_id, expected_metadata: version.metadata, category: classification.category, tags: classification.tags.split(',').map(t => t.trim()).filter(Boolean), visibility: classification.visibility }); setNotice('Clasificacion actualizada.'); }); }}><h3>Clasificacion publicada</h3><div className="metadata-fields"><label>Categoria publicada<input maxLength={100} value={classification.category} onChange={e => setClassification({ ...classification, category: e.target.value })}/></label><label>Etiquetas publicadas<input value={classification.tags} onChange={e => setClassification({ ...classification, tags: e.target.value })}/></label><label>Visibilidad publicada<select value={classification.visibility} onChange={e => setClassification({ ...classification, visibility: e.target.value })}><option value="usuarios">Usuarios</option><option value="admin">Administradores</option></select></label></div><button disabled={busy}>Guardar clasificacion</button></form>}
        <div className="review-status"><span>{statusNames[version.status]}</span><span className={version.reviewed_at ? 'ok' : 'muted'}>{version.reviewed_at ? 'Revisado' : 'Sin aprobar'}</span>{dirty && <span className="unsaved">Cambios sin guardar</span>}</div>
        {version.diagnostics.length > 0 && <ul className="diagnostics-list">{version.diagnostics.map(code => <li key={code}>{diagnosticNames[code] || (code.startsWith('possible_ocr_page_') ? `Posible necesidad de OCR en pagina ${code.split('_').pop()}` : code)}</li>)}</ul>}
        {metadata && <fieldset className="metadata-fields" disabled={!editable || busy}>
          <label className="wide-field">Titulo<input value={metadata.title} maxLength={300} onChange={e => field('title', e.target.value)}/></label>
          <label>Autor<input value={metadata.author} maxLength={200} onChange={e => field('author', e.target.value)}/></label>
          <label>Fecha<input type="date" value={metadata.date} onChange={e => field('date', e.target.value)}/></label>
          <label>Categoria<input value={metadata.category} maxLength={100} onChange={e => field('category', e.target.value)}/></label>
          <label>Idioma<input value={metadata.language} maxLength={16} onChange={e => field('language', e.target.value)}/></label>
          <label>Version visible<input value={metadata.version} maxLength={64} onChange={e => field('version', e.target.value)}/></label>
          <label>Visibilidad<select value={metadata.visibility} onChange={e => field('visibility', e.target.value)}><option value="usuarios">Usuarios</option><option value="admin">Administradores</option></select></label>
          <label className="wide-field">Etiquetas<input value={tagText} onChange={e => field('tags', e.target.value)}/></label>
        </fieldset>}
        {version.revision_id && <><div className="editor-toolbar"><div className="segmented-control" aria-label="Vista documental">
          <button aria-pressed={mode === 'editor'} onClick={() => setMode('editor')} title="Editor"><FileText size={16}/>Editor</button><button aria-pressed={mode === 'preview'} onClick={() => setMode('preview')} title="Vista previa"><Eye size={16}/>Vista previa</button><button aria-pressed={mode === 'provenance'} onClick={() => setMode('provenance')} title="Procedencia"><ListTree size={16}/>Procedencia</button></div>
          <select aria-label="Revision normalizada" value={revisionId} onChange={e => historical(e.target.value)}>{revisions.map(r => <option key={r.id} value={r.id}>Revision {r.number}{r.edited ? ' - editada' : ' - conversion'}</option>)}</select></div>
          {mode === 'editor' && <textarea className="markdown-editor" aria-label="Markdown" value={markdown} readOnly={!editable || busy} spellCheck={false} onChange={e => { setMarkdown(e.target.value); markDirty(); }}/>}
          {mode === 'preview' && <div className="markdown-preview"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{ img: ({ alt }) => <span>{alt}</span>, a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{markdown}</ReactMarkdown></div>}
          {mode === 'provenance' && <div className="table-wrap provenance-table"><table><thead><tr><th>Lineas</th><th>Pagina</th><th>Seccion</th><th>Origen</th></tr></thead><tbody>{provenance.map((locator, index) => <tr key={index}><td>{locator.line_start}-{locator.line_end}</td><td>{locator.page || '-'}</td><td>{locator.section_path.join(' / ') || '-'}</td><td>{locator.origin === 'manual' ? 'Edicion manual' : 'Original'}</td></tr>)}</tbody></table></div>}
          <div className="review-actions"><button disabled={busy || !editable || !dirty || !metadata?.title.trim()} onClick={() => action(async () => {
            await adminRequest(`versions/${version.id}`, csrf, 'PATCH', { expected_revision_id: revisionId, markdown, metadata }); clearDirty(); setNotice('Revision guardada.');
          })}><Save size={17}/>Guardar revision</button>
            <button disabled={busy || !editable || dirty || !markdown.trim() || !!version.reviewed_at} onClick={() => action(async () => { await adminRequest(`versions/${version.id}/review`, csrf, 'POST', { expected_revision_id: revisionId }); setNotice('Revision aprobada.'); })}><Check size={17}/>Marcar revisado</button>
            <button disabled={busy || dirty || !version.reviewed_at || !['requiere_revision', 'publicado', 'error'].includes(version.status)} onClick={() => action(async () => { if (version.status === 'publicado' && !window.confirm('Reindexar esta version publicada?')) return; await adminRequest(`versions/${version.id}/publish`, csrf, 'POST', { expected_revision_id: revisionId }); setNotice('Indexacion en cola; la publicacion se completa al terminar.'); })}>{version.status === 'publicado' ? 'Reindexar' : 'Publicar'}</button></div>
        </>}
      </section>}
    </div>
    {deleting && doc && <Modal titleId="delete-title" onClose={() => setDeleting(false)}><h2 id="delete-title">Eliminar documento</h2><p>{doc.title}</p><label>Confirmar titulo<input aria-label="Confirmar titulo" value={confirmation} onChange={e => setConfirmation(e.target.value)} autoFocus/></label>
      <div className="modal-actions"><button onClick={() => setDeleting(false)}>Cancelar</button><button className="danger-button" disabled={busy || confirmation !== doc.title} onClick={() => action(async () => {
        await adminRequest(`documents/${doc.id}`, csrf, 'DELETE', { confirmation }); setDeleting(false); clearDirty(); setSelected(null); setNotice('Eliminacion en cola.');
      })}><Trash2 size={17}/>Eliminar</button></div></Modal>}
  </section>;
}
