import { Component, DestroyRef, ElementRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { ApiError, parseApiError } from '../../../core/api/api-error';
import { AuthService } from '../../../core/auth/auth.service';
import { safeReturnUrl } from '../../../core/auth/guards';
import { FormAlert } from '../../../shared/forms/form-alert';
import {
  SERVER_ERROR,
  ValidationMessages,
  applyServerErrors,
  focusFirstInvalid,
  visibleError,
} from '../../../shared/forms/form-errors';
import {
  FULL_NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  passwordDiffersFromEmail,
} from '../password-rules';

const MESSAGES: Record<'full_name' | 'email' | 'password', ValidationMessages> = {
  full_name: {
    required: 'Enter your name.',
    maxlength: `Use at most ${String(FULL_NAME_MAX_LENGTH)} characters.`,
  },
  email: {
    required: 'Enter your email address.',
    email: 'Enter an email address like name@example.com.',
  },
  password: {
    required: 'Choose a password.',
    minlength: `Use at least ${String(PASSWORD_MIN_LENGTH)} characters.`,
    maxlength: `Use at most ${String(PASSWORD_MAX_LENGTH)} characters.`,
  },
};

const SAME_AS_EMAIL_MESSAGE = 'Choose a password that is different from your email address.';
const EMAIL_TAKEN = 'emailTaken';

@Component({
  selector: 'dp-register-page',
  imports: [ReactiveFormsModule, RouterLink, FormAlert],
  templateUrl: './register-page.html',
  styleUrl: '../auth-page.scss',
})
export class RegisterPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly destroyRef = inject(DestroyRef);

  private readonly requestedReturnUrl =
    inject(ActivatedRoute).snapshot.queryParamMap.get('returnUrl');

  protected readonly form = inject(NonNullableFormBuilder).group(
    {
      full_name: ['', [Validators.required, Validators.maxLength(FULL_NAME_MAX_LENGTH)]],
      email: ['', [Validators.required, Validators.email]],
      password: [
        '',
        [
          Validators.required,
          Validators.minLength(PASSWORD_MIN_LENGTH),
          Validators.maxLength(PASSWORD_MAX_LENGTH),
        ],
      ],
    },
    { validators: passwordDiffersFromEmail },
  );
  protected readonly pending = signal(false);
  protected readonly formError = signal<ApiError | null>(null);
  protected readonly returnUrlParams =
    this.requestedReturnUrl === null ? {} : { returnUrl: this.requestedReturnUrl };
  protected readonly passwordMinLength = PASSWORD_MIN_LENGTH;

  /** True while the email field shows the "already registered" message. */
  protected emailTaken(): boolean {
    return this.form.controls.email.hasError(EMAIL_TAKEN);
  }

  protected errorFor(field: keyof typeof MESSAGES): string | null {
    const message = visibleError(this.form.controls[field], MESSAGES[field]);
    if (message === null && field === 'password' && this.form.controls.password.touched) {
      return this.form.hasError('sameAsEmail') ? SAME_AS_EMAIL_MESSAGE : null;
    }
    return message;
  }

  protected submit(): void {
    this.formError.set(null);
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      focusFirstInvalid(this.host.nativeElement, this.form);
      return;
    }
    this.pending.set(true);
    this.auth
      .register(this.form.getRawValue())
      .pipe(
        finalize(() => {
          this.pending.set(false);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => void this.router.navigateByUrl(safeReturnUrl(this.requestedReturnUrl)),
        error: (error: unknown) => {
          this.showError(parseApiError(error));
        },
      });
  }

  private showError(error: ApiError): void {
    if (error.status === 409) {
      const email = this.form.controls.email;
      email.setErrors({ [SERVER_ERROR]: error.message, [EMAIL_TAKEN]: true });
      email.markAsTouched();
      focusFirstInvalid(this.host.nativeElement, this.form);
      return;
    }
    if (error.status !== 422 || !applyServerErrors(this.form, error)) {
      this.formError.set(error);
    }
  }
}
