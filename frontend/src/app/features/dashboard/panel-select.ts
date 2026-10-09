import { Component, computed, input, output } from '@angular/core';

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * A panel's selector, filled from `/api/meta`. "All" is always offered, and
 * so is the current value, even before the options arrive or when the
 * list could not be loaded.
 */
@Component({
  selector: 'dp-panel-select',
  template: `
    <div class="field">
      <label class="field__label" [for]="controlId()">{{ label() }}</label>
      <select
        class="input"
        [id]="controlId()"
        [attr.aria-describedby]="failed() ? controlId() + '-error' : null"
        (change)="choose($event)"
      >
        <option value="" [selected]="value() === null">{{ allLabel() }}</option>
        @for (option of shown(); track option.value) {
          <option [value]="option.value" [selected]="option.value === value()">
            {{ option.label }}
          </option>
        }
      </select>
      @if (failed()) {
        <p class="field__error" [id]="controlId() + '-error'">
          The list couldn't be loaded.
          <button class="button button--quiet" type="button" (click)="retry.emit()">
            Try again
          </button>
        </p>
      }
    </div>
  `,
})
export class PanelSelect {
  /** The select's id; not `id`, which would also land on this element. */
  readonly controlId = input.required<string>();
  readonly label = input.required<string>();
  /** The first option, which selects nothing. */
  readonly allLabel = input.required<string>();
  readonly options = input.required<readonly SelectOption[]>();
  readonly value = input.required<string | null>();
  readonly failed = input(false);
  readonly valueChange = output<string | null>();
  readonly retry = output();

  protected readonly shown = computed(() => {
    const value = this.value();
    const options = this.options();
    return value === null || options.some((option) => option.value === value)
      ? options
      : [{ value, label: value }, ...options];
  });

  protected choose(event: Event): void {
    const { value } = event.target as HTMLSelectElement;
    this.valueChange.emit(value === '' ? null : value);
  }
}
