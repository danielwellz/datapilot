import { readCookie } from './cookies';

describe('readCookie', () => {
  function documentWithCookies(cookie: string): Document {
    return { cookie } as Document;
  }

  it('finds a cookie among others', () => {
    const document = documentWithCookies('theme=dark; csrf_refresh_token=abc-123; other=1');

    expect(readCookie(document, 'csrf_refresh_token')).toBe('abc-123');
  });

  it('returns null when the cookie is absent', () => {
    expect(readCookie(documentWithCookies('theme=dark'), 'csrf_refresh_token')).toBeNull();
    expect(readCookie(documentWithCookies(''), 'csrf_refresh_token')).toBeNull();
  });

  it('does not match a cookie whose name only ends with the name', () => {
    expect(
      readCookie(documentWithCookies('x_csrf_refresh_token=1'), 'csrf_refresh_token'),
    ).toBeNull();
  });

  it('decodes encoded values and keeps equals signs inside them', () => {
    expect(readCookie(documentWithCookies('token=a%20b=c'), 'token')).toBe('a b=c');
  });

  it('keeps a value with a malformed escape as written', () => {
    expect(readCookie(documentWithCookies('token=100%'), 'token')).toBe('100%');
  });
});
