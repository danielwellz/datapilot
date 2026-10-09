import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, computed, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { ThemeService } from '../../core/theme/theme.service';

interface NavItem {
  path: string;
  label: string;
}

/** The frame around every signed-in page: header, navigation and the routed page. */
@Component({
  selector: 'dp-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, CdkMenu, CdkMenuItem, CdkMenuTrigger],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  protected readonly theme = inject(ThemeService);

  protected readonly navItems: readonly NavItem[] = [
    { path: '/dashboard', label: 'Dashboard' },
    { path: '/orders', label: 'Orders' },
    { path: '/ask', label: 'Ask' },
  ];

  protected readonly user = this.auth.user;
  protected readonly initials = computed(() => initialsOf(this.user()?.full_name ?? ''));
  protected readonly themeToggleLabel = computed(() =>
    this.theme.theme() === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
  );

  protected logout(): void {
    this.auth.logout().subscribe(() => {
      void this.router.navigateByUrl('/login');
    });
  }
}

/** Up to two letters for the account button: the first and last words of the name. */
export function initialsOf(fullName: string): string {
  const words = fullName.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return '';
  }
  const first = words[0];
  const last = words.length > 1 ? words[words.length - 1] : '';
  return (first.charAt(0) + last.charAt(0)).toUpperCase();
}
