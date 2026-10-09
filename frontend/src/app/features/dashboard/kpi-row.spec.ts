import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SummaryOut } from '../../core/api/models';
import { textOf } from '../../shared/forms/testing';
import { PeriodDays } from './dashboard-params';
import { KpiRow } from './kpi-row';
import { FAILURE, FakePanel, fakePanel, summaryOut } from './testing';

@Component({
  imports: [KpiRow],
  template: `<dp-kpi-row [panel]="panel" [days]="days()" (daysChange)="chosen.push($event)" />`,
})
class Host {
  panel: FakePanel<SummaryOut> = fakePanel(summaryOut());
  readonly days = signal<PeriodDays>(30);
  readonly chosen: PeriodDays[] = [];
}

describe('KpiRow', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;

  async function render(panel = fakePanel(summaryOut())): Promise<void> {
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.panel = panel;
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function metric(label: string): HTMLElement {
    const match = [...element.querySelectorAll<HTMLElement>('.kpi')].find(
      (kpi) => kpi.querySelector('dt')?.textContent.trim() === label,
    );
    if (match === undefined) {
      throw new Error(`No metric labelled ${label}`);
    }
    return match;
  }

  function squash(text: string | null | undefined): string {
    return (text ?? '').replace(/\s+/g, ' ').trim();
  }

  it('states the period and the one it is compared with, from the answer', async () => {
    await render();
    expect(textOf(element, '.panel__period')).toBe(
      'Sep 8 – Oct 7, 2026, compared with Aug 9 – Sep 7, 2026',
    );
  });

  it('shows the five metrics with their figures, changes and previous values', async () => {
    await render();

    expect([...element.querySelectorAll('dt')].map((dt) => dt.textContent.trim())).toEqual([
      'Revenue',
      'Paid orders',
      'Average order value',
      'Active customers',
      'Refund rate',
    ]);
    expect(squash(metric('Revenue').querySelector('.kpi__figure')?.textContent)).toBe(
      '$7,512,345.67',
    );
    expect(squash(metric('Revenue').querySelector('.kpi__change')?.textContent)).toBe(
      '+7.3% (favorable) from $7,000,000.00',
    );
    expect(squash(metric('Paid orders').querySelector('.kpi__change')?.textContent)).toBe(
      '−0.7% (unfavorable) from 70,000',
    );
    expect(squash(metric('Active customers').querySelector('.kpi__change')?.textContent)).toBe(
      '0.0% from 21,000',
    );
    expect(squash(metric('Refund rate').querySelector('.kpi__figure')?.textContent)).toBe('3.1%');
  });

  it('marks a rising refund rate as unfavorable', async () => {
    await render();
    const change = metric('Refund rate').querySelector('.change');
    expect(change?.classList).toContain('change--unfavorable');
    expect(squash(change?.textContent)).toBe('+6.9% (unfavorable)');
  });

  it('marks a falling refund rate as favorable', async () => {
    await render(
      fakePanel(summaryOut({ refund_rate: { current: 0.02, previous: 0.03, change: -0.3333 } })),
    );
    expect(metric('Refund rate').querySelector('.change')?.classList).toContain(
      'change--favorable',
    );
  });

  it('explains a period without paid orders instead of showing an empty average', async () => {
    await render(
      fakePanel(
        summaryOut({
          average_order_value: { current: null, previous: null, change: null },
          refund_rate: { current: null, previous: null, change: null },
        }),
      ),
    );

    expect(textOf(metric('Average order value'), '.kpi__figure')).toBe('No paid orders');
    expect(textOf(metric('Average order value'), '.kpi__change')).toBe('No earlier data');
    expect(textOf(metric('Refund rate'), '.kpi__figure')).toBe('No orders');
  });

  it('holds the place of every metric while the first answer loads', async () => {
    await render(fakePanel<SummaryOut>());

    expect(textOf(element, '.panel__period')).toBe('The last 30 complete days');
    expect(element.querySelectorAll('.kpi .skeleton__bar')).toHaveLength(10);
    expect(element.querySelector('.kpis')?.getAttribute('aria-hidden')).toBe('true');
    expect(element.querySelector('section')?.getAttribute('aria-busy')).toBe('true');
  });

  it('dims the previous numbers while a new period loads', async () => {
    const panel = fakePanel(summaryOut());
    await render(panel);

    panel.set({ status: 'loading', stale: true });
    await fixture.whenStable();

    expect(element.querySelector('dl')?.classList).toContain('panel__body--stale');
    expect(element.querySelector('section')?.getAttribute('aria-busy')).toBe('true');
  });

  it('explains a failure with its request id and asks again on request', async () => {
    const panel = fakePanel<SummaryOut>();
    panel.set({ status: 'failed', error: FAILURE });
    await render(panel);

    const alert = element.querySelector<HTMLElement>('[role="alert"]');
    expect([...(alert?.children ?? [])].map((child) => child.textContent.trim())).toEqual([
      "The key numbers couldn't be loaded.",
      'Something went wrong.',
      'Request ID req-9',
      'Try again',
    ]);
    alert?.querySelector('button')?.click();
    expect(panel.retries).toBe(1);
  });

  it('checks the current period and reports the one chosen', async () => {
    await render();
    const radios = [...element.querySelectorAll<HTMLInputElement>('input[type="radio"]')];

    expect(radios.map((radio) => radio.parentElement?.textContent.trim())).toEqual([
      '7 days',
      '30 days',
      '90 days',
    ]);
    expect(radios.map((radio) => radio.checked)).toEqual([false, true, false]);

    radios[0]?.click();
    expect(fixture.componentInstance.chosen).toEqual([7]);
  });
});
