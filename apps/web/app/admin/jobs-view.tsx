'use client';
import { useCallback, useEffect, useState } from 'react';
import { RotateCcw, CircleStop, List, X } from 'lucide-react';
import { adminRequest, statusNames } from './api';
import Modal from './modal';

type Job = { id: string; document_id: string; document_title: string; kind: string; status: string; progress: number; attempts: number; error_code: string | null };
type Event = { event: string; attempt: number; generation: number; created_at: number };

export default function JobsView({ csrf }: { csrf: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<Event[] | null>(null);
  const refresh = useCallback(async () => {
    const data = await adminRequest(`jobs?offset=${offset}`, csrf);
    setJobs(data.items); setMore(data.has_more);
  }, [csrf, offset]);
  useEffect(() => {
    const update = () => refresh().catch((e: Error) => setError(e.message));
    update(); const timer = setInterval(update, 2500); return () => clearInterval(timer);
  }, [refresh]);
  async function action(job: Job, operation: 'cancel' | 'retry' | 'events') {
    setBusy(true); setError('');
    try {
      const data = await adminRequest(`jobs/${job.id}/${operation}`, csrf, operation === 'events' ? 'GET' : 'POST');
      if (operation === 'events') setEvents(data.items);
      await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="jobs-section">{error && <p className="error" role="alert">{error}</p>}
    <div className="table-wrap"><table><thead><tr><th>Documento</th><th>Operacion</th><th>Estado</th><th>Progreso</th><th>Intentos</th><th>Diagnostico</th><th>Acciones</th></tr></thead><tbody>
      {jobs.map(job => <tr key={job.id}><th scope="row">{job.document_title}</th><td>{job.kind === 'convert' ? 'Conversion' : job.kind === 'index' ? 'Indexacion' : 'Eliminacion'}</td><td>{statusNames[job.status]}</td><td><progress value={job.progress} max={100} aria-label="Progreso"/><span className="progress-label">{job.progress}%</span></td><td>{job.attempts}</td><td>{job.error_code || '-'}</td><td><div className="job-actions">
        <button className="icon-button" title="Ver eventos" aria-label="Ver eventos" disabled={busy} onClick={() => action(job, 'events')}><List size={17}/></button>
        <button className="icon-button" title="Cancelar trabajo" aria-label="Cancelar trabajo" disabled={busy || !['convert', 'index'].includes(job.kind) || !['pendiente', 'en_ejecucion', 'reintentable'].includes(job.status)} onClick={() => action(job, 'cancel')}><CircleStop size={17}/></button>
        <button className="icon-button" title="Reintentar trabajo" aria-label="Reintentar trabajo" disabled={busy || !['fallido', 'cancelado'].includes(job.status)} onClick={() => action(job, 'retry')}><RotateCcw size={17}/></button>
      </div></td></tr>)}
    </tbody></table></div>{!jobs.length && <p className="muted">No hay trabajos</p>}
    <div className="pagination"><button disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 50))}>Anterior</button><span>{offset + 1} - {offset + jobs.length}</span><button disabled={!more || busy} onClick={() => setOffset(offset + 50)}>Siguiente</button></div>
    {events && <Modal titleId="events-title" onClose={() => setEvents(null)}><div className="review-heading"><h2 id="events-title">Eventos del trabajo</h2><button className="icon-button" title="Cerrar eventos" aria-label="Cerrar eventos" onClick={() => setEvents(null)} autoFocus><X size={18}/></button></div>
      <ol className="job-events">{events.map((event, index) => <li key={index}><strong>{event.event}</strong><span>Intento {event.attempt} / generacion {event.generation}</span><time>{new Date(event.created_at * 1000).toLocaleString('es-ES')}</time></li>)}</ol>
    </Modal>}
  </section>;
}
