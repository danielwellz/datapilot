import { FormControl, FormGroup, Validators } from '@angular/forms';

import { ApiError } from '../../core/api/api-error';
import { applyServerErrors, focusFirstInvalid, visibleError } from './form-errors';

const messages = { required: 'Enter your email address.', email: 'Enter a valid email address.' };

describe('visibleError', () => {
  it('stays silent until the field has been touched', () => {
    const control = new FormControl('', { nonNullable: true, validators: Validators.required });

    expect(visibleError(control, messages)).toBeNull();

    control.markAsTouched();
    expect(visibleError(control, messages)).toBe('Enter your email address.');
  });

  it('uses the message of the first failing validator', () => {
    const control = new FormControl('not-an-email', {
      nonNullable: true,
      validators: [Validators.required, Validators.email],
    });
    control.markAsTouched();

    expect(visibleError(control, messages)).toBe('Enter a valid email address.');
  });

  it('returns null for a valid control or an error without a message', () => {
    const valid = new FormControl('a@example.com', { validators: Validators.email });
    valid.markAsTouched();
    const unknown = new FormControl('');
    unknown.setErrors({ custom: true });
    unknown.markAsTouched();

    expect(visibleError(valid, messages)).toBeNull();
    expect(visibleError(unknown, messages)).toBeNull();
  });
});

describe('applyServerErrors', () => {
  function form(): FormGroup<{ email: FormControl<string>; password: FormControl<string> }> {
    return new FormGroup({
      email: new FormControl('a@example.com', { nonNullable: true }),
      password: new FormControl('short', { nonNullable: true }),
    });
  }

  it('shows each server message under its field until the field is edited', () => {
    const group = form();
    const error = new ApiError(422, 'validation_failed', 'The request is invalid.', [
      { loc: ['password'], message: 'The password must be at least 10 characters long.' },
    ]);

    expect(applyServerErrors(group, error)).toBe(true);
    expect(visibleError(group.controls.password, {})).toBe(
      'The password must be at least 10 characters long.',
    );

    group.controls.password.setValue('a-much-longer-password');
    expect(group.controls.password.errors).toBeNull();
  });

  it('reports when no message matched a field', () => {
    const error = new ApiError(422, 'validation_failed', 'Invalid.', [
      { loc: ['unknown_field'], message: 'Nope.' },
    ]);

    expect(applyServerErrors(form(), error)).toBe(false);
  });
});

describe('focusFirstInvalid', () => {
  it('focuses the first invalid field in declaration order', () => {
    const host = document.createElement('form');
    host.innerHTML = '<input formControlName="email" /><input formControlName="password" />';
    document.body.append(host);
    const group = new FormGroup({
      email: new FormControl('a@example.com'),
      password: new FormControl('', Validators.required),
    });

    focusFirstInvalid(host, group);

    expect(document.activeElement).toBe(host.querySelector('[formControlName="password"]'));
    host.remove();
  });
});
