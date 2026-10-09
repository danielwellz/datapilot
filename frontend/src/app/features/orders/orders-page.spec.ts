import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { META_URL } from '../../core/api/meta.service';
import { metaOut } from '../../core/api/testing';
import { textOf } from '../../shared/forms/testing';
import { ORDERS_URL } from './orders-api';
import { OrdersPage } from './orders-page';
import { OrdersStore } from './orders.store';
import { failWith, orderPage, orderSummary } from './testing';

@Component({ template: '' })
class Blank {}

describe('OrdersPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          {
            path: 'orders',
            providers: [OrdersStore],
            children: [
              { path: '', component: OrdersPage },
              { path: ':id', component: Blank },
            ],
          },
        ]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  async function open(url = '/orders'): Promise<void> {
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    const element = harness.routeNativeElement;
    if (element === null) {
      throw new Error(`Nothing rendered at ${url}`);
    }
    page = element;
    http.expectOne(META_URL).flush(metaOut());
  }

  function expectList(): TestRequest {
    return http.expectOne((request) => request.url === ORDERS_URL);
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
  }

  function rowIds(): string[] {
    return [...page.querySelectorAll('tbody tr')].map(
      (row) => row.querySelector('a')?.textContent.trim() ?? '',
    );
  }

  function button(label: string): HTMLButtonElement {
    const match = [...page.querySelectorAll('button')].find(
      (candidate) => candidate.textContent.trim() === label,
    );
    if (match === undefined) {
      throw new Error(`No button labelled "${label}"`);
    }
    return match;
  }

  it('shows a skeleton while the first page loads', async () => {
    await open();

    expect(textOf(page, '[role="status"]')).toBe('Loading orders…');
    expect(page.querySelector('.skeleton')?.closest('[aria-hidden="true"]')).not.toBeNull();
    expectList().flush(orderPage([]));
  });

  it('loads the filters in the URL and shows the orders as a table', async () => {
    await open('/orders?status=refunded&country=DE&sort=total');

    const request = expectList();
    expect(request.request.urlWithParams).toBe(
      `${ORDERS_URL}?sort=total&limit=50&status=refunded&country=DE`,
    );
    request.flush({
      items: [
        orderSummary(42, {
          status: 'refunded',
          channel: 'mobile',
          total: '1234.5',
          created_at: '2026-03-01T23:30:00Z',
          customer: { id: 7, name: 'Grace Hopper', country: 'DE' },
        }),
      ],
      next_cursor: null,
    });
    await settle();

    const cells = [...page.querySelectorAll('tbody td')].map((cell) =>
      cell.textContent.replace(/\s+/g, ' ').trim(),
    );
    expect(cells[0]).toBe('42');
    expect(cells[1]).toMatch(/^Mar 1, 2026, 23:30 /);
    expect(cells.slice(2)).toEqual(['Grace Hopper DE', 'Mobile app', 'Refunded', '$1,234.50']);
    expect(page.querySelector('time')?.getAttribute('datetime')).toBe('2026-03-01T23:30:00Z');
    expect(page.querySelector('tbody a')?.getAttribute('href')).toBe(
      '/orders/42?status=refunded&country=DE&sort=total',
    );
    expect(page.querySelector('th[aria-sort]')?.textContent.trim()).toBe('Total');
    expect(textOf(page, 'caption')).toBe('Orders, highest total first');
    expect(textOf(page, '[role="status"]')).toBe(
      'Showing the one order that matches these filters.',
    );
  });

  it('appends the next page with "Load more" and hides it on the last page', async () => {
    await open();
    expectList().flush(orderPage([5, 4], 'c1'));
    await settle();
    expect(textOf(page, '[role="status"]')).toBe('Showing 2 orders. More match these filters.');

    button('Load 50 more').click();
    await settle();
    expect(button('Loading more orders…').disabled).toBe(true);
    const request = expectList();
    expect(request.request.params.get('cursor')).toBe('c1');
    request.flush(orderPage([3], null));
    await settle();

    expect(rowIds()).toEqual(['5', '4', '3']);
    expect(page.querySelector('.more button')).toBeNull();
    expect(textOf(page, '[role="status"]')).toBe('Showing all 3 orders.');
  });

  it('loads new filters when the URL changes, dimming the old rows until they arrive', async () => {
    await open();
    expectList().flush(orderPage([5, 4], 'c1'));
    await settle();

    await harness.navigateByUrl('/orders?channel=web');
    const table = page.querySelector('table.orders');
    expect(table?.classList).toContain('orders--stale');
    expect(table?.getAttribute('aria-busy')).toBe('true');
    expect(textOf(page, '[role="status"]')).toBe('Loading orders for the new filters…');

    const request = expectList();
    expect(request.request.params.get('channel')).toBe('web');
    expect(request.request.params.get('cursor')).toBeNull();
    request.flush(orderPage([9], null));
    await settle();

    expect(rowIds()).toEqual(['9']);
    expect(page.querySelector('table.orders')?.classList).not.toContain('orders--stale');
  });

  it('puts a filter change in the URL, replacing the history entry', async () => {
    await open('/orders?sort=total');
    expectList().flush(orderPage([1]));
    await settle();
    const router = TestBed.inject(Router);
    const navigate = vi.spyOn(router, 'navigate');

    const channel = page.querySelector<HTMLSelectElement>('#filter-channel');
    if (channel === null) {
      throw new Error('No channel filter');
    }
    channel.value = 'web';
    channel.dispatchEvent(new Event('change'));
    await settle();

    expect(router.url).toBe('/orders?channel=web&sort=total');
    expect(navigate.mock.calls[0]?.[1]).toMatchObject({ replaceUrl: true });
    expect(expectList().request.params.get('channel')).toBe('web');
  });

  it('offers to clear the filters when nothing matches, keeping the sort', async () => {
    await open('/orders?country=DK&min_total=5000&sort=total');
    expectList().flush(orderPage([]));
    await settle();

    expect(textOf(page, '[role="status"]')).toBe('No orders match these filters.');
    button('Clear filters').click();
    await settle();

    expect(TestBed.inject(Router).url).toBe('/orders?sort=total');
    expect(expectList().request.params.has('country')).toBe(false);
  });

  it('says plainly when there are no orders at all', async () => {
    await open();
    expectList().flush(orderPage([]));
    await settle();

    expect(textOf(page, '[role="status"]')).toBe('There are no orders yet.');
    expect(page.textContent).toContain('Orders appear here once the sales data is loaded.');
    expect(page.querySelector('.state button')).toBeNull();
  });

  it('explains a failed load with the request id and tries again', async () => {
    await open('/orders?status=paid');
    failWith(expectList(), 500, 'internal_error');
    await settle();

    const alert = page.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("The orders couldn't be loaded.");
    expect(alert?.textContent).toContain('Failed with internal_error.');
    expect(alert?.textContent).toContain('Request ID req-1');
    expect(page.querySelector('table')).toBeNull();

    button('Try again').click();
    expectList().flush(orderPage([1]));
    await settle();

    expect(rowIds()).toEqual(['1']);
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('keeps the rows when "Load more" fails and offers to try again', async () => {
    await open();
    expectList().flush(orderPage([5, 4], 'c1'));
    await settle();

    button('Load 50 more').click();
    expectList().error(new ProgressEvent('error'));
    await settle();

    expect(rowIds()).toEqual(['5', '4']);
    expect(textOf(page, '[role="alert"] p')).toContain("More orders couldn't be loaded.");

    button('Try again').click();
    expect(expectList().request.params.get('cursor')).toBe('c1');
  });
});
