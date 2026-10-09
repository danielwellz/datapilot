import { Component, computed, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

import { MetaOut, TopCustomerOut, TopCustomersOut } from '../../core/api/models';
import { countryName, formatCount } from '../../shared/format/format';
import { UtcDatePipe } from '../../shared/format/format.pipes';
import { Money } from '../../shared/format/money';
import { Panel, PanelView, RANKING_DAYS, TOP_CUSTOMERS_IN_COUNTRY } from './dashboard.store';
import { PanelError } from './panel-error';
import { PanelSelect, SelectOption } from './panel-select';

/**
 * The best customers by paid revenue. Every country together shows each
 * country's best customer; one country shows its top ten.
 */
@Component({
  selector: 'dp-top-customers',
  imports: [Money, PanelError, PanelSelect, RouterLink, UtcDatePipe],
  templateUrl: './top-customers.html',
  styleUrl: './top-customers.scss',
})
export class TopCustomers {
  readonly panel = input.required<Panel<TopCustomersOut>>();
  readonly meta = input.required<Panel<MetaOut>>();
  readonly country = input.required<string | null>();
  readonly countryChange = output<string | null>();

  protected readonly days = RANKING_DAYS;
  protected readonly formatCount = formatCount;
  protected readonly countryName = countryName;

  protected readonly countries = computed<SelectOption[]>(() =>
    (this.meta().value()?.countries ?? [])
      .map((code) => ({ value: code, label: countryName(code) }))
      .sort((a, b) => a.label.localeCompare(b.label)),
  );

  /** Each country's best customer reads best in the order of country names. */
  protected readonly rows = computed<TopCustomerOut[]>(() => {
    const items = this.panel().value()?.items ?? [];
    return this.country() === null
      ? [...items].sort((a, b) => countryName(a.country).localeCompare(countryName(b.country)))
      : items;
  });

  protected readonly view = computed<PanelView>(() => {
    const panel = this.panel();
    if (panel.status() === 'failed') {
      return 'failed';
    }
    const value = panel.value();
    if (value === undefined) {
      return 'loading';
    }
    return value.items.length === 0 ? 'empty' : 'loaded';
  });

  protected readonly caption = computed(() => {
    const country = this.country();
    return country === null
      ? 'The best customer of each country, by paid revenue'
      : `The top ${String(TOP_CUSTOMERS_IN_COUNTRY)} customers in ${countryName(country)}, by paid revenue`;
  });

  protected readonly emptyText = computed(() => {
    const country = this.country();
    const where = country === null ? 'any country' : countryName(country);
    return `No customer in ${where} placed a paid order in the last ${String(this.days)} days.`;
  });
}
