import { HttpClient, HttpContext, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { DOCUMENT, Injectable, computed, inject, signal } from '@angular/core';
import {
  Observable,
  catchError,
  finalize,
  firstValueFrom,
  map,
  of,
  share,
  switchMap,
  tap,
  throwError,
} from 'rxjs';

import { readCookie } from '../api/cookies';
import { LoginIn, SessionOut, UserCreate, UserOut } from '../api/models';
import { SKIP_ERROR_TOAST } from '../http/error.interceptor';

export const AUTH_URLS = {
  login: '/api/auth/login',
  register: '/api/auth/register',
  refresh: '/api/auth/refresh',
  logout: '/api/auth/logout',
} as const;

/** Set by the backend next to the httpOnly refresh cookie; readable by our pages only. */
export const CSRF_COOKIE = 'csrf_refresh_token';
export const CSRF_HEADER = 'X-CSRF-TOKEN';

interface Session {
  accessToken: string;
  user: UserOut;
}

/**
 * The signed-in user and their access token.
 *
 * The access token lives only in memory, so injected script cannot find it in
 * storage and it disappears with the tab. The refresh token is an httpOnly
 * cookie the browser sends to `/api/auth` by itself; this service never sees
 * it, and proves the request comes from our origin by copying the CSRF cookie
 * into a header (ADR 0003).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly document = inject(DOCUMENT);

  private readonly session = signal<Session | null>(null);
  private refreshInFlight: Observable<string> | null = null;

  readonly user = computed(() => this.session()?.user ?? null);
  readonly accessToken = computed(() => this.session()?.accessToken ?? null);
  readonly isAuthenticated = computed(() => this.session() !== null);

  /** Logs in. Failures are left to the form, which reports every one of them inline. */
  login(credentials: LoginIn): Observable<UserOut> {
    return this.http
      .post<SessionOut>(AUTH_URLS.login, credentials, { context: formContext() })
      .pipe(
        tap((session) => {
          this.start(session);
        }),
        map((session) => session.user),
      );
  }

  /** Creates the account, then logs in with the same credentials. */
  register(account: UserCreate): Observable<UserOut> {
    return this.http
      .post<UserOut>(AUTH_URLS.register, account, { context: formContext() })
      .pipe(switchMap(() => this.login({ email: account.email, password: account.password })));
  }

  /**
   * Exchanges the refresh cookie for a new access token.
   *
   * Callers that arrive while a refresh is in flight join it instead of
   * starting another. That matters beyond saving a request: the backend
   * rotates the refresh token on every use, so parallel refreshes would
   * spend the same token twice and could look like token theft.
   */
  refresh(): Observable<string> {
    this.refreshInFlight ??= this.http
      .post<SessionOut>(AUTH_URLS.refresh, null, { headers: this.csrfHeaders() })
      .pipe(
        tap((session) => {
          this.start(session);
        }),
        map((session) => session.access_token),
        catchError((error: unknown) => {
          if (isSessionRejection(error)) {
            this.clear();
          }
          return throwError(() => error);
        }),
        finalize(() => {
          this.refreshInFlight = null;
        }),
        share(),
      );
    return this.refreshInFlight;
  }

  /**
   * Restores the session at startup from the refresh cookie, if there is one.
   *
   * Without the CSRF cookie there is no session to restore, so no request is
   * made. It never rejects: a failed restore means the user logs in again,
   * and the app must start either way.
   */
  restoreSession(): Promise<void> {
    if (readCookie(this.document, CSRF_COOKIE) === null) {
      return Promise.resolve();
    }
    return firstValueFrom(
      this.refresh().pipe(
        map(() => undefined),
        catchError(() => of(undefined)),
      ),
    );
  }

  /**
   * Revokes the refresh token and forgets the session. The session ends
   * locally whatever the server answers: an expired or already revoked token
   * should not keep anyone logged in on this page.
   */
  logout(): Observable<void> {
    return this.http.post<null>(AUTH_URLS.logout, null, { headers: this.csrfHeaders() }).pipe(
      map(() => undefined),
      catchError(() => of(undefined)),
      // Cleared before callers see the result, so a redirect to the login
      // page is not bounced back by the guest guard.
      tap(() => {
        this.clear();
      }),
    );
  }

  /** Forgets the session without contacting the server. */
  clear(): void {
    this.session.set(null);
  }

  private start(session: SessionOut): void {
    this.session.set({ accessToken: session.access_token, user: session.user });
  }

  private csrfHeaders(): HttpHeaders {
    const token = readCookie(this.document, CSRF_COOKIE);
    return token === null ? new HttpHeaders() : new HttpHeaders({ [CSRF_HEADER]: token });
  }
}

function formContext(): HttpContext {
  return new HttpContext().set(SKIP_ERROR_TOAST, true);
}

/** True when the server refused the refresh token itself, not when it was unreachable. */
export function isSessionRejection(error: unknown): boolean {
  return error instanceof HttpErrorResponse && (error.status === 401 || error.status === 403);
}
