import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { NO_FILTERS, OrderFilters } from './order-filters';
import { ORDERS_URL } from './orders-api';
import { OrdersStore, PAGE_SIZE } from './orders.store';
import { orderPage } from './testing';

const PAID: OrderFilters = { ...NO_FILTERS, statuses: ['paid'] };
const GERMANY: OrderFilters = { ...NO_FILTERS, country: 'DE' };

describe('OrdersStore', () => {
  let store: OrdersStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [OrdersStore, provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(OrdersStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  function expectList(): TestRequest {
    return http.expectOne((request) => request.url === ORDERS_URL);
  }

  function param(request: TestRequest, name: string): string | null {
    return request.request.params.get(name);
  }

  function fail(request: TestRequest, status: number, code: string): void {
    request.flush(
      { error: { code, message: `Failed with ${code}.`, details: [], request_id: 'req-1' } },
      { status, statusText: 'Error' },
    );
  }

  /** Loads a first page of `ids` for `filters` with a cursor to more. */
  function showFirstPage(filters: OrderFilters, ids: number[], cursor: string | null = 'c1') {
    store.applyFilters(filters);
    expectList().flush(orderPage(ids, cursor));
  }

  it('starts idle with no rows', () => {
    expect(store.status()).toBe('idle');
    expect(store.items()).toEqual([]);
    expect(store.isEmpty()).toBe(false);
  });

  it('loads the first page for the filters, without a cursor', () => {
    store.applyFilters(PAID);
    expect(store.status()).toBe('loading');

    const request = expectList();
    expect(param(request, 'status')).toBe('paid');
    expect(param(request, 'limit')).toBe(String(PAGE_SIZE));
    expect(param(request, 'cursor')).toBeNull();
    request.flush(orderPage([3, 2], 'c1'));

    expect(store.status()).toBe('loaded');
    expect(store.items().map((order) => order.id)).toEqual([3, 2]);
    expect(store.hasMore()).toBe(true);
    expect(store.filters()).toEqual(PAID);
  });

  it('appends the next page, sent with its cursor and the same filters', () => {
    showFirstPage(PAID, [5, 4]);

    store.loadMore();
    expect(store.status()).toBe('loading-more');
    const request = expectList();
    expect(param(request, 'cursor')).toBe('c1');
    expect(param(request, 'status')).toBe('paid');
    request.flush(orderPage([3, 2], null));

    expect(store.items().map((order) => order.id)).toEqual([5, 4, 3, 2]);
    expect(store.hasMore()).toBe(false);
  });

  it('resets the cursor and replaces the rows when the filters change', () => {
    showFirstPage(PAID, [5, 4]);

    store.applyFilters(GERMANY);
    expect(store.hasMore()).toBe(false);
    expect(store.isStale()).toBe(true);
    const request = expectList();
    expect(param(request, 'cursor')).toBeNull();
    expect(param(request, 'country')).toBe('DE');
    request.flush(orderPage([9], null));

    expect(store.items().map((order) => order.id)).toEqual([9]);
    expect(store.isStale()).toBe(false);
  });

  it('cancels the request in flight when the filters change, so stale rows never arrive', () => {
    store.applyFilters(PAID);
    const first = expectList();

    store.applyFilters(GERMANY);
    expect(first.cancelled).toBe(true);
    expectList().flush(orderPage([9], null));

    expect(store.items().map((order) => order.id)).toEqual([9]);
    expect(store.filters()).toEqual(GERMANY);
  });

  it('cancels a "Load more" in flight when the filters change', () => {
    showFirstPage(PAID, [5, 4]);
    store.loadMore();
    const more = expectList();

    store.applyFilters(GERMANY);
    expect(more.cancelled).toBe(true);
    expectList().flush(orderPage([9], null));

    expect(store.items().map((order) => order.id)).toEqual([9]);
  });

  it('does not reload filters that are already shown or loading', () => {
    showFirstPage(PAID, [5, 4]);
    store.applyFilters({ ...PAID });
    http.expectNone(ORDERS_URL);

    store.applyFilters(GERMANY);
    store.applyFilters({ ...GERMANY });
    expectList().flush(orderPage([9], null));
  });

  it('loads the empty first filters on the first call', () => {
    store.applyFilters(NO_FILTERS);
    expectList().flush(orderPage([], null));

    expect(store.isEmpty()).toBe(true);
  });

  it('does nothing on "Load more" at the end of the list or while a request runs', () => {
    store.loadMore();
    http.expectNone(ORDERS_URL);

    store.applyFilters(PAID);
    store.loadMore();
    expectList().flush(orderPage([5], null));

    store.loadMore();
    http.expectNone(ORDERS_URL);
  });

  it('surfaces a failed first page without rows of other filters', () => {
    showFirstPage(PAID, [5, 4]);

    store.applyFilters(GERMANY);
    fail(expectList(), 500, 'internal_error');

    expect(store.status()).toBe('failed');
    expect(store.error()?.message).toBe('Failed with internal_error.');
    expect(store.error()?.requestId).toBe('req-1');
    expect(store.items()).toEqual([]);
  });

  it('retries a failed first page with the same filters', () => {
    store.applyFilters(GERMANY);
    fail(expectList(), 503, 'unavailable');

    store.retry();
    expect(store.status()).toBe('loading');
    expect(store.error()).toBeNull();
    const request = expectList();
    expect(param(request, 'country')).toBe('DE');
    expect(param(request, 'cursor')).toBeNull();
    request.flush(orderPage([9], null));

    expect(store.status()).toBe('loaded');
  });

  it('keeps the rows when "Load more" fails, and retries the same cursor', () => {
    showFirstPage(PAID, [5, 4]);
    store.loadMore();
    expectList().error(new ProgressEvent('error'));

    expect(store.status()).toBe('more-failed');
    expect(store.error()?.isNetworkError).toBe(true);
    expect(store.items().map((order) => order.id)).toEqual([5, 4]);

    store.retry();
    expect(store.status()).toBe('loading-more');
    const request = expectList();
    expect(param(request, 'cursor')).toBe('c1');
    request.flush(orderPage([3], null));

    expect(store.items().map((order) => order.id)).toEqual([5, 4, 3]);
  });

  it('starts again from the first page when the server refuses the cursor', () => {
    showFirstPage(PAID, [5, 4]);
    store.loadMore();
    fail(expectList(), 400, 'invalid_cursor');

    expect(store.status()).toBe('loading');
    const request = expectList();
    expect(param(request, 'cursor')).toBeNull();
    expect(param(request, 'status')).toBe('paid');
    request.flush(orderPage([6, 5], 'c2'));

    expect(store.items().map((order) => order.id)).toEqual([6, 5]);
    expect(store.status()).toBe('loaded');
  });

  it('does nothing on retry when nothing failed', () => {
    store.retry();
    http.expectNone(ORDERS_URL);
    expect(store.status()).toBe('idle');
  });
});
