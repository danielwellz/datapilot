import { Component } from '@angular/core';

@Component({
  selector: 'dp-orders-page',
  template: `
    <section class="page" aria-labelledby="orders-title">
      <header class="page__header">
        <h1 id="orders-title">Orders</h1>
        <p class="page__lead">Every order, filtered by status, country, channel, date and total.</p>
      </header>
      <div class="sheet">
        <p>The orders table and the order detail page are not built yet.</p>
      </div>
    </section>
  `,
})
export class OrdersPage {}
