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
