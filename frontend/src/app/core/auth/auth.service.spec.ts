import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AUTH_URLS, AuthService, CSRF_COOKIE, CSRF_HEADER } from './auth.service';
import { clearCookie, sessionOut, setCookie, userOut } from './testing';

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    clearCookie(CSRF_COOKIE);
  });

  function logIn(token = 'access-1'): void {
    service.login({ email: 'analyst@example.com', password: 'correct-horse' }).subscribe();
    http.expectOne(AUTH_URLS.login).flush(sessionOut(token));
  }

  it('starts without a session', () => {
    expect(service.isAuthenticated()).toBe(false);
    expect(service.user()).toBeNull();
    expect(service.accessToken()).toBeNull();
  });

  describe('login', () => {
    it('keeps the user and the access token in memory', () => {
      let returned: unknown;
      service
        .login({ email: 'analyst@example.com', password: 'correct-horse' })
        .subscribe((user) => (returned = user));

      const request = http.expectOne(AUTH_URLS.login);
      expect(request.request.method).toBe('POST');
      expect(request.request.body).toEqual({
        email: 'analyst@example.com',
        password: 'correct-horse',
      });
      request.flush(sessionOut('access-1'));

      expect(returned).toEqual(userOut());
      expect(service.isAuthenticated()).toBe(true);
      expect(service.accessToken()).toBe('access-1');
      expect(service.user()?.full_name).toBe('Ada Analyst');
    });

    it('leaves the user logged out when the credentials are wrong', () => {
      let failed = false;
      service
        .login({ email: 'analyst@example.com', password: 'wrong' })
        .subscribe({ error: () => (failed = true) });

      http.expectOne(AUTH_URLS.login).flush(null, { status: 401, statusText: 'Unauthorized' });

      expect(failed).toBe(true);
      expect(service.isAuthenticated()).toBe(false);
    });
  });

  describe('register', () => {
    it('creates the account and then logs in with the same credentials', () => {
      const account = {
        email: 'new@example.com',
        full_name: 'New Analyst',
        password: 'a-long-password',
      };
      service.register(account).subscribe();

      const created = http.expectOne(AUTH_URLS.register);
      expect(created.request.body).toEqual(account);
      created.flush(userOut({ email: account.email }), { status: 201, statusText: 'Created' });

      const login = http.expectOne(AUTH_URLS.login);
      expect(login.request.body).toEqual({ email: account.email, password: account.password });
      login.flush(sessionOut('access-new', userOut({ email: account.email })));

      expect(service.user()?.email).toBe('new@example.com');
    });

    it('does not log in when registration fails', () => {
      service
        .register({ email: 'taken@example.com', full_name: 'Taken', password: 'a-long-password' })
        .subscribe({ error: () => undefined });

      http.expectOne(AUTH_URLS.register).flush(null, { status: 409, statusText: 'Conflict' });

      http.expectNone(AUTH_URLS.login);
      expect(service.isAuthenticated()).toBe(false);
    });
  });

  describe('refresh', () => {
    it('sends the CSRF cookie as a header and stores the new token', () => {
      setCookie(CSRF_COOKIE, 'csrf-abc');
      let token: string | undefined;
      service.refresh().subscribe((value) => (token = value));

      const request = http.expectOne(AUTH_URLS.refresh);
      expect(request.request.method).toBe('POST');
      expect(request.request.headers.get(CSRF_HEADER)).toBe('csrf-abc');
      request.flush(sessionOut('access-2'));

      expect(token).toBe('access-2');
      expect(service.accessToken()).toBe('access-2');
    });

    it('shares one request between callers that arrive while it is in flight', () => {
      const tokens: string[] = [];
      service.refresh().subscribe((token) => tokens.push(token));
      service.refresh().subscribe((token) => tokens.push(token));
      service.refresh().subscribe((token) => tokens.push(token));

      http.expectOne(AUTH_URLS.refresh).flush(sessionOut('access-2'));

      expect(tokens).toEqual(['access-2', 'access-2', 'access-2']);
    });

    it('starts a new request once the previous one has finished', () => {
      service.refresh().subscribe();
      http.expectOne(AUTH_URLS.refresh).flush(sessionOut('access-2'));

      service.refresh().subscribe();
      http.expectOne(AUTH_URLS.refresh).flush(sessionOut('access-3'));

      expect(service.accessToken()).toBe('access-3');
    });

    it('ends the session when the server rejects the refresh token', () => {
      logIn();
      service.refresh().subscribe({ error: () => undefined });

      http.expectOne(AUTH_URLS.refresh).flush(null, { status: 401, statusText: 'Unauthorized' });

      expect(service.isAuthenticated()).toBe(false);
    });

    it('ends the session when the CSRF check fails', () => {
      logIn();
      service.refresh().subscribe({ error: () => undefined });

      http.expectOne(AUTH_URLS.refresh).flush(null, { status: 403, statusText: 'Forbidden' });

      expect(service.isAuthenticated()).toBe(false);
    });

    it('keeps the session when the server cannot be reached', () => {
      logIn();
      service.refresh().subscribe({ error: () => undefined });

      http.expectOne(AUTH_URLS.refresh).error(new ProgressEvent('error'));

      expect(service.accessToken()).toBe('access-1');
    });
  });

  describe('restoreSession', () => {
    it('makes no request when there is no CSRF cookie', async () => {
      await service.restoreSession();

      http.expectNone(AUTH_URLS.refresh);
      expect(service.isAuthenticated()).toBe(false);
    });

    it('restores the session from the refresh cookie', async () => {
      setCookie(CSRF_COOKIE, 'csrf-abc');
      const restored = service.restoreSession();

      http.expectOne(AUTH_URLS.refresh).flush(sessionOut('access-restored'));
      await restored;

      expect(service.accessToken()).toBe('access-restored');
    });

    it('resolves logged out when the refresh cookie is no longer valid', async () => {
      setCookie(CSRF_COOKIE, 'csrf-abc');
      const restored = service.restoreSession();

      http.expectOne(AUTH_URLS.refresh).flush(null, { status: 401, statusText: 'Unauthorized' });

      await expect(restored).resolves.toBeUndefined();
      expect(service.isAuthenticated()).toBe(false);
    });

    it('resolves when the server cannot be reached', async () => {
      setCookie(CSRF_COOKIE, 'csrf-abc');
      const restored = service.restoreSession();

      http.expectOne(AUTH_URLS.refresh).error(new ProgressEvent('error'));

      await expect(restored).resolves.toBeUndefined();
    });
  });

  describe('logout', () => {
    it('revokes the refresh token with the CSRF header and forgets the session', () => {
      logIn();
      setCookie(CSRF_COOKIE, 'csrf-abc');
      let authenticatedWhenDone: boolean | undefined;
      service.logout().subscribe(() => (authenticatedWhenDone = service.isAuthenticated()));

      const request = http.expectOne(AUTH_URLS.logout);
      expect(request.request.method).toBe('POST');
      expect(request.request.headers.get(CSRF_HEADER)).toBe('csrf-abc');
      request.flush(null, { status: 204, statusText: 'No Content' });

      expect(authenticatedWhenDone).toBe(false);
    });

    it('forgets the session even when the server refuses the logout', () => {
      logIn();
      let completed = false;
      service.logout().subscribe({ complete: () => (completed = true) });

      http.expectOne(AUTH_URLS.logout).flush(null, { status: 401, statusText: 'Unauthorized' });

      expect(completed).toBe(true);
      expect(service.isAuthenticated()).toBe(false);
    });
  });
});
