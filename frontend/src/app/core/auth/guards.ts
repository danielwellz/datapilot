import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

export const HOME_URL = '/dashboard';
const GUEST_PAGES = ['/login', '/register'];

/**
 * A return URL from the query string, if it is safe to follow; otherwise the
 * home page. Only paths inside the app qualify: anything a browser could read
 * as another host (`//host`, `/\host`, a scheme) is refused, and so are the
 * login and register pages, which would send the user in a circle.
 */
export function safeReturnUrl(value: string | null | undefined): string {
  if (!value?.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return HOME_URL;
  }
  // Control characters have no place in a path and can confuse URL parsers.
  if (hasControlCharacter(value)) {
    return HOME_URL;
  }
  const path = value.split(/[?#]/, 1)[0];
  return GUEST_PAGES.includes(path) ? HOME_URL : value;
}

function hasControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 0x20 || code === 0x7f) {
      return true;
    }
  }
  return false;
}

/** Lets signed-in users through; sends everyone else to log in, then back here. */
export const authGuard: CanActivateFn = (_route, state) => {
  if (inject(AuthService).isAuthenticated()) {
    return true;
  }
  return inject(Router).createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** Keeps signed-in users off the login and register pages. */
export const guestGuard: CanActivateFn = (route) => {
  if (!inject(AuthService).isAuthenticated()) {
    return true;
  }
  return inject(Router).parseUrl(safeReturnUrl(route.queryParamMap.get('returnUrl')));
};
