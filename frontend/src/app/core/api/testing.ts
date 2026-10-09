import { TestRequest } from '@angular/common/http/testing';

import { MetaOut } from './models';

/** Builders for API test data shared by several features. */
export function metaOut(overrides: Partial<MetaOut> = {}): MetaOut {
  return {
    countries: ['DE', 'GB', 'US'],
    statuses: ['paid', 'refunded', 'cancelled'],
    channels: ['web', 'mobile', 'marketplace'],
    categories: ['Books', 'Electronics'],
    first_order_date: '2023-10-08',
    last_order_date: '2026-10-07',
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
