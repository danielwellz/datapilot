import { TestRequest } from '@angular/common/http/testing';

import { OrderOut, OrderPageOut, OrderSummaryOut } from '../../core/api/models';

/** Builders for orders test data, shared by the orders specs. */
export function orderSummary(
  id: number,
  overrides: Partial<OrderSummaryOut> = {},
): OrderSummaryOut {
  return {
    id,
    status: 'paid',
    channel: 'web',
    total: '1234.50',
    created_at: '2026-10-07T14:05:00Z',
    customer: { id: 7, name: 'Grace Hopper', country: 'US' },
    ...overrides,
  };
}

export function orderPage(ids: readonly number[], nextCursor: string | null = null): OrderPageOut {
  return { items: ids.map((id) => orderSummary(id)), next_cursor: nextCursor };
}

export function orderOut(overrides: Partial<OrderOut> = {}): OrderOut {
  return {
    id: 42,
    status: 'refunded',
    channel: 'marketplace',
    total: '1059.97',
    created_at: '2026-03-01T23:30:00Z',
    customer: {
      id: 7,
      name: 'Grace Hopper',
      email: 'grace@example.com',
      country: 'DE',
      signed_up_at: '2024-01-15T08:00:00Z',
    },
    items: [
      {
        product: { id: 3, name: 'Desk lamp', category: 'Home' },
        quantity: 2,
        unit_price: '29.99',
        line_total: '59.98',
      },
      {
        product: { id: 9, name: 'Monitor', category: 'Electronics' },
        quantity: 1,
        unit_price: '999.99',
        line_total: '999.99',
      },
    ],
    ...overrides,
  };
}

/** Answers a request with the backend's error envelope. */
export function failWith(request: TestRequest, status: number, code: string): void {
  request.flush(
    { error: { code, message: `Failed with ${code}.`, details: [], request_id: 'req-1' } },
    { status, statusText: 'Error' },
  );
}
