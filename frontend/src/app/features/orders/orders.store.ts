import { Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, Subject, catchError, map, of, switchMap } from 'rxjs';

import { ApiError, parseApiError } from '../../core/api/api-error';
import { OrderSummaryOut } from '../../core/api/models';
import { NO_FILTERS, OrderFilters, filtersToQuery, sameFilters } from './order-filters';
import { OrdersApi } from './orders-api';

/** Rows per request, for the first page and each "Load more". */
export const PAGE_SIZE = 50;

export type OrdersStatus =
  'idle' | 'loading' | 'loaded' | 'failed' | 'loading-more' | 'more-failed';

interface PageRequest {
  filters: OrderFilters;
  /** Null for the first page of these filters. */
  cursor: string | null;
}

type PageResult =
  | { request: PageRequest; items: OrderSummaryOut[]; nextCursor: string | null }
  | { request: PageRequest; error: ApiError };

interface OrdersState {
  filters: OrderFilters;
  items: readonly OrderSummaryOut[];
  nextCursor: string | null;
  status: OrdersStatus;
  error: ApiError | null;
  /** What to ask again on retry. */
  lastRequest: PageRequest | null;
}

/**
 * The orders list: its filters, the rows loaded so far, the cursor for the
 * next page, and whether a request is running or failed.
 *
 * Every request goes through one `switchMap`, so starting a request cancels
 * the one in flight: after quick filter changes, only the newest filters'
 * answer can arrive. Provided on the orders route, so the rows and cursor
 * survive a visit to an order's detail page.
 */
@Injectable()
export class OrdersStore {
  private readonly api = inject(OrdersApi);
  private readonly requests = new Subject<PageRequest>();
  private readonly state = signal<OrdersState>({
    filters: NO_FILTERS,
    items: [],
    nextCursor: null,
    status: 'idle',
    error: null,
    lastRequest: null,
  });

  readonly filters = computed(() => this.state().filters);
  readonly items = computed(() => this.state().items);
  readonly status = computed(() => this.state().status);
  readonly error = computed(() => this.state().error);
  readonly hasMore = computed(() => this.state().nextCursor !== null);
  readonly isEmpty = computed(() => this.status() === 'loaded' && this.items().length === 0);
  /** Rows of the previous filters, kept on screen (dimmed) while the new ones load. */
  readonly isStale = computed(() => this.status() === 'loading' && this.items().length > 0);

  constructor() {
    this.requests
      .pipe(
        switchMap((request) => this.fetch(request)),
        takeUntilDestroyed(),
      )
      .subscribe((result) => {
        this.settle(result);
      });
  }

  /** Shows the first page for these filters, unless they are already shown or loading. */
  applyFilters(filters: OrderFilters): void {
    const { status, filters: current } = this.state();
    if (status !== 'idle' && sameFilters(filters, current)) {
      return;
    }
    this.request({ filters, cursor: null });
  }

  /** Appends the next page. Does nothing on the last page or while a request runs. */
  loadMore(): void {
    const { status, filters, nextCursor } = this.state();
    if (status === 'loaded' && nextCursor !== null) {
      this.request({ filters, cursor: nextCursor });
    }
  }

  /** Repeats the request that failed. */
  retry(): void {
    const { status, lastRequest } = this.state();
    if ((status === 'failed' || status === 'more-failed') && lastRequest !== null) {
      this.request(lastRequest);
    }
  }

  private request(request: PageRequest): void {
    this.state.update((state) => ({
      ...state,
      filters: request.filters,
      // A first page starts a new list: the old cursor belongs to other filters.
      nextCursor: request.cursor === null ? null : state.nextCursor,
      status: request.cursor === null ? 'loading' : 'loading-more',
      error: null,
      lastRequest: request,
    }));
    this.requests.next(request);
  }

  private fetch(request: PageRequest): Observable<PageResult> {
    const query = filtersToQuery(request.filters, PAGE_SIZE, request.cursor);
    return this.api.list(query).pipe(
      map((page) => ({ request, items: page.items, nextCursor: page.next_cursor })),
      catchError((error: unknown) => of({ request, error: parseApiError(error) })),
    );
  }

  private settle(result: PageResult): void {
    const { request } = result;
    if (!('error' in result)) {
      this.state.update((state) => ({
        ...state,
        items: request.cursor === null ? result.items : [...state.items, ...result.items],
        nextCursor: result.nextCursor,
        status: 'loaded',
      }));
      return;
    }
    if (result.error.code === 'invalid_cursor' && request.cursor !== null) {
      // The server no longer accepts this cursor (its signing key changed, for
      // example). The first page is always valid, so start the list again.
      this.state.update((state) => ({ ...state, items: [] }));
      this.request({ filters: request.filters, cursor: null });
      return;
    }
    this.state.update((state) => ({
      ...state,
      // A failed first page leaves no rows: those on screen belong to other filters.
      items: request.cursor === null ? [] : state.items,
      status: request.cursor === null ? 'failed' : 'more-failed',
      error: result.error,
    }));
  }
}
