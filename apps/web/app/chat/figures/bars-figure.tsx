import type { Figure } from './types';
import { FigureCitations, FigureShell, type FigureProps } from './common';

type Props = { figure: Extract<Figure, { kind: 'bars' }> } & FigureProps;

/* Valor legible: coma decimal castellana, dos decimales como máximo.
   Formateado con Intl, nunca con el texto del modelo. */
const numberFormat = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 });

/* Barras: cada serie es una fila etiqueta + barra + valor con unidad.
   El ancho es un porcentaje calculado contra el máximo de la serie
   (redondeado y acotado a 0..100, con un mínimo visible del 2 %); el CSS solo
   recibe ese número, nunca una cadena del modelo. Además del gráfico
   (role="img" con etiqueta accesible) hay una lista textual equivalente para
   lectores de pantalla fuera del elemento con role="img". */
export function BarsFigure({ figure, messageId, figureIndex, sources, onShowSource }: Props) {
  const { bars } = figure;
  const max = bars.series.reduce((acc, item) => Math.max(acc, item.value), 0);
  const spoken = `${figure.title}. ${bars.series
    .map(item => `${item.label}: ${numberFormat.format(item.value)} ${bars.unit}`).join('. ')}.`;
  return <FigureShell kind="bars" title={figure.title} caption={figure.caption}>
    <div className="figure-bars" role="img" aria-label={spoken}>
      {bars.series.map((item, index) => {
        const percent = max > 0 ? Math.min(100, Math.max(0, Math.round((item.value / max) * 100))) : 0;
        const width = item.value > 0 && percent < 2 ? 2 : percent;
        return <div className="figure-bar-row" key={index}>
          <span className="figure-bar-label">{item.label}</span>
          <span className="figure-bar-track"><span className="figure-bar-fill" style={{ width: `${width}%` }} /></span>
          <span className="figure-bar-value">{numberFormat.format(item.value)} {bars.unit}</span>
        </div>;
      })}
    </div>
    <ul className="figure-sr-only">
      {bars.series.map((item, index) => <li key={index}>{item.label}: {numberFormat.format(item.value)} {bars.unit}</li>)}
    </ul>
    <FigureCitations ids={figure.source_citations} sources={sources} messageId={messageId}
      variant={`figure-bars-${figureIndex}`} block onShowSource={onShowSource} />
  </FigureShell>;
}
