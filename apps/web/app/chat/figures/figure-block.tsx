import type { Figure } from './types';
import { TableFigure } from './table-figure';
import { TimelineFigure } from './timeline-figure';
import { BarsFigure } from './bars-figure';
import { StepsFigure } from './steps-figure';
import type { FigureProps } from './common';

/* Dispatcher fijo: un componente por kind del contrato. Las figuras que llegan
   aquí ya pasaron `parseFigure`, así que el default solo cubre tipos nuevos
   futuros: no se pinta nada. */
export function FigureBlock({ figure, ...rest }: { figure: Figure } & FigureProps) {
  switch (figure.kind) {
    case 'table': return <TableFigure figure={figure} {...rest} />;
    case 'timeline': return <TimelineFigure figure={figure} {...rest} />;
    case 'bars': return <BarsFigure figure={figure} {...rest} />;
    case 'steps': return <StepsFigure figure={figure} {...rest} />;
    default: return null;
  }
}
