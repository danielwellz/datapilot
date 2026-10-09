import { Component, computed, inject } from '@angular/core';

import { formatCount } from '../../shared/format/format';
import { AskComposer } from './ask-composer';
import { AskStore } from './ask.store';
import { QueryReceipt } from './query-receipt';

/**
 * Ask your data: the composer, then the session's receipts, newest first,
 * so the latest answer is always just below the question box.
 */
@Component({
  selector: 'dp-ask-page',
  imports: [AskComposer, QueryReceipt],
  templateUrl: './ask-page.html',
  styleUrl: './ask-page.scss',
})
export class AskPage {
  protected readonly store = inject(AskStore);

  /**
   * Said once when the newest question is answered. Failures announce
   * themselves on their receipt, and a pending question says it is asking.
   */
  protected readonly announcement = computed(() => {
    const newest = this.store.entries().at(0);
    if (newest?.state.kind !== 'answered') {
      return '';
    }
    const { row_count: rows } = newest.state.answer;
    return `Answered: ${formatCount(rows)} ${rows === 1 ? 'row' : 'rows'}.`;
  });

  constructor() {
    this.store.load();
  }
}
