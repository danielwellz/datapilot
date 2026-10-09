import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { META_URL } from '../../core/api/meta.service';
import { metaOut } from '../../core/api/testing';
import { submitForm, textOf, typeInto } from '../../shared/forms/testing';
import { OrderFilterBar, TYPING_DEBOUNCE_MS } from './order-filter-bar';
import { NO_FILTERS, OrderFilters } from './order-filters';

describe('OrderFilterBar', () => {
  let fixture: ComponentFixture<OrderFilterBar>;
  let http: HttpTestingController;
  let bar: HTMLElement;
  let emitted: OrderFilters[];

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function render(filters: OrderFilters = NO_FILTERS, meta = metaOut()): void {
    fixture = TestBed.createComponent(OrderFilterBar);
    fixture.componentRef.setInput('filters', filters);
    emitted = [];
    // Like the orders page, which puts each change in the URL and passes it back.
    fixture.componentInstance.filtersChange.subscribe((value) => {
      emitted.push(value);
      fixture.componentRef.setInput('filters', value);
    });
    fixture.detectChanges();
    http.expectOne(META_URL).flush(meta);
    fixture.detectChanges();
    bar = fixture.nativeElement as HTMLElement;
  }

  function showFilters(filters: OrderFilters): void {
    fixture.componentRef.setInput('filters', filters);
    fixture.detectChanges();
  }

  function element(selector: string): HTMLElement {
    const match = bar.querySelector<HTMLElement>(selector);
    if (match === null) {
      throw new Error(`Nothing matches ${selector}`);
    }
    return match;
  }

  function input(selector: string): HTMLInputElement {
    return element(selector) as HTMLInputElement;
  }

  function select(selector: string): HTMLSelectElement {
    return element(selector) as HTMLSelectElement;
  }

  function checkbox(label: string): HTMLInputElement {
    const match = [...bar.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].find(
      (input) => input.labels?.[0]?.textContent.trim() === label,
    );
    if (match === undefined) {
      throw new Error(`No checkbox labelled ${label}`);
    }
    return match;
  }

  function choose(selector: string, value: string): void {
    const control = select(selector);
    control.value = value;
    control.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  }

  function buttonLabelled(label: string): HTMLButtonElement | undefined {
    return [...bar.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === label,
    );
  }

  it('shows the filters it is given and follows later changes', () => {
    render({
      ...NO_FILTERS,
      statuses: ['refunded'],
      country: 'DE',
      dateFrom: '2026-01-01',
      maxTotal: '250',
      sort: 'total',
    });

    expect(checkbox('Refunded').checked).toBe(true);
    expect(checkbox('Paid').checked).toBe(false);
    expect(select('#filter-country').value).toBe('DE');
    expect(input('#filter-date-from').value).toBe('2026-01-01');
    expect(input('#filter-max-total').value).toBe('250');
    expect(select('#filter-sort').value).toBe('total');

    showFilters(NO_FILTERS);
    expect(checkbox('Refunded').checked).toBe(false);
    expect(select('#filter-country').value).toBe('');
    expect(input('#filter-max-total').value).toBe('');
    expect(emitted).toEqual([]);
  });

  it('applies a choice at once', () => {
    render();

    checkbox('Cancelled').click();
    checkbox('Paid').click();
    choose('#filter-channel', 'marketplace');

    expect(emitted.at(-1)).toEqual({
      ...NO_FILTERS,
      statuses: ['paid', 'cancelled'],
      channel: 'marketplace',
    });
    expect(emitted).toHaveLength(3);
  });

  it('waits for typing to pause before applying a total', () => {
    render();

    typeInto(bar, '#filter-min-total', '1');
    typeInto(bar, '#filter-min-total', '12');
    typeInto(bar, '#filter-min-total', '125');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS - 1);
    expect(emitted).toEqual([]);

    vi.advanceTimersByTime(1);
    expect(emitted).toEqual([{ ...NO_FILTERS, minTotal: '125' }]);
  });

  it('applies typed values at once on Enter', () => {
    render();

    typeInto(bar, '#filter-date-to', '2026-02-01');
    submitForm(bar);

    expect(emitted).toEqual([{ ...NO_FILTERS, dateTo: '2026-02-01' }]);
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    expect(emitted).toHaveLength(1);
  });

  it('explains an amount it cannot read and applies nothing', () => {
    render();

    typeInto(bar, '#filter-max-total', '12,50');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    fixture.detectChanges();

    expect(emitted).toEqual([]);
    expect(textOf(bar, '#filter-max-total-error')).toBe('Enter an amount like 250 or 99.50.');
    expect(element('#filter-max-total').getAttribute('aria-invalid')).toBe('true');
    expect(element('#filter-max-total').getAttribute('aria-describedby')).toBe(
      'filter-max-total-error',
    );

    typeInto(bar, '#filter-min-total', '-5');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    fixture.detectChanges();
    expect(textOf(bar, '#filter-min-total-error')).toBe('Enter an amount like 250 or 99.50.');
    expect(emitted).toEqual([]);
  });

  it('explains an inverted range and applies nothing until it is fixed', () => {
    render({ ...NO_FILTERS, minTotal: '500' });

    typeInto(bar, '#filter-max-total', '100');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    fixture.detectChanges();

    expect(emitted).toEqual([]);
    expect(textOf(bar, '#filter-total-error')).toBe(
      'The minimum total must not be more than the maximum.',
    );
    expect(element('#filter-min-total').getAttribute('aria-invalid')).toBe('true');

    typeInto(bar, '#filter-max-total', '1000');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    fixture.detectChanges();

    expect(emitted).toEqual([{ ...NO_FILTERS, minTotal: '500', maxTotal: '1000' }]);
    expect(bar.querySelector('#filter-total-error')).toBeNull();
  });

  it('explains an inverted date range', () => {
    render({ ...NO_FILTERS, dateFrom: '2026-03-01' });

    typeInto(bar, '#filter-date-to', '2026-02-01');
    vi.advanceTimersByTime(TYPING_DEBOUNCE_MS);
    fixture.detectChanges();

    expect(emitted).toEqual([]);
    expect(textOf(bar, '#filter-date-error')).toBe(
      'The start date must be on or before the end date.',
    );
    expect(element('#filter-date-to').getAttribute('aria-invalid')).toBe('true');
  });

  it('applies a choice that matches earlier filters after the URL changed', () => {
    render({ ...NO_FILTERS, statuses: ['paid'] });

    // "Clear filters" elsewhere on the page changes the URL, then the user
    // picks the same status again: it must still apply.
    showFilters(NO_FILTERS);
    checkbox('Paid').click();

    expect(emitted).toEqual([{ ...NO_FILTERS, statuses: ['paid'] }]);
  });

  it('clears every filter but keeps the sort, and offers it only when filtered', () => {
    render({ ...NO_FILTERS, sort: 'total' });
    expect(buttonLabelled('Clear filters')).toBeUndefined();

    showFilters({ ...NO_FILTERS, country: 'GB', sort: 'total' });
    buttonLabelled('Clear filters')?.click();

    expect(emitted).toEqual([{ ...NO_FILTERS, sort: 'total' }]);
  });

  it('shows a customer filter as a chip that removes only itself', () => {
    render({ ...NO_FILTERS, customerId: 7, country: 'DE' });

    expect(textOf(bar, '.chip')).toBe('Customer 7');
    element('[aria-label="Remove the filter for customer 7"]').click();

    expect(emitted).toEqual([{ ...NO_FILTERS, country: 'DE' }]);
  });

  it('keeps the customer filter when another filter changes', () => {
    render({ ...NO_FILTERS, customerId: 7 });

    choose('#filter-sort', 'total');

    expect(emitted).toEqual([{ ...NO_FILTERS, customerId: 7, sort: 'total' }]);
  });

  it('lists countries by name, keeping one from the URL that the data does not have', () => {
    render({ ...NO_FILTERS, country: 'NZ' }, metaOut({ countries: ['US', 'DE', 'GB'] }));

    const options = [...select('#filter-country').options].map((option) =>
      option.textContent.trim(),
    );
    expect(options).toEqual([
      'All countries',
      'Germany',
      'New Zealand',
      'United Kingdom',
      'United States',
    ]);
    expect(select('#filter-country').value).toBe('NZ');
  });

  it('limits the date pickers to the days that have orders', () => {
    render();

    expect(element('#filter-date-from').getAttribute('min')).toBe('2023-10-08');
    expect(element('#filter-date-to').getAttribute('max')).toBe('2026-10-07');
  });

  it('says when the countries could not be loaded and loads them again on request', () => {
    fixture = TestBed.createComponent(OrderFilterBar);
    fixture.componentRef.setInput('filters', NO_FILTERS);
    fixture.detectChanges();
    bar = fixture.nativeElement as HTMLElement;
    expect(select('#filter-country').options.item(0)?.textContent.trim()).toBe(
      'Loading countries…',
    );

    http.expectOne(META_URL).flush(null, { status: 503, statusText: 'Service Unavailable' });
    fixture.detectChanges();
    expect(textOf(bar, '#filter-country-error')).toContain("Countries couldn't be loaded.");

    buttonLabelled('Try again')?.click();
    http.expectOne(META_URL).flush(metaOut());
    fixture.detectChanges();

    expect(bar.querySelector('#filter-country-error')).toBeNull();
    expect(select('#filter-country').options).toHaveLength(4);
  });
});
