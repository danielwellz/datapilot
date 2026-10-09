import { Component } from '@angular/core';

@Component({
  selector: 'dp-ask-page',
  template: `
    <section class="page" aria-labelledby="ask-title">
      <header class="page__header">
        <h1 id="ask-title">Ask your data</h1>
        <p class="page__lead">
          A question in plain English, answered with the SQL that was run and its results.
        </p>
      </header>
      <div class="sheet">
        <p>Asking questions is not built into the web app yet.</p>
      </div>
    </section>
  `,
})
export class AskPage {}
