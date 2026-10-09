import { HttpContextToken, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { parseApiError } from '../api/api-error';
import { ToastService } from '../toast/toast.service';

/** Set on a request whose page reports every failure itself. */
export const SKIP_ERROR_TOAST = new HttpContextToken<boolean>(() => false);

/**
 * Reports failures no page can do anything about, an unreachable server or a
 * 5xx, as a toast with the request id. Client errors (4xx) belong to the page
 * that made the request, which can say what to change. The error is passed on
 * either way.
 */
export const errorInterceptor: HttpInterceptorFn = (request, next) => {
  const toasts = inject(ToastService);
  return next(request).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && !request.context.get(SKIP_ERROR_TOAST)) {
        const apiError = parseApiError(error);
        if (apiError.isNetworkError || apiError.status >= 500) {
          toasts.error(
            apiError.message,
            apiError.requestId === null ? null : `Request ID ${apiError.requestId}`,
          );
        }
      }
      return throwError(() => error);
    }),
  );
};
