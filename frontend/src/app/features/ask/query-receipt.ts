import { Component, computed, inject, input } from '@angular/core';

import { ChartView } from '../../shared/chart/chart';
import { formatCount, formatDuration, formatUtcDateTime } from '../../shared/format/format';
import { answerChart } from './answer-chart';
import { AskStore, ThreadEntry, auditIdOf } from './ask.store';
import { ReceiptSql } from './receipt-sql';
import { ResultTable } from './result-table';

let nextId = 1;

/** `124` becomes `"000124"`: receipts are numbered by their audit id. */
export function receiptNumber(auditId: number): string {
  return String(auditId).padStart(6, '0');
}

/** The rows line of an answer: the count, and whether the row limit cut it short. */
export function rowsText(rowCount: number, truncated: boolean): string {
  const rows = formatCount(rowCount);
  return truncated ? `${rows}, the limit; more rows matched` : rows;
}

/**
 * One question and what became of it, presented as a query receipt: the
 * question, the explanation, a ledger of who answered and how, the SQL and
 * the result. It is the product's one memorable element (docs/design.md).
 */
@Component({
  selector: 'dp-query-receipt',
  imports: [ChartView, ReceiptSql, ResultTable],
  templateUrl: './query-receipt.html',
  styleUrl: './query-receipt.scss',
})
export class QueryReceipt {
  protected readonly store = inject(AskStore);

  readonly entry = input.required<ThreadEntry>();

  protected readonly questionId = `receipt-question-${String(nextId++)}`;
  protected readonly state = computed(() => this.entry().state);
  protected readonly answer = computed(() => {
    const state = this.state();
    return state.kind === 'answered' ? state.answer : null;
  });
  /** Drawn only when the model suggested a chart and the result's shape fits it. */
  protected readonly chart = computed(() => {
    const answer = this.answer();
    return answer === null ? null : answerChart(answer);
  });

  protected readonly number = computed(() => {
    const auditId = auditIdOf(this.entry());
    return auditId === null ? 'pending' : receiptNumber(auditId);
  });

  protected readonly askedAt = computed(() => {
    const state = this.state();
    return state.kind === 'answered'
      ? state.answer.created_at
      : new Date(this.entry().startedAt).toISOString();
  });

  protected readonly askedAtText = computed(() => `${formatUtcDateTime(this.askedAt())} UTC`);

  protected readonly elapsedSeconds = computed(() =>
    Math.max(0, Math.floor((this.store.now() - this.entry().startedAt) / 1000)),
  );

  protected readonly formatCount = formatCount;
  protected readonly formatDuration = formatDuration;
  protected readonly rowsText = rowsText;
}
