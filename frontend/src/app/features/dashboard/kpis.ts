import { SummaryOut } from '../../core/api/models';
import { formatCount, formatMoney, formatPercent } from '../../shared/format/format';

/** A figure as the KPI row shows it: money keeps its quieter unit. */
export type Figure = { kind: 'money'; amount: string } | { kind: 'text'; text: string };

export interface Kpi {
  label: string;
  /** The direction that is good news; a rising refund rate is not. */
  good: 'up' | 'down';
  figure: Figure;
  /** The previous period's value as plain text; null when there is none. */
  previous: string | null;
  change: number | null;
}

export interface KpiDefinition {
  label: string;
  good: 'up' | 'down';
  read: (summary: SummaryOut) => Omit<Kpi, 'label' | 'good'>;
}

const NO_ORDERS = 'No paid orders';

function money(amount: string | null): Figure {
  return amount === null ? { kind: 'text', text: NO_ORDERS } : { kind: 'money', amount };
}

/** The KPI row's metrics, in the order they are shown. */
export const KPI_DEFINITIONS: readonly KpiDefinition[] = [
  {
    label: 'Revenue',
    good: 'up',
    read: ({ revenue }) => ({
      figure: money(revenue.current),
      previous: revenue.previous === null ? null : formatMoney(revenue.previous),
      change: revenue.change,
    }),
  },
  {
    label: 'Paid orders',
    good: 'up',
    read: ({ orders }) => ({
      figure: { kind: 'text', text: formatCount(orders.current) },
      previous: formatCount(orders.previous),
      change: orders.change,
    }),
  },
  {
    label: 'Average order value',
    good: 'up',
    read: ({ average_order_value: average }) => ({
      figure: money(average.current),
      previous: average.previous === null ? null : formatMoney(average.previous),
      change: average.change,
    }),
  },
  {
    label: 'Active customers',
    good: 'up',
    read: ({ active_customers: customers }) => ({
      figure: { kind: 'text', text: formatCount(customers.current) },
      previous: formatCount(customers.previous),
      change: customers.change,
    }),
  },
  {
    label: 'Refund rate',
    good: 'down',
    read: ({ refund_rate: rate }) => ({
      figure: {
        kind: 'text',
        text: rate.current === null ? 'No orders' : formatPercent(rate.current),
      },
      previous: rate.previous === null ? null : formatPercent(rate.previous),
      change: rate.change,
    }),
  },
];

/** The metrics of a summary, ready to show. */
export function kpisFrom(summary: SummaryOut): Kpi[] {
  return KPI_DEFINITIONS.map(({ label, good, read }) => ({ label, good, ...read(summary) }));
}
