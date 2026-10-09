import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SKIP_ERROR_TOAST } from '../../core/http/error.interceptor';
import { AI_URL, AskApi } from './ask-api';
import { askOut, historyPageOut, modelsOut } from './testing';

describe('AskApi', () => {
  let api: AskApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(AskApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('gets the enabled models without a toast on failure', () => {
    let received: unknown;
    api.models().subscribe((value) => (received = value));

    const request = http.expectOne(`${AI_URL}/models`);
    expect(request.request.method).toBe('GET');
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(modelsOut());
    expect(received).toEqual(modelsOut());
  });

  it('gets the example questions without a toast on failure', () => {
    api.examples().subscribe();

    const request = http.expectOne(`${AI_URL}/examples`);
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush({ items: [] });
  });

  it('posts a question with its model', () => {
    let received: unknown;
    api
      .ask({ question: 'Orders by channel this year', model: 'groq-gpt-oss-120b' })
      .subscribe((value) => (received = value));

    const request = http.expectOne(`${AI_URL}/ask`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      question: 'Orders by channel this year',
      model: 'groq-gpt-oss-120b',
    });
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(askOut());
    expect(received).toEqual(askOut());
  });

  it('gets a history page with its cursor', () => {
    api.history({ limit: 20, cursor: 'abc' }).subscribe();

    const request = http.expectOne(
      (r) => r.urlWithParams === `${AI_URL}/history?limit=20&cursor=abc`,
    );
    expect(request.request.context.get(SKIP_ERROR_TOAST)).toBe(true);
    request.flush(historyPageOut());
  });
});
