import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { failWith } from '../../core/api/testing';
import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { AI_URL } from './ask-api';
import { AskComposer, MAX_QUESTION_LENGTH } from './ask-composer';
import { AskStore } from './ask.store';
import { askOut, historyPageOut, modelsOut } from './testing';

const EXAMPLE = 'How many orders came from each channel this year?';

describe('AskComposer', () => {
  let fixture: ComponentFixture<AskComposer>;
  let element: HTMLElement;
  let store: AskStore;
  let http: HttpTestingController;

  async function render(
    load: { models?: 'ok' | 'fail'; examples?: 'ok' | 'fail' } = {},
  ): Promise<void> {
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
    const models = http.expectOne(`${AI_URL}/models`);
    if (load.models === 'fail') {
      failWith(models, 502, 'http_error');
    } else {
      models.flush(modelsOut());
    }
    const examples = http.expectOne(`${AI_URL}/examples`);
    if (load.examples === 'fail') {
      failWith(examples, 502, 'http_error');
    } else {
      examples.flush({ items: [{ question: EXAMPLE }] });
    }
    http.expectOne((request) => request.url === `${AI_URL}/history`).flush(historyPageOut([]));
    fixture = TestBed.createComponent(AskComposer);
    element = fixture.nativeElement as HTMLElement;
    await fixture.whenStable();
  }

  function textarea(): HTMLTextAreaElement {
    const found = element.querySelector('textarea');
    if (found === null) {
      throw new Error('No text area');
    }
    return found;
  }

  function submitButton(): HTMLButtonElement {
    const found = element.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (found === null) {
      throw new Error('No submit button');
    }
    return found;
  }

  async function type(value: string): Promise<void> {
    textarea().value = value;
    textarea().dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  async function press(init: KeyboardEventInit): Promise<KeyboardEvent> {
    const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true, ...init });
    textarea().dispatchEvent(event);
    await fixture.whenStable();
    return event;
  }

  function expectAsk(): TestRequest {
    return http.expectOne(`${AI_URL}/ask`);
  }

  function errorText(): string | null {
    return element.querySelector('#ask-question-error')?.textContent.trim() ?? null;
  }

  it('asks the trimmed question with Enter and clears the box', async () => {
    await render();
    await type('  Orders by channel this year  ');

    const event = await press({});

    expect(event.defaultPrevented).toBe(true);
    expect(expectAsk().request.body).toEqual({
      question: 'Orders by channel this year',
      model: 'fake',
    });
    expect(textarea().value).toBe('');
  });

  it('asks with the Ask button', async () => {
    await render();
    await type('Orders by channel this year');

    submitButton().click();

    expectAsk();
  });

  it('starts a new line with Shift+Enter instead of asking', async () => {
    await render();
    await type('Orders by channel');

    const event = await press({ shiftKey: true });

    expect(event.defaultPrevented).toBe(false);
    http.expectNone(`${AI_URL}/ask`);
  });

  it('does not ask while an input method is still composing', async () => {
    await render();
    await type('注文');

    await press({ isComposing: true });

    http.expectNone(`${AI_URL}/ask`);
  });

  it('ignores keys other than Enter', async () => {
    await render();
    await type('Orders');

    await press({ key: 'a' });

    http.expectNone(`${AI_URL}/ask`);
  });

  it.each([
    ['', 'Write a question first.'],
    ['   ', 'Write a question first.'],
    ['ab', 'Write a question of at least 3 characters.'],
  ])('explains why %j cannot be asked', async (value, message) => {
    await render();
    await type(value);

    await press({});

    expect(errorText()).toBe(message);
    expect(textarea().getAttribute('aria-invalid')).toBe('true');
    expect(textarea().getAttribute('aria-describedby')).toBe(
      'ask-question-error ask-question-hint',
    );
    http.expectNone(`${AI_URL}/ask`);
  });

  it('shows no error before the user tries to ask', async () => {
    await render();
    await type('ab');

    expect(errorText()).toBeNull();
    expect(textarea().getAttribute('aria-invalid')).toBe('false');
  });

  it('shows no error when an empty box loses focus', async () => {
    await render();

    textarea().dispatchEvent(new Event('blur'));
    await fixture.whenStable();

    expect(errorText()).toBeNull();
  });

  it('forgets an earlier failed attempt once a question is asked', async () => {
    await render();
    await press({});
    expect(errorText()).toBe('Write a question first.');
    await type('Orders by channel this year');
    await press({});
    expectAsk();

    textarea().dispatchEvent(new Event('blur'));
    await fixture.whenStable();

    expect(errorText()).toBeNull();
  });

  it('counts characters near the limit and refuses a question over it', async () => {
    await render();
    await type('x'.repeat(MAX_QUESTION_LENGTH - 101));
    expect(element.querySelector('.composer__counter')).toBeNull();

    await type('x'.repeat(MAX_QUESTION_LENGTH + 1));
    expect(element.querySelector('.composer__counter')?.textContent.trim()).toBe(
      '501 of 500 characters',
    );
    await press({});

    expect(errorText()).toBe('Keep the question to 500 characters or fewer.');
    http.expectNone(`${AI_URL}/ask`);
  });

  it('lists the models with the default selected, and asks the one picked', async () => {
    await render();
    const select = element.querySelector('select');
    expect([...(select?.options ?? [])].map((option) => option.text.trim())).toEqual([
      'Demo model (example questions only)',
      'GPT-OSS 120B (Groq)',
      'Gemini 3.5 Flash-Lite',
    ]);
    expect(select?.value).toBe('fake');

    if (select !== null) {
      select.value = 'groq-gpt-oss-120b';
      select.dispatchEvent(new Event('change'));
    }
    await type('Orders by channel this year');
    await press({});

    expect(expectAsk().request.body).toMatchObject({ model: 'groq-gpt-oss-120b' });
  });

  it('says questions go to the default model when the model list fails, and retries', async () => {
    await render({ models: 'fail' });

    expect(element.querySelector('select')).toBeNull();
    expect(element.querySelector('.composer__model .field__hint')?.textContent).toContain(
      "couldn't be loaded, so questions go to the default model",
    );

    element.querySelector<HTMLButtonElement>('.composer__retry')?.click();

    http.expectOne(`${AI_URL}/models`).flush(modelsOut());
  });

  it('asks an example question with one click', async () => {
    await render();

    element.querySelector<HTMLButtonElement>('.composer__chip')?.click();

    expect(expectAsk().request.body).toEqual({ question: EXAMPLE, model: 'fake' });
  });

  it('says when the examples could not be loaded', async () => {
    await render({ examples: 'fail' });

    expect(element.querySelector('.composer__chip')).toBeNull();
    expect(element.textContent).toContain("The example questions couldn't be loaded.");
  });

  it('disables asking while a question is pending', async () => {
    await render();
    await type('Orders by channel this year');
    await press({});
    await fixture.whenStable();

    expect(submitButton().getAttribute('aria-disabled')).toBe('true');
    expect(submitButton().textContent.trim()).toBe('Asking…');
    const chip = element.querySelector<HTMLButtonElement>('.composer__chip');
    expect(chip?.getAttribute('aria-disabled')).toBe('true');
    // Still focusable, so focus stays put; pressing it asks nothing.
    expect(chip?.disabled).toBe(false);
    chip?.click();
    await type('Another question');
    await press({});

    expectAsk().flush(askOut());
    http.expectOne((request) => request.url === `${AI_URL}/history`).flush(historyPageOut([]));
    await fixture.whenStable();
    expect(submitButton().textContent.trim()).toBe('Ask');
    // The second question was kept, not sent and not cleared.
    expect(textarea().value).toBe('Another question');
  });

  it('says when the rate limit lets the next question through', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    try {
      await render();
      await type('Orders by channel this year');
      await press({});
      expectAsk().flush(
        {
          error: { code: 'rate_limited', message: 'Slow down.', details: [], request_id: 'r' },
        },
        { status: 429, statusText: 'Too Many Requests', headers: { 'Retry-After': '5' } },
      );
      await fixture.whenStable();

      expect(submitButton().textContent.trim()).toBe('Ask in 5 s');
      expect(submitButton().getAttribute('aria-disabled')).toBe('true');

      vi.advanceTimersByTime(5000);
      await fixture.whenStable();
      expect(submitButton().textContent.trim()).toBe('Ask');
    } finally {
      vi.useRealTimers();
    }
  });
});
