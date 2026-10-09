import {
  Injectable,
  ResourceRef,
  ResourceSnapshot,
  Signal,
  computed,
  inject,
  linkedSignal,
  signal,
} from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Observable, catchError, throwError } from 'rxjs';

import { ApiError, parseApiError } from '../../core/api/api-error';
import {
  CohortsOut,
  ProductRankingOut,
  RevenueMonthlyOut,
  SummaryOut,
  TopCustomersOut,
} from '../../core/api/models';
import { AnalyticsApi } from './analytics-api';
import { DEFAULT_PARAMS, DashboardParams } from './dashboard-params';

/** Fixed spans of the panels the period selector does not control. */
export const REVENUE_MONTHS = 24;
export const COHORT_MONTHS = 12;
export const RANKING_DAYS = 365;
export const TOP_PRODUCTS = 10;
/** One country lists its top ten; every country together lists only each one's best. */
export const TOP_CUSTOMERS_IN_COUNTRY = 10;
export const TOP_CUSTOMERS_PER_COUNTRY = 1;

export type PanelStatus = 'loading' | 'loaded' | 'failed';

/** One dashboard panel's data and request state. */
export interface Panel<T> {
  /** The latest answer; while new parameters load, the previous one. */
  readonly value: Signal<T | undefined>;
  readonly status: Signal<PanelStatus>;
  /** True while the value shown belongs to the parameters before the current ones. */
  readonly stale: Signal<boolean>;
  readonly error: Signal<ApiError | null>;
  /** Asks again with the same parameters. */
  retry(): void;
}

/**
 * The dashboard's five panels. Each is a resource that starts loading as
 * soon as the store exists, so all five requests run in parallel, and each
 * fails on its own: one broken query leaves the other panels working.
 *
 * A resource cancels its request in flight when its parameters change, so
 * only the newest selection's answer can arrive. Each resource reads only
 * the selector it depends on, so changing the period does not reload the
 * rankings.
 */
@Injectable()
export class DashboardStore {
  private readonly api = inject(AnalyticsApi);

  /** Set from the URL by the page. */
  readonly params = signal<DashboardParams>(DEFAULT_PARAMS);

  private readonly days = computed(() => this.params().days);
  private readonly country = computed(() => this.params().country);
  private readonly category = computed(() => this.params().category);

  readonly summary = panel<SummaryOut>(
    rxResource({
      params: () => ({ days: this.days() }),
      stream: ({ params }) => withApiError(this.api.summary(params)),
    }),
  );

  readonly revenue = panel<RevenueMonthlyOut>(
    rxResource({
      stream: () => withApiError(this.api.revenueMonthly({ months: REVENUE_MONTHS })),
    }),
  );

  readonly topCustomers = panel<TopCustomersOut>(
    rxResource({
      params: () => {
        const country = this.country();
        return country === null
          ? { limit: TOP_CUSTOMERS_PER_COUNTRY, days: RANKING_DAYS }
          : { country, limit: TOP_CUSTOMERS_IN_COUNTRY, days: RANKING_DAYS };
      },
      stream: ({ params }) => withApiError(this.api.topCustomers(params)),
    }),
  );

  readonly products = panel<ProductRankingOut>(
    rxResource({
      params: () => {
        const category = this.category();
        const query = { limit: TOP_PRODUCTS, days: RANKING_DAYS };
        return category === null ? query : { ...query, category };
      },
      stream: ({ params }) => withApiError(this.api.products(params)),
    }),
  );

  readonly cohorts = panel<CohortsOut>(
    rxResource({
      stream: () => withApiError(this.api.cohorts({ months: COHORT_MONTHS })),
    }),
  );
}

/** Errors leave the stream as {@link ApiError}, so panels can show the message and request id. */
function withApiError<T>(source: Observable<T>): Observable<T> {
  return source.pipe(catchError((error: unknown) => throwError(() => parseApiError(error))));
}

function panel<T>(resource: ResourceRef<T | undefined>): Panel<T> {
  // A resource forgets its value while new parameters load. The panel keeps
  // what it last showed (dimmed) until the answer arrives; "previous" is the
  // value last read, which is what the template rendered. A failure clears
  // it, because those numbers belong to other parameters.
  const value = linkedSignal<ResourceSnapshot<T | undefined>, T | undefined>({
    source: resource.snapshot,
    computation: (snapshot, previous) => {
      if (snapshot.status === 'error') {
        return undefined;
      }
      return snapshot.value ?? previous?.value;
    },
  });
  const status = computed<PanelStatus>(() => {
    if (resource.isLoading()) {
      return 'loading';
    }
    return resource.status() === 'error' ? 'failed' : 'loaded';
  });
  return {
    value: value.asReadonly(),
    status,
    stale: computed(() => status() === 'loading' && value() !== undefined),
    error: computed(() => {
      const error = resource.error();
      return error === undefined ? null : parseApiError(error);
    }),
    retry: () => {
      resource.reload();
    },
  };
}
