import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CohortsOut,
  CohortsQuery,
  ProductRankingOut,
  ProductRankingQuery,
  RevenueMonthlyOut,
  RevenueMonthlyQuery,
  SummaryOut,
  SummaryQuery,
  TopCustomersOut,
  TopCustomersQuery,
} from '../../core/api/models';
import { toHttpParams } from '../../core/api/query-params';
import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';

export const ANALYTICS_URL = '/api/analytics';

/** HTTP access to the analytics endpoints behind the dashboard. */
@Injectable({ providedIn: 'root' })
export class AnalyticsApi {
  private readonly http = inject(HttpClient);

  summary(query: SummaryQuery): Observable<SummaryOut> {
    return this.get('summary', query);
  }

  revenueMonthly(query: RevenueMonthlyQuery): Observable<RevenueMonthlyOut> {
    return this.get('revenue-monthly', query);
  }

  topCustomers(query: TopCustomersQuery): Observable<TopCustomersOut> {
    return this.get('top-customers', query);
  }

  products(query: ProductRankingQuery): Observable<ProductRankingOut> {
    return this.get('products', query);
  }

  cohorts(query: CohortsQuery): Observable<CohortsOut> {
    return this.get('cohorts', query);
  }

  // Each dashboard panel shows its own failure in place, so no toast.
  private get<T>(path: string, query: object): Observable<T> {
    return this.http.get<T>(`${ANALYTICS_URL}/${path}`, {
      params: toHttpParams(query),
      context: new HttpContext().set(SKIP_ERROR_TOAST, true),
    });
  }
}
