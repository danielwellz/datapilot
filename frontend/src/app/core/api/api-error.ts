import { HttpErrorResponse } from '@angular/common/http';

import { ErrorOut, JsonValue } from './models';

const NETWORK_MESSAGE = "DataPilot can't be reached. Check your connection and try again.";
const SERVER_MESSAGE = 'DataPilot ran into a problem. Try again in a moment.';

/**
 * A failed API request in one shape, whatever the failure was: the backend's
 * error envelope, a response without one (a proxy's HTML 502, for example),
 * or no response at all.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: readonly Record<string, JsonValue>[] = [],
    readonly requestId: string | null = null,
    /** Seconds to wait before asking again, from `Retry-After`; null when not given. */
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** True when the request never got a response. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  /**
   * The first message for each invalid body field, keyed by field name.
   * Validation details carry the field path in `loc`, e.g. `["email"]`.
   */
  fieldErrors(): Partial<Record<string, string>> {
    const errors: Partial<Record<string, string>> = {};
    for (const detail of this.details) {
      const { loc, message } = detail;
      const field = Array.isArray(loc) ? loc.at(-1) : undefined;
      if (typeof field === 'string' && typeof message === 'string') {
        errors[field] ??= message;
      }
    }
    return errors;
  }
}

/** Converts anything an HTTP call can throw into an {@link ApiError}. */
export function parseApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (!(error instanceof HttpErrorResponse)) {
    return new ApiError(0, 'client_error', SERVER_MESSAGE);
  }
  const requestId = error.headers.get('X-Request-ID');
  const retryAfter = parseRetryAfter(error.headers.get('Retry-After'));
  if (error.status === 0) {
    return new ApiError(0, 'network_error', NETWORK_MESSAGE, [], requestId);
  }
  if (isErrorOut(error.error)) {
    const { code, message, details, request_id } = error.error.error;
    return new ApiError(error.status, code, message, details, request_id, retryAfter);
  }
  const message =
    error.status >= 500
      ? SERVER_MESSAGE
      : `The request failed with status ${String(error.status)}.`;
  return new ApiError(error.status, 'http_error', message, [], requestId, retryAfter);
}

/**
 * The delay in a `Retry-After` header. The backend sends whole seconds; the
 * HTTP-date form is not used by it, so it is read as "not given".
 */
function parseRetryAfter(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value.trim()) ? Number(value.trim()) : null;
}

function isErrorOut(body: unknown): body is ErrorOut {
  if (typeof body !== 'object' || body === null || !('error' in body)) {
    return false;
  }
  const inner: unknown = body.error;
  return (
    typeof inner === 'object' &&
    inner !== null &&
    'code' in inner &&
    typeof inner.code === 'string' &&
    'message' in inner &&
    typeof inner.message === 'string' &&
    'details' in inner &&
    Array.isArray(inner.details) &&
    'request_id' in inner &&
    typeof inner.request_id === 'string'
  );
}
