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
  ValidationMessages,
  applyServerErrors,
  focusFirstInvalid,
  visibleError,
} from '../../../shared/forms/form-errors';
import { PASSWORD_MAX_LENGTH } from '../password-rules';

const MESSAGES: Record<'email' | 'password', ValidationMessages> = {
  email: {
    required: 'Enter your email address.',
    email: 'Enter an email address like name@example.com.',
  },
  password: {
    required: 'Enter your password.',
    maxlength: `Passwords are at most ${String(PASSWORD_MAX_LENGTH)} characters long.`,
  },
};

@Component({
  selector: 'dp-login-page',
  imports: [ReactiveFormsModule, RouterLink, FormAlert],
  templateUrl: './login-page.html',
  styleUrl: '../auth-page.scss',
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly destroyRef = inject(DestroyRef);

  private readonly requestedReturnUrl =
    inject(ActivatedRoute).snapshot.queryParamMap.get('returnUrl');

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.maxLength(PASSWORD_MAX_LENGTH)]],
  });
  protected readonly pending = signal(false);
  protected readonly formError = signal<ApiError | null>(null);
  /** Carried to the register page, so signing up also returns to the requested page. */
  protected readonly returnUrlParams =
    this.requestedReturnUrl === null ? {} : { returnUrl: this.requestedReturnUrl };

  protected errorFor(field: keyof typeof MESSAGES): string | null {
    return visibleError(this.form.controls[field], MESSAGES[field]);
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
      .login(this.form.getRawValue())
      .pipe(
        finalize(() => {
          this.pending.set(false);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => void this.router.navigateByUrl(safeReturnUrl(this.requestedReturnUrl)),
        error: (error: unknown) => {
          const apiError = parseApiError(error);
          if (apiError.status !== 422 || !applyServerErrors(this.form, apiError)) {
            this.formError.set(apiError);
          }
        },
      });
  }
}
