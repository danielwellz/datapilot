import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { ANALYTICS_URL } from './analytics-api';
import { DashboardPage } from './dashboard-page';
import {
  cohortsOut,
  productRankingOut,
  revenueMonthlyOut,
  summaryOut,
  topCustomersOut,
} from './testing';

describe('DashboardPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'dashboard', component: DashboardPage }]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  async function open(url: string): Promise<void> {
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    const element = harness.routeNativeElement;
    if (element === null) {
      throw new Error(`Nothing rendered at ${url}`);
    }
    page = element;
    await settle();
  }

  /**
   * Renders and lets resources start and take in answers. Not whenStable:
   * a resource keeps the app unstable until its request is answered.
   */
  async function settle(): Promise<void> {
    harness.detectChanges();
    await new Promise((resolve) => setTimeout(resolve));
    harness.detectChanges();
  }

  /** Answers every open analytics request, returning the paths asked for. */
  async function answerAll(): Promise<string[]> {
    const bodies: Record<string, object> = {
      summary: summaryOut(),
      'revenue-monthly': revenueMonthlyOut(),
      'top-customers': topCustomersOut(),
      products: productRankingOut(),
      cohorts: cohortsOut(),
    };
    const asked: string[] = [];
    for (const request of http.match((r) => r.url.startsWith(ANALYTICS_URL))) {
      if (request.cancelled) continue;
      const path = request.request.url.slice(ANALYTICS_URL.length + 1);
      asked.push(request.request.urlWithParams.slice(ANALYTICS_URL.length + 1));
      request.flush(bodies[path] ?? {});
    }
    await settle();
    return asked.sort();
  }

  it('loads every panel with the selectors in the URL', async () => {
    await open('/dashboard?days=7&country=de&category=Books');

    expect(await answerAll()).toEqual([
      'cohorts?months=12',
      'products?limit=10&days=365&category=Books',
      'revenue-monthly?months=24',
      'summary?days=7',
      'top-customers?country=DE&limit=10&days=365',
    ]);
    expect(page.querySelector<HTMLInputElement>('input[value="7"]')?.checked).toBe(true);
  });

  it('puts a new period in the URL, which loads it, and keeps the other selectors', async () => {
    await open('/dashboard?country=GB');
    await answerAll();

    page.querySelector<HTMLInputElement>('input[value="90"]')?.click();
    await settle();

    expect(TestBed.inject(Router).url).toBe('/dashboard?country=GB&days=90');
    expect(await answerAll()).toEqual(['summary?days=90']);
  });

  it('leaves the default period out of the URL', async () => {
    await open('/dashboard?days=7');
    await answerAll();

    page.querySelector<HTMLInputElement>('input[value="30"]')?.click();
    await settle();

    expect(TestBed.inject(Router).url).toBe('/dashboard');
    expect(await answerAll()).toEqual(['summary?days=30']);
  });
});
