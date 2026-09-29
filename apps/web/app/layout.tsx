import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'Bibliotecario', description: 'Biblioteca documental local' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body>{children}</body></html>;
}
