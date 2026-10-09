import { Routes } from '@angular/router';

import { OrdersStore } from './orders.store';

export const ORDERS_ROUTES: Routes = [
  {
    path: '',
    // One store for the list and the detail pages, so going back to the list
    // finds the rows, cursor and scroll position it left.
    providers: [OrdersStore],
    children: [
      {
        path: '',
        title: 'Orders',
        loadComponent: () => import('./orders-page').then((m) => m.OrdersPage),
      },
    ],
  },
];
