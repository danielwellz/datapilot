import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AuthService } from './auth.service';
import { HOME_URL, authGuard, guestGuard, safeReturnUrl } from './guards';

@Component({ template: '' })
class Blank {}

describe('safeReturnUrl', () => {
  it.each(['/orders', '/orders?status=paid&country=DE', '/orders/42#items', '/ask'])(
    'follows the app path %s',
    (url) => {
      expect(safeReturnUrl(url)).toBe(url);
    },
  );

  it.each([
    null,
    undefined,
    '',
    'orders',
    'https://evil.example',
    'javascript:alert(1)',
    '//evil.example',
    '/\\evil.example',
    '/orders\n',
    '/login',
    '/login?returnUrl=%2Forders',
    '/register',
  ])('falls back to the home page for %j', (url) => {
    expect(safeReturnUrl(url)).toBe(HOME_URL);
  });
});

describe('guards', () => {
  let signedIn: boolean;

  beforeEach(() => {
    signedIn = false;
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { isAuthenticated: () => signedIn } },
        provideRouter([
          { path: 'login', component: Blank, canActivate: [guestGuard] },
          { path: '', canActivateChild: [authGuard], children: [{ path: '**', component: Blank }] },
        ]),
      ],
    });
  });

  async function visit(url: string): Promise<string> {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    return TestBed.inject(Router).url;
  }

  it('lets a signed-in user open a protected page', async () => {
    signedIn = true;

    expect(await visit('/orders?status=paid')).toBe('/orders?status=paid');
  });

  it('sends a visitor to log in and remembers the requested page', async () => {
    expect(await visit('/orders?status=paid')).toBe('/login?returnUrl=%2Forders%3Fstatus%3Dpaid');
  });

  it('sends a visitor from the home page to a plain login page', async () => {
    expect(await visit(HOME_URL)).toBe('/login');
  });

  it('shows the login page to a visitor', async () => {
    expect(await visit('/login')).toBe('/login');
  });

  it('sends a signed-in user from the login page to the return URL', async () => {
    signedIn = true;

    expect(await visit('/login?returnUrl=%2Forders')).toBe('/orders');
  });

  it('sends a signed-in user from the login page home when the return URL is unsafe', async () => {
    signedIn = true;

    expect(await visit('/login?returnUrl=%2F%2Fevil.example')).toBe(HOME_URL);
  });
});
