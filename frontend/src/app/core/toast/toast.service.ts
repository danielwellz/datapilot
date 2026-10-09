import { DestroyRef, Injectable, inject, signal } from '@angular/core';

export type ToastKind = 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  /** A secondary line, such as a request id to quote when reporting a problem. */
  detail: string | null;
}

/** Visible at once; older toasts make room for newer ones. */
export const MAX_TOASTS = 3;
export const INFO_TOAST_DURATION_MS = 6000;

/**
 * Short messages about things that happened outside the current form, such as
 * a server error or an ended session.
 *
 * Information closes by itself. Errors stay until dismissed, so nobody has to
 * read a request id against a timer.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly items = signal<readonly Toast[]>([]);
  private readonly timers = new Map<number, ReturnType<typeof setTimeout>>();
  private nextId = 1;

  readonly toasts = this.items.asReadonly();

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      for (const timer of this.timers.values()) {
        clearTimeout(timer);
      }
    });
  }

  error(message: string, detail: string | null = null): void {
    this.show('error', message, detail);
  }

  info(message: string): void {
    this.show('info', message, null);
  }

  dismiss(id: number): void {
    clearTimeout(this.timers.get(id));
    this.timers.delete(id);
    this.items.update((toasts) => toasts.filter((toast) => toast.id !== id));
  }

  private show(kind: ToastKind, message: string, detail: string | null): void {
    // Parallel requests failing for one reason should produce one message.
    if (this.items().some((toast) => toast.kind === kind && toast.message === message)) {
      return;
    }
    const toast: Toast = { id: this.nextId++, kind, message, detail };
    const overflow = this.items().length + 1 - MAX_TOASTS;
    for (const old of this.items().slice(0, Math.max(overflow, 0))) {
      this.dismiss(old.id);
    }
    this.items.update((toasts) => [...toasts, toast]);
    if (kind === 'info') {
      this.timers.set(
        toast.id,
        setTimeout(() => {
          this.dismiss(toast.id);
        }, INFO_TOAST_DURATION_MS),
      );
    }
  }
}
