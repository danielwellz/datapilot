import { AbstractControl, FormGroup } from '@angular/forms';

import { ApiError } from '../../core/api/api-error';

/** Messages for a control's validator errors, keyed by error name (`required`, `email`, ...). */
export type ValidationMessages = Partial<Record<string, string>>;

/** Error key for a message the server returned for one field. */
export const SERVER_ERROR = 'server';

/**
 * The message to show under a control, or null when there is none to show
 * yet. Errors appear once the user has left the field or tried to submit, so
 * nobody is told an email is invalid while still typing it.
 */
export function visibleError(
  control: AbstractControl,
  messages: ValidationMessages,
): string | null {
  const errors = control.errors;
  if (errors === null || !control.touched) {
    return null;
  }
  const serverMessage: unknown = errors[SERVER_ERROR];
  if (typeof serverMessage === 'string') {
    return serverMessage;
  }
  for (const key of Object.keys(errors)) {
    const message = messages[key];
    if (message !== undefined) {
      return message;
    }
  }
  return null;
}

/**
 * Puts each field message from a validation error on the matching control.
 * The message clears itself when the user edits the field, because the
 * control's own validators then run again. Returns false when no message
 * matched a control, so the caller can show the error on the form instead.
 */
export function applyServerErrors(form: FormGroup, error: ApiError): boolean {
  let applied = false;
  for (const [field, message] of Object.entries(error.fieldErrors())) {
    const control = form.get(field);
    if (control !== null && message !== undefined) {
      control.setErrors({ [SERVER_ERROR]: message });
      control.markAsTouched();
      applied = true;
    }
  }
  return applied;
}

/** Moves focus to the first invalid field, in the order the form declares them. */
export function focusFirstInvalid(host: HTMLElement, form: FormGroup): void {
  const name = Object.keys(form.controls).find((key) => form.controls[key].invalid);
  if (name !== undefined) {
    host.querySelector<HTMLElement>(`[formControlName="${name}"]`)?.focus();
  }
}
