'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { BookOpen, LogOut, MessageSquare, Activity, RefreshCw, Library, Files, ListChecks } from 'lucide-react';
import DocumentsView from './admin/documents-view';
import JobsView from './admin/jobs-view';
import RetrievalView from './admin/retrieval-view';
import OperationsView from './admin/operations-view';
import ChatView from './chat/chat-view';

type User = { username: string; role: string; csrf_token: string };
type Check = { status: string; error?: string; latency_ms?: number };
type Health = { checks: Record<string, Check> };
const names: Record<string, string> = { database: 'Base de datos', llm: 'Generacion', embedding: 'Embeddings', reranker: 'Reranker' };

export default function Workspace({ admin = false, view = 'services', documentId, runId }: { admin?: boolean; view?: 'services' | 'documents' | 'jobs' | 'retrieval' | 'operations'; documentId?: string; runId?: string }) {
  const router = useRouter();
  const path = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [checked, setChecked] = useState('');
  useEffect(() => {
    let active = true;
    fetch('/api/auth/me', { cache: 'no-store' }).then(async response => {
      if (response.status === 401) { router.replace('/login'); return; }
      if (!response.ok) throw new Error();
      const current: User = await response.json();
      if (admin && current.role !== 'admin') { router.replace('/chat'); return; }
      if (active) setUser(current);
    }).catch(() => { if (active) setError('No se puede conectar con el servicio.'); });
    return () => { active = false; };
  }, [admin, router]);
  async function check() {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/health/dependencies', { cache: 'no-store' });
      if (response.status === 401) { router.replace('/login'); return; }
      if (response.status !== 200 && response.status !== 503) throw new Error();
      const result = await response.json();
      if (!result.checks) throw new Error();
      setHealth(result); setChecked(new Date().toLocaleTimeString('es-ES'));
    } catch { setError('No se ha podido comprobar la disponibilidad.'); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (!user || busy) return;
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': user.csrf_token } });
      if (!response.ok && response.status !== 401) throw new Error();
      router.replace('/login');
    } catch { setError('No se ha podido cerrar la sesion.'); }
    finally { setBusy(false); }
  }
  if (!user) return <main id="main-content" tabIndex={-1} className="loading" role="status">{error || 'Conectando...'}</main>;
  return <div className="workspace"><aside className="sidebar">
    <div className="sidebar-heading"><Link className="brand" href="/chat"><BookOpen size={25}/><span>Bibliotecario</span></Link></div>
    <nav aria-label="Principal"><Link href="/chat" aria-current={path === '/chat' ? 'page' : undefined}><MessageSquare size={19}/>Biblioteca</Link>
      {user.role === 'admin' && <><Link href="/admin/documents" aria-current={path.startsWith('/admin/documents') ? 'page' : undefined}><Files size={19}/>Documentos</Link>
        <Link href="/admin/jobs" aria-current={path === '/admin/jobs' ? 'page' : undefined}><ListChecks size={19}/>Trabajos</Link>
        <Link href="/admin/retrieval" aria-current={path.startsWith('/admin/retrieval') ? 'page' : undefined}><Library size={19}/>Recuperacion</Link>
        <Link href="/admin/operations" aria-current={path === '/admin/operations' ? 'page' : undefined}><ListChecks size={19}/>Operacion</Link>
        <Link href="/admin" aria-current={path === '/admin' ? 'page' : undefined}><Activity size={19}/>Administracion</Link></>}</nav>
    <div className="sidebar-footer"><div className="account"><div><strong>{user.username}</strong><span>{user.role === 'admin' ? 'Administrador' : 'Usuario'}</span></div>
      <button className="icon-button" onClick={logout} disabled={busy} title="Cerrar sesion" aria-label="Cerrar sesion"><LogOut size={19}/></button></div>
  </div></aside><main id="main-content" tabIndex={-1} className="content">
    <header className="page-header"><div><p className="eyebrow">Biblioteca local</p><h1>{admin ? view === 'documents' ? 'Documentos' : view === 'jobs' ? 'Trabajos de ingesta' : view === 'operations' ? 'Operacion administrativa' : view === 'retrieval' ? 'Inspeccion de recuperacion' : 'Estado de los servicios' : 'Biblioteca'}</h1></div>
      {admin && view === 'services' && <button className="primario" onClick={check} disabled={busy}><RefreshCw size={17} className={busy ? 'spin' : ''}/>{busy ? 'Comprobando...' : 'Comprobar'}</button>}</header>
    {error && <p role="alert" className="error">{error}</p>}
    {admin && view === 'operations' ? <OperationsView csrf={user.csrf_token}/> : admin && view === 'documents' ? <DocumentsView key={documentId || "list"} csrf={user.csrf_token} documentId={documentId}/> : admin && view === 'jobs' ? <JobsView csrf={user.csrf_token}/> : admin && view === 'retrieval' ? <RetrievalView key={runId || "list"} csrf={user.csrf_token} runId={runId}/> : admin ? <>{health && <ul className="stat-grid" aria-label="Resumen de disponibilidad">{(() => { const results = Object.keys(names).map(key => health.checks[key]).filter(Boolean); const up = results.filter(r => r.status === 'available'); const times = up.map(r => r.latency_ms).filter((ms): ms is number => ms !== undefined); return <><li className="stat-card pass"><strong>{up.length}</strong><span>Disponibles</span></li><li className={`stat-card ${results.length > up.length ? 'fail' : ''}`}><strong>{results.length - up.length}</strong><span>No disponibles</span></li><li className="stat-card info"><strong>{times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : '-'}</strong><span>Latencia media (ms)</span></li></>; })()}</ul>}<div className="status-summary"><span>Disponibilidad</span><span className="muted">{checked ? `Ultima comprobacion: ${checked}` : 'Sin comprobar'}</span></div>
      <div className="table-wrap" role="region" aria-label="Disponibilidad de servicios" tabIndex={0}><table><thead><tr><th scope="col">Servicio</th><th scope="col">Estado</th><th scope="col">Latencia</th><th scope="col">Diagnostico</th></tr></thead><tbody>
        {Object.entries(names).map(([key, label]) => { const result = health?.checks[key]; return <tr key={key}><th scope="row">{label}</th>
          <td><span className={`status ${result?.status === 'available' ? 'ok' : result ? 'bad' : ''}`}><span className="dot"/>{result ? result.status === 'available' ? 'Disponible' : 'No disponible' : 'Sin comprobar'}</span></td>
          <td>{result?.latency_ms !== undefined ? `${result.latency_ms} ms` : '-'}</td><td className="diagnostic">{result?.error || '-'}</td></tr>; })}
      </tbody></table></div></> : null}
    {!admin && <ChatView csrf={user.csrf_token}/>}
  </main></div>;
}
