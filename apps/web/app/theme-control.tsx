'use client';
import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';

const key = 'bibliotecario-theme';

export default function ThemeControl() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    function sync() {
      let saved: string | null = null;
      try { saved = localStorage.getItem(key); } catch { /* Theme still works without storage. */ }
      const value = saved === 'light' || saved === 'dark' ? saved : 'system';
      const resolved = value === 'dark' || (value === 'system' && media.matches) ? 'dark' : 'light';
      setTheme(resolved);
      document.documentElement.dataset.theme = resolved;
    }
    sync();
    media.addEventListener('change', sync);
    window.addEventListener('storage', sync);
    return () => { media.removeEventListener('change', sync); window.removeEventListener('storage', sync); };
  }, []);
  const label = theme === 'dark' ? 'Activar modo claro' : 'Activar modo oscuro';
  return <button type="button" className="theme-toggle icon-button" aria-label={label} title={label} onClick={() => {
      const value = theme === 'dark' ? 'light' : 'dark';
      setTheme(value);
      try { localStorage.setItem(key, value); } catch { /* Keep the selection for this page. */ }
      document.documentElement.dataset.theme = value;
    }}>{theme === 'dark' ? <Sun size={21} aria-hidden="true"/> : <Moon size={21} aria-hidden="true"/>}</button>;
}
