import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';
const allowed = new Set(['auth/login', 'auth/logout', 'auth/me', 'health/dependencies']);
const adminRoutes = /^(admin\/documents(?:\/[a-f0-9-]{36}(?:\/versions|\/withdraw)?)?|admin\/versions\/[a-f0-9-]{36}(?:\/original|\/normalized|\/revisions|\/review|\/convert|\/publish)?|admin\/jobs(?:\/[a-f0-9-]{36}\/(?:events|cancel|retry))?|admin\/retrieval\/(?:search|policy|calibrate|runs(?:\/[a-f0-9-]{36})?))$/;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!allowed.has(route) && !adminRoutes.test(route)) return Response.json({ detail: 'Ruta no encontrada' }, { status: 404 });
  const headers = new Headers();
  for (const name of ['cookie', 'content-type', 'origin', 'x-csrf-token', 'x-request-id', 'idempotency-key']) {
    const value = request.headers.get(name); if (value) headers.set(name, value);
  }
  try {
    const options: RequestInit & { duplex?: 'half' } = {
      method: request.method, headers,
      body: request.method === 'GET' ? undefined : request.body,
      duplex: 'half',
      cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(130000)
    };
    const upstream = await fetch(`${process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/${route}${request.nextUrl.search}`, options);
    const outgoing = new Headers({ 'Cache-Control': 'no-store' });
    for (const name of ['content-type', 'x-request-id', 'content-disposition', 'x-content-type-options']) {
      const value = upstream.headers.get(name); if (value) outgoing.set(name, value);
    }
    for (const cookie of upstream.headers.getSetCookie()) outgoing.append('set-cookie', cookie);
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: 'Servicio no disponible' }, { status: 503 });
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
