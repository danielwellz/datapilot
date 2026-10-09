import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import type { MockInstance } from 'vitest';

import { ToastService } from '../toast/toast.service';
import { SESSION_ENDED_MESSAGE, authInterceptor } from './auth.interceptor';
import { AUTH_URLS, AuthService } from './auth.service';
import { sessionOut } from './testing';

interface Outcome {
  value?: unknown;
  error?: { status: number };
}

describe('authInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let auth: AuthService;
  let router: Router;
  let toasts: ToastService;
  let navigate: MockInstance<Router['navigate']>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    toasts = TestBed.inject(ToastService);
    navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    controller.verify();
  });

  function logIn(token = 'token-old'): void {
    auth.login({ email: 'analyst@example.com', password: 'correct-horse' }).subscribe();
    controller.expectOne(AUTH_URLS.login).flush(sessionOut(token));
  }

  function get(url: string): Outcome {
    const outcome: Outcome = {};
    http.get(url).subscribe({
      next: (value) => (outcome.value = value),
      error: (error: { status: number }) => (outcome.error = error),
    });
    return outcome;
  }

  function unauthorized(): [null, { status: number; statusText: string }] {
    return [null, { status: 401, statusText: 'Unauthorized' }];
  }

  describe('adding the token', () => {
    it('sends the access token with API requests', () => {
      logIn('token-1');
      get('/api/orders');

      const request = controller.expectOne('/api/orders');
      expect(request.request.headers.get('Authorization')).toBe('Bearer token-1');
      request.flush({});
    });

    it('sends no Authorization header while logged out', () => {
      get('/api/meta');

      const request = controller.expectOne('/api/meta');
      expect(request.request.headers.has('Authorization')).toBe(false);
      request.flush({});
    });

    it('never sends the token to another origin', () => {
      logIn();
      get('https://example.com/api/orders');

      const request = controller.expectOne('https://example.com/api/orders');
      expect(request.request.headers.has('Authorization')).toBe(false);
      request.flush({});
    });

    it('leaves the authentication endpoints alone', () => {
      logIn();
      auth.refresh().subscribe();

      const request = controller.expectOne(AUTH_URLS.refresh);
      expect(request.request.headers.has('Authorization')).toBe(false);
      request.flush(sessionOut('token-new'));
    });
  });

  describe('recovering from an expired token', () => {
    it('refreshes and retries the request once', () => {
      logIn('token-old');
      const outcome = get('/api/orders');

      controller.expectOne('/api/orders').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).flush(sessionOut('token-new'));
      const retry = controller.expectOne('/api/orders');
      expect(retry.request.headers.get('Authorization')).toBe('Bearer token-new');
      retry.flush({ items: [] });

      expect(outcome.value).toEqual({ items: [] });
    });

    it('makes one refresh call for concurrent requests that all get a 401', () => {
      logIn('token-old');
      const urls = ['/api/orders', '/api/analytics/summary', '/api/meta'];
      const outcomes = urls.map((url) => get(url));

      for (const url of urls) {
        controller.expectOne(url).flush(...unauthorized());
      }
      const refreshes = controller.match(AUTH_URLS.refresh);
      expect(refreshes).toHaveLength(1);
      refreshes[0].flush(sessionOut('token-new'));

      for (const url of urls) {
        const retry = controller.expectOne(url);
        expect(retry.request.headers.get('Authorization')).toBe('Bearer token-new');
        retry.flush({ url });
      }
      expect(outcomes.map((outcome) => outcome.value)).toEqual(urls.map((url) => ({ url })));
    });

    it('retries without refreshing again when another request already refreshed', () => {
      logIn('token-old');
      const first = get('/api/orders');
      const late = get('/api/meta');

      controller.expectOne('/api/orders').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).flush(sessionOut('token-new'));
      controller.expectOne('/api/orders').flush({ first: true });

      // This 401 answers a request sent with the old token before the refresh.
      controller.expectOne('/api/meta').flush(...unauthorized());
      controller.expectNone(AUTH_URLS.refresh);
      const retry = controller.expectOne('/api/meta');
      expect(retry.request.headers.get('Authorization')).toBe('Bearer token-new');
      retry.flush({ late: true });

      expect(first.value).toEqual({ first: true });
      expect(late.value).toEqual({ late: true });
    });

    it('passes a second 401 to the caller instead of retrying again', () => {
      logIn('token-old');
      const outcome = get('/api/orders');

      controller.expectOne('/api/orders').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).flush(sessionOut('token-new'));
      controller.expectOne('/api/orders').flush(...unauthorized());

      controller.expectNone(AUTH_URLS.refresh);
      controller.expectNone('/api/orders');
      expect(outcome.error?.status).toBe(401);
    });

    it('ends the session and sends every waiting request to log in when refresh is rejected', () => {
      logIn('token-old');
      vi.spyOn(router, 'url', 'get').mockReturnValue('/orders?status=paid');
      const outcomes = ['/api/orders', '/api/meta'].map((url) => get(url));

      controller.expectOne('/api/orders').flush(...unauthorized());
      controller.expectOne('/api/meta').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).flush(...unauthorized());

      expect(auth.isAuthenticated()).toBe(false);
      expect(outcomes.map((outcome) => outcome.error?.status)).toEqual([401, 401]);
      expect(navigate).toHaveBeenCalledWith(['/login'], {
        queryParams: { returnUrl: '/orders?status=paid' },
      });
      expect(toasts.toasts().map((toast) => toast.message)).toEqual([SESSION_ENDED_MESSAGE]);
    });

    it('does not redirect again from the login page', () => {
      vi.spyOn(router, 'url', 'get').mockReturnValue('/login?returnUrl=%2Forders');
      get('/api/meta');

      controller.expectOne('/api/meta').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).flush(...unauthorized());

      expect(navigate).not.toHaveBeenCalled();
      expect(toasts.toasts()).toHaveLength(0);
    });

    it('keeps the session and reports the failure when refresh cannot reach the server', () => {
      logIn('token-old');
      const outcome = get('/api/orders');

      controller.expectOne('/api/orders').flush(...unauthorized());
      controller.expectOne(AUTH_URLS.refresh).error(new ProgressEvent('error'));

      expect(auth.accessToken()).toBe('token-old');
      expect(outcome.error?.status).toBe(0);
      expect(navigate).not.toHaveBeenCalled();
    });

    it('passes other errors through without refreshing', () => {
      logIn();
      const outcome = get('/api/orders/999');

      controller.expectOne('/api/orders/999').flush(null, { status: 404, statusText: 'Not Found' });

      controller.expectNone(AUTH_URLS.refresh);
      expect(outcome.error?.status).toBe(404);
    });
  });
});
