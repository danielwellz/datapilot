import { Component, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';

import { DashboardParams, paramsFromQuery, paramsToQuery } from './dashboard-params';
import { DashboardStore } from './dashboard.store';
import { KpiRow } from './kpi-row';
import { ProductRanking } from './product-ranking';
import { RevenueChart } from './revenue-chart';
import { TopCustomers } from './top-customers';

/**
 * The analytics dashboard. The URL's query string holds the selectors: this
 * page hands it to the store, which loads every panel, and writes selector
 * changes back to it.
 */
@Component({
  selector: 'dp-dashboard-page',
  imports: [KpiRow, ProductRanking, RevenueChart, TopCustomers],
  providers: [DashboardStore],
  templateUrl: './dashboard-page.html',
  styleUrl: './dashboard-page.scss',
})
export class DashboardPage {
  protected readonly store = inject(DashboardStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  constructor() {
    // The route emits its current parameters on subscribe, so the store has
    // them before its first requests start.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((query) => {
      this.store.params.set(paramsFromQuery(query));
    });
  }

  /** Puts a selection in the URL, which loads it; replaced, so Back leaves the page. */
  protected select(change: Partial<DashboardParams>): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: paramsToQuery({ ...this.store.params(), ...change }),
      queryParamsHandling: 'merge',
      replaceUrl: true,
      scroll: 'manual',
    });
  }
}
