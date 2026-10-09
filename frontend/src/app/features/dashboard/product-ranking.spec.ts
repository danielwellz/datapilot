import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MetaOut, ProductRankingOut } from '../../core/api/models';
import { metaOut } from '../../core/api/testing';
import { ChartConfig } from '../../shared/chart/chart-config';
import { provideFakeCharts } from '../../shared/chart/testing';
import { ProductRanking, productChartSpec, shortenLabel } from './product-ranking';
import { FAILURE, FakePanel, fakePanel, productRank, productRankingOut } from './testing';

describe('product ranking chart', () => {
  const items = [
    productRank({ product_id: 1, name: 'Harbor Backpack', revenue: '7012345.67', units: 9001 }),
    productRank({
      rank: 2,
      product_id: 2,
      name: 'Noise-cancelling headphones for travel',
      revenue: '2500000.00',
      category_share: null,
    }),
  ];
  const spec = productChartSpec(items);

  it('draws one horizontal bar per product, best first', () => {
    expect(spec).toMatchObject({ kind: 'bar', horizontal: true });
    expect(spec.labels).toEqual(['Harbor Backpack', 'Noise-cancelling headphones for travel']);
    expect(spec.series).toEqual([{ label: 'Revenue', values: [7012345.67, 2500000], color: 1 }]);
    expect(spec.formatTick(2_000_000)).toBe('$2M');
  });

  it('shortens long names on the axis only', () => {
    expect(spec.formatLabel?.('Noise-cancelling headphones for travel')).toBe(
      'Noise-cancelling head…',
    );
    expect(shortenLabel('Harbor Backpack')).toBe('Harbor Backpack');
    expect(shortenLabel('abcdef', 4)).toBe('abc…');
    expect(shortenLabel('ab  cdef', 4)).toBe('ab…');
  });

  it('shows exact revenue, category, units and share in the tooltip', () => {
    expect(spec.tooltipLabel?.(0, 0)).toBe('Revenue: $7,012,345.67');
    expect(spec.tooltipFooter?.(0)).toEqual([
      'Category: Electronics',
      'Units sold: 9,001',
      'Share of category: 8.1%',
    ]);
    expect(spec.tooltipFooter?.(1)).toContain('Share of category: none');
    expect(spec.tooltipLabel?.(0, 5)).toBe('');
    expect(spec.tooltipFooter?.(5)).toEqual([]);
  });
});

@Component({
  imports: [ProductRanking],
  template: `<dp-product-ranking
    [panel]="panel"
    [meta]="meta"
    [category]="category()"
    (categoryChange)="chosen.push($event)"
  />`,
})
class Host {
  panel: FakePanel<ProductRankingOut> = fakePanel(productRankingOut());
  meta: FakePanel<MetaOut> = fakePanel(metaOut());
  readonly category = signal<string | null>(null);
  readonly chosen: (string | null)[] = [];
}

describe('ProductRanking', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let drawn: ChartConfig[];

  async function render(
    panel: FakePanel<ProductRankingOut>,
    category: string | null = null,
  ): Promise<void> {
    drawn = [];
    TestBed.configureTestingModule({ providers: [provideFakeCharts(drawn)] });
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.panel = panel;
    fixture.componentInstance.category.set(category);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function toggle(): HTMLButtonElement | null {
    return element.querySelector<HTMLButtonElement>('button[aria-pressed]');
  }

  it('states its own period', async () => {
    await render(fakePanel(productRankingOut()));
    expect(element.querySelector('.panel__period')?.textContent.trim()).toBe(
      'Paid revenue over the last 365 complete days',
    );
  });

  it('draws the ranking, sized to its bars, with the same numbers as a hidden table', async () => {
    await render(fakePanel(productRankingOut()));

    expect(drawn).toHaveLength(1);
    expect(drawn[0]?.data.labels).toEqual(['Noise-cancelling headphones']);
    expect(element.querySelector<HTMLElement>('.chart__canvas')?.style.height).toBe('152px');
    expect(element.querySelector('.table-scroll')?.classList).toContain('visually-hidden');
    expect(element.querySelector('caption')?.textContent.trim()).toBe(
      'The top 10 products, by paid revenue',
    );
    const row = element.querySelector('tbody tr');
    expect([...(row?.children ?? [])].map((cell) => cell.textContent.trim())).toEqual([
      '1',
      'Noise-cancelling headphones',
      'Electronics',
      '512',
      '$98,765.43',
      '8.1%',
    ]);
  });

  it('grows the chart when ties return more than ten products', async () => {
    const items = Array.from({ length: 12 }, (_, index) =>
      productRank({ product_id: index, rank: Math.min(index + 1, 10) }),
    );
    await render(fakePanel(productRankingOut(items)));
    expect(element.querySelector<HTMLElement>('.chart__canvas')?.style.height).toBe('376px');
  });

  it('swaps the chart for the table when asked', async () => {
    await render(fakePanel(productRankingOut()));
    toggle()?.click();
    await fixture.whenStable();

    expect(toggle()?.getAttribute('aria-pressed')).toBe('true');
    expect(element.querySelector('dp-chart')).toBeNull();
    expect(element.querySelector('.table-scroll')?.classList).not.toContain('visually-hidden');
  });

  it('offers the categories and reports the one chosen', async () => {
    await render(fakePanel(productRankingOut()), 'Books');
    const select = element.querySelector('select');
    expect([...(select?.options ?? [])].map((option) => option.text.trim())).toEqual([
      'All categories',
      'Books',
      'Electronics',
    ]);
    expect(select?.value).toBe('Books');
    expect(element.querySelector('caption')?.textContent.trim()).toBe(
      'The top 10 products in Books, by paid revenue',
    );

    if (select !== null) {
      select.value = '';
      select.dispatchEvent(new Event('change'));
    }
    expect(fixture.componentInstance.chosen).toEqual([null]);
  });

  it('says when nothing in the category sold', async () => {
    await render(fakePanel(productRankingOut([])), 'Books');
    expect(element.querySelector('.state')?.textContent.trim()).toBe(
      'No product in Books sold in a paid order in the last 365 days.',
    );
    expect(toggle()).toBeNull();
    expect(drawn).toHaveLength(0);
  });

  it('says when nothing sold at all', async () => {
    await render(fakePanel(productRankingOut([])));
    expect(element.querySelector('.state')?.textContent.trim()).toBe(
      'No product sold in a paid order in the last 365 days.',
    );
  });

  it('holds its place while loading and dims old bars while a new category loads', async () => {
    const panel = fakePanel<ProductRankingOut>();
    await render(panel);
    expect(element.querySelector('.panel__placeholder')?.textContent.trim()).toBe(
      'Loading the product ranking…',
    );

    panel.set({ value: productRankingOut(), status: 'loading', stale: true });
    await fixture.whenStable();
    expect(element.querySelector('.panel__body')?.classList).toContain('panel__body--stale');
  });

  it('explains a failure and asks again on request', async () => {
    const panel = fakePanel<ProductRankingOut>();
    panel.set({ status: 'failed', error: FAILURE });
    await render(panel);

    expect(element.querySelector('.state__title')?.textContent.trim()).toBe(
      "The product ranking couldn't be loaded.",
    );
    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expect(panel.retries).toBe(1);
  });
});
