import { Component, input, output } from '@angular/core';

import { ApiError } from '../../core/api/api-error';

/** A panel's failed request, in place of its content, with a way to ask again. */
@Component({
  selector: 'dp-panel-error',
  template: `
    <div class="state" role="alert">
      <p class="state__title">{{ subject() }} couldn't be loaded.</p>
      <p>{{ error()?.message }}</p>
      @if (error()?.requestId; as requestId) {
        <p class="request-id">Request ID {{ requestId }}</p>
      }
      <button class="button" type="button" (click)="retry.emit()">Try again</button>
    </div>
  `,
})
export class PanelError {
  /** What failed, as the start of a sentence: "The key numbers". */
  readonly subject = input.required<string>();
  readonly error = input.required<ApiError | null>();
  readonly retry = output();
}
