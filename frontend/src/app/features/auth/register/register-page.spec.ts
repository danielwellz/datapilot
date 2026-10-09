import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AUTH_URLS, AuthService } from '../../../core/auth/auth.service';
import { sessionOut, userOut } from '../../../core/auth/testing';
import { submitForm, textOf, typeInto } from '../../../shared/forms/testing';
import { RegisterPage } from './register-page';

@Component({ template: '' })
class Blank {}

describe('RegisterPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(url = '/register'): Promise<void> {
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url, RegisterPage);
    const element = harness.routeNativeElement;
    if (element === null) {
      throw new Error(`Nothing rendered at ${url}`);
    }
    page = element;
  }

  async function fillAndSubmit(fields: { name?: string; email?: string; password?: string } = {}) {
    typeInto(page, '#register-name', fields.name ?? 'New Analyst');
    typeInto(page, '#register-email', fields.email ?? 'new@example.com');
    typeInto(page, '#register-password', fields.password ?? 'a-long-password');
    submitForm(page);
    await harness.fixture.whenStable();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'register', component: RegisterPage },
          { path: '**', component: Blank },
        ]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('applies the password rules before calling the server', async () => {
    await open();

    await fillAndSubmit({ password: 'short' });

    expect(textOf(page, '#register-password-error')).toBe('Use at least 10 characters.');
    expect(page.querySelector('#register-password')?.getAttribute('aria-describedby')).toBe(
      'register-password-hint register-password-error',
    );
    http.expectNone(AUTH_URLS.register);
  });

  it('refuses a password that equals the email address', async () => {
    await open();

    await fillAndSubmit({ email: 'new@example.com', password: 'NEW@example.com' });

    expect(textOf(page, '#register-password-error')).toBe(
      'Choose a password that is different from your email address.',
    );
    http.expectNone(AUTH_URLS.register);
  });

  it('creates the account, logs in and opens the dashboard', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.register).flush(userOut({ email: 'new@example.com' }), {
      status: 201,
      statusText: 'Created',
    });
    http
      .expectOne(AUTH_URLS.login)
      .flush(sessionOut('token', userOut({ email: 'new@example.com' })));
    await harness.fixture.whenStable();

    expect(TestBed.inject(AuthService).user()?.email).toBe('new@example.com');
    expect(TestBed.inject(Router).url).toBe('/dashboard');
  });

  it('offers to log in when the email already has an account', async () => {
    await open('/register?returnUrl=%2Forders');

    await fillAndSubmit({ email: 'taken@example.com' });
    http.expectOne(AUTH_URLS.register).flush(
      {
        error: {
          code: 'conflict',
          message: 'An account with this email address already exists.',
          details: [],
          request_id: 'req-1',
        },
      },
      { status: 409, statusText: 'Conflict' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '#register-email-error')).toContain(
      'An account with this email address already exists.',
    );
    expect(page.querySelector('#register-email-error a')?.getAttribute('href')).toBe(
      '/login?returnUrl=%2Forders',
    );
    expect(document.activeElement?.id).toBe('register-email');

    typeInto(page, '#register-email', 'other@example.com');
    await harness.fixture.whenStable();
    expect(page.querySelector('#register-email-error')).toBeNull();
  });

  it('puts server validation messages under their fields', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.register).flush(
      {
        error: {
          code: 'validation_failed',
          message: 'The request is invalid.',
          details: [{ loc: ['full_name'], message: 'Enter a shorter name.', type: 'too_long' }],
          request_id: 'req-2',
        },
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '#register-name-error')).toBe('Enter a shorter name.');
  });

  it('shows the message when registrations are rate limited', async () => {
    await open();

    await fillAndSubmit();
    http.expectOne(AUTH_URLS.register).flush(
      {
        error: {
          code: 'rate_limited',
          message: 'Too many accounts were registered from this address. Try again later.',
          details: [],
          request_id: 'req-3',
        },
      },
      { status: 429, statusText: 'Too Many Requests' },
    );
    await harness.fixture.whenStable();

    expect(textOf(page, '[role="alert"]')).toBe(
      'Too many accounts were registered from this address. Try again later.',
    );
  });
});
