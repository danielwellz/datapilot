import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { failWith } from '../../core/api/testing';
import { ANALYTICS_URL } from './analytics-api';
import { DashboardStore } from './dashboard.store';
import {
  cohortsOut,
  productRankingOut,
  revenueMonthlyOut,
  summaryOut,
  topCustomer,
  topCustomersOut,
} from './testing';

describe('DashboardStore', () => {
  let store: DashboardStore;
  let http: HttpTestingController;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), DashboardStore],
    });
    store = TestBed.inject(DashboardStore);
    http = TestBed.inject(HttpTestingController);
    await settle();
  });

  afterEach(() => {
    http.verify();
  });

  /** Open requests to one endpoint; a cancelled request stays listed, so it is left out. */
  function pending(path: string): TestRequest[] {
    return http
      .match((request) => request.url === `${ANALYTICS_URL}/${path}`)
      .filter((request) => !request.cancelled);
  }

  /** Runs effects, then lets resources take in what was flushed (they resolve a promise). */
  async function settle(): Promise<void> {
    TestBed.tick();
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }

  function only(path: string): TestRequest {
    const requests = pending(path);
    expect(requests).toHaveLength(1);
    return requests[0];
  }

  async function answerAll(): Promise<void> {
    only('summary').flush(summaryOut());
    only('revenue-monthly').flush(revenueMonthlyOut());
    only('top-customers').flush(topCustomersOut());
    only('products').flush(productRankingOut());
    only('cohorts').flush(cohortsOut());
    await settle();
  }

  it('starts all five requests at once, before any of them answers', () => {
    const urls = http
      .match((request) => request.url.startsWith(ANALYTICS_URL))
      .map((request) => request.request.urlWithParams.slice(ANALYTICS_URL.length + 1));

    expect(urls.sort()).toEqual([
      'cohorts?months=12',
      'products?limit=10&days=365',
      'revenue-monthly?months=24',
      'summary?days=30',
      'top-customers?limit=1&days=365',
    ]);
    expect(store.summary.status()).toBe('loading');
    expect(store.cohorts.status()).toBe('loading');
  });

  it('holds each answer in its own panel', async () => {
    await answerAll();

    expect(store.summary.value()).toEqual(summaryOut());
    expect(store.revenue.value()).toEqual(revenueMonthlyOut());
    expect(store.topCustomers.value()).toEqual(topCustomersOut());
    expect(store.products.value()).toEqual(productRankingOut());
    expect(store.cohorts.value()).toEqual(cohortsOut());
    expect(store.summary.status()).toBe('loaded');
    expect(store.summary.stale()).toBe(false);
  });

  it('asks for the top ten of one country once a country is chosen', async () => {
    await answerAll();

    store.params.set({ days: 30, country: 'DE', category: null });
    await settle();

    expect(only('top-customers').request.urlWithParams).toBe(
      `${ANALYTICS_URL}/top-customers?country=DE&limit=10&days=365`,
    );
    http
      .match(() => true)
      .forEach((request) => {
        request.flush(topCustomersOut());
      });
  });

  it('ranks products within a chosen category', async () => {
    await answerAll();

    store.params.set({ days: 30, country: null, category: 'Books' });
    await settle();

    const request = only('products');
    expect(request.request.urlWithParams).toBe(
      `${ANALYTICS_URL}/products?limit=10&days=365&category=Books`,
    );
    request.flush(productRankingOut());
  });

  it('reloads only the KPIs when the period changes', async () => {
    await answerAll();

    store.params.set({ days: 7, country: null, category: null });
    await settle();

    const requests = http.match(() => true).filter((request) => !request.cancelled);
    expect(requests.map((request) => request.request.urlWithParams)).toEqual([
      `${ANALYTICS_URL}/summary?days=7`,
    ]);
    requests[0]?.flush(summaryOut());
  });

  it('cancels the KPI request in flight when the period changes again', async () => {
    store.params.set({ days: 7, country: null, category: null });
    await settle();
    const first = only('summary');
    expect(first.request.urlWithParams).toBe(`${ANALYTICS_URL}/summary?days=7`);

    store.params.set({ days: 90, country: null, category: null });
    await settle();

    expect(first.cancelled).toBe(true);
    only('summary').flush(summaryOut());
    await settle();
    expect(store.summary.value()).toEqual(summaryOut());
    http
      .match(() => true)
      .forEach((request) => {
        request.flush({ items: [] });
      });
  });

  it('keeps the previous answer on screen, marked stale, while new parameters load', async () => {
    await answerAll();
    // Read, as the template does once the answer is on screen.
    expect(store.topCustomers.value()).toEqual(topCustomersOut());

    store.params.set({ days: 30, country: 'GB', category: null });
    await settle();

    expect(store.topCustomers.status()).toBe('loading');
    expect(store.topCustomers.stale()).toBe(true);
    expect(store.topCustomers.value()).toEqual(topCustomersOut());

    const british = topCustomersOut([topCustomer({ country: 'GB' })]);
    only('top-customers').flush(british);
    await settle();

    expect(store.topCustomers.stale()).toBe(false);
    expect(store.topCustomers.value()).toEqual(british);
  });

  it('fails one panel with the error and request id and leaves the others working', async () => {
    failWith(only('cohorts'), 500, 'internal_error');
    only('summary').flush(summaryOut());
    only('revenue-monthly').flush(revenueMonthlyOut());
    only('top-customers').flush(topCustomersOut());
    only('products').flush(productRankingOut());
    await settle();

    expect(store.cohorts.status()).toBe('failed');
    expect(store.cohorts.value()).toBeUndefined();
    expect(store.cohorts.error()).toMatchObject({ code: 'internal_error', requestId: 'req-1' });
    expect(store.summary.status()).toBe('loaded');
    expect(store.summary.error()).toBeNull();
  });

  it('clears the previous answer when new parameters fail', async () => {
    await answerAll();
    expect(store.summary.value()).toEqual(summaryOut());

    store.params.set({ days: 90, country: null, category: null });
    await settle();
    failWith(only('summary'), 503, 'service_unavailable');
    await settle();

    expect(store.summary.status()).toBe('failed');
    expect(store.summary.value()).toBeUndefined();
    expect(store.summary.stale()).toBe(false);
  });

  it('asks again with the same parameters on retry', async () => {
    await answerAll();
    store.params.set({ days: 7, country: null, category: null });
    await settle();
    failWith(only('summary'), 500, 'internal_error');
    await settle();

    store.summary.retry();
    await settle();

    expect(store.summary.status()).toBe('loading');
    only('summary').flush(summaryOut());
    await settle();
    expect(store.summary.status()).toBe('loaded');
    expect(store.summary.error()).toBeNull();
    expect(store.summary.value()).toEqual(summaryOut());
  });
});
