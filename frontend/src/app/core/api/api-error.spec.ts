import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';

import { ApiError, parseApiError } from './api-error';

function httpError(status: number, body: unknown, requestId?: string): HttpErrorResponse {
  const headers = requestId ? new HttpHeaders({ 'X-Request-ID': requestId }) : new HttpHeaders();
  return new HttpErrorResponse({ status, error: body, headers, url: '/api/test' });
}

describe('parseApiError', () => {
  it('reads the backend error envelope', () => {
    const error = parseApiError(
      httpError(409, {
        error: {
          code: 'conflict',
          message: 'An account with this email already exists.',
          details: [],
          request_id: 'req-1',
        },
      }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.code).toBe('conflict');
    expect(error.message).toBe('An account with this email already exists.');
    expect(error.requestId).toBe('req-1');
  });

  it('describes a request that got no response as a network error', () => {
    const error = parseApiError(httpError(0, new ProgressEvent('error'), 'req-2'));

    expect(error.isNetworkError).toBe(true);
    expect(error.code).toBe('network_error');
    expect(error.message).toContain("can't be reached");
  });

  it('keeps the request id header for a 5xx without an envelope', () => {
    const error = parseApiError(httpError(502, '<html>Bad gateway</html>', 'req-3'));

    expect(error.status).toBe(502);
    expect(error.code).toBe('http_error');
    expect(error.message).toBe('DataPilot ran into a problem. Try again in a moment.');
    expect(error.requestId).toBe('req-3');
  });

  it('names the status for a 4xx without an envelope', () => {
    const error = parseApiError(httpError(404, { detail: 'not here' }));

    expect(error.message).toBe('The request failed with status 404.');
    expect(error.requestId).toBeNull();
  });

  it('rejects an envelope with missing fields', () => {
    const error = parseApiError(httpError(400, { error: { code: 'bad_request' } }));

    expect(error.code).toBe('http_error');
  });

  it('returns an ApiError unchanged', () => {
    const original = new ApiError(401, 'unauthorized', 'Log in again.');

    expect(parseApiError(original)).toBe(original);
  });

  it('wraps an error that did not come from HTTP', () => {
    const error = parseApiError(new TypeError('boom'));

    expect(error.code).toBe('client_error');
    expect(error.message).not.toContain('boom');
  });
});

describe('ApiError.fieldErrors', () => {
  it('keys the first message of each field by its name', () => {
    const error = new ApiError(422, 'validation_failed', 'The request is invalid.', [
      { loc: ['email'], message: 'Enter a valid email address.', type: 'value_error' },
      { loc: ['password'], message: 'Too short.', type: 'password_too_short' },
      { loc: ['password'], message: 'Second message.', type: 'other' },
    ]);

    expect(error.fieldErrors()).toEqual({
      email: 'Enter a valid email address.',
      password: 'Too short.',
    });
  });

  it('skips details without a field path', () => {
    const error = new ApiError(422, 'validation_failed', 'Invalid.', [
      { message: 'Body must be JSON.' },
      { loc: [], message: 'Empty path.' },
    ]);

    expect(error.fieldErrors()).toEqual({});
  });
});
