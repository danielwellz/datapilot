import { ViewportScroller } from '@angular/common';
import { Component, afterNextRender, computed, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationStart, Router, RouterLink, Scroll } from '@angular/router';
import { filter, map, take } from 'rxjs';

import { LOCALE } from '../../shared/format/format';
import { RelativeTimePipe, UtcDateTimePipe } from '../../shared/format/format.pipes';
import { Money } from '../../shared/format/money';
import { OrderFilterBar } from './order-filter-bar';
import { CHANNEL_LABELS } from './order-labels';
import {
  NO_FILTERS,
  OrderFilters,
  filtersFromParams,
  filtersToParams,
  hasFilters,
} from './order-filters';
import { OrderStatusLabel } from './order-status';
import { OrdersStore, PAGE_SIZE } from './orders.store';

type View = 'skeleton' | 'table' | 'empty' | 'failed';

/** Rows the skeleton shows while the first page loads. */
const SKELETON_ROWS = 10;

/**
 * The orders explorer. The URL's query string is the only source of the
 * filters: this page reads them from it and writes changes back to it, and
 * the store loads whatever the URL says.
 */
@Component({
  selector: 'dp-orders-page',
  imports: [RouterLink, Money, OrderFilterBar, OrderStatusLabel, UtcDateTimePipe, RelativeTimePipe],
  templateUrl: './orders-page.html',
  styleUrl: './orders-page.scss',
})
export class OrdersPage {
  protected readonly store = inject(OrdersStore);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly channelLabels = CHANNEL_LABELS;
  protected readonly pageSize = PAGE_SIZE;
  protected readonly skeletonRows = Array.from({ length: SKELETON_ROWS }, (_, index) => index);
  /** Relative times count from when the page opened. */
  protected readonly now = new Date();

  protected readonly filtered = computed(() => hasFilters(this.store.filters()));

  protected readonly view = computed<View>(() => {
    if (this.store.status() === 'failed') {
      return 'failed';
    }
    if (this.store.isEmpty()) {
      return 'empty';
    }
    return this.store.items().length === 0 ? 'skeleton' : 'table';
  });

  /** One line, read out by screen readers whenever it changes. */
  protected readonly summary = computed(() => {
    const count = this.store.items().length;
    switch (this.store.status()) {
      case 'idle':
      case 'loading':
        return count === 0 ? 'Loading orders…' : 'Loading orders for the new filters…';
      case 'failed':
        return '';
      case 'loading-more':
        return 'Loading more orders…';
      default:
        break;
    }
    if (count === 0) {
      return this.filtered() ? 'No orders match these filters.' : 'There are no orders yet.';
    }
    if (this.store.hasMore()) {
      return `Showing ${count.toLocaleString(LOCALE)} orders. More match these filters.`;
    }
    if (count === 1) {
      return this.filtered()
        ? 'Showing the one order that matches these filters.'
        : 'Showing the one order.';
    }
    const all = `Showing all ${count.toLocaleString(LOCALE)} orders`;
    return this.filtered() ? `${all} that match these filters.` : `${all}.`;
  });

  constructor() {
    this.route.queryParamMap
      .pipe(map(filtersFromParams), takeUntilDestroyed())
      .subscribe((filters) => {
        this.store.applyFilters(filters);
      });
    this.keepScrollPosition();
  }

  /** Clears every filter but keeps the sort. */
  protected clearFilters(): void {
    this.showFilters({ ...NO_FILTERS, sort: this.store.filters().sort });
  }

  /**
   * Puts the filters in the URL, which loads them. The URL is replaced rather
   * than pushed, so Back leaves the page instead of undoing each change.
   */
  protected showFilters(filters: OrderFilters): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: filtersToParams(filters),
      replaceUrl: true,
      // Stay where the user is: the filter they changed may be far down the bar.
      scroll: 'manual',
    });
  }

  /**
   * Back from an order, the store still holds the rows, so the page returns
   * to where it was. The router's own restoration is not enough: it can
   * scroll before this page has rendered its rows, and the browser clamps
   * the position to the short page. So the position is applied after this
   * page's first render and again after the router's scroll, whichever
   * comes last. It is saved when a navigation starts, before the page
   * changes.
   */
  private keepScrollPosition(): void {
    const scroller = inject(ViewportScroller);
    const position = this.store.takeSavedScroll();
    if (position !== null) {
      const resume = (): void => {
        scroller.scrollToPosition([...position], { behavior: 'instant' });
      };
      afterNextRender({ write: resume });
      this.router.events
        .pipe(
          filter((event) => event instanceof Scroll),
          take(1),
          takeUntilDestroyed(),
        )
        .subscribe(resume);
    }
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationStart),
        takeUntilDestroyed(),
      )
      .subscribe(() => {
        this.store.saveScroll(scroller.getScrollPosition());
      });
  }
}
