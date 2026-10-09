import type { TooltipItem } from 'chart.js';

import { ChartKind, ChartSpec, buildChartConfig, shortenLabel } from './chart-config';
import { ChartTokens } from './chart-tokens';

const TOKENS: ChartTokens = {
  palette: ['#c1', '#c2', '#c3', '#c4', '#c5'],
  ink: '#ink',
  graphite: '#graphite',
  rule: '#rule',
  sheet: '#sheet',
  fontFamily: 'Plex',
};

function spec(overrides: Partial<ChartSpec> = {}): ChartSpec {
  return {
    kind: 'line',
    labels: ['Jan 2026', 'Feb 2026'],
    series: [
      { label: 'Revenue', values: [1000, 2500], color: 1 },
      { label: 'Average', values: [900, 1750], color: 2, dashed: true },
    ],
    formatTick: (value) => `$${String(value / 1000)}K`,
    ...overrides,
  };
}

/** The pieces of the configuration the tests read, typed loosely on purpose. */
interface Loose {
  options: {
    indexAxis: string;
    animation: boolean;
    interaction: { mode: string; axis: string };
    scales: Record<
      string,
      {
        beginAtZero?: boolean;
        grid: { color?: string; display?: boolean };
        border: { color?: string; display?: boolean };
        ticks: {
          color: string;
          font: { family: string };
          callback: (value: number | string) => string;
        };
      }
    >;
    plugins: {
      legend: { display: boolean };
      tooltip: {
        backgroundColor: string;
        borderColor: string;
        titleColor: string;
        bodyColor: string;
        footerColor: string;
        bodyFont: { family: string };
        callbacks: {
          title: (items: Partial<TooltipItem<ChartKind>>[]) => string;
          label: (item: Partial<TooltipItem<ChartKind>>) => string;
          footer: (items: Partial<TooltipItem<ChartKind>>[]) => string[];
        };
      };
    };
  };
}

function loose(chartSpec: ChartSpec): Loose {
  return buildChartConfig(chartSpec, TOKENS) as unknown as Loose;
}

describe('buildChartConfig', () => {
  it('maps every series to a dataset in the palette slot it names', () => {
    const config = buildChartConfig(spec(), TOKENS);

    expect(config.type).toBe('line');
    expect(config.data.labels).toEqual(['Jan 2026', 'Feb 2026']);
    expect(config.data.datasets).toMatchObject([
      { label: 'Revenue', data: [1000, 2500], borderColor: '#c1', borderDash: [], borderWidth: 2 },
      { label: 'Average', data: [900, 1750], borderColor: '#c2', borderDash: [6, 4] },
    ]);
  });

  it('copies labels and values, so Chart.js never holds the caller’s arrays', () => {
    const chartSpec = spec();
    const config = buildChartConfig(chartSpec, TOKENS);

    expect(config.data.labels).not.toBe(chartSpec.labels);
    expect(config.data.datasets[0]?.data).not.toBe(chartSpec.series[0]?.values);
  });

  it('draws bars without an outline', () => {
    const config = buildChartConfig(
      spec({ kind: 'bar', series: [{ label: 'Revenue', values: [1, 2], color: 3 }] }),
      TOKENS,
    );
    expect(config.type).toBe('bar');
    expect(config.data.datasets[0]).toMatchObject({ backgroundColor: '#c3', borderWidth: 0 });
  });

  it('puts labels along the bottom and values up the side by default', () => {
    const { options } = loose(spec());

    expect(options.indexAxis).toBe('x');
    expect(options.interaction).toEqual({ mode: 'index', intersect: false, axis: 'x' });
    expect(options.scales['y'].beginAtZero).toBe(true);
    expect(options.scales['y'].ticks.callback(2500)).toBe('$2.5K');
    expect(options.scales['x'].ticks.callback(1)).toBe('Feb 2026');
  });

  it('turns the axes for horizontal bars and shortens labels with the label format', () => {
    const { options } = loose(
      spec({ kind: 'bar', horizontal: true, formatLabel: (label) => label.slice(0, 3) }),
    );

    expect(options.indexAxis).toBe('y');
    expect(options.scales['x'].beginAtZero).toBe(true);
    expect(options.scales['y'].ticks.callback(0)).toBe('Jan');
  });

  it('colors axes, grid and tooltip from the theme tokens', () => {
    const { options } = loose(spec());
    const { tooltip } = options.plugins;

    expect(options.scales['y'].grid.color).toBe('#rule');
    expect(options.scales['x'].border.color).toBe('#rule');
    expect(options.scales['x'].ticks.color).toBe('#graphite');
    expect(options.scales['x'].ticks.font.family).toBe('Plex');
    expect(tooltip).toMatchObject({
      backgroundColor: '#sheet',
      borderColor: '#rule',
      titleColor: '#ink',
      bodyColor: '#ink',
      footerColor: '#graphite',
    });
    expect(tooltip.bodyFont.family).toBe('Plex');
  });

  it('keeps the readings still and leaves the legend to the page', () => {
    const { options } = loose(spec());
    expect(options.animation).toBe(false);
    expect(options.plugins.legend.display).toBe(false);
  });

  it('titles the tooltip with the label and lists each series with the tick format', () => {
    const { callbacks } = loose(spec()).options.plugins.tooltip;

    expect(callbacks.title([{ dataIndex: 1 }])).toBe('Feb 2026');
    expect(callbacks.label({ datasetIndex: 1, dataIndex: 1 })).toBe('Average: $1.75K');
    expect(callbacks.footer([{ dataIndex: 1 }])).toEqual([]);
  });

  it('uses the caller’s tooltip lines and footer when given', () => {
    const { callbacks } = loose(
      spec({
        tooltipLabel: (series, index) => `series ${String(series)} at ${String(index)}`,
        tooltipFooter: (index) => [`MoM at ${String(index)}`, 'YoY'],
      }),
    ).options.plugins.tooltip;

    expect(callbacks.label({ datasetIndex: 0, dataIndex: 1 })).toBe('series 0 at 1');
    expect(callbacks.footer([{ dataIndex: 1 }])).toEqual(['MoM at 1', 'YoY']);
  });

  it('gives an empty tooltip for positions it does not know', () => {
    const { callbacks } = loose(spec({ tooltipFooter: () => ['x'] })).options.plugins.tooltip;

    expect(callbacks.title([])).toBe('');
    expect(callbacks.footer([])).toEqual([]);
    expect(callbacks.label({ datasetIndex: 5, dataIndex: 0 })).toBe('');
  });
});

describe('shortenLabel', () => {
  it('shortens a long label with an ellipsis and leaves a short one', () => {
    expect(shortenLabel('Noise-cancelling headphones for travel')).toBe('Noise-cancelling head…');
    expect(shortenLabel('Harbor Backpack')).toBe('Harbor Backpack');
    expect(shortenLabel('abcdef', 4)).toBe('abc…');
    expect(shortenLabel('ab  cdef', 4)).toBe('ab…');
  });
});
