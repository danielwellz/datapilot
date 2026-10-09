import { Component, computed, input, signal } from '@angular/core';

import { MonthlyRevenueOut, RevenueMonthlyOut } from '../../core/api/models';
import { ChartView } from '../../shared/chart/chart';
import { ChartSpec } from '../../shared/chart/chart-config';
import { ChangeIndicator } from '../../shared/format/change';
import {
  formatChange,
  formatCompactMoney,
  formatCount,
  formatMoney,
  formatMonth,
} from '../../shared/format/format';
import { Money } from '../../shared/format/money';
import { Panel, PanelView, REVENUE_MONTHS } from './dashboard.store';
import { PanelError } from './panel-error';

/** The chart's line and the tooltip's exact figures, from the API's rows. */
export function revenueChartSpec(items: readonly MonthlyRevenueOut[]): ChartSpec {
  const changeLine = (label: string, change: number | null, missing: string): string =>
    `${label}: ${change === null ? missing : formatChange(change).text}`;
  return {
    kind: 'line',
    labels: items.map((item) => formatMonth(item.month)),
    series: [
      { label: 'Revenue', values: items.map((item) => Number(item.revenue)), color: 1 },
      {
        label: '3-month average',
        values: items.map((item) => Number(item.revenue_moving_average_3m)),
        color: 2,
        dashed: true,
      },
    ],
    formatTick: formatCompactMoney,
    // The tooltip shows the exact amounts from the API, not the chart's numbers.
    tooltipLabel: (series, index) => {
      const item = items.at(index);
      if (item === undefined) {
        return '';
      }
      return series === 0
        ? `Revenue: ${formatMoney(item.revenue)}`
        : `3-month average: ${formatMoney(item.revenue_moving_average_3m)}`;
    },
    tooltipFooter: (index) => {
      const item = items.at(index);
      return item === undefined
        ? []
        : [
            changeLine('Month over month', item.revenue_change_mom, 'no earlier month'),
            changeLine('Year over year', item.revenue_change_yoy, 'no month a year earlier'),
          ];
    },
  };
}

/** Paid revenue per month with its 3-month moving average. */
@Component({
  selector: 'dp-revenue-chart',
  imports: [ChartView, ChangeIndicator, Money, PanelError],
  templateUrl: './revenue-chart.html',
  styleUrl: './revenue-chart.scss',
})
export class RevenueChart {
  readonly panel = input.required<Panel<RevenueMonthlyOut>>();

  protected readonly months = REVENUE_MONTHS;
  protected readonly showTable = signal(false);

  protected readonly items = computed(() => this.panel().value()?.items ?? []);
  protected readonly spec = computed(() => revenueChartSpec(this.items()));

  protected readonly view = computed<PanelView>(() => {
    const panel = this.panel();
    if (panel.status() === 'failed') {
      return 'failed';
    }
    if (panel.value() === undefined) {
      return 'loading';
    }
    return this.items().some((item) => Number(item.revenue) > 0) ? 'loaded' : 'empty';
  });

  protected readonly period = computed(() => {
    const items = this.items();
    const first = items.at(0);
    const last = items.at(-1);
    const span = `The last ${String(this.months)} complete months`;
    return first === undefined || last === undefined
      ? span
      : `${span}, ${formatMonth(first.month)} to ${formatMonth(last.month)}`;
  });

  protected readonly formatCount = formatCount;
  protected readonly formatMonth = formatMonth;
}
