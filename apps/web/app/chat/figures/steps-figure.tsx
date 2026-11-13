import type { Figure } from './types';
import { FigureCitations, FigureShell, type FigureProps } from './common';

type Props = { figure: Extract<Figure, { kind: 'steps' }> } & FigureProps;

/* Pasos: lista ordenada (la numeración la da el propio <ol>), detalle
   opcional y citas de cada paso junto a su etiqueta. */
export function StepsFigure({ figure, messageId, figureIndex, sources, onShowSource }: Props) {
  return <FigureShell kind="steps" title={figure.title} caption={figure.caption}>
    <ol className="figure-steps">
      {figure.steps.items.map((item, index) => <li key={index}>
        <span className="figure-step-label">{item.label}</span>
        {item.detail && <span className="figure-step-detail">{item.detail}</span>}
        <FigureCitations ids={item.citations} sources={sources} messageId={messageId}
          variant={`figure-steps-${figureIndex}-${index}`} onShowSource={onShowSource} />
      </li>)}
    </ol>
  </FigureShell>;
}
