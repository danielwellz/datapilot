import { Routes } from '@angular/router';

import { AskStore } from './ask.store';

export const ASK_ROUTES: Routes = [
  {
    path: '',
    title: 'Ask your data',
    // On the route rather than the page, so the thread survives a visit to
    // another page; the store clears itself when the signed-in user changes.
    providers: [AskStore],
    loadComponent: () => import('./ask-page').then((m) => m.AskPage),
  },
];
