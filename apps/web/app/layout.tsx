import type { Metadata } from 'next';
import './globals.css';
const themeBootstrap = `(()=>{let t='system';try{t=localStorage.getItem('bibliotecario-theme')||t}catch{}document.documentElement.dataset.theme=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'})()`;

export const metadata: Metadata = { title: 'Bibliotecario', description: 'Biblioteca documental local' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es" suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }}/></head><body><a className="skip-link" href="#main-content">Saltar al contenido</a>{children}</body></html>;
}
