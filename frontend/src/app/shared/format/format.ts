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
