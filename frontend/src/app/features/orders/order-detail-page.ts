import { Location } from '@angular/common';
import { Component, computed, inject, input } from '@angular/core';
import { rxResource, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { ApiError, parseApiError } from '../../core/api/api-error';
import { RelativeTimePipe, UtcDatePipe, UtcDateTimePipe } from '../../shared/format/format.pipes';
import { Money } from '../../shared/format/money';
import { validId } from './order-filters';
import { CHANNEL_LABELS, countryName } from './order-labels';
import { OrderStatusLabel } from './order-status';
import { OrdersApi } from './orders-api';

/**
 * One order: its summary, customer and items. The list's query string rides
 * along in this page's URL, so "Back to orders" returns to the same filters
 * even after a reload or from a shared link.
 */
@Component({
  selector: 'dp-order-detail-page',
  imports: [RouterLink, Money, OrderStatusLabel, UtcDateTimePipe, UtcDatePipe, RelativeTimePipe],
  templateUrl: './order-detail-page.html',
  styleUrl: './order-detail-page.scss',
})
export class OrderDetailPage {
  private readonly api = inject(OrdersApi);
  private readonly router = inject(Router);
  private readonly location = inject(Location);

  private readonly queryParams = toSignal(inject(ActivatedRoute).queryParams, {
    requireSync: true,
  });

  /** The `:id` route parameter, bound by the router. */
  readonly id = input.required<string>();

  protected readonly channelLabels = CHANNEL_LABELS;
  protected readonly countryName = countryName;
  protected readonly now = new Date();

  /** The list with the filters it had, which this page's URL carries. */
  protected readonly listUrl = computed(() =>
    this.router.serializeUrl(
      this.router.createUrlTree(['/orders'], { queryParams: this.queryParams() }),
    ),
  );

  /** Null for an id no order can have, which is answered without a request. */
  protected readonly orderId = computed(() => validId(this.id()));

  protected readonly order = rxResource({
    params: () => this.orderId() ?? undefined,
    stream: ({ params: id }) =>
      this.api.get(id).pipe(catchError((error: unknown) => throwError(() => parseApiError(error)))),
  });

  protected readonly failure = computed(() => {
    const error = this.order.error();
    return error instanceof ApiError ? error : null;
  });

  protected readonly notFound = computed(
    () => this.orderId() === null || this.failure()?.status === 404,
  );

  protected readonly itemCount = computed(() =>
    this.order.hasValue()
      ? this.order.value().items.reduce((sum, item) => sum + item.quantity, 0)
      : 0,
  );

  /**
   * A plain click on "Back to orders" goes back in history when the list is
   * the previous page, so the browser's back button and this link agree.
   * Otherwise (a reload, a shared link) it opens the list with the same
   * filters. Modified clicks keep the link's normal behavior, such as
   * opening a new tab.
   */
  protected backToList(event: MouseEvent): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    const previous = this.router.lastSuccessfulNavigation()?.previousNavigation?.finalUrl;
    if (previous !== undefined && this.router.serializeUrl(previous) === this.listUrl()) {
      this.location.back();
    } else {
      void this.router.navigateByUrl(this.listUrl());
    }
  }
}
