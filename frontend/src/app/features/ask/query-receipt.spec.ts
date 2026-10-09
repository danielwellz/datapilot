import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import {
  ComponentFixture,
  DeferBlockBehavior,
  DeferBlockState,
  TestBed,
} from '@angular/core/testing';

import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { ChartConfig } from '../../shared/chart/chart-config';
import { provideFakeCharts } from '../../shared/chart/testing';
import { AI_URL } from './ask-api';
import { AskStore, ThreadEntry } from './ask.store';
import { MAX_OTHER_MODELS, QueryReceipt, receiptNumber, rowsText } from './query-receipt';
import { askOut, historyItemOut, historyPageOut, modelOut, modelsOut } from './testing';

const STARTED = Date.parse('2026-10-09T14:02:00Z');

function answered(overrides: Parameters<typeof askOut>[0] = {}): ThreadEntry {
  const answer = askOut(overrides);
  return {
    key: 1,
    question: answer.question,
    modelId: answer.requested_model,
    startedAt: STARTED,
    state: { kind: 'answered', answer },
  };
}

@Component({
  imports: [QueryReceipt],
  template: `<dp-query-receipt [entry]="entry()" />`,
})
class Host {
  readonly entry = signal<ThreadEntry>(answered());
}

describe('receiptNumber and rowsText', () => {
  it('pads the audit id to six digits', () => {
    expect(receiptNumber(124)).toBe('000124');
    expect(receiptNumber(1_234_567)).toBe('1234567');
  });

  it('says when the row limit cut the result short', () => {
    expect(rowsText(12, false)).toBe('12');
    expect(rowsText(1000, true)).toBe('1,000, the limit; more rows matched');
  });
});

describe('QueryReceipt', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let drawn: ChartConfig[];

  async function render(entry: ThreadEntry): Promise<void> {
    drawn = [];
    TestBed.configureTestingModule({
      deferBlockBehavior: DeferBlockBehavior.Manual,
      providers: [
        provideFakeCharts(drawn),
        AskStore,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { user: signal(userOut()) } },
      ],
    });
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.entry.set(entry);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function text(selector: string): string {
    return (element.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  function ledger(): Record<string, string> {
    const lines: Record<string, string> = {};
    for (const line of element.querySelectorAll('.receipt__line')) {
      const label = line.querySelector('dt')?.textContent.trim() ?? '';
      lines[label] = (line.querySelector('dd')?.textContent ?? '').replace(/\s+/g, ' ').trim();
    }
    return lines;
  }

  it('heads the receipt with its number and the time it was answered, in UTC', async () => {
    await render(answered());

    expect(text('.receipt__head span')).toBe('Receipt 000124');
    const time = element.querySelector('time');
    expect(time?.getAttribute('datetime')).toBe('2026-10-09T14:02:00Z');
    expect(time?.textContent.trim()).toBe('Oct 9, 2026, 14:02 UTC');
  });

  it('labels the receipt with its question and shows the explanation', async () => {
    await render(answered());

    const question = element.querySelector('h2');
    expect(question?.textContent.trim()).toBe(
      'What was the monthly revenue over the last 12 months?',
    );
    expect(element.querySelector('article')?.getAttribute('aria-labelledby')).toBe(question?.id);
    expect(text('.receipt__explanation')).toBe(
      'Revenue from paid orders in each of the last 12 complete months.',
    );
  });

  it('lists the model, rows, time and assumptions in the ledger', async () => {
    await render(answered());

    expect(ledger()).toEqual({
      Model: 'Demo model (example questions only)',
      Rows: '2',
      Time: '214 ms',
      Assumed: 'The current month is left out because it is not complete yet.',
    });
  });

  it('notes a fallback to another model', async () => {
    await render(
      answered({
        requested_model: 'groq-qwen3.8-27b',
        fell_back: true,
        model: {
          id: 'groq-gpt-oss-120b',
          label: 'GPT-OSS 120B (Groq)',
          provider: 'groq',
          provider_label: 'Groq',
        },
      }),
    );

    expect(ledger()['Model']).toBe(
      "GPT-OSS 120B (Groq) groq-qwen3.8-27b couldn't answer, so this model did.",
    );
  });

  it('notes a corrected query and a truncated result', async () => {
    await render(answered({ repaired: true, truncated: true, row_count: 1000, assumptions: [] }));

    expect(ledger()).toMatchObject({
      Rows: '1,000, the limit; more rows matched',
      Corrected: 'Once, after the database refused the first query',
    });
    expect(ledger()['Assumed']).toBeUndefined();
  });

  it('offers the SQL that ran', async () => {
    await render(answered());

    expect(text('.receipt-sql__toggle')).toContain('Show SQL that ran');
  });

  it('shows the result rows under the SQL', async () => {
    await render(answered());

    const region = element.querySelector('dp-result-table [role="region"]');
    expect(region?.getAttribute('aria-label')).toBe(
      'Result of: What was the monthly revenue over the last 12 months?',
    );
    expect(element.querySelectorAll('dp-result-table tbody tr')).toHaveLength(2);
    expect(text('.receipt__section:last-child .receipt__note')).toBe('');
  });

  it('says how to get the rows a truncated result left out', async () => {
    await render(answered({ truncated: true, row_count: 1000 }));

    expect(text('.receipt__section:last-child .receipt__note')).toBe(
      'Showing the first 1,000 rows, the most one answer returns. More rows matched: ask for fewer, for example a top 10 or a shorter period.',
    );
  });

  it('draws the chart the model suggested once it is in view', async () => {
    await render(answered());
    expect(element.querySelector('.receipt__chart-placeholder')).not.toBeNull();
    expect(drawn).toHaveLength(0);

    for (const block of await fixture.getDeferBlocks()) {
      await block.render(DeferBlockState.Complete);
    }

    expect(drawn).toHaveLength(1);
    expect(drawn[0]?.type).toBe('line');
    expect(drawn[0]?.data.labels).toEqual(['Aug 2026', 'Sep 2026']);
  });

  it('draws no chart when the shape does not fit the suggestion', async () => {
    await render(
      answered({
        chart: 'line',
        columns: [
          { name: 'country', type: 'string' },
          { name: 'revenue', type: 'number' },
        ],
        rows: [
          ['DE', '1'],
          ['GB', '2'],
        ],
      }),
    );

    expect(element.querySelector('.receipt__chart-placeholder')).toBeNull();
    expect(await fixture.getDeferBlocks()).toHaveLength(0);
  });

  it('shows a pending question with the model asked and the seconds so far', async () => {
    vi.useFakeTimers({ now: STARTED + 3200, toFake: ['Date'] });
    try {
      await render({
        key: 2,
        question: 'Orders by channel this year',
        modelId: 'fake',
        startedAt: STARTED,
        state: { kind: 'pending' },
      });

      expect(text('.receipt__head span')).toBe('Receipt pending');
      expect(element.querySelector('article')?.getAttribute('aria-busy')).toBe('true');
      expect(text('[role="status"]')).toBe('Asking fake.');
      expect(text('.receipt__elapsed')).toBe('3 s');
      expect(element.querySelector('.receipt__ledger')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('QueryReceipt for a question without an answer', () => {
  const QUESTION = 'Delete all cancelled orders';
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let store: AskStore;
  let http: HttpTestingController;

  /** A store with `models` enabled, and fake time from STARTED. */
  function setUp(models = modelsOut()): void {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        AskStore,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { user: signal(userOut()) } },
      ],
    });
    store = TestBed.inject(AskStore);
    http = TestBed.inject(HttpTestingController);
    store.load();
    http.expectOne(`${AI_URL}/models`).flush(models);
    http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
    http.expectOne((request) => request.url === `${AI_URL}/history`).flush(historyPageOut([]));
  }

  beforeEach(() => {
    vi.useFakeTimers({ now: STARTED, toFake: ['Date', 'setInterval', 'clearInterval'] });
    setUp();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Asks through the store, answers with `respond`, and renders the receipt. */
  async function askAndRender(respond: (request: TestRequest) => void): Promise<void> {
    store.ask(QUESTION);
    respond(http.expectOne(`${AI_URL}/ask`));
    http
      .match((request) => request.url === `${AI_URL}/history`)
      .forEach((request) => {
        request.flush(historyPageOut([]));
      });
    await renderEntry(store.entries()[0]);
  }

  async function renderEntry(entry: ThreadEntry): Promise<void> {
    fixture = TestBed.createComponent(Host);
    fixture.componentInstance.entry.set(entry);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function errorBody(code: string, message: string, details: object[] = []) {
    return { error: { code, message, details, request_id: 'req-42' } };
  }

  function refused(request: TestRequest): void {
    request.flush(
      errorBody('sql_rejected', 'The generated query was not safe to run.', [
        {
          audit_id: 130,
          requested_model: 'fake',
          model: 'fake',
          provider: 'fake',
          sql: "DELETE FROM v_orders WHERE status = 'cancelled'",
          reason: 'data_modification',
        },
      ]),
      { status: 422, statusText: 'Unprocessable' },
    );
  }

  function text(selector: string): string {
    return (element.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  function buttons(): HTMLButtonElement[] {
    return [...element.querySelectorAll<HTMLButtonElement>('.receipt__actions button')];
  }

  function button(label: string): HTMLButtonElement {
    const found = buttons().find((candidate) => candidate.textContent.trim() === label);
    if (found === undefined) {
      throw new Error(`No button "${label}"`);
    }
    return found;
  }

  /** Shown as unavailable but still focusable, so pressing it keeps focus where it is. */
  function unavailable(candidate: HTMLButtonElement): boolean {
    return candidate.getAttribute('aria-disabled') === 'true' && !candidate.disabled;
  }

  function notes(): string[] {
    return [...element.querySelectorAll('.receipt__notes dd')].map((dd) => dd.textContent.trim());
  }

  it('stamps a refused query, says why and announces it', async () => {
    await askAndRender(refused);

    expect(text('.receipt__head span')).toBe('Receipt 000130');
    expect(text('.receipt__stamp')).toBe('Refused');
    expect(element.querySelector('.receipt__failure')?.getAttribute('role')).toBe('alert');
    expect(notes()).toEqual([
      'The query would have changed data, and DataPilot only runs queries that read it. Nothing was run.',
      'Ask for figures to read rather than changes to make, or ask another model.',
    ]);
    expect(text('.request-id')).toBe('Request ID req-42');
  });

  it('shows the refused SQL and the model that wrote it', async () => {
    await askAndRender(refused);

    expect(text('.receipt__line dd')).toBe('Demo model (example questions only)');
    expect(text('.receipt-sql__toggle')).toContain('Show SQL that was refused');
    expect(element.querySelector('dp-result-table')).toBeNull();
  });

  it('offers the other models, but not the same question again', async () => {
    await askAndRender(refused);

    expect(buttons().map((candidate) => candidate.textContent.trim())).toEqual([
      'Ask GPT-OSS 120B (Groq) instead',
      'Ask Gemini 3.5 Flash-Lite instead',
    ]);

    button('Ask Gemini 3.5 Flash-Lite instead').click();

    expect(http.expectOne(`${AI_URL}/ask`).request.body).toEqual({
      question: QUESTION,
      model: 'gemini-3.5-flash-lite',
    });
  });

  it(`offers at most ${String(MAX_OTHER_MODELS)} other models`, async () => {
    const models = modelsOut();
    models.items.push(modelOut({ id: 'a', label: 'A' }), modelOut({ id: 'b', label: 'B' }));
    setUp(models);

    await askAndRender(refused);

    expect(buttons()).toHaveLength(MAX_OTHER_MODELS);
  });

  it('counts down the per-user limit before the question can be asked again', async () => {
    await askAndRender((request) => {
      request.flush(errorBody('rate_limited', 'You can ask 10 questions a minute.'), {
        status: 429,
        statusText: 'Too Many Requests',
        headers: { 'Retry-After': '42' },
      });
    });

    expect(text('.receipt__head span')).toBe('Receipt not recorded');
    expect(text('.receipt__stamp')).toBe('Limit reached');
    expect(unavailable(button('Ask again in 42 s'))).toBe(true);
    expect(element.querySelector('.receipt__ledger')).toBeNull();

    vi.advanceTimersByTime(42_000);
    await fixture.whenStable();

    expect(unavailable(button('Ask again'))).toBe(false);
  });

  it("waits for a provider's limit but offers other models at once", async () => {
    await askAndRender((request) => {
      request.flush(
        errorBody(
          'llm_rate_limited',
          'The provider of Demo model is rate limiting requests. Try again in 20 seconds, or pick another model.',
          [{ audit_id: 131, requested_model: 'fake', model: null, provider: null, sql: null }],
        ),
        { status: 503, statusText: 'Unavailable', headers: { 'Retry-After': '20' } },
      );
    });

    expect(notes()[0]).toBe(
      'The provider of Demo model is rate limiting requests. Try again in 20 seconds, or pick another model.',
    );
    expect(unavailable(button('Ask again in 20 s'))).toBe(true);
    button('Ask again in 20 s').click();
    http.expectNone(`${AI_URL}/ask`);
    expect(unavailable(button('Ask GPT-OSS 120B (Groq) instead'))).toBe(false);

    vi.advanceTimersByTime(20_000);
    await fixture.whenStable();
    expect(unavailable(button('Ask again'))).toBe(false);
  });

  it('asks the same question of the same model again after a network failure', async () => {
    await askAndRender((request) => {
      request.error(new ProgressEvent('error'), { status: 0, statusText: '' });
    });

    expect(text('.receipt__stamp')).toBe('Not sent');
    expect(element.querySelector('.request-id')).toBeNull();

    button('Ask again').click();

    expect(http.expectOne(`${AI_URL}/ask`).request.body).toEqual({
      question: QUESTION,
      model: 'fake',
    });
  });

  it('disables every action while another question is pending', async () => {
    await askAndRender(refused);
    store.ask('Another question?');
    await fixture.whenStable();

    expect(buttons().every(unavailable)).toBe(true);
    buttons().forEach((candidate) => {
      candidate.click();
    });
    http.expectOne(`${AI_URL}/ask`).flush(askOut());
  });

  describe('recalled from history', () => {
    it('shows the stored answer without its rows, and runs it again on request', async () => {
      const item = historyItemOut({
        requested_model: 'groq-gpt-oss-120b',
        model: 'groq-gpt-oss-120b',
        assumptions: ['Counts every status.'],
      });
      store.recall(item);
      await renderEntry(store.entries()[0]);

      expect(text('.receipt__head span')).toBe('Receipt 000120');
      expect(text('time')).toBe('Oct 8, 2026, 12:00 UTC');
      expect(text('.receipt__explanation')).toBe(
        'The number of orders placed through each channel since 1 January.',
      );
      const ledger = [...element.querySelectorAll('.receipt__line')].map((line) => [
        line.querySelector('dt')?.textContent.trim(),
        line.querySelector('dd')?.textContent.trim(),
      ]);
      expect(ledger).toEqual([
        ['Model', 'GPT-OSS 120B (Groq)'],
        ['Rows', '3'],
        ['Time', '31 ms'],
        ['Assumed', 'Counts every status.'],
      ]);
      expect(element.querySelector('dp-result-table')).toBeNull();
      expect(text('.receipt__actions .receipt__note')).toBe(
        "From your history. Results aren't kept, so run the question again to see them.",
      );

      button('Run again').click();

      expect(http.expectOne(`${AI_URL}/ask`).request.body).toEqual({
        question: item.question,
        model: 'groq-gpt-oss-120b',
      });
    });

    it('notes a fallback recorded in history', async () => {
      store.recall(historyItemOut({ requested_model: 'groq-gpt-oss-120b', model: 'fake' }));
      await renderEntry(store.entries()[0]);

      expect(text('.receipt__note')).toBe(
        "GPT-OSS 120B (Groq) couldn't answer, so this model did.",
      );
    });

    it('stamps a refused question from history without announcing it', async () => {
      store.recall(
        historyItemOut({
          status: 'rejected',
          error_code: 'sql_rejected',
          sql: 'DELETE FROM v_orders',
          row_count: null,
          explanation: 'Deletes the cancelled orders.',
        }),
      );
      await renderEntry(store.entries()[0]);

      expect(text('.receipt__stamp')).toBe('Refused');
      expect(element.querySelector('.receipt__failure')?.getAttribute('role')).toBeNull();
      expect(element.querySelector('.receipt__explanation')).toBeNull();
      expect(text('.receipt-sql__toggle')).toContain('Show SQL that was refused');
      expect(buttons().map((candidate) => candidate.textContent.trim())).toEqual(['Run again']);
    });
  });
});
