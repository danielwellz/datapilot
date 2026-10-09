import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'dp-not-found-page',
  imports: [RouterLink],
  template: `
    <section class="page" aria-labelledby="not-found-title">
      <header class="page__header">
        <h1 id="not-found-title">Page not found</h1>
        <p class="page__lead">There is no page at this address.</p>
      </header>
      <p><a routerLink="/dashboard">Go to the dashboard</a></p>
    </section>
  `,
})
export class NotFoundPage {}
