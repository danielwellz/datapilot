import { SessionOut, UserOut } from '../api/models';

/** Builders for auth test data, shared by the auth specs. */
export function userOut(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: 1,
    email: 'analyst@example.com',
    full_name: 'Ada Analyst',
    created_at: '2026-10-01T09:00:00Z',
    ...overrides,
  };
}

export function sessionOut(accessToken = 'access-1', user: UserOut = userOut()): SessionOut {
  return { access_token: accessToken, token_type: 'Bearer', expires_in: 900, user };
}

export function setCookie(name: string, value: string): void {
  document.cookie = `${name}=${value}; path=/`;
}

export function clearCookie(name: string): void {
  document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
}
