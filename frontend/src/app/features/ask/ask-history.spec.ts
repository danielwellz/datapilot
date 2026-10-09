import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HistoryItemOut } from '../../core/api/models';
import { failWith } from '../../core/api/testing';
import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { AI_URL } from './ask-api';
import { AskHistory, outcomeText } from './ask-history';
import { AskStore } from './ask.store';
import { historyItemOut, historyPageOut, modelsOut } from './testing';

@Component({
  imports: [AskHistory],
  template: `<dp-ask-history (selected)="chosen.push($event)" />`,
})
class Host {
  readonly chosen: HistoryItemOut[] = [];
}

describe('outcomeText', () => {
  it.each<[Partial<HistoryItemOut>, string]>([
    [{ status: 'ok' }, 'Answered'],
    [{ status: 'rejected', error_code: 'sql_rejected' }, 'Refused'],
    [{ status: 'error', error_code: 'query_timeout' }, 'Stopped'],
    [{ status: 'error', error_code: 'llm_rate_limited' }, 'Limit reached'],
    [{ status: 'error', error_code: 'question_unanswerable' }, 'Not answered'],
  ])('describes %j as %s', (overrides, expected) => {
    expect(outcomeText(historyItemOut(overrides))).toBe(expected);
  });
});

describe('AskHistory', () => {
  let fixture: ComponentFixture<Host>;
  let element: HTMLElement;
  let store: AskStore;
  let http: HttpTestingController;

  async function render(): Promise<void> {
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
    fixture = TestBed.createComponent(Host);
    element = fixture.nativeElement as HTMLElement;
    store.load();
    http.expectOne(`${AI_URL}/models`).flush(modelsOut());
    http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
    await fixture.whenStable();
  }

  function expectHistory(): TestRequest {
    return http.expectOne((request) => request.url === `${AI_URL}/history`);
  }

  function text(selector: string): string {
    return (element.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  function items(): HTMLButtonElement[] {
    return [...element.querySelectorAll<HTMLButtonElement>('.history__item')];
  }

  it('says it is loading, then lists the questions newest first', async () => {
    await render();
    expect(text('.history__state')).toBe('Loading your questions…');

    expectHistory().flush(
      historyPageOut([
        historyItemOut({ id: 121, question: 'Newest?' }),
        historyItemOut({
          id: 120,
          question: 'Older?',
          status: 'rejected',
          error_code: 'sql_rejected',
        }),
      ]),
    );
    await fixture.whenStable();

    expect(items().map((item) => item.querySelector('.history__question')?.textContent)).toEqual([
      'Newest?',
      'Older?',
    ]);
    const meta = items().map((item) =>
      [...(item.querySelector('.history__meta')?.children ?? [])].map((part) =>
        part.textContent.trim(),
      ),
    );
    expect(meta).toEqual([
      ['Answered', 'Oct 8, 2026, 12:00 UTC'],
      ['Refused', 'Oct 8, 2026, 12:00 UTC'],
    ]);
    expect(items()[1]?.querySelector('.history__outcome--failed')).not.toBeNull();
    // Named by the question alone; the outcome and time describe it, read once.
    expect(items()[0]?.getAttribute('aria-labelledby')).toBe('history-question-121');
    expect(element.querySelector('#history-question-121')?.textContent).toBe('Newest?');
    expect(items()[0]?.getAttribute('aria-describedby')).toBe('history-meta-121');
  });

  it('hands the chosen question to the page without asking anything', async () => {
    await render();
    const item = historyItemOut({ id: 121 });
    expectHistory().flush(historyPageOut([item]));
    await fixture.whenStable();

    items()[0]?.click();

    expect(fixture.componentInstance.chosen).toEqual([item]);
    http.expectNone(`${AI_URL}/ask`);
  });

  it('says where questions will appear when there are none', async () => {
    await render();
    expectHistory().flush(historyPageOut([]));
    await fixture.whenStable();

    expect(text('.history__state')).toBe('Questions you ask are kept here, newest first.');
  });

  it('explains a failure with the request id and tries again', async () => {
    await render();
    failWith(expectHistory(), 502, 'http_error');
    await fixture.whenStable();

    expect(text('[role="alert"] p')).toBe("Your questions couldn't be loaded.");
    expect(text('.request-id')).toBe('Request ID req-1');

    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expectHistory().flush(historyPageOut());
    await fixture.whenStable();

    expect(items()).toHaveLength(1);
  });

  it('loads older questions, and tries again when that fails', async () => {
    await render();
    expectHistory().flush(historyPageOut([historyItemOut({ id: 121 })], 'c1'));
    await fixture.whenStable();

    element.querySelector<HTMLButtonElement>('.history__more')?.click();
    await fixture.whenStable();
    expect(text('.history__state')).toBe('Loading older questions…');
    failWith(expectHistory(), 502, 'http_error');
    await fixture.whenStable();
    expect(text('[role="alert"] p')).toBe("Older questions couldn't be loaded.");

    element.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();
    expectHistory().flush(historyPageOut([historyItemOut({ id: 110 })]));
    await fixture.whenStable();

    expect(items()).toHaveLength(2);
    expect(element.querySelector('.history__more')).toBeNull();
  });

  it('folds the list away on narrow screens until it is opened', async () => {
    await render();
    expectHistory().flush(historyPageOut());
    await fixture.whenStable();
    const toggle = element.querySelector<HTMLButtonElement>('.history__toggle');
    const body = element.querySelector('#history-body');
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    expect(toggle?.getAttribute('aria-controls')).toBe('history-body');
    expect(body?.classList).not.toContain('history__body--open');

    toggle?.click();
    await fixture.whenStable();

    expect(toggle?.getAttribute('aria-expanded')).toBe('true');
    expect(toggle?.textContent.trim()).toBe('Hide');
    expect(body?.classList).toContain('history__body--open');
  });
});
