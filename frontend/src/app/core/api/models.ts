/**
 * Request and response bodies of the DataPilot API. Each interface mirrors a
 * backend Pydantic schema of the same name field for field, so JSON keys stay
 * snake_case. Timestamps are ISO 8601 UTC strings.
 */

/** A JSON value, as the backend's `JsonValue`. */
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface UserOut {
  id: number;
  email: string;
  full_name: string;
  created_at: string;
}

export interface UserCreate {
  email: string;
  full_name: string;
  password: string;
}

export interface LoginIn {
  email: string;
  password: string;
}

export interface SessionOut {
  access_token: string;
  token_type: 'Bearer';
  /** Seconds until the access token expires. */
  expires_in: number;
  user: UserOut;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: Record<string, JsonValue>[];
  request_id: string;
}

export interface ErrorOut {
  error: ErrorBody;
}

export const ORDER_STATUSES = ['paid', 'refunded', 'cancelled'] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const ORDER_CHANNELS = ['web', 'mobile', 'marketplace'] as const;
export type OrderChannel = (typeof ORDER_CHANNELS)[number];

/** Both sorts are descending, with ties broken by id. */
export const ORDER_SORTS = ['created_at', 'total'] as const;
export type OrderSort = (typeof ORDER_SORTS)[number];

export interface MetaOut {
  /** ISO 3166-1 alpha-2 codes of customer countries. */
  countries: string[];
  statuses: OrderStatus[];
  channels: OrderChannel[];
  categories: string[];
  /** UTC date (`YYYY-MM-DD`) of the oldest order; null when there are none. */
  first_order_date: string | null;
  last_order_date: string | null;
}

/**
 * The query string of `GET /api/orders`. Absent fields are not sent. Money
 * bounds are decimal strings and dates are UTC days (`YYYY-MM-DD`), both
 * inclusive.
 */
export interface OrderListQuery {
  status?: readonly OrderStatus[];
  country?: string;
  customer_id?: number;
  channel?: OrderChannel;
  date_from?: string;
  date_to?: string;
  min_total?: string;
  max_total?: string;
  sort?: OrderSort;
  limit?: number;
  cursor?: string;
}

export interface OrderCustomerOut {
  id: number;
  name: string;
  country: string;
}

export interface OrderSummaryOut {
  id: number;
  status: OrderStatus;
  channel: OrderChannel;
  /** A decimal string, such as `"1234.50"`. */
  total: string;
  created_at: string;
  customer: OrderCustomerOut;
}

export interface OrderPageOut {
  items: OrderSummaryOut[];
  /** Pass as `cursor` with the same filters for the next page; null on the last page. */
  next_cursor: string | null;
}

export interface CustomerOut {
  id: number;
  name: string;
  email: string;
  country: string;
  signed_up_at: string;
}

export interface OrderItemProductOut {
  id: number;
  name: string;
  category: string;
}

export interface OrderItemOut {
  product: OrderItemProductOut;
  quantity: number;
  unit_price: string;
  line_total: string;
}

export interface OrderOut {
  id: number;
  status: OrderStatus;
  channel: OrderChannel;
  total: string;
  created_at: string;
  customer: CustomerOut;
  items: OrderItemOut[];
}

/**
 * A relative change against the previous period as a JSON number: 0.25 is
 * +25%. Null when the previous value is zero or unknown.
 */
export type Change = number | null;

/** `GET /api/analytics/summary`. */
export interface SummaryQuery {
  /** Whole UTC days ending yesterday, 1 to 365. */
  days?: number;
}

/** `GET /api/analytics/revenue-monthly`. */
export interface RevenueMonthlyQuery {
  /** Complete UTC months ending last month, 1 to 36. */
  months?: number;
}

/** `GET /api/analytics/top-customers`. */
export interface TopCustomersQuery {
  /** Every country when left out. */
  country?: string;
  /** The worst rank returned in each country; ties can return more rows. */
  limit?: number;
  days?: number;
}

/** `GET /api/analytics/products`. */
export interface ProductRankingQuery {
  /** Every category when left out. */
  category?: string;
  /** The worst rank returned; ties can return more rows. */
  limit?: number;
  days?: number;
}

/** `GET /api/analytics/cohorts`. */
export interface CohortsQuery {
  /** Monthly signup cohorts, the newest from last month, 1 to 24. */
  months?: number;
}

export interface PeriodOut {
  /** First UTC day of the period (`YYYY-MM-DD`). */
  start_date: string;
  /** Last UTC day of the period, included. */
  end_date: string;
}

export interface MoneyMetricOut {
  /** Null only for an average over no orders. */
  current: string | null;
  previous: string | null;
  change: Change;
}

export interface CountMetricOut {
  current: number;
  previous: number;
  change: Change;
}

export interface RateMetricOut {
  /** A fraction: 0.1234 is 12.34%. Null when the period has no orders. */
  current: number | null;
  previous: number | null;
  change: Change;
}

export interface SummaryOut {
  period: PeriodOut;
  previous_period: PeriodOut;
  /** Total of paid orders. */
  revenue: MoneyMetricOut;
  /** Paid orders. */
  orders: CountMetricOut;
  average_order_value: MoneyMetricOut;
  /** Customers with at least one paid order. */
  active_customers: CountMetricOut;
  /** Refunded orders divided by all orders placed. */
  refund_rate: RateMetricOut;
}

export interface MonthlyRevenueOut {
  /** First day of the month (`YYYY-MM-DD`). */
  month: string;
  revenue: string;
  /** Paid orders. */
  orders: number;
  revenue_change_mom: Change;
  revenue_change_yoy: Change;
  /** Average revenue of this month and the two before it. */
  revenue_moving_average_3m: string;
}

/** Oldest month first, every month present. */
export interface RevenueMonthlyOut {
  items: MonthlyRevenueOut[];
}

export interface TopCustomerOut {
  country: string;
  /** Rank by revenue within the country; ties share a rank. */
  rank: number;
  customer_id: number;
  name: string;
  revenue: string;
  /** Paid orders in the period. */
  orders: number;
  last_order_at: string;
}

/** By country, then rank. */
export interface TopCustomersOut {
  items: TopCustomerOut[];
}

export interface ProductRankOut {
  /** Rank by revenue; ties share a rank. */
  rank: number;
  product_id: number;
  name: string;
  category: string;
  revenue: string;
  /** Units sold in paid orders. */
  units: number;
  /** Share of its category's revenue; null if the category earned nothing. */
  category_share: number | null;
}

/** Best first. */
export interface ProductRankingOut {
  items: ProductRankOut[];
}

export interface CohortMonthOut {
  /** 0 is the signup month itself. */
  months_since_signup: number;
  active_customers: number;
  retention_rate: number;
}

export interface CohortOut {
  /** First day of the signup month (`YYYY-MM-DD`). */
  cohort_month: string;
  /** Size of the cohort. */
  customers: number;
  /** One entry per month from signup to last month. */
  retention: CohortMonthOut[];
}

/** Oldest cohort first; months without signups have no cohort. */
export interface CohortsOut {
  items: CohortOut[];
}
