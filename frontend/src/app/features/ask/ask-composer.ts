import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  AbstractControl,
  NonNullableFormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
} from '@angular/forms';

import { ValidationMessages, visibleError } from '../../shared/forms/form-errors';
import { AskStore } from './ask.store';

/** The backend's limits on a question, counted after trimming. */
export const MIN_QUESTION_LENGTH = 3;
export const MAX_QUESTION_LENGTH = 500;
/** The character count appears once a question gets this close to the limit. */
const COUNTER_FROM = MAX_QUESTION_LENGTH - 100;

const MESSAGES: ValidationMessages = {
  required: 'Write a question first.',
  minlength: `Write a question of at least ${String(MIN_QUESTION_LENGTH)} characters.`,
  maxlength: `Keep the question to ${String(MAX_QUESTION_LENGTH)} characters or fewer.`,
};

/** Checks the length the backend will see: the question without surrounding spaces. */
export function questionLength(control: AbstractControl<string>): ValidationErrors | null {
  const length = control.value.trim().length;
  if (length === 0) {
    return { required: true };
  }
  if (length < MIN_QUESTION_LENGTH) {
    return { minlength: true };
  }
  return length > MAX_QUESTION_LENGTH ? { maxlength: true } : null;
}

/**
 * Where a question is written: a text area (Enter asks, Shift+Enter starts a
 * new line), the model to ask, and example questions to start from.
 */
@Component({
  selector: 'dp-ask-composer',
  imports: [ReactiveFormsModule],
  templateUrl: './ask-composer.html',
  styleUrl: './ask-composer.scss',
})
export class AskComposer {
  protected readonly store = inject(AskStore);

  protected readonly form = inject(NonNullableFormBuilder).group({
    question: ['', questionLength],
  });
  private readonly question = toSignal(this.form.controls.question.valueChanges, {
    initialValue: '',
  });
  /** Every value, status and touched change, so the error follows edits and submit attempts. */
  private readonly changes = toSignal(this.form.controls.question.events);

  protected readonly length = computed(() => this.question().trim().length);
  protected readonly showCounter = computed(() => this.length() >= COUNTER_FROM);
  protected readonly maxLength = MAX_QUESTION_LENGTH;

  /**
   * Set by an attempt to ask. A text area is marked touched on blur, so
   * without this an empty box would show an error as soon as focus moved on.
   */
  private readonly attempted = signal(false);

  protected readonly error = computed(() => {
    this.changes();
    return this.attempted() ? visibleError(this.form.controls.question, MESSAGES) : null;
  });

  protected readonly submitLabel = computed(() => {
    if (this.store.isAsking()) {
      return 'Asking…';
    }
    const wait = this.store.secondsUntilAskable();
    return wait > 0 ? `Ask in ${String(wait)} s` : 'Ask';
  });

  protected selectModel(event: Event): void {
    this.store.selectModel((event.target as HTMLSelectElement).value);
  }

  /** Enter asks, unless Shift is held or an input method is still composing text. */
  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this.submit();
    }
  }

  protected submit(): void {
    const control = this.form.controls.question;
    control.markAsTouched();
    this.attempted.set(true);
    if (control.invalid || !this.store.canAsk()) {
      return;
    }
    if (this.store.ask(control.value.trim())) {
      this.form.reset();
      this.attempted.set(false);
    }
  }

  protected askExample(question: string): void {
    this.store.ask(question);
  }
}
