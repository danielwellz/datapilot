import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AuthService } from '../../core/auth/auth.service';
import { userOut } from '../../core/auth/testing';
import { AI_URL } from './ask-api';
import { AskPage } from './ask-page';
import { AskStore } from './ask.store';
import { askOut, historyPageOut, modelsOut } from './testing';

describe('AskPage', () => {
  let fixture: ComponentFixture<AskPage>;
  let element: HTMLElement;
  let store: AskStore;
  let http: HttpTestingController;

  beforeEach(async () => {
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
    fixture = TestBed.createComponent(AskPage);
    element = fixture.nativeElement as HTMLElement;
    http.expectOne(`${AI_URL}/models`).flush(modelsOut());
    http.expectOne(`${AI_URL}/examples`).flush({ items: [] });
    http.expectOne((request) => request.url === `${AI_URL}/history`).flush(historyPageOut([]));
    await fixture.whenStable();
  });

  afterEach(() => {
    http.verify();
  });

  async function ask(question: string, id: number): Promise<void> {
    store.ask(question);
    http.expectOne(`${AI_URL}/ask`).flush(askOut({ id, question, row_count: id === 1 ? 1 : 2 }));
    http.expectOne((request) => request.url === `${AI_URL}/history`).flush(historyPageOut([]));
    await fixture.whenStable();
  }

  it('loads the models, examples and history when it opens', () => {
    expect(store.modelsStatus()).toBe('loaded');
    expect(store.historyStatus()).toBe('loaded');
  });

  it('says what to do before the first question', () => {
    expect(element.querySelector('.ask__empty')?.textContent).toContain('No questions yet');
    expect(element.querySelector('.ask__thread')).toBeNull();
  });

  it('lists the receipts newest first under the composer', async () => {
    await ask('First question?', 1);
    await ask('Second question?', 2);

    const questions = [...element.querySelectorAll('.ask__thread h2')].map((heading) =>
      heading.textContent.trim(),
    );
    expect(questions).toEqual(['Second question?', 'First question?']);
    expect(element.querySelector('.ask__empty')).toBeNull();
  });

  it('announces how many rows the newest answer returned', async () => {
    const status = () => element.querySelector('.visually-hidden[role="status"]')?.textContent;
    expect(status()?.trim()).toBe('');

    await ask('One row?', 1);
    expect(status()?.trim()).toBe('Answered: 1 row.');

    await ask('Two rows?', 2);
    expect(status()?.trim()).toBe('Answered: 2 rows.');
  });
});
