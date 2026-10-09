import { Routes } from '@angular/router';

import { guestGuard } from './core/auth/guards';

export const routes: Routes = [
  {
    path: 'login',
    title: 'Log in',
    canActivate: [guestGuard],
    loadComponent: () => import('./features/auth/login/login-page').then((m) => m.LoginPage),
  },
  {
    path: 'register',
    title: 'Create an account',
    canActivate: [guestGuard],
    loadComponent: () =>
      import('./features/auth/register/register-page').then((m) => m.RegisterPage),
  },
];
