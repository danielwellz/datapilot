import { Location } from '@angular/common';
import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { failWith } from '../../core/api/testing';
import { textOf } from '../../shared/forms/testing';
import { OrderDetailPage } from './order-detail-page';
import { ORDERS_URL } from './orders-api';
import { orderOut } from './testing';

@Component({ template: '' })
class List {}

describe('OrderDetailPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;
  let opened: boolean;

  beforeEach(() => {
    opened = false;
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter(
          [
            { path: 'orders', component: List },
            { path: 'orders/:id', component: OrderDetailPage },
          ],
          withComponentInputBinding(),
        ),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  /** Navigates within one harness per test, so history spans the calls. */
  async function open(url: string): Promise<void> {
    if (!opened) {
      harness = await RouterTestingHarness.create();
      opened = true;
    }
    await harness.navigateByUrl(url);
    const element = harness.routeNativeElement;
    if (element === null) {
      throw new Error(`Nothing rendered at ${url}`);
    }
    page = element;
    // Not whenStable: an order request still in flight keeps the app unstable.
    harness.detectChanges();
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
  }

  function backLink(): HTMLAnchorElement {
    const link = page.querySelector<HTMLAnchorElement>('a.back');
    if (link === null) {
      throw new Error('No back link');
    }
    return link;
  }

  function clickBack(init: MouseEventInit = {}): MouseEvent {
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init });
    backLink().dispatchEvent(event);
    return event;
  }

  it('shows the order summary, customer and items', async () => {
    await open('/orders/42?status=refunded&country=DE');
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();

    expect(textOf(page, 'h1')).toBe('Order 42');
    expect(textOf(page, '.page__lead')?.replace(/\s+/g, ' ')).toMatch(
      /^Placed Mar 1, 2026, 23:30 UTC, .+\.$/,
    );
    const facts = [...page.querySelectorAll('.facts div')].map(
      (fact) =>
        `${textOf(fact as HTMLElement, 'dt') ?? ''}: ${textOf(fact as HTMLElement, 'dd') ?? ''}`,
    );
    expect(facts).toEqual([
      'Status: Refunded',
      'Channel: Marketplace',
      'Items: 3',
      'Total: $1,059.97',
      'Name: Grace Hopper',
      'Email: grace@example.com',
      'Country: Germany (DE)',
      'Customer since: Jan 15, 2024',
    ]);

    const rows = [...page.querySelectorAll('tbody tr')].map((row) =>
      [...row.querySelectorAll('td')].map((cell) => cell.textContent.trim()),
    );
    expect(rows).toEqual([
      ['Desk lamp', 'Home', '2', '$29.99', '$59.98'],
      ['Monitor', 'Electronics', '1', '$999.99', '$999.99'],
    ]);
    expect(textOf(page, 'tfoot th')).toBe('Order total');
    expect(textOf(page, 'tfoot td')).toBe('$1,059.97');
  });

  it("links to the customer's orders and back to the list with its filters", async () => {
    await open('/orders/42?status=refunded&country=DE');
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();

    const customerLink = [...page.querySelectorAll('a')].find((link) =>
      link.textContent.includes('All orders from'),
    );
    expect(customerLink?.getAttribute('href')).toBe('/orders?customer_id=7');
    expect(backLink().getAttribute('href')).toBe('/orders?status=refunded&country=DE');
  });

  it('goes back in history when it came from the list, so the list resumes where it was', async () => {
    await open('/orders?status=paid');
    await open('/orders/42?status=paid');
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();
    const back = vi.spyOn(TestBed.inject(Location), 'back');

    const event = clickBack();

    expect(event.defaultPrevented).toBe(true);
    expect(back).toHaveBeenCalledOnce();
  });

  it('opens the list with the same filters when the detail page was opened directly', async () => {
    await open('/orders/42?status=paid');
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();
    const back = vi.spyOn(TestBed.inject(Location), 'back');

    clickBack();
    await settle();

    expect(back).not.toHaveBeenCalled();
    expect(TestBed.inject(Router).url).toBe('/orders?status=paid');
  });

  it('leaves a modified click to the browser, such as opening a new tab', async () => {
    await open('/orders/42');
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();

    const event = clickBack({ metaKey: true });
    // jsdom would follow the link itself; the page must not have handled it.
    expect(event.defaultPrevented).toBe(false);
  });

  it('says there is no such order on a 404', async () => {
    await open('/orders/404404');
    failWith(http.expectOne(`${ORDERS_URL}/404404`), 404, 'not_found');
    await settle();

    expect(textOf(page, '[role="alert"] .state__title')).toBe('There is no order 404404.');
    expect(page.querySelector('button')).toBeNull();
  });

  it('answers an id no order can have without asking the server', async () => {
    await open('/orders/abc');
    http.expectNone((request) => request.url.startsWith(ORDERS_URL));

    expect(textOf(page, '[role="alert"] .state__title')).toBe('There is no order abc.');
  });

  it('shows the loading state, then explains a failure and tries again', async () => {
    await open('/orders/42');
    expect(textOf(page, '[role="status"]')).toBe('Loading order 42…');

    failWith(http.expectOne(`${ORDERS_URL}/42`), 503, 'unavailable');
    await settle();
    const alert = page.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("Order 42 couldn't be loaded.");
    expect(alert?.textContent).toContain('Request ID req-1');

    page.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    // The resource starts its request when its effects next run.
    TestBed.tick();
    http.expectOne(`${ORDERS_URL}/42`).flush(orderOut());
    await settle();

    expect(page.querySelector('[role="alert"]')).toBeNull();
    expect(textOf(page, 'tfoot td')).toBe('$1,059.97');
  });
});
