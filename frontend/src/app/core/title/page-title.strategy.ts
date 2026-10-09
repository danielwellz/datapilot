import { Injectable, inject } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { RouterStateSnapshot, TitleStrategy } from '@angular/router';

export const PRODUCT_NAME = 'DataPilot';

/** Names the browser tab after the page first, so many open tabs stay tellable apart. */
@Injectable()
export class PageTitleStrategy extends TitleStrategy {
  private readonly title = inject(Title);

  override updateTitle(snapshot: RouterStateSnapshot): void {
    const page = this.buildTitle(snapshot);
    this.title.setTitle(page === undefined ? PRODUCT_NAME : `${page} – ${PRODUCT_NAME}`);
  }
}
