import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import {
  TitleStrategy,
  provideRouter,
  withComponentInputBinding,
  withInMemoryScrolling,
} from '@angular/router';

import { routes } from './app.routes';
import { authInterceptor } from './core/auth/auth.interceptor';
import { AuthService } from './core/auth/auth.service';
import { errorInterceptor } from './core/http/error.interceptor';
import { PageTitleStrategy } from './core/title/page-title.strategy';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(
      routes,
      // Route parameters such as an order's `:id` arrive as component inputs.
      withComponentInputBinding(),
      // Back and forward return to the scroll position a page was left at.
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled' }),
    ),
    { provide: TitleStrategy, useClass: PageTitleStrategy },
    // The first interceptor is the outermost: it sees the final error, after
    // the auth interceptor has refreshed and retried.
    provideHttpClient(withInterceptors([errorInterceptor, authInterceptor])),
    // Routing waits for this, so guards already know whether a reload kept the session.
    provideAppInitializer(() => inject(AuthService).restoreSession()),
  ],
};
