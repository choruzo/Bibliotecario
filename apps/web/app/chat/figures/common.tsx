import type { ReactNode } from 'react';
import type { FigureSource } from './types';

/* Dependencias comunes de los cuatro componentes de figura. */
export type FigureProps = {
  messageId: string;
  figureIndex: number;
  sources: FigureSource[];
  onShowSource: (messageId: string, citation: FigureSource) => void;
};

/* Cáscara común: título y descripción en figcaption, cuerpo y citas como
   hijos. React escapa todo el texto; nunca hay HTML del modelo. */
export function FigureShell({ kind, title, caption, children }: {
  kind: 'table' | 'timeline' | 'bars' | 'steps';
  title: string;
  caption?: string;
  children: ReactNode;
}) {
  return <figure className={`figure figure-${kind}`}>
    <figcaption>
      <span className="figure-title">{title}</span>
      {caption && <span className="figure-caption">{caption}</span>}
    </figcaption>
    {children}
  </figure>;
}

/* Chips de cita: si la cita existe en las fuentes del mensaje, botón que abre
   el panel «Fragmento citado»; si no, texto plano. Nunca un botón muerto. */
export function FigureCitations({ ids, sources, messageId, variant, block, onShowSource }: {
  ids: readonly string[];
  sources: FigureSource[];
  messageId: string;
  variant: string;
  block?: boolean;
  onShowSource: FigureProps['onShowSource'];
}) {
  if (!ids.length) return null;
  const chips = ids.map(id => {
    const source = sources.find(candidate => candidate.citation_id === id);
    return source
      ? <button key={id} type="button" className="citation-link"
        data-citation={`${messageId}-${source.citation_id}-${variant}`}
        onClick={() => onShowSource(messageId, source)}>[{source.citation_id}]</button>
      : <span key={id} className="figure-citation-missing">[{id}]</span>;
  });
  return block
    ? <div className="figure-citations">{chips}</div>
    : <span className="figure-inline-citations">{chips}</span>;
}
