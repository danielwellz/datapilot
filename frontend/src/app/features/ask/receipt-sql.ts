import {
  Component,
  DOCUMENT,
  InjectionToken,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { highlightSql } from './sql-highlight';

/** Writes text to the clipboard; tests replace it, because jsdom has no clipboard. */
export const CLIPBOARD_WRITE = new InjectionToken<(text: string) => Promise<void>>(
  'CLIPBOARD_WRITE',
  {
    providedIn: 'root',
    factory: () => {
      const clipboard = inject(DOCUMENT).defaultView?.navigator.clipboard;
      return (text) =>
        clipboard === undefined
          ? Promise.reject(new Error('The clipboard is not available.'))
          : clipboard.writeText(text);
    },
  },
);

type CopyState = 'idle' | 'copied' | 'failed';

let nextId = 1;

/**
 * The SQL of a receipt: collapsed until asked for, then shown with line
 * numbers and light highlighting, with a button that copies it. The SQL is
 * model output, so it is rendered as text spans and never as HTML.
 */
@Component({
  selector: 'dp-receipt-sql',
  templateUrl: './receipt-sql.html',
  styleUrl: './receipt-sql.scss',
})
export class ReceiptSql {
  private readonly writeClipboard = inject(CLIPBOARD_WRITE);

  readonly sql = input.required<string>();
  /** What the SQL is: "SQL that ran", "SQL that was refused". */
  readonly label = input('SQL that ran');
  readonly expandedByDefault = input(false);

  protected readonly regionId = `receipt-sql-${String(nextId++)}`;
  private readonly toggled = signal<boolean | null>(null);
  protected readonly expanded = computed(() => this.toggled() ?? this.expandedByDefault());
  protected readonly lines = computed(() => highlightSql(this.sql()));
  protected readonly copyState = signal<CopyState>('idle');

  protected toggle(): void {
    this.toggled.set(!this.expanded());
  }

  protected copy(): void {
    this.writeClipboard(this.sql()).then(
      () => {
        this.copyState.set('copied');
      },
      () => {
        this.copyState.set('failed');
      },
    );
  }
}
