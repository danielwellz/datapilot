import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CohortsOut } from '../../core/api/models';
import { CohortHeatmap } from './cohort-heatmap';
import { FAILURE, FakePanel, cohortsOut, fakePanel } from './testing';

@Component({
  imports: [CohortHeatmap],
  template: `<dp-cohort-heatmap [panel]="panel" />`,
})
class Host {
  panel: FakePanel<CohortsOut> = fakePanel(cohortsOut());
}

describe('CohortHeatmap', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;

  async function render(panel: FakePanel<CohortsOut>): Promise<void> {
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.panel = panel;
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function text(node: Element | null | undefined): string {
    return (node?.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  it('is a table with a caption, a row header per cohort and a column per month', async () => {
    await render(fakePanel(cohortsOut()));

    expect(text(element.querySelector('caption'))).toBe(
      "Share of each signup month's customers with a paid order, by months since signup",
    );
    const headerRows = [...element.querySelectorAll('thead tr')];
    const groups = headerRows.at(0);
    const months = headerRows.at(1);
    expect(text(groups?.querySelector('th[scope="colgroup"]'))).toBe('Months since signup');
    expect(groups?.querySelector('th')?.getAttribute('colspan')).toBe('2');
    expect([...(months?.querySelectorAll('th') ?? [])].map(text)).toEqual([
      'Signup month',
      'Customers',
      'Month 0',
      'Month 1',
    ]);
    expect([...element.querySelectorAll('tbody th[scope="row"]')].map(text)).toEqual([
      'Aug 2026',
      'Sep 2026',
    ]);
  });

  it('prints every value as a whole percent and leaves months not yet reached empty', async () => {
    await render(fakePanel(cohortsOut()));

    const rows = [...element.querySelectorAll('tbody tr')].map((row) =>
      [...row.children].map(text),
    );
    expect(rows).toEqual([
      ['Aug 2026', '200', '40%', '65%'],
      ['Sep 2026', '150', '30%', ''],
    ]);
  });

  it('shades each value on the scale fitted to the rates shown', async () => {
    await render(fakePanel(cohortsOut()));

    // Rates 30%, 40% and 65% fit a 30% to 70% scale in steps of 8%.
    const shades = [...element.querySelectorAll('tbody td.heat')].map((cell) =>
      [...cell.classList].find((name) => name.startsWith('heat--')),
    );
    expect(shades).toEqual(['heat--2', 'heat--5', 'heat--1', 'heat--none']);
  });

  it('states the fitted range in words, with a swatch and range per shade', async () => {
    await render(fakePanel(cohortsOut()));

    expect(text(element.querySelector('.legend__range'))).toBe(
      'Shading covers 30% to 70%, the range of these cohorts, not 0% to 100%.',
    );
    expect([...element.querySelectorAll('.legend__step')].map(text)).toEqual([
      '30%–38%',
      '38%–46%',
      '46%–54%',
      '54%–62%',
      '62%–70%',
    ]);
    expect(element.querySelector('.legend__swatch')?.classList).toContain('heat--1');
    expect(element.querySelector('.legend')?.getAttribute('aria-labelledby')).toBe(
      'cohorts-legend-title',
    );
  });

  it('states the signup months it covers', async () => {
    await render(fakePanel(cohortsOut()));
    expect(text(element.querySelector('.panel__period'))).toBe(
      'Customers who signed up in the last 12 complete months, Aug 2026 to Sep 2026',
    );
  });

  it('scrolls sideways inside its sheet, reachable by keyboard', async () => {
    await render(fakePanel(cohortsOut()));
    const region = element.querySelector('.table-scroll');
    expect(region?.getAttribute('role')).toBe('region');
    expect(region?.getAttribute('tabindex')).toBe('0');
  });

  it('says so when nobody signed up', async () => {
    await render(fakePanel<CohortsOut>({ items: [] }));
    expect(text(element.querySelector('.state'))).toBe('No customer signed up in these months.');
    expect(element.querySelector('table')).toBeNull();
  });

  it('holds its place while loading and dims old cells while reloading', async () => {
    const panel = fakePanel<CohortsOut>();
    await render(panel);
    expect(text(element.querySelector('.panel__placeholder'))).toBe(
      'Loading the retention cohorts…',
    );
    expect(text(element.querySelector('.panel__period'))).toBe(
      'Customers who signed up in the last 12 complete months',
    );

    panel.set({ value: cohortsOut(), status: 'loading', stale: true });
    await fixture.whenStable();
    expect(element.querySelector('.panel__body')?.classList).toContain('panel__body--stale');
  });

  it('explains a failure and asks again on request', async () => {
    const panel = fakePanel<CohortsOut>();
    panel.set({ status: 'failed', error: FAILURE });
    await render(panel);

    expect(text(element.querySelector('.state__title'))).toBe(
      "The retention cohorts couldn't be loaded.",
    );
    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expect(panel.retries).toBe(1);
  });
});
