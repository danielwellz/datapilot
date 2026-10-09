import { Component, computed, input, output } from '@angular/core';

import { SummaryOut } from '../../core/api/models';
import { ChangeIndicator } from '../../shared/format/change';
import { formatDayRange } from '../../shared/format/format';
import { Money } from '../../shared/format/money';
import { PERIOD_DAYS, PeriodDays } from './dashboard-params';
import { Panel } from './dashboard.store';
import { KPI_DEFINITIONS, kpisFrom } from './kpis';
import { PanelError } from './panel-error';

/**
 * The headline numbers of a period, each with its change against the period
 * just before. The period selector sits in this panel because it controls
 * only these numbers.
 */
@Component({
  selector: 'dp-kpi-row',
  imports: [ChangeIndicator, Money, PanelError],
  templateUrl: './kpi-row.html',
  styleUrl: './kpi-row.scss',
})
export class KpiRow {
  readonly panel = input.required<Panel<SummaryOut>>();
  readonly days = input.required<PeriodDays>();
  readonly daysChange = output<PeriodDays>();

  protected readonly periods = PERIOD_DAYS;
  protected readonly labels = KPI_DEFINITIONS.map((definition) => definition.label);

  protected readonly kpis = computed(() => {
    const summary = this.panel().value();
    return summary === undefined ? null : kpisFrom(summary);
  });

  /** The dates the numbers cover, from the answer itself: periods end yesterday, in UTC. */
  protected readonly period = computed(() => {
    const summary = this.panel().value();
    if (summary === undefined) {
      return `The last ${String(this.days())} complete days`;
    }
    const { period, previous_period: previous } = summary;
    return `${formatDayRange(period.start_date, period.end_date)}, compared with ${formatDayRange(
      previous.start_date,
      previous.end_date,
    )}`;
  });
}
