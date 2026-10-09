import { Component, inject } from '@angular/core';

import { ToastService } from './toast.service';

/**
 * Renders the toasts in one polite live region. The region is always in the
 * page, because screen readers only announce changes to a region they already
 * know about.
 */
@Component({
  selector: 'dp-toast-stack',
  templateUrl: './toast-stack.html',
  styleUrl: './toast-stack.scss',
})
export class ToastStack {
  protected readonly toastService = inject(ToastService);
}
