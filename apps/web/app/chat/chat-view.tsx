'use client';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Source = { citation_id: string; title: string; version: number; quote: string; locator: { page?: number; section_path?: string[]; line_start?: number; line_end?: number } };
type Message = { id: string; role: string; content: string; status: string; sources: Source[] };
type Conversation = { id: string; title: string };
type Detail = Conversation & { preferences: string; busy: boolean; messages: Message[] };

export default function ChatView({ csrf }: { csrf: string }) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [current, setCurrent] = useState<Detail | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState('');
  const [draft, setDraft] = useState('');
  const [source, setSource] = useState<{ message: string; source: Source } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const selected = useRef('');
  const sourceRef = useRef<HTMLElement>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  function showSource(message: string, citation: Source) {
    sourceTrigger.current = document.activeElement as HTMLElement;
    setSource({ message, source: citation });
  }
  useEffect(() => {
    if (source) sourceRef.current?.focus();
    else if (sourceTrigger.current) {
      const trigger = sourceTrigger.current;
      const citation = trigger.dataset.citation;
      (trigger.isConnected ? trigger : citation ? document.querySelector<HTMLElement>(`[data-citation="${CSS.escape(citation)}"]`) : null)?.focus();
      sourceTrigger.current = null;
    }
  }, [source]);
  async function api(path: string, method = 'GET', body?: unknown) {
    const response = await fetch(`/api/chat/${path}`, { method, cache: 'no-store',
      headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: body ? JSON.stringify(body) : undefined });
    if (response.status === 401) { window.location.assign('/login'); throw new Error('Sesión caducada'); }
    if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(typeof value.detail === 'string' ? value.detail : 'No se pudo completar la operación'); }
    return response;
  }
  async function list() { const data = await (await api('conversations')).json(); setItems(data.items); }
  async function open(id: string) {
    selected.current = id; setSource(null); setError('');
    const data = await (await api(`conversations/${id}`)).json();
    if (selected.current === id) setCurrent(data);
  }
  useEffect(() => {
    list().catch(e => setError(e.message));
    return () => { abort.current?.abort(); };
    // A session owns this component for its entire lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [csrf]);
  async function create() {
    setBusy(true); setError('');
    try { const row = await (await api('conversations', 'POST', {})).json(); await list(); await open(row.id); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    if (!current) return;
    setBusy(true); setError('');
    try { await api(`conversations/${current.id}`, 'PATCH', { title: current.title, preferences: current.preferences }); await list(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function send(e: React.FormEvent) {
    e.preventDefault(); if (!current || !question.trim() || busy) return;
    const id = current.id;
    setBusy(true); setError(''); setDraft(''); setProgress('Conectando…');
    abort.current = new AbortController();
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch(`/api/chat/conversations/${id}/messages`, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ content: question }), signal: abort.current.signal });
      if (!response.ok || !response.body) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || 'No se pudo enviar la pregunta'); }
      setQuestion('');
      await open(id);
      reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let done = false;
      while (true) {
        const part = await reader.read(); buffer += decoder.decode(part.value, { stream: !part.done });
        const lines = buffer.split('\n'); buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const value = JSON.parse(line);
          if (value.type === 'status') setProgress(value.message);
          if (value.type === 'delta') setDraft(text => text + value.content);
          if (value.type === 'error') throw new Error(value.message);
          if (value.type === 'done') done = true;
        }
        if (part.done) break;
      }
      if (!done) throw new Error('La conexión se interrumpió. La pregunta permanece guardada.');
    } catch (e) { setError((e as Error).name === 'AbortError' ? 'Respuesta detenida. Puedes continuar la conversación.' : (e as Error).message); }
    finally {
      await reader?.cancel().catch(() => {});
      setBusy(false); setDraft(''); setProgress(''); abort.current = null;
      await open(id).catch(e => setError(e.message)); await list().catch(e => setError(e.message));
    }
  }
  function renderContent(message: Message) {
    const [documentary, general] = message.content.split('\n\nExplicación general\n\n');
    const markdown = documentary.replace(/\[(C\d+)\]/g, (text, id) => message.sources.some(s => s.citation_id === id) ? `[${text}](#bibliotecario-citation-${id})` : text);
    return <><div className="chat-text chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={{
      img: ({ alt }) => <span>{alt}</span>,
      a: ({ href, children }) => {
        const citation = message.sources.find(s => href === `#bibliotecario-citation-${s.citation_id}`);
        return citation ? <button data-citation={`${message.id}-${citation.citation_id}-inline`} className="citation-link" onClick={() => showSource(message.id, citation)}>{children}</button> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
      }
    }}>{markdown}</ReactMarkdown></div>{general && <aside className="general-explanation"><strong>Explicación general</strong><p>{general}</p></aside>}</>;
  }
  return <section className="chat-layout"><aside className="conversation-list">
    <button onClick={create} disabled={busy}>Nueva conversación</button>
    <nav aria-label="Conversaciones">{items.map(item => <button key={item.id} disabled={busy} aria-pressed={current?.id === item.id}
      onClick={() => open(item.id).catch(e => setError(e.message))}>{item.title}</button>)}</nav>
  </aside><div className="chat-panel">
    {error && <p role="alert" className="error">{error}</p>}
    {!current ? <div className="empty-state"><h2>Conversa con tu biblioteca</h2><p>Crea o abre una conversación para consultar los documentos.</p></div> : <>
      <div className="conversation-settings"><label>Título de la conversación<input maxLength={200} value={current.title} disabled={busy} onChange={e => setCurrent({ ...current, title: e.target.value })}/></label>
        <label>Preferencias pedagógicas<input maxLength={500} placeholder="Ej.: explicación sencilla, ejemplos y pasos" disabled={busy} value={current.preferences} onChange={e => setCurrent({ ...current, preferences: e.target.value })}/></label>
        <button disabled={busy} onClick={save}>Guardar cambios</button></div>
      <section className="chat-messages" aria-label="Mensajes">{current.messages.map(message => <article key={message.id} className={`chat-message ${message.role}`}>
        <strong>{message.role === 'user' ? 'Tú' : 'Bibliotecario'}</strong>
        {message.status === 'pending' ? <p>{current.busy ? 'Respuesta en curso…' : 'Respuesta interrumpida. Puedes volver a preguntar.'}</p> : renderContent(message)}
        {message.sources.length > 0 && <div className="citation-list">{message.sources.map(s => <button key={s.citation_id} data-citation={`${message.id}-${s.citation_id}-list`} onClick={() => showSource(message.id, s)}>[{s.citation_id}] {s.title} · v{s.version}</button>)}</div>}
      </article>)}{draft && <div className="chat-text">{draft}</div>}</section>
      {progress && <p role="status">{progress}</p>}
      <form className="chat-composer" onSubmit={send}><label htmlFor="question">Pregunta a la biblioteca</label><textarea id="question" maxLength={1000} disabled={busy} value={question} onChange={e => setQuestion(e.target.value)} required/>
        <div><button disabled={busy || !question.trim()} type="submit">Enviar</button>{busy && <button type="button" onClick={() => abort.current?.abort()}>Detener</button>}</div></form>
    </>}
    {source && <section ref={sourceRef} tabIndex={-1} className="source-view" aria-label="Fragmento citado"><h2>{source.source.title} · v{source.source.version}</h2>
      <p>{source.source.locator.page ? `Página ${source.source.locator.page}` : source.source.locator.section_path?.join(' / ') || `Líneas ${source.source.locator.line_start}–${source.source.locator.line_end}`}</p>
      <pre>{source.source.quote}</pre><a href={`/api/chat/messages/${source.message}/sources/${source.source.citation_id}/original`} target="_blank" rel="noreferrer">Descargar original</a>
      <button onClick={() => setSource(null)}>Cerrar fragmento</button></section>}
  </div></section>;
}
