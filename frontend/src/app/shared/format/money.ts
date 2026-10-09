import { Component, computed, input } from '@angular/core';

import { moneyParts } from './format';

/**
 * An amount of money, with its currency symbol in the quieter graphite the
 * design uses for units. Figures are tabular through the typeface itself.
 */
@Component({
  selector: 'dp-money',
  template: `{{ parts().sign }}<span class="money__unit">{{ parts().unit }}</span
    >{{ parts().figure }}`,
  styles: `
    :host {
      white-space: nowrap;
    }

    .money__unit {
      color: var(--color-graphite);
    }
  `,
})
export class Money {
  /** A decimal string from the API, such as `"1234.50"`. */
  readonly amount = input.required<string>();

  protected readonly parts = computed(() => moneyParts(this.amount()));
}
