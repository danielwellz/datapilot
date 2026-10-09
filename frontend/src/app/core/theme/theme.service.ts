import { DestroyRef, Injectable, computed, inject, signal, DOCUMENT } from '@angular/core';

export type Theme = 'light' | 'dark';
export type ThemePreference = Theme | 'system';

/** localStorage key, shared with the inline script in index.html. */
export const THEME_STORAGE_KEY = 'datapilot.theme';

const DARK_QUERY = '(prefers-color-scheme: dark)';

/**
 * The colour theme: the system preference until the user picks one.
 *
 * An explicit choice is written to `data-theme` on the root element and to
 * localStorage; "system" removes both, so the stylesheet's media query
 * decides. Storage can be unavailable (private windows, blocked site data),
 * so every access is guarded and the theme still works for the session.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly window = this.document.defaultView;
  private readonly darkQuery = this.window?.matchMedia(DARK_QUERY);

  private readonly systemTheme = signal<Theme>(this.darkQuery?.matches ? 'dark' : 'light');

  readonly preference = signal<ThemePreference>(this.readStoredPreference());
  readonly theme = computed<Theme>(() => {
    const preference = this.preference();
    return preference === 'system' ? this.systemTheme() : preference;
  });

  constructor() {
    const query = this.darkQuery;
    if (query) {
      const onChange = (event: MediaQueryListEvent): void => {
        this.systemTheme.set(event.matches ? 'dark' : 'light');
      };
      query.addEventListener('change', onChange);
      inject(DestroyRef).onDestroy(() => {
        query.removeEventListener('change', onChange);
      });
    }
    this.apply(this.preference());
  }

  /** Switches to the other theme and remembers the choice. */
  toggle(): void {
    this.setPreference(this.theme() === 'dark' ? 'light' : 'dark');
  }

  /** Forgets the explicit choice and follows the system again. */
  matchSystem(): void {
    this.setPreference('system');
  }

  private setPreference(preference: ThemePreference): void {
    this.preference.set(preference);
    this.apply(preference);
    this.store(preference);
  }

  private apply(preference: ThemePreference): void {
    const root = this.document.documentElement;
    if (preference === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', preference);
    }
  }

  private readStoredPreference(): ThemePreference {
    try {
      const stored = this.window?.localStorage.getItem(THEME_STORAGE_KEY);
      return stored === 'light' || stored === 'dark' ? stored : 'system';
    } catch {
      return 'system';
    }
  }

  private store(preference: ThemePreference): void {
    try {
      if (preference === 'system') {
        this.window?.localStorage.removeItem(THEME_STORAGE_KEY);
      } else {
        this.window?.localStorage.setItem(THEME_STORAGE_KEY, preference);
      }
    } catch {
      // The choice still applies for this page; it just won't be remembered.
    }
  }
}
