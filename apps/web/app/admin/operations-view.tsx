'use client';
import { useCallback, useEffect, useState } from 'react';
import { adminRequest, statusNames } from './api';
import Modal from './modal';

type Tab = 'reindex' | 'audit' | 'settings' | 'exports' | 'responses';
type Values = Record<string, string | number>;
type Settings = { revision: number; active: Values; saved: Values; restart_required: boolean };
type Document = { id: string; title: string; active_version_id: string | null };
type Plan = { count: number; snapshot: string; items: { document_id: string; title: string; version: number; revision_id: string }[] };
type Batch = { id: string; total: number; finished: number; failed: number; progress: number; items: { id: string; status: string; progress: number; error_code: string | null }[] };
type Audit = { id: string; action: string; actor_id: string; object_id: string; correlation_id: string; result: string; created_at: string };
type Evaluation = { id: string; scope: string; created_at: number; approved: boolean };
type Source = { document_id: string; document_version_id: string; revision_id: string; title: string; version: number; source_sha256: string };
type Response = { id: string; conversation_id: string; status: string; retrieval_run_id: string | null; sources: Source[] };
const tabs: [Tab, string][] = [['reindex', 'Reindexacion'], ['audit', 'Auditoria'], ['settings', 'Configuracion'], ['exports', 'Exportaciones'], ['responses', 'Fuentes de respuestas']];
const labels: Record<string, string> = { llm_base_url: 'URL de generacion (LiteLLM)', llm_model: 'Modelo de generacion', embedding_base_url: 'URL de embeddings', embedding_model: 'Modelo de embeddings', reranker_base_url: 'URL del reranker', reranker_model: 'Modelo del reranker', model_timeout_seconds: 'Timeout de modelos (segundos)', sufficiency_reasoning_effort: 'Esfuerzo de razonamiento', index_timeout_seconds: 'Timeout de indexacion (segundos)', conversion_timeout_seconds: 'Timeout de conversion (segundos)' };

export default function OperationsView({ csrf }: { csrf: string }) {
  const [tab, setTab] = useState<Tab>('reindex');
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null); const [values, setValues] = useState<Values>({});
  const [documents, setDocuments] = useState<Document[]>([]); const [selected, setSelected] = useState<string[]>([]);
  const [docOffset, setDocOffset] = useState(0); const [docMore, setDocMore] = useState(false); const [query, setQuery] = useState('');
  const [plan, setPlan] = useState<Plan | null>(null); const [total, setTotal] = useState(false); const [confirmation, setConfirmation] = useState('');
  const [batches, setBatches] = useState<Batch[]>([]); const [audit, setAudit] = useState<Audit[]>([]);
  const [actionFilter, setActionFilter] = useState(''); const [objectFilter, setObjectFilter] = useState(''); const [actorFilter, setActorFilter] = useState(''); const [resultFilter, setResultFilter] = useState('');
  const [offset, setOffset] = useState(0); const [more, setMore] = useState(false);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]); const [responses, setResponses] = useState<Response[]>([]);
  const [status, setStatus] = useState<{ jobs: Record<string, number>; workers: { name: string; available: boolean; heartbeat_at: number }[] } | null>(null);
  const request = useCallback((path: string) => adminRequest(`operations/${path}`, csrf), [csrf]);
  useEffect(() => {
    let live = true;
    request('settings').then(data => { if (live) { setSettings(data); setValues(data.saved); } }).catch(e => setError(e.message));
    return () => { live = false; };
  }, [request]);
  useEffect(() => {
    let live = true;
    const update = async () => {
      try {
        const [s, b] = await Promise.all([request('status'), request('batches')]);
        if (live) { setStatus(s); setBatches(b.items); }
      } catch (e) { if (live) setError((e as Error).message); }
    };
    update(); const timer = setInterval(update, 2500); return () => { live = false; clearInterval(timer); };
  }, [request]);
  useEffect(() => {
    let live = true;
    adminRequest(`documents?q=${encodeURIComponent(query)}&offset=${docOffset}`, csrf).then(data => {
      if (live) { setDocuments(data.items); setDocMore(data.has_more); }
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [csrf, docOffset, query]);
  useEffect(() => {
    let live = true;
    const path = tab === 'audit' ? `audit?offset=${offset}&action=${encodeURIComponent(actionFilter)}&object_id=${encodeURIComponent(objectFilter)}&actor_id=${encodeURIComponent(actorFilter)}&result=${encodeURIComponent(resultFilter)}` : tab === 'exports' ? `evaluations?offset=${offset}` : tab === 'responses' ? `responses?offset=${offset}` : null;
    if (path) request(path).then(data => { if (live) { setMore(data.has_more); if (tab === 'audit') setAudit(data.items); if (tab === 'exports') setEvaluations(data.items); if (tab === 'responses') setResponses(data.items); } }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [request, tab, offset, actionFilter, objectFilter, actorFilter, resultFilter]);
  async function run(operation: () => Promise<void>) {
    if (busy) return; setBusy(true); setError(''); setNotice('');
    try { await operation(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function preview(all: boolean) {
    await run(async () => { const data = await adminRequest('operations/reindex/preview', csrf, 'POST', { document_ids: all ? null : selected }); setPlan(data); setTotal(all); setConfirmation(''); });
  }
  return <section className="operations-section">
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    {status && <div className="retrieval-card"><h2>Operacion</h2><p>{Object.entries(status.jobs).map(([s, n]) => `${statusNames[s] || s}: ${n}`).join(' · ') || 'Sin trabajos'}</p><p>{status.workers.length ? status.workers.map(w => `${w.name}: ${w.available ? 'Disponible' : 'Sin heartbeat reciente'}`).join(' · ') : 'Worker sin registrar'}</p></div>}
    <div className="operation-tabs" role="group" aria-label="Operacion administrativa">{tabs.map(([key, name]) => <button key={key} aria-pressed={tab === key} onClick={() => { setTab(key); setOffset(0); setMore(false); }}>{name}</button>)}</div>
    {tab === 'settings' && settings && <form className="retrieval-card" onSubmit={e => { e.preventDefault(); run(async () => { const data = await adminRequest('operations/settings', csrf, 'PUT', { expected_revision: settings.revision, values }); setSettings(data); setValues(data.saved); setNotice('Configuracion guardada. Reinicie API y worker para aplicarla.'); }); }}>
      <h2>Proveedores y parametros</h2><p>Las claves se mantienen en variables de entorno. Embeddings: 768 dimensiones. Los cambios de modelos requieren reindexacion y nueva calibracion.</p>
      {settings.restart_required && <p className="notice">Hay cambios pendientes de reiniciar API y worker.</p>}
      <div className="metadata-fields">{Object.entries(values).map(([key, value]) => <label key={key}>{labels[key] || key}{key === 'sufficiency_reasoning_effort' ? <select value={String(value)} onChange={e => setValues({ ...values, [key]: e.target.value })}>{['low', 'medium', 'high', 'disabled'].map(v => <option key={v}>{v}</option>)}</select> : <input required type={typeof value === 'number' ? 'number' : key.endsWith('url') ? 'url' : 'text'} step={typeof value === 'number' ? 'any' : undefined} value={value} onChange={e => setValues({ ...values, [key]: typeof value === 'number' ? Number(e.target.value) : e.target.value })}/>}<small>Activo: {settings.active[key]}</small></label>)}</div>
      <button disabled={busy}>Guardar configuracion</button><button type="button" disabled={busy} onClick={() => run(async () => { const data = await request('settings'); setSettings(data); setValues(data.saved); })}>Recargar configuracion</button>
    </form>}
    {tab === 'reindex' && <><div className="document-toolbar"><input aria-label="Buscar para reindexar" placeholder="Buscar documentos" value={query} onChange={e => { setQuery(e.target.value); setDocOffset(0); }}/><button disabled={busy || !selected.length} onClick={() => preview(false)}>Previsualizar seleccion ({selected.length})</button><button disabled={busy} onClick={() => preview(true)}>Previsualizar toda la biblioteca</button></div>
      <p>Solo se reindexan versiones publicadas. Cada trabajo conserva su progreso y admite reintentos desde Trabajos.</p>
      <div className="table-wrap"><table><thead><tr><th>Seleccion</th><th>Documento</th><th>Version activa</th></tr></thead><tbody>{documents.map(d => <tr key={d.id}><td><input type="checkbox" aria-label={`Seleccionar ${d.title}`} disabled={!d.active_version_id} checked={selected.includes(d.id)} onChange={e => setSelected(e.target.checked ? [...selected, d.id] : selected.filter(id => id !== d.id))}/></td><td>{d.title}</td><td>{d.active_version_id || 'Sin publicar'}</td></tr>)}</tbody></table></div>
      <div className="pagination"><button disabled={!docOffset} onClick={() => setDocOffset(Math.max(0, docOffset - 50))}>Documentos anteriores</button><button disabled={!docMore} onClick={() => setDocOffset(docOffset + 50)}>Mas documentos</button></div>
      <h2>Lotes recientes</h2>{batches.map(b => <details className="retrieval-card" key={b.id}><summary>Lote {b.id}: {b.finished}/{b.total} finalizados · {b.failed} fallidos</summary><progress aria-label="Progreso del lote" value={b.progress} max={100}/><p>{b.progress}%</p>{b.items.map(j => <p key={j.id}>{j.id} · {statusNames[j.status]} · {j.progress}% {j.error_code}</p>)}<a href="/admin/jobs">Abrir trabajos</a></details>)}
    </>}
    {plan && <Modal titleId="reindex-title" onClose={() => setPlan(null)}><h2 id="reindex-title">Confirmar reindexacion</h2><p>{total ? 'Biblioteca completa' : 'Seleccion'}: {plan.count} documentos.</p><ul>{plan.items.map(i => <li key={i.document_id}>{i.title} · version {i.version} · revision {i.revision_id}</li>)}</ul><label>Escriba REINDEXAR<input autoFocus value={confirmation} onChange={e => setConfirmation(e.target.value)}/></label><div className="modal-actions"><button disabled={busy} onClick={() => setPlan(null)}>Cancelar</button><button disabled={busy || !plan.count || confirmation !== 'REINDEXAR'} onClick={() => run(async () => { const batch = await adminRequest('operations/reindex', csrf, 'POST', { document_ids: total ? null : plan.items.map(i => i.document_id), snapshot: plan.snapshot, confirmation }); setPlan(null); setNotice(`Lote ${batch.id} en cola: ${batch.total} trabajos.`); const data = await request('batches'); setBatches(data.items); })}>Confirmar reindexacion</button></div></Modal>}
    {tab === 'audit' && <><div className="metadata-fields">{[['Accion', actionFilter, setActionFilter], ['Objeto', objectFilter, setObjectFilter], ['Actor', actorFilter, setActorFilter], ['Resultado', resultFilter, setResultFilter]].map(([name, value, setter]) => <label key={String(name)}>{String(name)}<input value={String(value)} onChange={e => { (setter as (v: string) => void)(e.target.value); setOffset(0); }}/></label>)}</div><div className="table-wrap"><table><thead><tr><th>Fecha</th><th>Accion</th><th>Actor</th><th>Objeto</th><th>Resultado / correlacion</th></tr></thead><tbody>{audit.map(a => <tr key={a.id}><td>{new Date(a.created_at).toLocaleString('es-ES')}</td><td>{a.action}</td><td>{a.actor_id || '-'}</td><td>{a.object_id || '-'}</td><td>{a.result}<br/>{a.correlation_id}</td></tr>)}</tbody></table></div></>}
    {tab === 'exports' && <div className="retrieval-card"><h2>Exportar diagnosticos y evaluaciones</h2><p>El diagnostico incluye configuracion publica, estado del worker y hasta 1000 trabajos recientes. Las evaluaciones pueden incluir identificadores de fuentes internas.</p><a className="tool-link" href="/api/admin/operations/export/diagnostics">Descargar diagnosticos JSON</a><h3>Evaluaciones registradas</h3>{evaluations.length ? evaluations.map(e => <p key={e.id}>{new Date(e.created_at * 1000).toLocaleString('es-ES')} · {e.scope} · {e.approved ? 'Aprobada' : 'No aprobada'} · <a href={`/api/admin/operations/export/evaluations/${e.id}`}>Descargar {e.id}</a></p>) : <p>No hay evaluaciones registradas.</p>}</div>}
    {tab === 'responses' && <><p>Cada respuesta conserva sus fuentes y la traza de recuperacion. Puede comprobar la version activa en Documentos.</p>{responses.map(r => <details className="retrieval-card" key={r.id}><summary>Respuesta {r.id} · {r.status}</summary><p>Conversacion: {r.conversation_id}</p>{r.retrieval_run_id && <a href={`/api/admin/retrieval/runs/${r.retrieval_run_id}`} target="_blank" rel="noreferrer">Abrir traza de recuperacion</a>}{r.sources.length ? r.sources.map((s, i) => <p key={i}>{s.title} · version {s.version} · documento {s.document_id} · version ID {s.document_version_id} · revision {s.revision_id} · SHA-256 {s.source_sha256}<br/><a href={`/api/admin/versions/${s.document_version_id}/original`}>Descargar original citado</a> · <a href={`/api/admin/documents/${s.document_id}`} target="_blank" rel="noreferrer">Ver versiones del documento</a></p>) : <p>Sin fuentes documentales.</p>}</details>)}</>}
    {['audit', 'exports', 'responses'].includes(tab) && <div className="pagination"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Anterior</button><span>Pagina {offset / 50 + 1}</span><button disabled={!more} onClick={() => setOffset(offset + 50)}>Siguiente</button></div>}
  </section>;
}
