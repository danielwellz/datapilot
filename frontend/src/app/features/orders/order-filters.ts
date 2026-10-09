import { ParamMap, Params } from '@angular/router';

import {
  ORDER_CHANNELS,
  ORDER_SORTS,
  ORDER_STATUSES,
  OrderChannel,
  OrderListQuery,
  OrderSort,
  OrderStatus,
} from '../../core/api/models';

/**
 * What the orders list is filtered and sorted by. The URL holds it, so a
 * filtered view can be shared and survives a reload. Query parameter names
 * are the API's own.
 */
export interface OrderFilters {
  /** In the order of {@link ORDER_STATUSES}, without repeats. */
  readonly statuses: readonly OrderStatus[];
  readonly country: string | null;
  readonly channel: OrderChannel | null;
  readonly customerId: number | null;
  /** First and last UTC days included, as `YYYY-MM-DD`. */
  readonly dateFrom: string | null;
  readonly dateTo: string | null;
  /** Inclusive decimal strings, as the API returns money. */
  readonly minTotal: string | null;
  readonly maxTotal: string | null;
  readonly sort: OrderSort;
}

export const DEFAULT_SORT: OrderSort = 'created_at';

export const NO_FILTERS: OrderFilters = {
  statuses: [],
  country: null,
  channel: null,
  customerId: null,
  dateFrom: null,
  dateTo: null,
  minTotal: null,
  maxTotal: null,
  sort: DEFAULT_SORT,
};

/** The backend's `numeric(12,2)`: at most ten whole digits and two decimals. */
export const TOTAL_PATTERN = /^\d{1,10}(\.\d{1,2})?$/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const COUNTRY_PATTERN = /^[A-Za-z]{2}$/;
const ID_PATTERN = /^[1-9]\d*$/;

/**
 * Reads filters from a URL, keeping only values the API accepts. Anything
 * else (an unknown status, an impossible date, an inverted range) is dropped
 * rather than sent, so a hand-edited link shows orders instead of a 422.
 */
export function filtersFromParams(params: ParamMap): OrderFilters {
  const requested = new Set(params.getAll('status'));
  const range = <T>(from: T | null, to: T | null, ordered: (a: T, b: T) => boolean) =>
    from !== null && to !== null && !ordered(from, to) ? [null, null] : [from, to];

  const [dateFrom, dateTo] = range(
    validDate(params.get('date_from')),
    validDate(params.get('date_to')),
    (from, to) => from <= to,
  );
  const [minTotal, maxTotal] = range(
    validTotal(params.get('min_total')),
    validTotal(params.get('max_total')),
    (min, max) => compareTotals(min, max) <= 0,
  );
  return {
    statuses: ORDER_STATUSES.filter((status) => requested.has(status)),
    country: validCountry(params.get('country')),
    channel: oneOf(ORDER_CHANNELS, params.get('channel')),
    customerId: validId(params.get('customer_id')),
    dateFrom,
    dateTo,
    minTotal,
    maxTotal,
    sort: oneOf(ORDER_SORTS, params.get('sort')) ?? DEFAULT_SORT,
  };
}

/** The query parameters for a URL; defaults are left out, so `/orders` stays clean. */
export function filtersToParams(filters: OrderFilters): Params {
  const params: Params = {};
  if (filters.statuses.length > 0) {
    params['status'] = [...filters.statuses];
  }
  const single: [string, string | number | null][] = [
    ['country', filters.country],
    ['channel', filters.channel],
    ['customer_id', filters.customerId],
    ['date_from', filters.dateFrom],
    ['date_to', filters.dateTo],
    ['min_total', filters.minTotal],
    ['max_total', filters.maxTotal],
    ['sort', filters.sort === DEFAULT_SORT ? null : filters.sort],
  ];
  for (const [key, value] of single) {
    if (value !== null) {
      params[key] = value;
    }
  }
  return params;
}

/** The API query for one page of the filtered list. */
export function filtersToQuery(
  filters: OrderFilters,
  limit: number,
  cursor: string | null = null,
): OrderListQuery {
  const query: OrderListQuery = { sort: filters.sort, limit };
  if (filters.statuses.length > 0) query.status = filters.statuses;
  if (filters.country !== null) query.country = filters.country;
  if (filters.channel !== null) query.channel = filters.channel;
  if (filters.customerId !== null) query.customer_id = filters.customerId;
  if (filters.dateFrom !== null) query.date_from = filters.dateFrom;
  if (filters.dateTo !== null) query.date_to = filters.dateTo;
  if (filters.minTotal !== null) query.min_total = filters.minTotal;
  if (filters.maxTotal !== null) query.max_total = filters.maxTotal;
  if (cursor !== null) query.cursor = cursor;
  return query;
}

export function sameFilters(a: OrderFilters, b: OrderFilters): boolean {
  return (
    a.statuses.length === b.statuses.length &&
    a.statuses.every((status, index) => status === b.statuses[index]) &&
    a.country === b.country &&
    a.channel === b.channel &&
    a.customerId === b.customerId &&
    a.dateFrom === b.dateFrom &&
    a.dateTo === b.dateTo &&
    a.minTotal === b.minTotal &&
    a.maxTotal === b.maxTotal &&
    a.sort === b.sort
  );
}

/** True when anything narrows the list. The sort is not a filter, so clearing keeps it. */
export function hasFilters(filters: OrderFilters): boolean {
  return !sameFilters({ ...filters, sort: DEFAULT_SORT }, NO_FILTERS);
}

/**
 * How many kinds of filter are set; a range counts once and so do the
 * statuses, as each is one control group on the filter bar.
 */
export function activeFilterCount(filters: OrderFilters): number {
  return [
    filters.statuses.length > 0,
    filters.country !== null,
    filters.channel !== null,
    filters.customerId !== null,
    filters.dateFrom !== null || filters.dateTo !== null,
    filters.minTotal !== null || filters.maxTotal !== null,
  ].filter(Boolean).length;
}

/** Orders two totals that match {@link TOTAL_PATTERN}, without passing through a float. */
export function compareTotals(a: string, b: string): number {
  return toCents(a) - toCents(b);
}

function toCents(total: string): number {
  const [whole = '0', fraction = ''] = total.split('.');
  // At most twelve digits, well inside a double's exact integer range.
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}

/** A real calendar day written as `YYYY-MM-DD`, from year 1 to 9999. */
export function validDate(value: string | null): string | null {
  const match = value === null ? null : DATE_PATTERN.exec(value);
  if (match === null) {
    return null;
  }
  const [year, month, day] = match.slice(1).map(Number) as [number, number, number];
  const date = new Date(0);
  // setUTCFullYear, unlike Date.UTC, does not map years 0 to 99 onto the 1900s.
  date.setUTCFullYear(year, month - 1, day);
  const real =
    year >= 1 &&
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day;
  return real ? value : null;
}

export function validTotal(value: string | null): string | null {
  return value !== null && TOTAL_PATTERN.test(value) ? value : null;
}

function validCountry(value: string | null): string | null {
  return value !== null && COUNTRY_PATTERN.test(value) ? value.toUpperCase() : null;
}

/** A positive whole number that a JavaScript number holds exactly, such as a database id. */
export function validId(value: string | null): number | null {
  if (value === null || !ID_PATTERN.test(value)) {
    return null;
  }
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}

function oneOf<T extends string>(allowed: readonly T[], value: string | null): T | null {
  return allowed.find((candidate) => candidate === value) ?? null;
}
