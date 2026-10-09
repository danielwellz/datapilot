import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RevenueMonthlyOut } from '../../core/api/models';
import { ChartConfig } from '../../shared/chart/chart-config';
import { provideFakeCharts } from '../../shared/chart/testing';
import { RevenueChart, revenueChartSpec } from './revenue-chart';
import { FAILURE, FakePanel, fakePanel, revenueMonthlyOut } from './testing';

describe('revenueChartSpec', () => {
  const items = revenueMonthlyOut(3).items;
  const spec = revenueChartSpec(items);

  it('draws revenue and its dashed 3-month average per month', () => {
    expect(spec.kind).toBe('line');
    expect(spec.labels).toEqual(['Jan 2026', 'Feb 2026', 'Mar 2026']);
    expect(spec.series).toEqual([
      { label: 'Revenue', values: [1000.5, 2000.5, 3000.5], color: 1 },
      { label: '3-month average', values: [500.25, 1000.25, 1500.25], color: 2, dashed: true },
    ]);
    expect(spec.formatTick(2_500_000)).toBe('$2.5M');
  });

  it('shows the exact amounts from the API in the tooltip', () => {
    expect(spec.tooltipLabel?.(0, 1)).toBe('Revenue: $2,000.50');
    expect(spec.tooltipLabel?.(1, 1)).toBe('3-month average: $1,000.25');
    expect(spec.tooltipLabel?.(0, 9)).toBe('');
  });

  it('adds the month-over-month and year-over-year change below', () => {
    expect(spec.tooltipFooter?.(2)).toEqual(['Month over month: +50.0%', 'Year over year: −12.5%']);
    expect(spec.tooltipFooter?.(0)).toEqual([
      'Month over month: no earlier month',
      'Year over year: no month a year earlier',
    ]);
    expect(spec.tooltipFooter?.(9)).toEqual([]);
  });
});

@Component({
  imports: [RevenueChart],
  template: `<dp-revenue-chart [panel]="panel" />`,
})
class Host {
  panel: FakePanel<RevenueMonthlyOut> = fakePanel(revenueMonthlyOut());
}

describe('RevenueChart', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let drawn: ChartConfig[];

  async function render(panel: FakePanel<RevenueMonthlyOut>): Promise<void> {
    drawn = [];
    TestBed.configureTestingModule({ providers: [provideFakeCharts(drawn)] });
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.panel = panel;
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function toggle(): HTMLButtonElement | null {
    return element.querySelector<HTMLButtonElement>('button[aria-pressed]');
  }

  it('states the months it covers', async () => {
    await render(fakePanel(revenueMonthlyOut()));
    expect(element.querySelector('.panel__period')?.textContent.trim()).toBe(
      'The last 24 complete months, Jan 2026 to Mar 2026',
    );
  });

  it('draws the chart and keeps the same numbers as a table for screen readers', async () => {
    await render(fakePanel(revenueMonthlyOut()));

    expect(drawn).toHaveLength(1);
    expect(drawn[0]?.data.labels).toEqual(['Jan 2026', 'Feb 2026', 'Mar 2026']);
    const region = element.querySelector('.table-scroll');
    expect(region?.classList).toContain('visually-hidden');
    expect(element.querySelector('caption')?.textContent.trim()).toBe(
      'Monthly revenue, oldest month first',
    );
    const lastRow = [...element.querySelectorAll('tbody tr')].at(-1);
    expect([...(lastRow?.children ?? [])].map((cell) => cell.textContent.trim())).toEqual([
      'Mar 2026',
      '$3,000.50',
      '30',
      '$1,500.25',
      '+50.0% (favorable)',
      '−12.5% (unfavorable)',
    ]);
    expect(
      [...element.querySelectorAll('tbody tr')].at(0)?.querySelectorAll('td')[3]?.textContent,
    ).toContain('None');
  });

  it('shows the table in place of the chart when asked', async () => {
    await render(fakePanel(revenueMonthlyOut()));
    expect(toggle()?.getAttribute('aria-pressed')).toBe('false');

    toggle()?.click();
    await fixture.whenStable();

    expect(toggle()?.getAttribute('aria-pressed')).toBe('true');
    expect(element.querySelector('dp-chart')).toBeNull();
    expect(element.querySelector('.table-scroll')?.classList).not.toContain('visually-hidden');
    expect(element.querySelector('.table-scroll')?.getAttribute('tabindex')).toBe('0');
  });

  it('dims the chart while it reloads', async () => {
    const panel = fakePanel(revenueMonthlyOut());
    panel.set({ status: 'loading', stale: true });
    await render(panel);
    expect(element.querySelector('.panel__body')?.classList).toContain('panel__body--stale');
  });

  it('holds the chart’s place while the first answer loads', async () => {
    await render(fakePanel<RevenueMonthlyOut>());
    expect(element.querySelector('.panel__placeholder')?.textContent.trim()).toBe(
      'Loading monthly revenue…',
    );
    expect(toggle()).toBeNull();
    expect(drawn).toHaveLength(0);
  });

  it('says so when no month had a sale, without an empty chart', async () => {
    const empty = revenueMonthlyOut(2);
    for (const item of empty.items) {
      item.revenue = '0.00';
    }
    await render(fakePanel(empty));

    expect(element.querySelector('.state')?.textContent.trim()).toBe(
      'There were no paid orders in these months.',
    );
    expect(toggle()).toBeNull();
    expect(drawn).toHaveLength(0);
  });

  it('explains a failure and asks again on request', async () => {
    const panel = fakePanel<RevenueMonthlyOut>();
    panel.set({ status: 'failed', error: FAILURE });
    await render(panel);

    expect(element.querySelector('.state__title')?.textContent.trim()).toBe(
      "Monthly revenue couldn't be loaded.",
    );
    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expect(panel.retries).toBe(1);
  });
});
