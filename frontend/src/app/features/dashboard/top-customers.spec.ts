import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { MetaOut, TopCustomersOut } from '../../core/api/models';
import { metaOut } from '../../core/api/testing';
import { TopCustomers } from './top-customers';
import { FAILURE, FakePanel, fakePanel, topCustomer, topCustomersOut } from './testing';

@Component({
  imports: [TopCustomers],
  template: `<dp-top-customers
    [panel]="panel"
    [meta]="meta"
    [country]="country()"
    (countryChange)="chosen.push($event)"
  />`,
})
class Host {
  panel: FakePanel<TopCustomersOut> = fakePanel(topCustomersOut());
  meta: FakePanel<MetaOut> = fakePanel(metaOut());
  readonly country = signal<string | null>(null);
  readonly chosen: (string | null)[] = [];
}

describe('TopCustomers', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;

  async function render(
    panel: FakePanel<TopCustomersOut>,
    country: string | null = null,
    meta: FakePanel<MetaOut> = fakePanel(metaOut()),
  ): Promise<void> {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.panel = panel;
    fixture.componentInstance.meta = meta;
    fixture.componentInstance.country.set(country);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function cells(): string[][] {
    return [...element.querySelectorAll('tbody tr')].map((row) =>
      [...row.children].map((cell) => cell.textContent.trim()),
    );
  }

  function select(): HTMLSelectElement {
    const match = element.querySelector('select');
    if (match === null) {
      throw new Error('No select');
    }
    return match;
  }

  const everyCountry = topCustomersOut([
    topCustomer({ country: 'US', customer_id: 1, name: 'Elena Smith', revenue: '37833.50' }),
    topCustomer({ country: 'DE', customer_id: 2, name: 'Emma Costa', revenue: '38773.25' }),
    topCustomer({ country: 'GB', customer_id: 3, name: 'Noah Tanaka', revenue: '40715.14' }),
  ]);

  it('lists the best customer of each country in the order of country names', async () => {
    await render(fakePanel(everyCountry));

    expect([...element.querySelectorAll('thead th')].map((th) => th.textContent.trim())).toEqual([
      'Country',
      'Customer',
      'Paid orders',
      'Revenue',
      'Last order (UTC)',
    ]);
    expect(cells()).toEqual([
      ['Germany', 'Emma Costa', '31', '$38,773.25', 'Oct 5, 2026'],
      ['United Kingdom', 'Noah Tanaka', '31', '$40,715.14', 'Oct 5, 2026'],
      ['United States', 'Elena Smith', '31', '$37,833.50', 'Oct 5, 2026'],
    ]);
    expect(element.querySelector('caption')?.textContent.trim()).toBe(
      'The best customer of each country, by paid revenue',
    );
  });

  it('links each customer to their orders', async () => {
    await render(fakePanel(everyCountry));
    const link = element.querySelector('tbody a');
    expect(link?.getAttribute('href')).toBe('/orders?customer_id=2');
    expect(link?.getAttribute('aria-label')).toBe('Orders of Emma Costa');
  });

  it('ranks the top customers of one country, ties sharing a rank', async () => {
    await render(
      fakePanel(
        topCustomersOut([
          topCustomer({ rank: 1, customer_id: 1, name: 'Ada' }),
          topCustomer({ rank: 1, customer_id: 2, name: 'Grace' }),
          topCustomer({ rank: 2, customer_id: 3, name: 'Alan' }),
        ]),
      ),
      'DE',
    );

    expect(element.querySelector('thead th')?.textContent.trim()).toBe('Rank');
    expect(cells().map((row) => row.slice(0, 2))).toEqual([
      ['1', 'Ada'],
      ['1', 'Grace'],
      ['2', 'Alan'],
    ]);
    expect(element.querySelector('caption')?.textContent.trim()).toBe(
      'The top 10 customers in Germany, by paid revenue',
    );
  });

  it('states its own period', async () => {
    await render(fakePanel(everyCountry));
    expect(element.querySelector('.panel__period')?.textContent.trim()).toBe(
      'Paid revenue over the last 365 complete days',
    );
  });

  it('offers every country by name and reports the one chosen', async () => {
    await render(fakePanel(everyCountry));
    const options = [...select().options].map((option) => [option.value, option.text.trim()]);
    expect(options).toEqual([
      ['', 'All countries, best of each'],
      ['DE', 'Germany'],
      ['GB', 'United Kingdom'],
      ['US', 'United States'],
    ]);
    expect(element.querySelector('label')?.getAttribute('for')).toBe(select().id);

    select().value = 'GB';
    select().dispatchEvent(new Event('change'));
    select().value = '';
    select().dispatchEvent(new Event('change'));

    expect(fixture.componentInstance.chosen).toEqual(['GB', null]);
  });

  it('keeps showing a chosen country the list does not offer', async () => {
    await render(fakePanel(topCustomersOut([])), 'NZ');
    expect(select().value).toBe('NZ');
    expect(select().selectedOptions[0].text.trim()).toBe('NZ');
  });

  it('says when the countries could not be loaded and asks again on request', async () => {
    const meta = fakePanel<MetaOut>();
    meta.set({ status: 'failed', error: FAILURE });
    await render(fakePanel(everyCountry), null, meta);

    const error = element.querySelector('.field__error');
    expect(error?.textContent).toContain("The list couldn't be loaded.");
    expect(select().getAttribute('aria-describedby')).toBe(error?.id);
    error?.querySelector('button')?.click();
    expect(meta.retries).toBe(1);
  });

  it('says when nobody in the country ordered', async () => {
    await render(fakePanel(topCustomersOut([])), 'DE');
    expect(element.querySelector('.state')?.textContent.trim()).toBe(
      'No customer in Germany placed a paid order in the last 365 days.',
    );
    expect(element.querySelector('table')).toBeNull();
  });

  it('holds its place while loading and dims old rows while a new country loads', async () => {
    const panel = fakePanel<TopCustomersOut>();
    await render(panel);
    expect(element.querySelector('.panel__placeholder')?.textContent.trim()).toBe(
      'Loading the top customers…',
    );

    panel.set({ value: everyCountry, status: 'loading', stale: true });
    await fixture.whenStable();
    expect(element.querySelector('.panel__body')?.classList).toContain('panel__body--stale');
  });

  it('explains a failure and asks again on request', async () => {
    const panel = fakePanel<TopCustomersOut>();
    panel.set({ status: 'failed', error: FAILURE });
    await render(panel);

    expect(element.querySelector('.state__title')?.textContent.trim()).toBe(
      "The top customers couldn't be loaded.",
    );
    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expect(panel.retries).toBe(1);
  });
});
