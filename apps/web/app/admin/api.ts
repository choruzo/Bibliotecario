export async function adminRequest(path: string, csrf: string, method = 'GET', body?: unknown, key?: string) {
  const headers: Record<string, string> = {};
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (key) headers['Idempotency-Key'] = key;
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api/admin/${path}`, {
    method, headers, cache: 'no-store', body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined
  });
  if (response.status === 401) { window.location.assign('/login'); throw new Error('Sesion caducada'); }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `No se pudo completar la operacion (${response.status})`);
  }
  return response.json();
}

export const statusNames: Record<string, string> = {
  subido: 'Subido', procesando: 'Procesando', requiere_revision: 'En revision', indexando: 'Indexando',
  publicado: 'Publicado', retirado: 'Retirado', error: 'Error', eliminando: 'Eliminando', eliminado: 'Eliminado',
  pendiente: 'Pendiente', en_ejecucion: 'En ejecucion', completado: 'Completado', reintentable: 'Esperando reintento',
  fallido: 'Fallido', cancelando: 'Cancelando', cancelado: 'Cancelado'
};
// Color semántico de cada estado: verde éxito, rojo fallo, ámbar revisión/espera, azul en curso.
const tones: Record<string, string> = {
  publicado: 'b-pass', completado: 'b-pass', completed: 'b-pass',
  error: 'b-fail', fallido: 'b-fail', failed: 'b-fail',
  requiere_revision: 'b-inc', pendiente: 'b-inc', reintentable: 'b-inc', eliminando: 'b-inc', cancelando: 'b-inc', pending: 'b-inc',
  procesando: 'b-info b-live', indexando: 'b-info b-live', en_ejecucion: 'b-info b-live', running: 'b-info b-live'
};
export const statusTone = (status?: string) => `badge ${status && tones[status] || 'b-dim'}`;
export const diagnosticNames: Record<string, string> = {
  empty_document: 'Documento vacio', edited_provenance: 'Contenido editado con procedencia manual',
  docx_images_omitted: 'Imagenes DOCX omitidas', pdf_images_omitted: 'Imagenes PDF omitidas',
  docx_header_footer_omitted: 'Cabeceras o pies DOCX omitidos', numbering_normalized: 'Numeracion de listas normalizada'
};
