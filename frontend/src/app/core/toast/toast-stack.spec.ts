import { TestBed } from '@angular/core/testing';

import { ToastStack } from './toast-stack';
import { ToastService } from './toast.service';

describe('ToastStack', () => {
  it('renders each toast in the live region and dismisses it on request', async () => {
    const fixture = TestBed.createComponent(ToastStack);
    const toasts = TestBed.inject(ToastService);
    const element = fixture.nativeElement as HTMLElement;

    toasts.error('DataPilot ran into a problem.', 'Request ID req-1');
    await fixture.whenStable();

    const region = element.querySelector('[aria-live="polite"]');
    expect(region?.textContent).toContain('DataPilot ran into a problem.');
    expect(region?.textContent).toContain('Request ID req-1');

    element.querySelector<HTMLButtonElement>('button')?.click();
    await fixture.whenStable();

    expect(toasts.toasts()).toHaveLength(0);
    expect(element.querySelector('.toast')).toBeNull();
  });
});
