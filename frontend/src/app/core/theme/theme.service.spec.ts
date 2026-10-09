import { TestBed } from '@angular/core/testing';

import { THEME_STORAGE_KEY, ThemeService } from './theme.service';

interface FakeMediaQuery {
  matches: boolean;
  listeners: ((event: MediaQueryListEvent) => void)[];
  addEventListener: (type: 'change', listener: (event: MediaQueryListEvent) => void) => void;
  removeEventListener: (type: 'change', listener: (event: MediaQueryListEvent) => void) => void;
}

function fakeDarkQuery(matches: boolean): FakeMediaQuery {
  const query: FakeMediaQuery = {
    matches,
    listeners: [],
    addEventListener: (_type, listener) => query.listeners.push(listener),
    removeEventListener: (_type, listener) => {
      query.listeners = query.listeners.filter((existing) => existing !== listener);
    },
  };
  return query;
}

describe('ThemeService', () => {
  let query: FakeMediaQuery;

  function createService(systemDark = false): ThemeService {
    query = fakeDarkQuery(systemDark);
    vi.spyOn(window, 'matchMedia').mockReturnValue(query as unknown as MediaQueryList);
    return TestBed.inject(ThemeService);
  }

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('follows the system theme when nothing is stored', () => {
    const service = createService(true);

    expect(service.preference()).toBe('system');
    expect(service.theme()).toBe('dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('applies a stored choice at startup', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');

    const service = createService(false);

    expect(service.theme()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('ignores an unknown stored value', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'sepia');

    expect(createService().preference()).toBe('system');
  });

  it('toggles to the other theme and remembers it', () => {
    const service = createService(false);

    service.toggle();

    expect(service.theme()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');

    service.toggle();

    expect(service.theme()).toBe('light');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('forgets the choice when asked to match the system', () => {
    const service = createService(true);
    service.toggle();

    service.matchSystem();

    expect(service.preference()).toBe('system');
    expect(service.theme()).toBe('dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('follows system changes while matching the system', () => {
    const service = createService(false);

    for (const listener of query.listeners) {
      listener({ matches: true } as MediaQueryListEvent);
    }

    expect(service.theme()).toBe('dark');
  });

  it('keeps working when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    const service = createService(false);

    service.toggle();

    expect(service.theme()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('stops listening to the system when destroyed', () => {
    createService(false);

    TestBed.resetTestingModule();

    expect(query.listeners).toHaveLength(0);
  });
});
