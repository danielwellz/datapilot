import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ApiError } from '../../core/api/api-error';
import { UserOut } from '../../core/api/models';
import { failWith } from '../../core/api/testing';
import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { AI_URL } from './ask-api';
import {
  AskStore,
  HISTORY_PAGE_SIZE,
  RATE_LIMIT_FALLBACK_SECONDS,
  auditIdOf,
  retryAtOf,
} from './ask.store';
import { askOut, historyItemOut, historyPageOut, modelsOut } from './testing';

const QUESTION = 'What was the monthly revenue over the last 12 months?';

describe('AskStore', () => {
  let store: AskStore;
  let http: HttpTestingController;
  let user: ReturnType<typeof signal<UserOut | null>>;

  beforeEach(() => {
    user = signal<UserOut | null>(userOut());
    TestBed.configureTestingModule({
      providers: [
        AskStore,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { user } },
      ],
    });
    store = TestBed.inject(AskStore);
    http = TestBed.inject(HttpTestingController);
    TestBed.tick();
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  function expectAsk(): TestRequest {
    return http.expectOne(`${AI_URL}/ask`);
  }

  function expectHistory(): TestRequest {
    return http.expectOne((request) => request.url === `${AI_URL}/history`);
  }

  /** Loads models, examples and history with the given history page. */
  function loadAll(page = historyPageOut()): void {
    store.load();
    http.expectOne(`${AI_URL}/models`).flush(modelsOut());
    http.expectOne(`${AI_URL}/examples`).flush({ items: [{ question: QUESTION }] });
    expectHistory().flush(page);
  }

  function rateLimit(request: TestRequest, retryAfter: string | null): void {
    request.flush(
      { error: { code: 'rate_limited', message: 'Slow down.', details: [], request_id: 'r' } },
      {
        status: 429,
        statusText: 'Too Many Requests',
        headers: retryAfter === null ? {} : { 'Retry-After': retryAfter },
      },
    );
  }

  function receiptError(request: TestRequest, code: string, status: number, auditId = 130): void {
    request.flush(
      {
        error: {
          code,
          message: `Failed with ${code}.`,
          details: [
            {
              audit_id: auditId,
              requested_model: 'fake',
              model: 'fake',
              provider: 'fake',
              sql: null,
            },
          ],
          request_id: 'r',
        },
      },
      { status, statusText: 'Error' },
    );
  }

  describe('loading', () => {
    it('loads the models, examples and first history page', () => {
      loadAll();

      expect(store.models().map((model) => model.id)).toEqual([
        'fake',
        'groq-gpt-oss-120b',
        'gemini-3.5-flash-lite',
      ]);
      expect(store.examples()).toEqual([QUESTION]);
      expect(store.history()).toHaveLength(1);
      expect(store.historyStatus()).toBe('loaded');
    });

    it('asks for a page of history', () => {
      store.load();
      http.expectOne(`${AI_URL}/models`).flush(modelsOut());
      http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
      const request = expectHistory();

      expect(request.request.params.get('limit')).toBe(String(HISTORY_PAGE_SIZE));
      expect(request.request.params.has('cursor')).toBe(false);
      request.flush(historyPageOut());
    });

    it('does not load again what is already loaded', () => {
      loadAll();

      store.load();
      http.expectNone(`${AI_URL}/models`);
    });

    it('loads only what failed on the next load', () => {
      store.load();
      failWith(http.expectOne(`${AI_URL}/models`), 502, 'http_error');
      http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
      expectHistory().flush(historyPageOut());
      expect(store.modelsStatus()).toBe('failed');

      store.load();
      http.expectOne(`${AI_URL}/models`).flush(modelsOut());

      expect(store.modelsStatus()).toBe('loaded');
    });

    it('marks failed examples', () => {
      store.load();
      http.expectOne(`${AI_URL}/models`).flush(modelsOut());
      failWith(http.expectOne(`${AI_URL}/examples`), 502, 'http_error');
      expectHistory().flush(historyPageOut());

      expect(store.examplesStatus()).toBe('failed');
    });
  });

  describe('the selected model', () => {
    it("defaults to the server's default model", () => {
      loadAll();

      expect(store.selectedModelId()).toBe('fake');
    });

    it('is the model the user picked', () => {
      loadAll();

      store.selectModel('groq-gpt-oss-120b');

      expect(store.selectedModelId()).toBe('groq-gpt-oss-120b');
    });

    it('falls back to the default when the pick is not offered', () => {
      loadAll();

      store.selectModel('retired-model');

      expect(store.selectedModelId()).toBe('fake');
    });

    it('falls back to the first model when the default is not offered', () => {
      store.load();
      http.expectOne(`${AI_URL}/models`).flush({ ...modelsOut(), default_model: 'gone' });
      http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
      expectHistory().flush(historyPageOut());

      expect(store.selectedModelId()).toBe('fake');
    });

    it('is null before the models are known', () => {
      expect(store.selectedModelId()).toBeNull();
    });

    it('is sent with the question', () => {
      loadAll();
      store.selectModel('gemini-3.5-flash-lite');

      store.ask(QUESTION);

      expect(expectAsk().request.body).toEqual({
        question: QUESTION,
        model: 'gemini-3.5-flash-lite',
      });
    });

    it("leaves the model out, for the server's default, when the models failed to load", () => {
      store.ask(QUESTION);

      expect(expectAsk().request.body).toEqual({ question: QUESTION });
    });

    it('can be overridden for one question by an enabled model', () => {
      loadAll();

      store.ask(QUESTION, 'groq-gpt-oss-120b');

      expect(expectAsk().request.body).toEqual({ question: QUESTION, model: 'groq-gpt-oss-120b' });
      expect(store.entries()[0]?.modelId).toBe('groq-gpt-oss-120b');
    });

    it('is used when the override is no longer offered', () => {
      loadAll();

      store.ask(QUESTION, 'retired-model');

      expect(expectAsk().request.body).toEqual({ question: QUESTION, model: 'fake' });
    });

    it('names models by label, and keeps the id of one no longer offered', () => {
      loadAll();

      expect(store.modelLabel('groq-gpt-oss-120b')).toBe('GPT-OSS 120B (Groq)');
      expect(store.modelLabel('retired-model')).toBe('retired-model');
      expect(store.modelLabel(null)).toBe('the default model');
    });

    it('lists the other models for a receipt to suggest', () => {
      loadAll();

      expect(store.otherModels('fake').map((model) => model.id)).toEqual([
        'groq-gpt-oss-120b',
        'gemini-3.5-flash-lite',
      ]);
    });
  });

  describe('asking', () => {
    beforeEach(() => {
      loadAll(historyPageOut([historyItemOut({ id: 120 })]));
    });

    it('puts a pending entry at the top of the thread', () => {
      store.ask(QUESTION);

      expect(store.isAsking()).toBe(true);
      expect(store.canAsk()).toBe(false);
      expect(store.entries()[0]).toMatchObject({
        question: QUESTION,
        modelId: 'fake',
        state: { kind: 'pending' },
      });
      expectAsk().flush(askOut());
      expectHistory().flush(historyPageOut());
    });

    it('settles the entry with the answer and refreshes the history', () => {
      store.ask(QUESTION);
      expectAsk().flush(askOut({ id: 124 }));

      expect(store.isAsking()).toBe(false);
      expect(store.entries()[0]?.state).toEqual({ kind: 'answered', answer: askOut({ id: 124 }) });

      expectHistory().flush(
        historyPageOut([historyItemOut({ id: 124 }), historyItemOut({ id: 120 })]),
      );
      expect(store.history().map((item) => item.id)).toEqual([124, 120]);
    });

    it('keeps older history pages when it adds the newest question', () => {
      store.loadMoreHistory();
      // The first page had no cursor, so nothing more is asked for.
      http.expectNone((request) => request.url === `${AI_URL}/history`);

      store.ask(QUESTION);
      expectAsk().flush(askOut({ id: 124 }));
      expectHistory().flush(historyPageOut([historyItemOut({ id: 124 })], 'next'));

      expect(store.history().map((item) => item.id)).toEqual([124, 120]);
      expect(store.hasMoreHistory()).toBe(false);
    });

    it('keeps the history as it is when the refresh fails', () => {
      store.ask(QUESTION);
      expectAsk().flush(askOut({ id: 124 }));
      failWith(expectHistory(), 502, 'http_error');

      expect(store.history().map((item) => item.id)).toEqual([120]);
      expect(store.historyStatus()).toBe('loaded');
    });

    it('puts newer questions above older ones', () => {
      store.ask('First question?');
      expectAsk().flush(askOut({ id: 124 }));
      expectHistory().flush(historyPageOut());
      store.ask('Second question?');
      expectAsk().flush(askOut({ id: 125 }));
      expectHistory().flush(historyPageOut());

      expect(store.entries().map((entry) => entry.question)).toEqual([
        'Second question?',
        'First question?',
      ]);
    });

    it('asks nothing while another question is pending', () => {
      store.ask('First question?');

      expect(store.ask('Second question?')).toBe(false);
      expectAsk().flush(askOut());
      expectHistory().flush(historyPageOut());
      expect(store.entries()).toHaveLength(1);
    });

    it('settles the entry with the error and refreshes the history of an audited failure', () => {
      store.ask(QUESTION);
      receiptError(expectAsk(), 'sql_rejected', 422);

      const state = store.entries()[0]?.state;
      expect(state.kind).toBe('failed');
      expect(state.kind === 'failed' && state.error.code).toBe('sql_rejected');
      expectHistory().flush(historyPageOut());
    });

    it('does not refresh the history after a failure that was never recorded', () => {
      store.ask(QUESTION);
      failWith(expectAsk(), 0, 'network_error');

      http.expectNone((request) => request.url === `${AI_URL}/history`);
      expect(store.canAsk()).toBe(true);
    });

    it('reloads the models and returns to the default after an unavailable model', () => {
      store.selectModel('groq-gpt-oss-120b');
      store.ask(QUESTION);
      failWith(expectAsk(), 422, 'model_not_available');

      http.expectOne(`${AI_URL}/models`).flush(modelsOut());
      expect(store.selectedModelId()).toBe('fake');
    });
  });

  describe('the rate limit', () => {
    beforeEach(() => {
      vi.useFakeTimers({ now: new Date('2026-10-09T14:00:00Z') });
      loadAll();
    });

    it('counts down the seconds from Retry-After and then lets questions through', () => {
      store.ask(QUESTION);
      rateLimit(expectAsk(), '3');

      expect(store.secondsUntilAskable()).toBe(3);
      expect(store.canAsk()).toBe(false);
      expect(store.ask(QUESTION)).toBe(false);

      vi.advanceTimersByTime(1000);
      expect(store.secondsUntilAskable()).toBe(2);

      vi.advanceTimersByTime(2000);
      expect(store.secondsUntilAskable()).toBe(0);
      expect(store.canAsk()).toBe(true);
    });

    it("waits the limiter's window when Retry-After is missing", () => {
      store.ask(QUESTION);
      rateLimit(expectAsk(), null);

      expect(store.secondsUntilAskable()).toBe(RATE_LIMIT_FALLBACK_SECONDS);
    });

    it('stops the clock once nothing counts', () => {
      store.ask(QUESTION);
      rateLimit(expectAsk(), '1');
      vi.advanceTimersByTime(1000);
      const stopped = store.now();

      vi.advanceTimersByTime(5000);

      expect(store.now()).toBe(stopped);
    });

    it('ticks the clock while a question is pending', () => {
      store.ask(QUESTION);
      const started = store.now();

      vi.advanceTimersByTime(3000);

      expect(store.now() - started).toBe(3000);
      expectAsk().flush(askOut());
      expectHistory().flush(historyPageOut());
    });

    it("keeps a provider's wait on the entry, without blocking other questions", () => {
      store.ask(QUESTION, 'groq-gpt-oss-120b');
      expectAsk().flush(
        {
          error: {
            code: 'llm_rate_limited',
            message: 'The provider is limiting requests.',
            details: [
              {
                audit_id: 131,
                requested_model: 'groq-gpt-oss-120b',
                model: null,
                provider: null,
                sql: null,
              },
            ],
            request_id: 'r',
          },
        },
        { status: 503, statusText: 'Unavailable', headers: { 'Retry-After': '20' } },
      );
      expectHistory().flush(historyPageOut());

      const entry = store.entries()[0];
      expect(retryAtOf(entry)).toBe(Date.parse('2026-10-09T14:00:20Z'));
      expect(store.canAsk()).toBe(true);
      vi.advanceTimersByTime(5000);
      expect(store.now()).toBe(Date.parse('2026-10-09T14:00:05Z'));
    });
  });

  describe('history', () => {
    it('appends older pages with the cursor', () => {
      loadAll(historyPageOut([historyItemOut({ id: 120 })], 'c1'));

      store.loadMoreHistory();
      expect(store.historyStatus()).toBe('loading-more');
      const request = expectHistory();
      expect(request.request.params.get('cursor')).toBe('c1');
      request.flush(historyPageOut([historyItemOut({ id: 110 })]));

      expect(store.history().map((item) => item.id)).toEqual([120, 110]);
      expect(store.hasMoreHistory()).toBe(false);
    });

    it('retries a failed first page', () => {
      store.load();
      http.expectOne(`${AI_URL}/models`).flush(modelsOut());
      http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
      failWith(expectHistory(), 502, 'http_error');
      expect(store.historyStatus()).toBe('failed');
      expect(store.historyError()?.code).toBe('http_error');

      store.retryHistory();
      expectHistory().flush(historyPageOut());

      expect(store.historyStatus()).toBe('loaded');
      expect(store.historyError()).toBeNull();
    });

    it('retries a failed older page with its cursor', () => {
      loadAll(historyPageOut([historyItemOut({ id: 120 })], 'c1'));
      store.loadMoreHistory();
      failWith(expectHistory(), 502, 'http_error');
      expect(store.historyStatus()).toBe('more-failed');

      store.retryHistory();
      const request = expectHistory();

      expect(request.request.params.get('cursor')).toBe('c1');
      request.flush(historyPageOut([historyItemOut({ id: 110 })]));
      expect(store.history()).toHaveLength(2);
    });

    it('does nothing on retry when nothing failed', () => {
      loadAll();

      store.retryHistory();

      http.expectNone((request) => request.url === `${AI_URL}/history`);
    });

    it('starts again from the first page when the cursor is refused', () => {
      loadAll(historyPageOut([historyItemOut({ id: 120 })], 'stale'));
      store.loadMoreHistory();
      failWith(expectHistory(), 400, 'invalid_cursor');

      const request = expectHistory();
      expect(request.request.params.has('cursor')).toBe(false);
      request.flush(historyPageOut([historyItemOut({ id: 121 })]));
      expect(store.history().map((item) => item.id)).toEqual([121]);
    });

    it('loads the first page on a refresh when it had failed', () => {
      store.load();
      http.expectOne(`${AI_URL}/models`).flush(modelsOut());
      http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
      failWith(expectHistory(), 502, 'http_error');

      store.ask(QUESTION);
      expectAsk().flush(askOut({ id: 124 }));
      expectHistory().flush(historyPageOut([historyItemOut({ id: 124 })]));

      expect(store.historyStatus()).toBe('loaded');
      expect(store.history().map((item) => item.id)).toEqual([124]);
    });
  });

  describe('recalling a history item', () => {
    beforeEach(() => {
      loadAll();
    });

    it('shows it at the top of the thread without asking anything', () => {
      const item = historyItemOut({ id: 120 });

      const key = store.recall(item);

      expect(store.entries()[0]).toEqual({
        key,
        question: item.question,
        modelId: 'fake',
        startedAt: Date.parse(item.created_at),
        state: { kind: 'recalled', item },
      });
      http.expectNone(`${AI_URL}/ask`);
    });

    it('moves a question already in the thread to the top instead of repeating it', () => {
      store.ask(QUESTION);
      expectAsk().flush(askOut({ id: 124 }));
      expectHistory().flush(historyPageOut());
      store.recall(historyItemOut({ id: 120 }));

      const key = store.recall(historyItemOut({ id: 124, question: QUESTION }));

      expect(store.entries()).toHaveLength(2);
      expect(store.entries()[0]?.key).toBe(key);
      expect(store.entries()[0]?.state.kind).toBe('answered');
    });

    it('can be asked again, as a new question', () => {
      store.recall(historyItemOut({ id: 120, requested_model: 'groq-gpt-oss-120b' }));
      const recalled = store.entries()[0];

      store.ask(recalled.question, recalled.modelId);

      expect(expectAsk().request.body).toEqual({
        question: recalled.question,
        model: 'groq-gpt-oss-120b',
      });
      expect(store.entries()).toHaveLength(2);
    });
  });

  describe('auditIdOf and retryAtOf', () => {
    const base = { key: 1, question: QUESTION, modelId: null, startedAt: 0 };
    const receipt = {
      audit_id: 7,
      requested_model: 'fake',
      model: null,
      provider: null,
      sql: null,
    };

    it('reads the audit id of every kind of entry', () => {
      expect(auditIdOf({ ...base, state: { kind: 'pending' } })).toBeNull();
      expect(auditIdOf({ ...base, state: { kind: 'answered', answer: askOut({ id: 5 }) } })).toBe(
        5,
      );
      expect(
        auditIdOf({ ...base, state: { kind: 'recalled', item: historyItemOut({ id: 6 }) } }),
      ).toBe(6);
      const audited = new ApiError(422, 'sql_rejected', 'Refused.', [receipt]);
      expect(auditIdOf({ ...base, state: { kind: 'failed', error: audited, settledAt: 0 } })).toBe(
        7,
      );
      const unaudited = new ApiError(0, 'network_error', 'Offline.');
      expect(
        auditIdOf({ ...base, state: { kind: 'failed', error: unaudited, settledAt: 0 } }),
      ).toBeNull();
    });

    it('has no retry time for an entry that did not fail with a wait', () => {
      expect(retryAtOf({ ...base, state: { kind: 'pending' } })).toBeNull();
      const error = new ApiError(503, 'llm_unavailable', 'No model.');
      expect(retryAtOf({ ...base, state: { kind: 'failed', error, settledAt: 0 } })).toBeNull();
    });
  });

  describe('a change of user', () => {
    it('clears the thread, history and models when the user logs out', () => {
      loadAll();
      store.recall(historyItemOut());

      user.set(null);
      TestBed.tick();

      expect(store.entries()).toEqual([]);
      expect(store.history()).toEqual([]);
      expect(store.models()).toEqual([]);
      expect(store.historyStatus()).toBe('idle');
    });

    it('drops the answer of a question asked by the previous user', () => {
      loadAll();
      store.ask(QUESTION);
      const pending = expectAsk();

      user.set(userOut({ id: 2, email: 'other@example.com' }));
      TestBed.tick();

      expect(pending.cancelled).toBe(true);
      expect(store.entries()).toEqual([]);
      expect(store.canAsk()).toBe(true);
    });

    it('keeps everything while the same user stays signed in', () => {
      loadAll();
      store.recall(historyItemOut());

      user.set(userOut());
      TestBed.tick();

      expect(store.entries()).toHaveLength(1);
    });
  });
});
