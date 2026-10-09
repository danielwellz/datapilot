import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AUTH_URLS } from '../../../core/auth/auth.service';
import { sessionOut } from '../../../core/auth/testing';
import { submitForm, textOf, typeInto } from '../../../shared/forms/testing';
import { LoginPage } from './login-page';

@Component({ template: '' })
class Blank {}

describe('LoginPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(url = '/login'): Promise<void> {
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url, LoginPage);
    const element = harness.routeNativeElement;
    if (element === null) {
      throw new Error(`Nothing rendered at ${url}`);
    }
    page = element;
  }

  async function fillAndSubmit(email = 'analyst@example.com', password = 'correct-horse') {
    typeInto(page, '#login-email', email);
    typeInto(page, '#login-password', password);
    submitForm(page);
    await harness.fixture.whenStable();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login', component: LoginPage },
          { path: '**', component: Blank },
        ]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('explains missing fields without calling the server and focuses the first one', async () => {
    await open();

    submitForm(page);
    await harness.fixture.whenStable();

    expect(textOf(page, '#login-email-error')).toBe('Enter your email address.');
    expect(textOf(page, '#login-password-error')).toBe('Enter your password.');
    expect(page.querySelector('#login-email')?.getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement?.id).toBe('login-email');
    http.expectNone(AUTH_URLS.login);
  });

  it('checks the email format before calling the server', async () => {
    await open();

    await fillAndSubmit('not-an-email');

    expect(textOf(page, '#login-email-error')).toBe(
      'Enter an email address like name@example.com.',
    );
    http.expectNone(AUTH_URLS.login);
  });

  it('logs in and returns to the page that was requested', async () => {
    await open('/login?returnUrl=%2Forders%3Fstatus%3Dpaid');

    await fillAndSubmit();
    const request = http.expectOne(AUTH_URLS.login);
    expect(textOf(page, 'button[type="submit"]')).toBe('Logging in');
    request.flush(sessionOut());
    await harness.fixture.whenStable();

    expect(TestBed.inject(Router).url).toBe('/orders?status=paid');
  });

  it('goes to the dashboard when the return URL points elsewhere', async () => {
    await open('/login?returnUrl=https%3A%2F%2Fevil.example');

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.login).flush(sessionOut());
    await harness.fixture.whenStable();

    expect(TestBed.inject(Router).url).toBe('/dashboard');
  });

  it('shows the server message when the credentials are wrong', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.login).flush(
      {
        error: {
          code: 'unauthorized',
          message: 'Email or password is incorrect.',
          details: [],
          request_id: 'req-1',
        },
      },
      { status: 401, statusText: 'Unauthorized' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '[role="alert"]')).toBe('Email or password is incorrect.');
    expect(page.querySelector('button[type="submit"]')?.hasAttribute('disabled')).toBe(false);
  });

  it('puts server validation messages under their fields', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.login).flush(
      {
        error: {
          code: 'validation_failed',
          message: 'The request is invalid.',
          details: [
            { loc: ['email'], message: 'The email domain is not valid.', type: 'value_error' },
          ],
          request_id: 'req-2',
        },
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '#login-email-error')).toBe('The email domain is not valid.');
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('shows the request id when the server fails', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.login).flush(
      {
        error: {
          code: 'internal_error',
          message: 'Something went wrong on our side.',
          details: [],
          request_id: 'req-3',
        },
      },
      { status: 500, statusText: 'Internal Server Error' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '[role="alert"]')).toContain('Something went wrong on our side.');
    expect(textOf(page, '[role="alert"]')).toContain('Request ID req-3');
  });

  it('keeps the return URL on the link to the register page', async () => {
    await open('/login?returnUrl=%2Fask');

    expect(page.querySelector('a[href^="/register"]')?.getAttribute('href')).toBe(
      '/register?returnUrl=%2Fask',
    );
  });
});
