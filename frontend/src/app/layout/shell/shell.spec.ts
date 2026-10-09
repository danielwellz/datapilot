import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AUTH_URLS, AuthService } from '../../core/auth/auth.service';
import { sessionOut, userOut } from '../../core/auth/testing';
import { ThemeService } from '../../core/theme/theme.service';
import { Shell, initialsOf } from './shell';

@Component({ template: '<h1>Page</h1>' })
class Page {}

describe('Shell', () => {
  let harness: RouterTestingHarness;
  let http: HttpTestingController;
  let page: HTMLElement;

  beforeEach(async () => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login', component: Page },
          {
            path: '',
            component: Shell,
            children: [
              { path: 'dashboard', component: Page },
              { path: 'orders', component: Page },
              { path: 'ask', component: Page },
            ],
          },
        ]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(AuthService)
      .login({ email: 'analyst@example.com', password: 'correct-horse' })
      .subscribe();
    http
      .expectOne(AUTH_URLS.login)
      .flush(sessionOut('token', userOut({ full_name: 'Ada Lovelace Byron' })));

    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/orders');
    page = harness.fixture.nativeElement as HTMLElement;
  });

  afterEach(() => {
    http.verify();
  });

  function button(label: string): HTMLButtonElement {
    const match = [...document.querySelectorAll('button')].find(
      (element) =>
        element.getAttribute('aria-label') === label || element.textContent.trim() === label,
    );
    if (match === undefined) {
      throw new Error(`No button labelled ${label}`);
    }
    return match;
  }

  async function openAccountMenu(): Promise<void> {
    button('Account menu for Ada Lovelace Byron').click();
    await harness.fixture.whenStable();
  }

  it('marks the current page in the primary navigation', () => {
    const links = [...page.querySelectorAll('nav[aria-label="Primary"] a')];

    expect(links.map((link) => link.textContent.trim())).toEqual(['Dashboard', 'Orders', 'Ask']);
    expect(links.map((link) => link.getAttribute('aria-current'))).toEqual([null, 'page', null]);
  });

  it('offers a skip link to the main content', () => {
    expect(page.querySelector('.skip-link')?.getAttribute('href')).toBe('#main');
    expect(page.querySelector('main#main')).not.toBeNull();
  });

  it('shows the signed-in user on the account button', () => {
    expect(page.querySelector('.account-button__initials')?.textContent.trim()).toBe('AB');
    expect(page.querySelector('.account-button__name')?.textContent.trim()).toBe(
      'Ada Lovelace Byron',
    );
  });

  it('toggles the theme and names the next action', async () => {
    button('Switch to dark theme').click();
    await harness.fixture.whenStable();

    expect(TestBed.inject(ThemeService).theme()).toBe('dark');
    expect(button('Switch to light theme')).toBeDefined();
  });

  it('does not offer to match the system theme while already following it', async () => {
    await openAccountMenu();

    expect(document.querySelector('[role="menu"]')?.textContent).not.toContain(
      'Match system theme',
    );
  });

  it('offers to match the system theme again after a theme was picked', async () => {
    TestBed.inject(ThemeService).toggle();
    await openAccountMenu();

    button('Match system theme').click();

    expect(TestBed.inject(ThemeService).preference()).toBe('system');
  });

  it('logs out from the account menu and opens the login page', async () => {
    await openAccountMenu();
    const menu = document.querySelector('[role="menu"]');
    expect(menu?.textContent).toContain('analyst@example.com');

    button('Log out').click();
    http.expectOne(AUTH_URLS.logout).flush(null, { status: 204, statusText: 'No Content' });
    await harness.fixture.whenStable();

    expect(TestBed.inject(AuthService).isAuthenticated()).toBe(false);
    expect(TestBed.inject(Router).url).toBe('/login');
  });
});

describe('initialsOf', () => {
  it.each([
    ['Ada Analyst', 'AA'],
    ['  ada   lovelace byron ', 'AB'],
    ['Plato', 'P'],
    ['', ''],
  ])('turns %j into %j', (name, initials) => {
    expect(initialsOf(name)).toBe(initials);
  });
});
