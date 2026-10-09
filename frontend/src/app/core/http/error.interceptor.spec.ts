import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ToastService } from '../toast/toast.service';
import { SKIP_ERROR_TOAST, errorInterceptor } from './error.interceptor';

describe('errorInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let toasts: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    toasts = TestBed.inject(ToastService);
  });

  afterEach(() => {
    controller.verify();
  });

  function get(context?: HttpContext): { error: unknown } {
    const outcome: { error: unknown } = { error: undefined };
    http
      .get('/api/orders', { context })
      .subscribe({ error: (error: unknown) => (outcome.error = error) });
    return outcome;
  }

  it('shows the server message and request id for a 5xx and passes the error on', () => {
    const outcome = get();

    controller.expectOne('/api/orders').flush(
      {
        error: {
          code: 'internal_error',
          message: 'Something went wrong on our side.',
          details: [],
          request_id: 'req-9',
        },
      },
      { status: 500, statusText: 'Internal Server Error' },
    );

    expect(toasts.toasts()).toEqual([
      expect.objectContaining({
        kind: 'error',
        message: 'Something went wrong on our side.',
        detail: 'Request ID req-9',
      }),
    ]);
    expect(outcome.error).toBeDefined();
  });

  it('explains an unreachable server', () => {
    get();

    controller.expectOne('/api/orders').error(new ProgressEvent('error'));

    expect(toasts.toasts()[0].message).toContain("can't be reached");
    expect(toasts.toasts()[0].detail).toBeNull();
  });

  it('leaves client errors to the page', () => {
    const outcome = get();

    controller.expectOne('/api/orders').flush(null, { status: 422, statusText: 'Unprocessable' });

    expect(toasts.toasts()).toHaveLength(0);
    expect(outcome.error).toBeDefined();
  });

  it('stays quiet for a request that opted out', () => {
    get(new HttpContext().set(SKIP_ERROR_TOAST, true));

    controller.expectOne('/api/orders').flush(null, { status: 503, statusText: 'Unavailable' });

    expect(toasts.toasts()).toHaveLength(0);
  });
});
