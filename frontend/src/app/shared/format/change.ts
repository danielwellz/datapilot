import { Component, computed, input } from '@angular/core';

import { formatChange } from './format';

/**
 * A change against an earlier value. The sign shows the direction; green or
 * red shows whether that is good news for this metric, so a rising refund
 * rate is red. Screen readers hear the judgement as words, because color
 * alone must not carry it.
 */
@Component({
  selector: 'dp-change',
  template: `
    @if (view(); as view) {
      <span class="change" [class]="'change--' + view.sentiment"
        >{{ view.text }}
        @if (view.sentiment !== 'neutral') {
          <span class="visually-hidden">({{ view.sentiment }})</span>
        }
      </span>
    } @else {
      <span class="change change--none">{{ missing() }}</span>
    }
  `,
  styles: `
    .change {
      white-space: nowrap;
    }

    .change--favorable {
      color: var(--color-favorable);
    }

    .change--unfavorable {
      color: var(--color-unfavorable);
    }

    .change--neutral,
    .change--none {
      color: var(--color-graphite);
    }
  `,
})
export class ChangeIndicator {
  /** A relative change (0.25 is +25%); null when there is nothing to compare with. */
  readonly change = input.required<number | null>();
  /** The direction that is good news for this metric. */
  readonly good = input<'up' | 'down'>('up');
  /** Shown instead of a figure when the change is null. */
  readonly missing = input('No earlier data');

  protected readonly view = computed(() => {
    const change = this.change();
    return change === null ? null : formatChange(change, this.good());
  });
}
