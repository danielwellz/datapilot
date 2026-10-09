import type { ChartConfiguration, FontSpec, TooltipItem } from 'chart.js';

import { ChartTokens } from './chart-tokens';

export type ChartKind = 'line' | 'bar';

/** A slot of the categorical palette, `--chart-1` to `--chart-5`. */
export type PaletteSlot = 1 | 2 | 3 | 4 | 5;

export interface ChartSeries {
  label: string;
  values: readonly number[];
  color: PaletteSlot;
  /** A dashed line, for a derived series such as a moving average. */
  dashed?: boolean;
}

/** What a chart shows, independent of Chart.js and of the theme. */
export interface ChartSpec {
  kind: ChartKind;
  /** One label per value, shared by every series. */
  labels: readonly string[];
  series: readonly ChartSeries[];
  /** Bars along the horizontal axis, with the labels down the side. */
  horizontal?: boolean;
  /** Ticks on the value axis, where a short form reads best: `"$7.5M"`. */
  formatTick: (value: number) => string;
  /** Ticks on the label axis, for example to shorten long names. */
  formatLabel?: (label: string) => string;
  /** One tooltip line for a series at a position; defaults to its label and tick format. */
  tooltipLabel?: (seriesIndex: number, index: number) => string;
  /** Extra tooltip lines for a position, below the series values. */
  tooltipFooter?: (index: number) => readonly string[];
}

export type ChartConfig = ChartConfiguration<ChartKind, number[], string>;

const TICK_SIZE = 12;
const TOOLTIP_SIZE = 13;

/**
 * Maps a chart spec and the theme's tokens to a Chart.js configuration. Pure,
 * so the mapping is tested without a canvas and a theme change only has to
 * call it again.
 */
export function buildChartConfig(spec: ChartSpec, tokens: ChartTokens): ChartConfig {
  const horizontal = spec.horizontal ?? false;
  const valueAxis = horizontal ? 'x' : 'y';
  const labelAxis = horizontal ? 'y' : 'x';
  const font = (size: number, weight: FontSpec['weight'] = 400): Partial<FontSpec> => ({
    family: tokens.fontFamily,
    size,
    weight,
  });
  const color = (series: ChartSeries): string => tokens.palette.at(series.color - 1) ?? tokens.ink;
  const formatLabel = spec.formatLabel ?? ((label: string) => label);
  const tooltipLabel =
    spec.tooltipLabel ??
    ((seriesIndex: number, index: number): string => {
      const series = spec.series.at(seriesIndex);
      return series === undefined
        ? ''
        : `${series.label}: ${spec.formatTick(series.values.at(index) ?? 0)}`;
    });

  return {
    type: spec.kind,
    data: {
      labels: [...spec.labels],
      datasets: spec.series.map((series) => ({
        label: series.label,
        data: [...series.values],
        borderColor: color(series),
        backgroundColor: color(series),
        borderWidth: spec.kind === 'line' ? 2 : 0,
        borderDash: series.dashed === true ? [6, 4] : [],
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHitRadius: 8,
        maxBarThickness: 18,
      })),
    },
    options: {
      // An instrument does not animate its readings (docs/design.md).
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: labelAxis,
      interaction: { mode: 'index', intersect: false, axis: labelAxis },
      scales: {
        [valueAxis]: {
          beginAtZero: true,
          border: { display: false },
          grid: { color: tokens.rule },
          ticks: {
            color: tokens.graphite,
            font: font(TICK_SIZE),
            maxTicksLimit: 6,
            callback: (value: number | string) => spec.formatTick(Number(value)),
          },
        },
        [labelAxis]: {
          border: { color: tokens.rule },
          grid: { display: false },
          ticks: {
            color: tokens.graphite,
            font: font(TICK_SIZE),
            maxRotation: 0,
            autoSkipPadding: 12,
            // On a category axis the tick's value is the label's index.
            callback: (value: number | string) => formatLabel(spec.labels.at(Number(value)) ?? ''),
          },
        },
      },
      plugins: {
        // The legend is HTML beside the canvas, so it uses the page's type and is readable.
        legend: { display: false },
        tooltip: {
          backgroundColor: tokens.sheet,
          borderColor: tokens.rule,
          borderWidth: 1,
          cornerRadius: 6,
          padding: 12,
          titleColor: tokens.ink,
          bodyColor: tokens.ink,
          footerColor: tokens.graphite,
          titleFont: font(TOOLTIP_SIZE, 600),
          bodyFont: font(TOOLTIP_SIZE),
          footerFont: font(TOOLTIP_SIZE, 400),
          boxPadding: 4,
          callbacks: {
            title: (items: TooltipItem<ChartKind>[]) => {
              const index = items.at(0)?.dataIndex;
              return index === undefined ? '' : (spec.labels.at(index) ?? '');
            },
            label: (item: TooltipItem<ChartKind>) =>
              tooltipLabel(item.datasetIndex, item.dataIndex),
            footer: (items: TooltipItem<ChartKind>[]) => {
              const index = items.at(0)?.dataIndex;
              return index === undefined || spec.tooltipFooter === undefined
                ? []
                : [...spec.tooltipFooter(index)];
            },
          },
        },
      },
    },
  };
}
