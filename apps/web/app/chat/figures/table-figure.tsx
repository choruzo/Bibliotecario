import type { Figure } from './types';
import { FigureCitations, type FigureProps } from './common';

type Props = { figure: Extract<Figure, { kind: 'table' }> } & FigureProps;

/* Tabla fija: el título va en <caption> y la descripción (caption) en
   figcaption, sin repetir el título. El contenedor desplaza en horizontal
   (móvil) y es alcanzable con teclado. */
export function TableFigure({ figure, messageId, figureIndex, sources, onShowSource }: Props) {
  return <figure className="figure figure-table">
    {figure.caption && <figcaption className="figure-caption">{figure.caption}</figcaption>}
    <div className="figure-table-wrap" role="region" tabIndex={0} aria-label={`Tabla: ${figure.title}`}>
      <table>
        <caption>{figure.title}</caption>
        <thead><tr>{figure.table.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
        <tbody>{figure.table.rows.map((row, index) => <tr key={index}>
          {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    <FigureCitations ids={figure.source_citations} sources={sources} messageId={messageId}
      variant={`figure-table-${figureIndex}`} block onShowSource={onShowSource} />
  </figure>;
}
