import type { Figure } from './types';
import { FigureCitations, FigureShell, type FigureProps } from './common';

type Props = { figure: Extract<Figure, { kind: 'timeline' }> } & FigureProps;

/* Línea de tiempo: lista ordenada con el `when` como texto literal.
   Sin parseo de fechas ni objetos Date: el contrato es la fuente. */
export function TimelineFigure({ figure, messageId, figureIndex, sources, onShowSource }: Props) {
  return <FigureShell kind="timeline" title={figure.title} caption={figure.caption}>
    <ol className="figure-timeline">
      {figure.timeline.events.map((event, index) => <li key={index}>
        <span className="figure-when">{event.when}</span>
        <span className="figure-event-label">{event.label}</span>
        <FigureCitations ids={event.citations} sources={sources} messageId={messageId}
          variant={`figure-timeline-${figureIndex}-${index}`} onShowSource={onShowSource} />
      </li>)}
    </ol>
  </FigureShell>;
}
