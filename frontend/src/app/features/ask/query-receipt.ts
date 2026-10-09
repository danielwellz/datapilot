import { Component, computed, inject, input } from '@angular/core';

import { ModelOut } from '../../core/api/models';
import { ChartView } from '../../shared/chart/chart';
import { formatCount, formatDuration, formatUtcDateTime } from '../../shared/format/format';
import { answerChart } from './answer-chart';
import {
  FailureExplanation,
  explainFailure,
  failureFromError,
  failureFromHistory,
  failureReceipt,
} from './ask-failure';
import { AskStore, ThreadEntry, auditIdOf, retryAtOf } from './ask.store';
import { ReceiptSql } from './receipt-sql';
import { ResultTable } from './result-table';

/** At most this many "Ask … instead" buttons, so a long model list stays a choice. */
export const MAX_OTHER_MODELS = 3;

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

/** The ledger's lines; a line without a value is left out. */
interface Ledger {
  explanation: string | null;
  model: string | null;
  /** Says which model was asked, when another one answered. */
  fallbackNote: string | null;
  rows: string | null;
  time: string | null;
  repaired: boolean;
  assumptions: readonly string[];
  sql: string | null;
  sqlLabel: string;
}

interface Failure {
  explanation: FailureExplanation;
  requestId: string | null;
}

/**
 * One question and what became of it, presented as a query receipt: the
 * question, the explanation, a ledger of who answered and how, the SQL and
 * the result. It is the product's one memorable element (docs/design.md).
 *
 * The same slip records a question that was not answered, with a stamp, what
 * happened and what to try next, and a question recalled from history, whose
 * rows were not kept.
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

  protected readonly failure = computed<Failure | null>(() => {
    const state = this.state();
    if (state.kind === 'failed') {
      return {
        explanation: explainFailure(failureFromError(state.error)),
        requestId: state.error.requestId,
      };
    }
    if (state.kind === 'recalled' && state.item.status !== 'ok') {
      return { explanation: explainFailure(failureFromHistory(state.item)), requestId: null };
    }
    return null;
  });

  protected readonly ledger = computed<Ledger | null>(() => {
    const state = this.state();
    switch (state.kind) {
      case 'pending':
        return null;
      case 'answered': {
        const { answer } = state;
        return {
          explanation: answer.explanation,
          model: answer.model.label,
          fallbackNote: answer.fell_back ? this.fallbackNote(answer.requested_model) : null,
          rows: rowsText(answer.row_count, answer.truncated),
          time: formatDuration(answer.latency_ms),
          repaired: answer.repaired,
          assumptions: answer.assumptions,
          sql: answer.sql,
          sqlLabel: 'SQL that ran',
        };
      }
      case 'recalled': {
        const { item } = state;
        const answered = item.status === 'ok';
        return {
          explanation: answered ? item.explanation : null,
          model: item.model === null ? null : this.store.modelLabel(item.model),
          fallbackNote:
            item.model !== null && item.model !== item.requested_model
              ? this.fallbackNote(item.requested_model)
              : null,
          rows: item.row_count === null ? null : rowsText(item.row_count, item.truncated),
          time: formatDuration(item.latency_ms),
          repaired: item.repaired,
          assumptions: answered ? item.assumptions : [],
          sql: item.sql,
          sqlLabel: item.status === 'rejected' ? 'SQL that was refused' : 'SQL that ran',
        };
      }
      case 'failed': {
        const receipt = failureReceipt(state.error);
        const answeredBy = receipt?.model ?? null;
        const sql = receipt?.sql ?? null;
        return {
          explanation: null,
          model: answeredBy === null ? null : this.store.modelLabel(answeredBy),
          fallbackNote: null,
          rows: null,
          time: null,
          repaired: false,
          assumptions: [],
          sql,
          sqlLabel: state.error.code === 'sql_rejected' ? 'SQL that was refused' : 'SQL that ran',
        };
      }
    }
  });

  protected readonly number = computed(() => {
    const auditId = auditIdOf(this.entry());
    if (auditId !== null) {
      return receiptNumber(auditId);
    }
    return this.state().kind === 'pending' ? 'pending' : 'not recorded';
  });

  protected readonly askedAt = computed(() => {
    const state = this.state();
    if (state.kind === 'answered') {
      return state.answer.created_at;
    }
    return state.kind === 'recalled'
      ? state.item.created_at
      : new Date(this.entry().startedAt).toISOString();
  });

  protected readonly askedAtText = computed(() => `${formatUtcDateTime(this.askedAt())} UTC`);

  protected readonly elapsedSeconds = computed(() =>
    Math.max(0, Math.floor((this.store.now() - this.entry().startedAt) / 1000)),
  );

  /** Whole seconds before this question can be asked again; 0 when it can. */
  protected readonly retryWait = computed(() => {
    const state = this.state();
    if (state.kind === 'failed' && state.error.code === 'rate_limited') {
      return this.store.secondsUntilAskable();
    }
    const retryAt = retryAtOf(this.entry());
    return retryAt === null ? 0 : Math.max(0, Math.ceil((retryAt - this.store.now()) / 1000));
  });

  protected readonly otherModels = computed<readonly ModelOut[]>(() =>
    this.store.otherModels(this.entry().modelId).slice(0, MAX_OTHER_MODELS),
  );

  protected readonly formatCount = formatCount;

  /**
   * Asks the same question again, with `modelId` or the model it was asked
   * of. The buttons stay focusable while asking is blocked, so a press then
   * does nothing; the store refuses while a question is pending or the
   * user's limit holds, and this provider's own wait is checked here.
   */
  protected askAgain(modelId: string | null = this.entry().modelId): void {
    if (modelId === this.entry().modelId && this.retryWait() > 0) {
      return;
    }
    this.store.ask(this.entry().question, modelId);
  }

  private fallbackNote(requestedModel: string): string {
    return `${this.store.modelLabel(requestedModel)} couldn't answer, so this model did.`;
  }
}
