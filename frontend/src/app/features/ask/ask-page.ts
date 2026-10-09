import { Component, ElementRef, Injector, afterNextRender, computed, inject } from '@angular/core';

import { AskOut, HistoryItemOut } from '../../core/api/models';

import { formatCount } from '../../shared/format/format';
import { AskComposer } from './ask-composer';
import { AskHistory } from './ask-history';
import { AskStore } from './ask.store';
import { QueryReceipt } from './query-receipt';

/**
 * Ask your data: the composer, then the session's receipts, newest first,
 * so the latest answer is always just below the question box, and the
 * user's history beside them.
 */
@Component({
  selector: 'dp-ask-page',
  imports: [AskComposer, AskHistory, QueryReceipt],
  templateUrl: './ask-page.html',
  styleUrl: './ask-page.scss',
})
export class AskPage {
  protected readonly store = inject(AskStore);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  /**
   * Said once when the newest question is answered. Failures announce
   * themselves on their receipt, and a pending question says it is asking.
   */
  protected readonly announcement = computed(() => {
    // The most recently asked answer, not the top of the thread: recalling
    // an older receipt moves it up but must not announce it again.
    let latest: AskOut | null = null;
    let latestKey = 0;
    for (const entry of this.store.entries()) {
      if (entry.state.kind === 'answered' && entry.key > latestKey) {
        latest = entry.state.answer;
        latestKey = entry.key;
      }
    }
    if (latest === null) {
      return '';
    }
    const rows = latest.row_count;
    return `Answered: ${formatCount(rows)} ${rows === 1 ? 'row' : 'rows'}.`;
  });

  constructor() {
    this.store.load();
  }

  /** Shows a history item's receipt at the top of the thread and moves focus to it. */
  protected recall(item: HistoryItemOut): void {
    const key = this.store.recall(item);
    afterNextRender(
      () => {
        this.host.nativeElement
          .querySelector<HTMLElement>(`[data-entry="${String(key)}"] h2`)
          ?.focus();
      },
      { injector: this.injector },
    );
  }
}
