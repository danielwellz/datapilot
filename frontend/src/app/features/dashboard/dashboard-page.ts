import { Component } from '@angular/core';

@Component({
  selector: 'dp-dashboard-page',
  template: `
    <section class="page" aria-labelledby="dashboard-title">
      <header class="page__header">
        <h1 id="dashboard-title">Dashboard</h1>
        <p class="page__lead">
          Revenue, orders and customers at a glance, with the change since the previous period.
        </p>
      </header>
      <div class="sheet">
        <p>
          The key numbers, monthly revenue, top customers, product ranking and retention cohorts are
          not built yet.
        </p>
      </div>
    </section>
  `,
})
export class DashboardPage {}
