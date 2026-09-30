'use client';
import { useEffect, useState } from 'react';
import { adminRequest } from './api';

type Candidate = { chunk_id: string; version_id: string; revision_id: string; title: string; version: number; content: string; rerank_score: number; rrf_score: number; channels: Record<string, { rank: number; score: number }>; provenance: { page: number | null; section_path: string[]; origin: string; chunk_line_start: number; chunk_line_end: number }[] };
type Result = { run_id?: string; results: Candidate[]; candidates: Candidate[]; decision: { action: string; reason: string; threshold?: number }; latency: Record<string, number>; chat_outcome?: { status: string; reason?: string; error?: string } };
type Run = { id: string; query: string; status: string; error?: string };

export default function RetrievalView({ csrf }: { csrf: string }) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('admin');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [policy, setPolicy] = useState<{ approved: boolean; reason: string; threshold?: number | null } | null>(null);
  async function refresh() { setRuns((await adminRequest('retrieval/runs', csrf)).items); }
  useEffect(() => {
    adminRequest('retrieval/runs', csrf).then(r => setRuns(r.items)).catch(e => setError(e.message));
    adminRequest(`retrieval/policy?scope=${scope}`, csrf).then(r => setPolicy(r.report)).catch(e => setError(e.message));
  }, [csrf, scope]);
  async function search() {
    setBusy(true); setError(''); setResult(null);
    try { setResult(await adminRequest('retrieval/search', csrf, 'POST', { query, scope })); }
    catch (e) { setError(e instanceof Error ? e.message : 'Error de recuperacion'); }
    finally { setBusy(false); refresh().catch(() => {}); }
  }
  return <section>
    {policy && <p className="muted">{policy.approved ? `Calibracion validada para este corpus · Umbral ${policy.threshold}` : 'Sin calibracion validada para este corpus: se mantiene la abstencion.'}</p>}
    <form className="document-toolbar" onSubmit={e => { e.preventDefault(); search(); }}>
      <label>Ámbito<select value={scope} disabled={busy} onChange={e => { setScope(e.target.value); setResult(null); }}><option value="admin">Administrador</option><option value="usuario">Usuario</option></select></label>
      <label className="search-field">Consulta<input value={query} maxLength={1000} onChange={e => setQuery(e.target.value)} required aria-label="Consulta de recuperacion"/></label>
      <button disabled={busy || !query.trim()}>{busy ? 'Buscando...' : 'Inspeccionar'}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div aria-live="polite">
      {result.chat_outcome && <p className="notice">Respuesta del chat: {result.chat_outcome.status} · {result.chat_outcome.reason || result.chat_outcome.error}</p>}
      <p className="notice">Decision: {result.decision.action === 'answer' ? 'Evidencia suficiente' : 'Abstencion'} · {result.decision.reason}{result.decision.threshold !== undefined && ` · Umbral ${result.decision.threshold.toFixed(4)}`}</p>
      <p className="muted">{Object.entries(result.latency).map(([name, ms]) => `${name}: ${ms} ms`).join(' · ')}</p>
      {!result.results.length && <p>No hay fragmentos publicados para esta consulta.</p>}
      {result.results.map((candidate, index) => <article className="retrieval-card" key={candidate.chunk_id}>
        <h2>{index + 1}. {candidate.title} <small>v{candidate.version}</small></h2>
        <p>Reranker: {candidate.rerank_score.toFixed(4)} · Fusion: {candidate.rrf_score.toFixed(5)} · {Object.entries(candidate.channels).map(([name, value]) => `${name}: rango ${value.rank}, puntuacion ${value.score.toFixed(4)}`).join(' · ')}</p>
        {candidate.provenance.map((p, i) => <p className="muted" key={i}>{p.page ? `Pagina ${p.page} · ` : ''}{p.section_path.join(' > ') || 'Sin encabezado'} · Lineas {p.chunk_line_start}–{p.chunk_line_end} · {p.origin}</p>)}
        <pre className="retrieval-excerpt">{candidate.content}</pre>
        <a href={`/api/admin/versions/${candidate.version_id}/original`}>Descargar original</a>
        <details><summary>Identificadores de la cita</summary><p>Fragmento: {candidate.chunk_id}<br/>Version: {candidate.version_id}<br/>Revision: {candidate.revision_id}</p></details>
      </article>)}
      <details><summary>Todos los candidatos y puntuaciones</summary><pre className="retrieval-excerpt">{JSON.stringify(result.candidates, null, 2)}</pre></details>
    </div>}
    <h2>Consultas recientes</h2>
    <div className="table-wrap"><table><thead><tr><th>Consulta</th><th>Estado</th><th>Traza</th></tr></thead><tbody>{runs.map(run => <tr key={run.id}><td>{run.query}</td><td>{run.error || run.status}</td><td><button disabled={busy} onClick={async () => {
      try { const data = await adminRequest(`retrieval/runs/${run.id}`, csrf); if (data.status === 'completed') setResult(data.result); else setError(data.result.error); }
      catch (e) { setError(e instanceof Error ? e.message : 'Error'); }
    }}>Ver traza</button></td></tr>)}</tbody></table></div>
  </section>;
}
