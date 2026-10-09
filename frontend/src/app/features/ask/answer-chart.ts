import { AskOut, ColumnType, JsonValue } from '../../core/api/models';
import { ChartSpec, shortenLabel } from '../../shared/chart/chart-config';
import {
  formatCompactNumber,
  formatDecimal,
  formatMonth,
  formatUtcDate,
  formatUtcDateTime,
} from '../../shared/format/format';

/** More bars than this cannot be read or labelled; the table shows them instead. */
export const MAX_BARS = 50;
/** A line needs two points to show a direction. */
export const MIN_LINE_POINTS = 2;

const BAR_LABEL_TYPES: ReadonlySet<ColumnType> = new Set(['string', 'date', 'datetime']);
const LINE_LABEL_TYPES: ReadonlySet<ColumnType> = new Set(['date', 'datetime']);
const BAR_HEIGHT = 28;
const AXIS_HEIGHT = 40;
const MIN_BARS_HEIGHT = 4;
const PLOT_HEIGHT = 280;

/** What an answer's result needs for a chart: the suggestion and the data. */
export type ChartInput = Pick<AskOut, 'chart' | 'columns' | 'rows' | 'truncated'>;

export interface AnswerChart {
  spec: ChartSpec;
  /** Canvas height in pixels; horizontal bars grow with their count. */
  height: number;
}

interface Point {
  label: string;
  /** The exact value from the API, for the tooltip. */
  value: string | number;
}

/**
 * The chart for an answer, or null when there should be none. A chart is
 * drawn only when the model suggested one and the result's shape fits it:
 *
 * - exactly two columns, one of them a number;
 * - for a bar chart, the other column is text or a date, with 1 to
 *   {@link MAX_BARS} rows;
 * - for a line chart, the other column is a date, with at least
 *   {@link MIN_LINE_POINTS} rows (sorted by date here, whatever the SQL did);
 * - every label is present and every value is a finite number;
 * - the result is complete: a truncated series would mislead.
 *
 * Otherwise the receipt shows only the table, which it always shows anyway.
 */
export function answerChart(answer: ChartInput): AnswerChart | null {
  const { chart, columns, rows, truncated } = answer;
  if (chart === 'none' || truncated || columns.length !== 2) {
    return null;
  }
  const valueIndex = columns.findIndex((column) => column.type === 'number');
  if (valueIndex === -1) {
    return null;
  }
  const labelIndex = 1 - valueIndex;
  const labelColumn = columns[labelIndex];
  const valueColumn = columns[valueIndex];
  const labelTypes = chart === 'line' ? LINE_LABEL_TYPES : BAR_LABEL_TYPES;
  if (!labelTypes.has(labelColumn.type)) {
    return null;
  }
  const points = toPoints(rows, labelIndex, valueIndex);
  if (points === null) {
    return null;
  }
  if (chart === 'bar' && (points.length === 0 || points.length > MAX_BARS)) {
    return null;
  }
  if (chart === 'line') {
    if (points.length < MIN_LINE_POINTS) {
      return null;
    }
    // ISO 8601 dates and UTC instants sort by their text.
    points.sort((a, b) => a.label.localeCompare(b.label));
  }

  const horizontal = chart === 'bar' && labelColumn.type === 'string';
  const formatPointLabel = labelFormatter(labelColumn.type, points);
  const spec: ChartSpec = {
    kind: chart,
    horizontal,
    labels: points.map((point) => formatPointLabel(point.label)),
    series: [
      { label: valueColumn.name, values: points.map((point) => Number(point.value)), color: 1 },
    ],
    formatTick: formatCompactNumber,
    ...(horizontal ? { formatLabel: (label: string) => shortenLabel(label) } : {}),
    tooltipLabel: (_series, index) => {
      const point = points.at(index);
      return point === undefined ? '' : `${valueColumn.name}: ${formatDecimal(point.value)}`;
    },
  };
  const height = horizontal
    ? Math.max(points.length, MIN_BARS_HEIGHT) * BAR_HEIGHT + AXIS_HEIGHT
    : PLOT_HEIGHT;
  return { spec, height };
}

function toPoints(
  rows: readonly (readonly JsonValue[])[],
  labelIndex: number,
  valueIndex: number,
): Point[] | null {
  const points: Point[] = [];
  for (const row of rows) {
    const label = row[labelIndex];
    const value = row[valueIndex];
    if (typeof label !== 'string' || !isFiniteNumber(value)) {
      return null;
    }
    points.push({ label, value });
  }
  return points;
}

function isFiniteNumber(value: JsonValue | undefined): value is string | number {
  return (
    (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) &&
    Number.isFinite(Number(value))
  );
}

/** Dates that are all first days of a month read as months: `"Sep 2026"`. */
function labelFormatter(type: ColumnType, points: readonly Point[]): (label: string) => string {
  if (type === 'date') {
    return points.every((point) => point.label.endsWith('-01')) ? formatMonth : formatUtcDate;
  }
  if (type === 'datetime') {
    return formatUtcDateTime;
  }
  return (label) => label;
}
