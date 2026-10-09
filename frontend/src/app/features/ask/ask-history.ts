import { Component, computed, inject, output, signal } from '@angular/core';

import { HistoryItemOut } from '../../core/api/models';
import { formatUtcDateTime } from '../../shared/format/format';
import { explainFailure, failureFromHistory } from './ask-failure';
import { AskStore } from './ask.store';

/** A history item's outcome in a word or two, the same words as its receipt's stamp. */
export function outcomeText(item: HistoryItemOut): string {
  return item.status === 'ok' ? 'Answered' : explainFailure(failureFromHistory(item)).stamp;
}

/**
 * The user's earlier questions, newest first, with older pages on request.
 * Choosing one shows its receipt in the thread; it is never asked again
 * without the user saying so.
 */
@Component({
  selector: 'dp-ask-history',
  templateUrl: './ask-history.html',
  styleUrl: './ask-history.scss',
})
export class AskHistory {
  protected readonly store = inject(AskStore);

  readonly selected = output<HistoryItemOut>();

  /** On narrow screens the list folds away under its heading; wide screens always show it. */
  protected readonly expanded = signal(false);
  protected readonly outcomeText = outcomeText;

  protected readonly view = computed(() => {
    const status = this.store.historyStatus();
    if (status === 'idle' || status === 'loading') {
      return 'loading';
    }
    if (status === 'failed') {
      return 'failed';
    }
    return this.store.history().length === 0 ? 'empty' : 'list';
  });

  protected askedAt(item: HistoryItemOut): string {
    return `${formatUtcDateTime(item.created_at)} UTC`;
  }
}
