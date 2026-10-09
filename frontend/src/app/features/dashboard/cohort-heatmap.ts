import { Component, computed, input } from '@angular/core';

import { CohortsOut } from '../../core/api/models';
import { formatCount, formatMonth, formatPercent } from '../../shared/format/format';
import { cohortScale } from './cohort-scale';
import { COHORT_MONTHS, Panel, PanelView, panelView } from './dashboard.store';
import { PanelError } from './panel-error';

interface HeatCell {
  /** Whole percent, as the cell prints it; null for a month that has not happened yet. */
  text: string | null;
  step: number;
}

interface HeatRow {
  month: string;
  label: string;
  customers: string;
  cells: HeatCell[];
}

/**
 * Retention of monthly signup cohorts as a table: a row per cohort, a
 * column per month since signup, every cell printing its percentage and
 * shaded on a scale fitted to the rates shown.
 */
@Component({
  selector: 'dp-cohort-heatmap',
  imports: [PanelError],
  templateUrl: './cohort-heatmap.html',
  styleUrl: './cohort-heatmap.scss',
})
export class CohortHeatmap {
  readonly panel = input.required<Panel<CohortsOut>>();

  private readonly cohorts = computed(() => this.panel().value()?.items ?? []);

  protected readonly scale = computed(() =>
    cohortScale(
      this.cohorts().flatMap((cohort) => cohort.retention.map((month) => month.retention_rate)),
    ),
  );

  /** One column per month since signup, as many as the oldest cohort has. */
  protected readonly columns = computed(() =>
    Array.from(
      { length: Math.max(0, ...this.cohorts().map((cohort) => cohort.retention.length)) },
      (_, index) => index,
    ),
  );

  protected readonly rows = computed<HeatRow[]>(() => {
    const scale = this.scale();
    const columns = this.columns();
    return this.cohorts().map((cohort) => ({
      month: cohort.cohort_month,
      label: formatMonth(cohort.cohort_month),
      customers: formatCount(cohort.customers),
      cells: columns.map((index) => {
        const month = cohort.retention.at(index);
        return month === undefined
          ? { text: null, step: 0 }
          : {
              text: formatPercent(month.retention_rate, 0),
              step: scale.stepOf(month.retention_rate),
            };
      }),
    }));
  });

  protected readonly legend = computed(() =>
    this.scale().steps.map((step) => ({
      step: step.step,
      label: `${formatPercent(step.from, 0)}–${formatPercent(step.to, 0)}`,
    })),
  );

  /** States the fitted range in words, so the darkest shade is not read as 100%. */
  protected readonly range = computed(() => {
    const { from, to } = this.scale();
    return `Shading covers ${formatPercent(from, 0)} to ${formatPercent(to, 0)}, the range of these cohorts, not 0% to 100%.`;
  });

  protected readonly period = computed(() => {
    const cohorts = this.cohorts();
    const first = cohorts.at(0);
    const last = cohorts.at(-1);
    const span = `Customers who signed up in the last ${String(COHORT_MONTHS)} complete months`;
    return first === undefined || last === undefined
      ? span
      : `${span}, ${formatMonth(first.cohort_month)} to ${formatMonth(last.cohort_month)}`;
  });

  protected readonly view = computed<PanelView>(() =>
    panelView(this.panel(), (value) => value.items.length === 0),
  );
}
