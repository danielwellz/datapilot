import {
  DestroyRef,
  Injectable,
  Signal,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { Subscription } from 'rxjs';

import { ApiError, parseApiError } from '../../core/api/api-error';
import { AskOut, HistoryItemOut, HistoryPageOut, ModelOut } from '../../core/api/models';
import { AuthService } from '../../core/auth/auth.service';
import { AskApi } from './ask-api';
import { failureReceipt } from './ask-failure';

/** History rows per request. */
export const HISTORY_PAGE_SIZE = 20;
/** The wait after a rate limit that came without `Retry-After`: the limiter's window. */
export const RATE_LIMIT_FALLBACK_SECONDS = 60;
const TICK_MS = 1000;

export type EntryState =
  | { kind: 'pending' }
  | { kind: 'answered'; answer: AskOut }
  | { kind: 'failed'; error: ApiError; settledAt: number }
  /** Shown from history: the backend keeps no rows, so there is no result. */
  | { kind: 'recalled'; item: HistoryItemOut };

/** One question in the thread and what became of it. */
export interface ThreadEntry {
  /** Unique within the thread, for `track`. */
  key: number;
  question: string;
  /** The model the question was sent to; null for the server's default. */
  modelId: string | null;
  /** Epoch milliseconds. */
  startedAt: number;
  state: EntryState;
}

export type LoadStatus = 'idle' | 'loading' | 'loaded' | 'failed';
export type HistoryStatus = LoadStatus | 'loading-more' | 'more-failed';

interface AskState {
  models: readonly ModelOut[];
  defaultModelId: string | null;
  modelsStatus: LoadStatus;
  /** What the user picked; null until they pick. */
  chosenModelId: string | null;
  examples: readonly string[];
  examplesStatus: LoadStatus;
  /** Newest first. */
  entries: readonly ThreadEntry[];
  /** Epoch milliseconds when the per-user rate limit lets the next question through. */
  askableAt: number | null;
  history: readonly HistoryItemOut[];
  historyCursor: string | null;
  historyStatus: HistoryStatus;
  historyError: ApiError | null;
}

const INITIAL_STATE: AskState = {
  models: [],
  defaultModelId: null,
  modelsStatus: 'idle',
  chosenModelId: null,
  examples: [],
  examplesStatus: 'idle',
  entries: [],
  askableAt: null,
  history: [],
  historyCursor: null,
  historyStatus: 'idle',
  historyError: null,
};

/** The audit id behind an entry, once the backend has recorded the question. */
export function auditIdOf(entry: ThreadEntry): number | null {
  switch (entry.state.kind) {
    case 'answered':
      return entry.state.answer.id;
    case 'recalled':
      return entry.state.item.id;
    case 'failed':
      return failureReceipt(entry.state.error)?.auditId ?? null;
    case 'pending':
      return null;
  }
}

/** When a failed entry's provider said it can be asked again, in epoch milliseconds. */
export function retryAtOf(entry: ThreadEntry): number | null {
  const { state } = entry;
  if (state.kind !== 'failed' || state.error.retryAfterSeconds === null) {
    return null;
  }
  return state.settledAt + state.error.retryAfterSeconds * 1000;
}

/**
 * Ask your data: the models to pick from, the question thread, the rate-limit
 * wait, and the user's history.
 *
 * One question is asked at a time, so answers never race each other into the
 * thread. Provided on the Ask route, so the thread survives a visit to another
 * page; it is cleared when the signed-in user changes, because the route's
 * injector outlives a logout and questions belong to the person who asked.
 */
@Injectable()
export class AskStore {
  private readonly api = inject(AskApi);
  private readonly auth = inject(AuthService);
  private readonly state = signal<AskState>(INITIAL_STATE);
  private readonly clock = signal(Date.now());
  private requests = new Subscription();
  private ticker: ReturnType<typeof setInterval> | null = null;
  private nextKey = 1;
  /** The user this state belongs to; undefined until the first check. */
  private ownerId: number | null | undefined = undefined;

  readonly models = computed(() => this.state().models);
  readonly modelsStatus = computed(() => this.state().modelsStatus);
  readonly examples = computed(() => this.state().examples);
  readonly examplesStatus = computed(() => this.state().examplesStatus);
  readonly entries = computed(() => this.state().entries);
  readonly history = computed(() => this.state().history);
  readonly historyStatus = computed(() => this.state().historyStatus);
  readonly historyError = computed(() => this.state().historyError);
  readonly hasMoreHistory = computed(() => this.state().historyCursor !== null);
  /** Epoch milliseconds, updated every second while something on screen counts. */
  readonly now: Signal<number> = this.clock.asReadonly();

  /** The model a question goes to: the user's pick, else the server's default. */
  readonly selectedModelId = computed(() => {
    const { models, chosenModelId, defaultModelId } = this.state();
    const enabled = (id: string | null) => id !== null && models.some((model) => model.id === id);
    if (enabled(chosenModelId)) {
      return chosenModelId;
    }
    return enabled(defaultModelId) ? defaultModelId : (models.at(0)?.id ?? null);
  });

  readonly isAsking = computed(() =>
    this.state().entries.some((entry) => entry.state.kind === 'pending'),
  );

  /** Whole seconds until the rate limit lets another question through; 0 when it does. */
  readonly secondsUntilAskable = computed(() => {
    const { askableAt } = this.state();
    return askableAt === null ? 0 : Math.max(0, Math.ceil((askableAt - this.now()) / 1000));
  });

  readonly canAsk = computed(() => !this.isAsking() && this.secondsUntilAskable() === 0);

  constructor() {
    effect(() => {
      const userId = this.auth.user()?.id ?? null;
      untracked(() => {
        this.checkOwner(userId);
      });
    });
    inject(DestroyRef).onDestroy(() => {
      this.requests.unsubscribe();
      this.stopClock();
    });
  }

  /** Loads the models, examples and first history page, skipping what is already loaded. */
  load(): void {
    const { modelsStatus, examplesStatus, historyStatus } = this.state();
    if (modelsStatus === 'idle' || modelsStatus === 'failed') {
      this.loadModels();
    }
    if (examplesStatus === 'idle' || examplesStatus === 'failed') {
      this.loadExamples();
    }
    if (historyStatus === 'idle' || historyStatus === 'failed') {
      this.loadHistory();
    }
  }

  selectModel(id: string): void {
    this.patch({ chosenModelId: id });
  }

  /** The label of a model id, or the id itself for a model no longer offered. */
  modelLabel(id: string | null): string {
    if (id === null) {
      return 'the default model';
    }
    return this.state().models.find((model) => model.id === id)?.label ?? id;
  }

  /** Enabled models other than `id`, for a receipt that suggests asking another one. */
  otherModels(id: string | null): readonly ModelOut[] {
    return this.state().models.filter((model) => model.id !== id);
  }

  /**
   * Asks a question, with `modelId` when it is still enabled and otherwise
   * the selected model. Returns false, and asks nothing, while another
   * question is pending or the rate limit is in force.
   */
  ask(question: string, modelId?: string | null): boolean {
    if (!this.canAsk()) {
      return false;
    }
    const enabled = this.state().models.some((model) => model.id === modelId);
    const model = enabled ? (modelId ?? null) : this.selectedModelId();
    const key = this.nextKey++;
    const entry: ThreadEntry = {
      key,
      question,
      modelId: model,
      startedAt: Date.now(),
      state: { kind: 'pending' },
    };
    this.patch({ entries: [entry, ...this.state().entries] });
    this.startClock();
    this.requests.add(
      this.api.ask(model === null ? { question } : { question, model }).subscribe({
        next: (answer) => {
          this.settle(key, { kind: 'answered', answer });
          this.refreshHistory();
        },
        error: (error: unknown) => {
          this.fail(key, parseApiError(error));
        },
      }),
    );
    return true;
  }

  /**
   * Shows a history item at the top of the thread and returns its entry's
   * key. A question already in the thread moves up rather than repeating.
   */
  recall(item: HistoryItemOut): number {
    const { entries } = this.state();
    const existing = entries.find((entry) => auditIdOf(entry) === item.id);
    const entry: ThreadEntry = existing ?? {
      key: this.nextKey++,
      question: item.question,
      modelId: item.requested_model,
      startedAt: Date.parse(item.created_at),
      state: { kind: 'recalled', item },
    };
    this.patch({ entries: [entry, ...entries.filter((other) => other !== entry)] });
    return entry.key;
  }

  /** Appends the next, older page of history. */
  loadMoreHistory(): void {
    const { historyStatus, historyCursor } = this.state();
    if (historyStatus === 'loaded' && historyCursor !== null) {
      this.loadHistory(historyCursor);
    }
  }

  /** Repeats the history request that failed. */
  retryHistory(): void {
    const { historyStatus, historyCursor } = this.state();
    if (historyStatus === 'failed') {
      this.loadHistory();
    } else if (historyStatus === 'more-failed' && historyCursor !== null) {
      this.loadHistory(historyCursor);
    }
  }

  private loadModels(): void {
    this.patch({ modelsStatus: 'loading' });
    this.requests.add(
      this.api.models().subscribe({
        next: (page) => {
          this.patch({
            models: page.items,
            defaultModelId: page.default_model,
            modelsStatus: 'loaded',
          });
        },
        error: () => {
          this.patch({ modelsStatus: 'failed' });
        },
      }),
    );
  }

  private loadExamples(): void {
    this.patch({ examplesStatus: 'loading' });
    this.requests.add(
      this.api.examples().subscribe({
        next: (page) => {
          this.patch({
            examples: page.items.map((example) => example.question),
            examplesStatus: 'loaded',
          });
        },
        error: () => {
          this.patch({ examplesStatus: 'failed' });
        },
      }),
    );
  }

  private loadHistory(cursor: string | null = null): void {
    this.patch({
      historyStatus: cursor === null ? 'loading' : 'loading-more',
      historyError: null,
    });
    const query =
      cursor === null ? { limit: HISTORY_PAGE_SIZE } : { limit: HISTORY_PAGE_SIZE, cursor };
    this.requests.add(
      this.api.history(query).subscribe({
        next: (page) => {
          this.patch({
            history: cursor === null ? page.items : [...this.state().history, ...page.items],
            historyCursor: page.next_cursor,
            historyStatus: 'loaded',
          });
        },
        error: (error: unknown) => {
          const apiError = parseApiError(error);
          if (cursor !== null && apiError.code === 'invalid_cursor') {
            // The server no longer accepts this cursor; the first page always works.
            this.loadHistory();
            return;
          }
          this.patch({
            historyStatus: cursor === null ? 'failed' : 'more-failed',
            historyError: apiError,
          });
        },
      }),
    );
  }

  /**
   * Adds the questions recorded since the history was loaded, keeping the
   * older pages already shown. A failure leaves the list as it is: the
   * question's own receipt has already told the user what happened.
   */
  private refreshHistory(): void {
    if (this.state().historyStatus !== 'loaded') {
      this.loadHistory();
      return;
    }
    this.requests.add(
      this.api.history({ limit: HISTORY_PAGE_SIZE }).subscribe({
        next: (page) => {
          this.mergeNewestHistory(page);
        },
        error: () => undefined,
      }),
    );
  }

  private mergeNewestHistory(page: HistoryPageOut): void {
    const { history } = this.state();
    const newest = history.at(0)?.id ?? 0;
    const added = page.items.filter((item) => item.id > newest);
    this.patch({ history: [...added, ...history] });
  }

  private settle(key: number, state: EntryState): void {
    this.patch({
      entries: this.state().entries.map((entry) =>
        entry.key === key ? { ...entry, state } : entry,
      ),
    });
  }

  private fail(key: number, error: ApiError): void {
    const settledAt = Date.now();
    this.settle(key, { kind: 'failed', error, settledAt });
    if (error.code === 'rate_limited') {
      const seconds = error.retryAfterSeconds ?? RATE_LIMIT_FALLBACK_SECONDS;
      this.patch({ askableAt: settledAt + seconds * 1000 });
    }
    if (error.code === 'model_not_available') {
      // The list the user picked from is out of date: reload it, and let the
      // selection fall back to the server's default.
      this.patch({ chosenModelId: null });
      this.loadModels();
    }
    if (failureReceipt(error) !== null) {
      this.refreshHistory();
    }
    this.startClock();
  }

  private checkOwner(userId: number | null): void {
    if (this.ownerId !== undefined && userId !== this.ownerId) {
      this.reset();
    }
    this.ownerId = userId;
  }

  private reset(): void {
    this.requests.unsubscribe();
    this.requests = new Subscription();
    this.stopClock();
    this.state.set(INITIAL_STATE);
  }

  /** True while something on screen counts seconds: a pending question or a wait. */
  private needsClock(): boolean {
    const now = Date.now();
    const { entries, askableAt } = this.state();
    return (
      (askableAt !== null && askableAt > now) ||
      entries.some((entry) => entry.state.kind === 'pending' || (retryAtOf(entry) ?? 0) > now)
    );
  }

  private startClock(): void {
    this.clock.set(Date.now());
    if (this.ticker !== null || !this.needsClock()) {
      return;
    }
    this.ticker = setInterval(() => {
      this.clock.set(Date.now());
      if (!this.needsClock()) {
        this.stopClock();
      }
    }, TICK_MS);
  }

  private stopClock(): void {
    if (this.ticker !== null) {
      clearInterval(this.ticker);
      this.ticker = null;
    }
  }

  private patch(changes: Partial<AskState>): void {
    this.state.update((state) => ({ ...state, ...changes }));
  }
}
