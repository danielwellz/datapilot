import { TestBed } from '@angular/core/testing';

import { INFO_TOAST_DURATION_MS, MAX_TOASTS, ToastService } from './toast.service';

describe('ToastService', () => {
  let service: ToastService;

  beforeEach(() => {
    vi.useFakeTimers();
    service = TestBed.inject(ToastService);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows an error with its detail line', () => {
    service.error('DataPilot ran into a problem.', 'Request ID req-1');

    expect(service.toasts()).toEqual([
      expect.objectContaining({
        kind: 'error',
        message: 'DataPilot ran into a problem.',
        detail: 'Request ID req-1',
      }),
    ]);
  });

  it('closes information after a few seconds', () => {
    service.info('Your session has ended.');

    vi.advanceTimersByTime(INFO_TOAST_DURATION_MS - 1);
    expect(service.toasts()).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(service.toasts()).toHaveLength(0);
  });

  it('keeps errors until they are dismissed', () => {
    service.error('Something failed.');

    vi.advanceTimersByTime(INFO_TOAST_DURATION_MS * 10);
    expect(service.toasts()).toHaveLength(1);

    service.dismiss(service.toasts()[0].id);
    expect(service.toasts()).toHaveLength(0);
  });

  it('shows the same message only once while it is visible', () => {
    service.error('DataPilot cannot be reached.');
    service.error('DataPilot cannot be reached.');

    expect(service.toasts()).toHaveLength(1);
  });

  it('drops the oldest toast to make room for a new one', () => {
    for (let index = 1; index <= MAX_TOASTS + 1; index++) {
      service.error(`Error ${String(index)}`);
    }

    expect(service.toasts().map((toast) => toast.message)).toEqual([
      'Error 2',
      'Error 3',
      'Error 4',
    ]);
  });

  it('cancels the timer of an information toast dismissed early', () => {
    service.info('Saved.');
    const [toast] = service.toasts();

    service.dismiss(toast.id);
    service.info('Saved.');
    vi.advanceTimersByTime(INFO_TOAST_DURATION_MS - 1);

    expect(service.toasts()).toHaveLength(1);
  });
});
