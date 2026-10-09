import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { AskStore, ThreadEntry } from './ask.store';
import { QueryReceipt, receiptNumber, rowsText } from './query-receipt';
import { askOut } from './testing';

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

  async function render(entry: ThreadEntry): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
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
