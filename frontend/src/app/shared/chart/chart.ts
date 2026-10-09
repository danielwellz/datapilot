import {
  Component,
  DestroyRef,
  DOCUMENT,
  ElementRef,
  InjectionToken,
  afterRenderEffect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from 'chart.js';

import { ThemeService } from '../../core/theme/theme.service';
import { ChartConfig, ChartKind, ChartSpec, buildChartConfig } from './chart-config';
import { readChartTokens } from './chart-tokens';

// Only what the dashboard draws, so the rest of Chart.js is left out of the bundle.
Chart.register(
  LineController,
  LineElement,
  PointElement,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
);

/** The part of a Chart.js chart this component drives. */
export interface ChartHandle {
  data: ChartConfig['data'];
  options: NonNullable<ChartConfig['options']>;
  update(mode?: 'none'): void;
  destroy(): void;
}

export type ChartFactory = (canvas: HTMLCanvasElement, config: ChartConfig) => ChartHandle;

/** Creates the Chart.js chart; tests replace it, because jsdom has no canvas. */
export const CHART_FACTORY = new InjectionToken<ChartFactory>('CHART_FACTORY', {
  providedIn: 'root',
  factory: () => (canvas, config) => new Chart<ChartKind, number[], string>(canvas, config),
});

/**
 * The one Chart.js wrapper every chart goes through. It turns a
 * {@link ChartSpec} into a chart drawn with the theme's tokens, updates it in
 * place when the spec or the theme changes, and destroys it with the view.
 *
 * The canvas is hidden from assistive technology: every chart's page shows
 * the same numbers as a table, which screen readers read instead.
 */
@Component({
  selector: 'dp-chart',
  template: `
    @if (spec().series.length > 1) {
      <ul class="chart__legend" aria-hidden="true">
        @for (series of spec().series; track series.label) {
          <li class="chart__key">
            <span
              class="chart__swatch"
              [class.chart__swatch--dashed]="series.dashed"
              [style.--swatch]="'var(--chart-' + series.color + ')'"
            ></span
            >{{ series.label }}
          </li>
        }
      </ul>
    }
    <div class="chart__canvas" [style.height.px]="height()">
      <canvas #canvas aria-hidden="true"></canvas>
    </div>
  `,
  styleUrl: './chart.scss',
})
export class ChartView {
  readonly spec = input.required<ChartSpec>();
  /** Height of the drawing area in pixels; the width follows the container. */
  readonly height = input(280);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly theme = inject(ThemeService);
  private readonly create = inject(CHART_FACTORY);
  private chart: ChartHandle | null = null;

  constructor() {
    afterRenderEffect(() => {
      const spec = this.spec();
      // Read so a theme change runs this again; the tokens below carry its colors.
      this.theme.theme();
      this.draw(spec);
    });
    // A chart drawn before the web font loaded used a fallback face; redraw it
    // once. jsdom, which runs the unit tests, has no font loading API.
    const { fonts } = inject(DOCUMENT) as Partial<Document>;
    void fonts?.ready.then(() => this.chart?.update('none'));
    inject(DestroyRef).onDestroy(() => {
      this.chart?.destroy();
      this.chart = null;
    });
  }

  private draw(spec: ChartSpec): void {
    const config = buildChartConfig(spec, readChartTokens(this.host.nativeElement));
    if (this.chart === null) {
      this.chart = this.create(this.canvas().nativeElement, config);
      return;
    }
    this.chart.data = config.data;
    if (config.options !== undefined) {
      this.chart.options = config.options;
    }
    this.chart.update('none');
  }
}
