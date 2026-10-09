import { Component, input } from '@angular/core';

import { ApiError } from '../../core/api/api-error';

/**
 * A failed submission that belongs to no single field, shown above the form.
 * Server errors add their request id, which is what support needs to find
 * the request in the logs.
 */
@Component({
  selector: 'dp-form-alert',
  template: `
    <div class="form-alert" role="alert">
      <p>{{ error().message }}</p>
      @if (error().status >= 500 && error().requestId) {
        <p class="form-alert__request-id">Request ID {{ error().requestId }}</p>
      }
    </div>
  `,
  styles: `
    .form-alert__request-id {
      margin-top: var(--space-1);
      color: var(--color-graphite);
      font-family: var(--font-mono);
      font-size: var(--text-caption);
      line-height: var(--leading-caption);
    }
  `,
})
export class FormAlert {
  readonly error = input.required<ApiError>();
}
