/** The design tokens a chart is drawn with, resolved for the current theme. */
export interface ChartTokens {
  /** The categorical palette, `--chart-1` to `--chart-5`. */
  palette: readonly string[];
  ink: string;
  graphite: string;
  rule: string;
  sheet: string;
  fontFamily: string;
}

export const PALETTE_SIZE = 5;

/**
 * Reads the chart tokens from the CSS custom properties that apply to an
 * element. A canvas cannot use `var()`, so the values are resolved here and
 * read again whenever the theme changes.
 */
export function readChartTokens(element: Element): ChartTokens {
  const style = getComputedStyle(element);
  const read = (name: string): string => style.getPropertyValue(name).trim();
  return {
    palette: Array.from({ length: PALETTE_SIZE }, (_, index) =>
      read(`--chart-${String(index + 1)}`),
    ),
    ink: read('--color-ink'),
    graphite: read('--color-graphite'),
    rule: read('--color-rule'),
    sheet: read('--color-sheet'),
    fontFamily: read('--font-sans'),
  };
}
