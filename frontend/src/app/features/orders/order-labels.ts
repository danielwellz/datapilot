import { OrderChannel, OrderStatus } from '../../core/api/models';

export const STATUS_LABELS: Readonly<Record<OrderStatus, string>> = {
  paid: 'Paid',
  refunded: 'Refunded',
  cancelled: 'Cancelled',
};

export const CHANNEL_LABELS: Readonly<Record<OrderChannel, string>> = {
  web: 'Web',
  mobile: 'Mobile app',
  marketplace: 'Marketplace',
};
