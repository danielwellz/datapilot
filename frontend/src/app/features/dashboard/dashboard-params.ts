import { ParamMap, Params } from '@angular/router';

/** The periods the KPI row offers, in whole UTC days ending yesterday. */
export const PERIOD_DAYS = [7, 30, 90] as const;
export type PeriodDays = (typeof PERIOD_DAYS)[number];

/**
 * The dashboard's selectors. The URL holds them, so a view can be shared and
 * survives a reload; defaults stay out of it. Parameter names are the API's.
 */
export interface DashboardParams {
  /** The KPI period only; the rankings and charts state their own. */
  readonly days: PeriodDays;
  /** Top customers of one country; null shows the best customer of each. */
  readonly country: string | null;
  /** Product ranking within one category; null ranks every product. */
  readonly category: string | null;
}

export const DEFAULT_PARAMS: DashboardParams = { days: 30, country: null, category: null };

const COUNTRY_PATTERN = /^[A-Za-z]{2}$/;
/** The backend's limit on a category name. */
const CATEGORY_MAX_LENGTH = 50;

/**
 * Reads the selectors from a URL, dropping values the API would refuse, so
 * a hand-edited link shows the dashboard rather than a 422.
 */
export function paramsFromQuery(query: ParamMap): DashboardParams {
  const days = Number(query.get('days'));
  const country = query.get('country');
  const category = query.get('category')?.trim() ?? '';
  return {
    days: PERIOD_DAYS.find((period) => period === days) ?? DEFAULT_PARAMS.days,
    country: country !== null && COUNTRY_PATTERN.test(country) ? country.toUpperCase() : null,
    category: category.length > 0 && category.length <= CATEGORY_MAX_LENGTH ? category : null,
  };
}

/**
 * Query parameters for the router: a default is `null`, which removes it
 * from the URL when merged, so `/dashboard` stays clean.
 */
export function paramsToQuery(params: DashboardParams): Params {
  return {
    days: params.days === DEFAULT_PARAMS.days ? null : params.days,
    country: params.country,
    category: params.category,
  };
}
