import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/** The backend's password rules (`backend/app/schemas/auth.py`), checked here first for quick feedback. */
export const PASSWORD_MIN_LENGTH = 10;
export const PASSWORD_MAX_LENGTH = 128;
/** `FULL_NAME_MAX_LENGTH` in `backend/app/models/user.py`. */
export const FULL_NAME_MAX_LENGTH = 100;

/**
 * Fails with `sameAsEmail` when the group's password equals its email,
 * ignoring case and surrounding spaces as the backend does.
 */
export const passwordDiffersFromEmail: ValidatorFn = (
  group: AbstractControl,
): ValidationErrors | null => {
  const email: unknown = group.get('email')?.value;
  const password: unknown = group.get('password')?.value;
  if (typeof email !== 'string' || typeof password !== 'string' || password === '') {
    return null;
  }
  return password.toLowerCase() === email.trim().toLowerCase() ? { sameAsEmail: true } : null;
};
