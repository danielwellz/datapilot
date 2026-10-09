import { ColumnType, JsonValue, ResultColumnOut } from '../../core/api/models';
import { formatDecimal, formatUtcDate, formatUtcDateTime } from '../../shared/format/format';

/** Shown for SQL NULL, so an empty cell never looks like missing data. */
export const NULL_TEXT = '—';
/** No column grows past this width; longer text wraps within it. */
const MAX_COLUMN_CH = 40;

/** A result value as text, formatted by its column's type. */
export function formatCell(value: JsonValue, type: ColumnType): string {
  if (value === null) {
    return NULL_TEXT;
  }
  if (type === 'number' && (typeof value === 'number' || typeof value === 'string')) {
    return formatDecimal(value);
  }
  if (type === 'date' && typeof value === 'string') {
    return formatUtcDate(value);
  }
  if (type === 'datetime' && typeof value === 'string') {
    return `${formatUtcDateTime(value)} UTC`;
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export interface FormattedColumn {
  name: string;
  numeric: boolean;
  /** The widest value's length in `ch`, so columns keep their width while rows scroll by. */
  widthCh: number;
}

export interface FormattedResult {
  columns: FormattedColumn[];
  rows: string[][];
}

/** Formats every cell once, and measures each column, so scrolling only moves text. */
export function formatResult(
  columns: readonly ResultColumnOut[],
  rows: readonly (readonly JsonValue[])[],
): FormattedResult {
  const formatted = rows.map((row) =>
    columns.map((column, index) => formatCell(row[index] ?? null, column.type)),
  );
  return {
    columns: columns.map((column, index) => ({
      name: column.name,
      numeric: column.type === 'number',
      widthCh: Math.min(
        MAX_COLUMN_CH,
        Math.max(column.name.length, ...formatted.map((row) => row[index]?.length ?? 0)),
      ),
    })),
    rows: formatted,
  };
}
