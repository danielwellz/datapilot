import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, of, switchMap, throwError } from 'rxjs';

import { ToastService } from '../toast/toast.service';
import { AUTH_URLS, AuthService, isSessionRejection } from './auth.service';

const API_PREFIX = '/api/';
// These authenticate with credentials or the refresh cookie, never the
// bearer token, and a 401 from them must not trigger a refresh.
const COOKIE_OR_CREDENTIAL_URLS = new Set<string>(Object.values(AUTH_URLS));

export const SESSION_ENDED_MESSAGE = 'Your session has ended. Log in again to continue.';

/**
 * Sends the access token with API requests and recovers from its expiry.
 *
 * On a 401 the request is retried once with a fresh token. If another
 * request already refreshed while this one was in flight, the newer token is
 * used as is; otherwise this request joins the single shared refresh in
 * {@link AuthService.refresh}. The retry goes to the rest of the chain, not
 * back through this interceptor, so a second 401 reaches the caller instead
 * of looping. When the server rejects the refresh token, the session is over
 * and the user is sent to log in, then brought back to the same page.
 */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  if (!request.url.startsWith(API_PREFIX) || COOKIE_OR_CREDENTIAL_URLS.has(request.url)) {
    return next(request);
  }
  const auth = inject(AuthService);
  const router = inject(Router);
  const toasts = inject(ToastService);
  const sentToken = auth.accessToken();

  return next(withToken(request, sentToken)).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
        return throwError(() => error);
      }
      const currentToken = auth.accessToken();
      const freshToken: Observable<string> =
        currentToken !== null && currentToken !== sentToken ? of(currentToken) : auth.refresh();

      return freshToken.pipe(
        catchError((refreshError: unknown) => {
          if (!isSessionRejection(refreshError)) {
            // The server could not be reached or failed; that is not proof
            // the session is over, so report the refresh failure instead.
            return throwError(() => refreshError);
          }
          sendToLogin(router, toasts);
          return throwError(() => error);
        }),
        switchMap((token) => next(withToken(request, token))),
      );
    }),
  );
};

function withToken<T>(request: HttpRequest<T>, token: string | null): HttpRequest<T> {
  return token === null
    ? request
    : request.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

function sendToLogin(router: Router, toasts: ToastService): void {
  const returnUrl = router.url;
  if (returnUrl.startsWith('/login')) {
    return;
  }
  toasts.info(SESSION_ENDED_MESSAGE);
  void router.navigate(['/login'], { queryParams: { returnUrl } });
}
