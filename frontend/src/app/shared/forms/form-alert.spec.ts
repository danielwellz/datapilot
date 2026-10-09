import { TestBed } from '@angular/core/testing';

import { ApiError } from '../../core/api/api-error';
import { FormAlert } from './form-alert';

describe('FormAlert', () => {
  async function render(error: ApiError): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(FormAlert);
    fixture.componentRef.setInput('error', error);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('announces the message', async () => {
    const element = await render(
      new ApiError(401, 'unauthorized', 'Email or password is incorrect.'),
    );

    expect(element.querySelector('[role="alert"]')?.textContent.trim()).toBe(
      'Email or password is incorrect.',
    );
  });

  it('adds the request id for a server error only', async () => {
    const serverError = await render(new ApiError(500, 'internal_error', 'Failed.', [], 'req-1'));
    const clientError = await render(new ApiError(429, 'rate_limited', 'Slow down.', [], 'req-2'));

    expect(serverError.textContent).toContain('Request ID req-1');
    expect(clientError.textContent).not.toContain('req-2');
  });
});
