import { OrderChannel, OrderStatus } from '../../core/api/models';
import { LOCALE } from '../../shared/format/format';

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

const regions = new Intl.DisplayNames([LOCALE], { type: 'region' });

/** "DE" becomes "Germany"; a code the browser does not know stays as it is. */
export function countryName(code: string): string {
  return regions.of(code) ?? code;
}
