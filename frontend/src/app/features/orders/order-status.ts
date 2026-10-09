import { Component, computed, input } from '@angular/core';

import { OrderStatus } from '../../core/api/models';
import { STATUS_LABELS } from './order-labels';

/**
 * An order's status as a word with a small marker. The markers differ in
 * shape, not color: green and red are reserved for changes (docs/design.md).
 */
@Component({
  selector: 'dp-order-status',
  template: `<span class="marker marker--{{ status() }}" aria-hidden="true"></span>{{ label() }}`,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
    }

    .marker {
      width: 8px;
      height: 8px;
      border: 1.5px solid var(--color-ink);
      border-radius: var(--radius-round);
    }

    .marker--paid {
      background: var(--color-ink);
    }

    .marker--refunded {
      background: linear-gradient(90deg, var(--color-ink) 50%, transparent 50%);
    }

    .marker--cancelled {
      border-color: var(--color-graphite);
    }
  `,
})
export class OrderStatusLabel {
  readonly status = input.required<OrderStatus>();

  protected readonly label = computed(() => STATUS_LABELS[this.status()]);
}
