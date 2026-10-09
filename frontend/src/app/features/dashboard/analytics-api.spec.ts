import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Observable } from 'rxjs';

import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';
import { ANALYTICS_URL, AnalyticsApi } from './analytics-api';
import {
  cohortsOut,
  productRankingOut,
  revenueMonthlyOut,
  summaryOut,
  topCustomersOut,
} from './testing';

describe('AnalyticsApi', () => {
  let api: AnalyticsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(AnalyticsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  const cases: [string, (api: AnalyticsApi) => Observable<unknown>, string, object][] = [
    ['summary', (a) => a.summary({ days: 7 }), 'summary?days=7', summaryOut()],
    [
      'monthly revenue',
      (a) => a.revenueMonthly({ months: 24 }),
      'revenue-monthly?months=24',
      revenueMonthlyOut(),
    ],
    [
      'top customers',
      (a) => a.topCustomers({ country: 'DE', limit: 10, days: 365 }),
      'top-customers?country=DE&limit=10&days=365',
      topCustomersOut(),
    ],
    [
      'products',
      (a) => a.products({ category: 'Home & Kitchen', limit: 10 }),
      'products?category=Home%20%26%20Kitchen&limit=10',
      productRankingOut(),
    ],
    ['cohorts', (a) => a.cohorts({ months: 12 }), 'cohorts?months=12', cohortsOut()],
  ];

  it.each(cases)('gets %s with the query and no toast on failure', (_, call, url, body) => {
    let received: unknown;
    call(api).subscribe((value) => (received = value));

    const request = http.expectOne((r) => r.urlWithParams === `${ANALYTICS_URL}/${url}`);
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(body);
    expect(received).toEqual(body);
  });

  it('leaves absent filters out of the query string', () => {
    api.topCustomers({ limit: 1, days: 365 }).subscribe();
    http.expectOne(`${ANALYTICS_URL}/top-customers?limit=1&days=365`).flush(topCustomersOut([]));
  });
});
