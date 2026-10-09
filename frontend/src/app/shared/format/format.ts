/**
 * Number and date formatting shared by every screen, so the same value always
 * reads the same way. Amounts are US dollars (docs/design.md), and times are
 * shown in UTC because the API's date filters are UTC days.
 */

export const LOCALE = 'en-US';
export const CURRENCY = 'USD';

/** U+2212, the minus sign the design asks for in place of a hyphen. */
const MINUS = '−';

const money = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: CURRENCY });
const dateTime = new Intl.DateTimeFormat(LOCALE, {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
  hourCycle: 'h23',
});
const dateOnly = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium', timeZone: 'UTC' });
const monthOnly = new Intl.DateTimeFormat(LOCALE, {
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});
const dayRange = new Intl.DateTimeFormat(LOCALE, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
});
const count = new Intl.NumberFormat(LOCALE);
const compactMoney = new Intl.NumberFormat(LOCALE, {
  style: 'currency',
  currency: CURRENCY,
  notation: 'compact',
  maximumFractionDigits: 1,
});
const seconds = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 });
const relative = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' });
const regions = new Intl.DisplayNames([LOCALE], { type: 'region' });

export interface MoneyParts {
  sign: string;
  unit: string;
  figure: string;
}

/**
 * An API money string split into sign, currency symbol and figure, so the
 * symbol can be shown in a quieter color. The string is formatted as it is:
 * converting it to a Number first could change the cents of large amounts.
 */
export function moneyParts(amount: string): MoneyParts {
  const parts: MoneyParts = { sign: '', unit: '', figure: '' };
  for (const part of money.formatToParts(amount as `${number}`)) {
    if (part.type === 'minusSign') {
      parts.sign = MINUS;
    } else if (part.type === 'currency') {
      parts.unit = part.value;
    } else if (part.type !== 'literal') {
      parts.figure += part.value;
    }
  }
  return parts;
}

/** `"-1234.5"` becomes `"−$1,234.50"`. */
export function formatMoney(amount: string): string {
  const { sign, unit, figure } = moneyParts(amount);
  return `${sign}${unit}${figure}`;
}

/** `"2026-03-01T23:30:00Z"` becomes `"Mar 1, 2026, 23:30"`, in UTC. */
export function formatUtcDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

/** A timestamp or a `YYYY-MM-DD` day, as its UTC calendar day: `"Mar 1, 2026"`. */
export function formatUtcDate(isoOrDay: string): string {
  return dateOnly.format(new Date(isoOrDay));
}

/** `"2026-09-01"` becomes `"Sep 2026"`. */
export function formatMonth(day: string): string {
  return monthOnly.format(new Date(day));
}

/** Two UTC days as one range: `"Sep 8 – Oct 7, 2026"`, the year written once when shared. */
export function formatDayRange(start: string, end: string): string {
  return dayRange.formatRange(new Date(start), new Date(end));
}

/** `69500` becomes `"69,500"`. */
export function formatCount(value: number): string {
  return withMinus(count.format(value));
}

/** How long something took: `"214 ms"` below a second, `"2.4 s"` from one on. */
export function formatDuration(milliseconds: number): string {
  const rounded = Math.round(milliseconds);
  return rounded < 1000 ? `${String(rounded)} ms` : `${seconds.format(rounded / 1000)} s`;
}

/** An amount for a chart axis, where the exact cents would be noise: `"$7.5M"`. */
export function formatCompactMoney(amount: number): string {
  return withMinus(compactMoney.format(amount));
}

const percentFormats = new Map<string, Intl.NumberFormat>();

function percentFormat(digits: number, signed: boolean): Intl.NumberFormat {
  const key = `${String(digits)}:${String(signed)}`;
  let format = percentFormats.get(key);
  if (format === undefined) {
    format = new Intl.NumberFormat(LOCALE, {
      style: 'percent',
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      // A change that rounds to zero is written without a sign.
      signDisplay: signed ? 'exceptZero' : 'auto',
    });
    percentFormats.set(key, format);
  }
  return format;
}

/** A fraction as a percentage: `0.1234` becomes `"12.3%"`. */
export function formatPercent(ratio: number, digits = 1): string {
  return withMinus(percentFormat(digits, false).format(ratio));
}

/** Which way a value moved, as its rounded, written change shows it. */
export type Direction = 'up' | 'down' | 'flat';

/**
 * Whether a change is good news. Each metric says which direction is good:
 * more revenue is, a higher refund rate is not.
 */
export type Sentiment = 'favorable' | 'unfavorable' | 'neutral';

export interface ChangeText {
  /** Always signed when not zero: `"+7.3%"`, `"−0.7%"`, `"0.0%"`. */
  text: string;
  direction: Direction;
  sentiment: Sentiment;
}

/**
 * A relative change as signed text, with its direction and whether it is
 * favorable for a metric where `good` is the desirable direction. Direction
 * and sentiment follow the rounded text, so "0.0%" is never colored.
 */
export function formatChange(change: number, good: 'up' | 'down' = 'up'): ChangeText {
  const parts = percentFormat(1, true).formatToParts(change);
  let direction: Direction = 'flat';
  if (parts.some((part) => part.type === 'plusSign')) direction = 'up';
  if (parts.some((part) => part.type === 'minusSign')) direction = 'down';
  const sentiment: Sentiment =
    direction === 'flat' ? 'neutral' : direction === good ? 'favorable' : 'unfavorable';
  const text = withMinus(parts.map((part) => part.value).join(''));
  return { text, direction, sentiment };
}

/** Replaces the hyphen-minus Intl writes with the true minus sign. */
function withMinus(text: string): string {
  return text.replace('-', MINUS);
}

const UNITS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 60 * 60],
  ['month', 30 * 24 * 60 * 60],
  ['day', 24 * 60 * 60],
  ['hour', 60 * 60],
  ['minute', 60],
];

/** How long ago a timestamp was, in its largest whole unit: "3 days ago", "yesterday". */
export function formatRelative(iso: string, now: Date): string {
  // A timestamp slightly ahead of this machine's clock still reads as now.
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  for (const [unit, size] of UNITS) {
    if (seconds >= size) {
      return relative.format(-Math.floor(seconds / size), unit);
    }
  }
  return 'just now';
}

/** "DE" becomes "Germany"; a code the browser does not know stays as it is. */
export function countryName(code: string): string {
  return regions.of(code) ?? code;
}
