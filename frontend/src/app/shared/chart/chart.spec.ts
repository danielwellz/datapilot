import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ThemeService } from '../../core/theme/theme.service';
import { CHART_FACTORY, ChartHandle, ChartView } from './chart';
import { ChartConfig, ChartSpec } from './chart-config';

class FakeChart implements ChartHandle {
  data: ChartConfig['data'];
  options: NonNullable<ChartConfig['options']>;
  readonly updates: (string | undefined)[] = [];
  destroyed = false;

  constructor(
    readonly canvas: HTMLCanvasElement,
    config: ChartConfig,
  ) {
    this.data = config.data;
    this.options = config.options ?? {};
  }

  update(mode?: 'none'): void {
    this.updates.push(mode);
  }

  destroy(): void {
    this.destroyed = true;
  }
}

function lineSpec(values: number[]): ChartSpec {
  return {
    kind: 'line',
    labels: values.map((_, index) => `M${String(index)}`),
    series: [
      { label: 'Revenue', values, color: 1 },
      { label: '3-month average', values, color: 2, dashed: true },
    ],
    formatTick: String,
  };
}

@Component({
  imports: [ChartView],
  template: `<dp-chart [spec]="spec()" [height]="200" />`,
})
class Host {
  readonly spec = signal(lineSpec([1, 2, 3]));
}

describe('ChartView', () => {
  let charts: FakeChart[];
  let fixture: ComponentFixture<Host>;

  beforeEach(async () => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    charts = [];
    TestBed.configureTestingModule({
      providers: [
        {
          provide: CHART_FACTORY,
          useValue: (canvas: HTMLCanvasElement, config: ChartConfig) => {
            const chart = new FakeChart(canvas, config);
            charts.push(chart);
            return chart;
          },
        },
      ],
    });
    fixture = TestBed.createComponent(Host);
    await fixture.whenStable();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  /** Sets a token on the chart's own element, where the component reads it. */
  function setToken(name: string, value: string): void {
    element().querySelector<HTMLElement>('dp-chart')?.style.setProperty(name, value);
  }

  it('draws one chart on a canvas hidden from assistive technology', () => {
    expect(charts).toHaveLength(1);
    const canvas = element().querySelector('canvas');
    expect(charts[0]?.canvas).toBe(canvas);
    expect(canvas?.getAttribute('aria-hidden')).toBe('true');
    expect(charts[0]?.data.datasets[0]?.data).toEqual([1, 2, 3]);
  });

  it('sizes the drawing area from the height input', () => {
    expect(element().querySelector<HTMLElement>('.chart__canvas')?.style.height).toBe('200px');
  });

  it('shows a legend for several series, marking the dashed one', () => {
    const keys = [...element().querySelectorAll('.chart__key')];
    expect(keys.map((key) => key.textContent.trim())).toEqual(['Revenue', '3-month average']);
    expect(keys.at(1)?.querySelector('.chart__swatch--dashed')).not.toBeNull();
    expect(
      keys.at(0)?.querySelector<HTMLElement>('.chart__swatch')?.style.getPropertyValue('--swatch'),
    ).toBe('var(--chart-1)');
  });

  it('leaves the legend out for a single series', async () => {
    fixture.componentInstance.spec.set({
      ...lineSpec([1]),
      series: [{ label: 'Revenue', values: [1], color: 1 }],
    });
    await fixture.whenStable();
    expect(element().querySelector('.chart__legend')).toBeNull();
  });

  it('updates the same chart in place when the spec changes', async () => {
    fixture.componentInstance.spec.set(lineSpec([4, 5]));
    await fixture.whenStable();

    expect(charts).toHaveLength(1);
    expect(charts[0]?.data.labels).toEqual(['M0', 'M1']);
    expect(charts[0]?.data.datasets[0]?.data).toEqual([4, 5]);
    expect(charts[0]?.updates).toContain('none');
  });

  it('reads the tokens again and recolors the chart when the theme changes', async () => {
    setToken('--chart-1', '#93a2ff');
    TestBed.inject(ThemeService).toggle();
    await fixture.whenStable();

    expect(charts).toHaveLength(1);
    expect(charts[0]?.data.datasets[0]?.borderColor).toBe('#93a2ff');
    expect(charts[0]?.updates).toContain('none');
  });

  it('destroys the chart with the view', () => {
    fixture.destroy();
    expect(charts[0]?.destroyed).toBe(true);
  });
});
