import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'Bibliotecario', description: 'Biblioteca documental local' };
export const viewport: Viewport = { colorScheme: 'dark', themeColor: '#0a1214' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body><a className="skip-link" href="#main-content">Saltar al contenido</a>{children}</body></html>;
}
