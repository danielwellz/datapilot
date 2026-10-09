import {
  CohortsOut,
  ProductRankOut,
  ProductRankingOut,
  RevenueMonthlyOut,
  SummaryOut,
  TopCustomerOut,
  TopCustomersOut,
} from '../../core/api/models';

/** Builders for analytics test data, shared by the dashboard specs. */
export function summaryOut(overrides: Partial<SummaryOut> = {}): SummaryOut {
  return {
    period: { start_date: '2026-09-08', end_date: '2026-10-07' },
    previous_period: { start_date: '2026-08-09', end_date: '2026-09-07' },
    revenue: { current: '7512345.67', previous: '7000000.00', change: 0.0732 },
    orders: { current: 69_500, previous: 70_000, change: -0.0071 },
    average_order_value: { current: '108.09', previous: '100.00', change: 0.0809 },
    active_customers: { current: 21_000, previous: 21_000, change: 0 },
    refund_rate: { current: 0.031, previous: 0.029, change: 0.069 },
    ...overrides,
  };
}

export function revenueMonthlyOut(months = 3): RevenueMonthlyOut {
  return {
    items: Array.from({ length: months }, (_, index) => ({
      month: `2026-${String(index + 1).padStart(2, '0')}-01`,
      revenue: `${String(1000 * (index + 1))}.50`,
      orders: 10 * (index + 1),
      revenue_change_mom: index === 0 ? null : 1 / index,
      revenue_change_yoy: index === 0 ? null : -0.125,
      revenue_moving_average_3m: `${String(500 * (index + 1))}.25`,
    })),
  };
}

export function topCustomer(overrides: Partial<TopCustomerOut> = {}): TopCustomerOut {
  return {
    country: 'DE',
    rank: 1,
    customer_id: 7,
    name: 'Grace Hopper',
    revenue: '12345.60',
    orders: 31,
    last_order_at: '2026-10-05T09:15:00Z',
    ...overrides,
  };
}

export function topCustomersOut(items: TopCustomerOut[] = [topCustomer()]): TopCustomersOut {
  return { items };
}

export function productRank(overrides: Partial<ProductRankOut> = {}): ProductRankOut {
  return {
    rank: 1,
    product_id: 3,
    name: 'Noise-cancelling headphones',
    category: 'Electronics',
    revenue: '98765.43',
    units: 512,
    category_share: 0.0812,
    ...overrides,
  };
}

export function productRankingOut(items: ProductRankOut[] = [productRank()]): ProductRankingOut {
  return { items };
}

/** Two cohorts: the older one has two months of history, the newer one only its signup month. */
export function cohortsOut(): CohortsOut {
  return {
    items: [
      {
        cohort_month: '2026-08-01',
        customers: 200,
        retention: [
          { months_since_signup: 0, active_customers: 80, retention_rate: 0.4 },
          { months_since_signup: 1, active_customers: 130, retention_rate: 0.65 },
        ],
      },
      {
        cohort_month: '2026-09-01',
        customers: 150,
        retention: [{ months_since_signup: 0, active_customers: 45, retention_rate: 0.3 }],
      },
    ],
  };
}
