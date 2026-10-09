import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';
import { ORDERS_URL, OrdersApi, toHttpParams } from './orders-api';
import { orderOut, orderPage } from './testing';

describe('OrdersApi', () => {
  let api: OrdersApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(OrdersApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('lists orders with the query in the query string and no toast on failure', () => {
    let received: unknown;
    api.list({ status: ['paid'], limit: 50 }).subscribe((page) => (received = page));

    const request = http.expectOne((r) => r.url === ORDERS_URL);
    expect(request.request.urlWithParams).toBe(`${ORDERS_URL}?status=paid&limit=50`);
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(orderPage([1]));
    expect(received).toEqual(orderPage([1]));
  });

  it('gets one order by id', () => {
    let received: unknown;
    api.get(42).subscribe((order) => (received = order));

    const request = http.expectOne(`${ORDERS_URL}/42`);
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(orderOut());
    expect(received).toEqual(orderOut());
  });

  describe('toHttpParams', () => {
    it('repeats a key for each status and keeps the order of fields', () => {
      const params = toHttpParams({
        status: ['paid', 'refunded'],
        country: 'DE',
        customer_id: 7,
        min_total: '10.00',
        cursor: 'abc',
      });
      expect(params.toString()).toBe(
        'status=paid&status=refunded&country=DE&customer_id=7&min_total=10.00&cursor=abc',
      );
    });

    it('leaves out absent fields and empty lists', () => {
      expect(toHttpParams({ status: [], country: undefined }).toString()).toBe('');
    });
  });
});
