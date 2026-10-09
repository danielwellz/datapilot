import { Provider } from '@angular/core';

import { CHART_FACTORY } from './chart';
import { ChartConfig } from './chart-config';

/**
 * Replaces Chart.js, which needs a canvas jsdom does not have. Every chart
 * created is pushed to `drawn` with its configuration.
 */
export function provideFakeCharts(drawn: ChartConfig[] = []): Provider {
  return {
    provide: CHART_FACTORY,
    useValue: (_canvas: HTMLCanvasElement, config: ChartConfig) => {
      drawn.push(config);
      return { ...config, update: () => undefined, destroy: () => undefined };
    },
  };
}
