'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, LogIn } from 'lucide-react';

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const fields = new FormData(event.currentTarget);
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: fields.get('username'), password: fields.get('password') }) });
      if (!response.ok) { setError(response.status === 401 ? 'Usuario o contrasena incorrectos.' : 'No se puede iniciar sesion.'); return; }
      const user = await response.json();
      router.replace(user.role === 'admin' ? '/admin' : '/chat');
    } catch { setError('No se puede conectar con el servicio.'); }
    finally { setBusy(false); }
  }
  return <main id="main-content" tabIndex={-1} className="login-page"><div className="login-shell"><form className="login-form" onSubmit={submit}>
    <BookOpen size={34} className="brand-icon" aria-hidden="true"/><h1>Bibliotecario</h1>
    <p className="muted">Acceso a la biblioteca</p>
    <label htmlFor="username">Usuario</label><input id="username" name="username" autoComplete="username" required maxLength={64}/>
    <label htmlFor="password">Contrasena</label><input id="password" name="password" type="password" autoComplete="current-password" required maxLength={1024}/>
    {error && <p className="error" role="alert">{error}</p>}
    <button className="primary" disabled={busy}><LogIn size={18}/>{busy ? 'Accediendo...' : 'Entrar'}</button>
  </form></div></main>;
}
