/** The value of a cookie readable by scripts, or null when it is not set. */
export function readCookie(document: Document, name: string): string | null {
  for (const pair of document.cookie.split(';')) {
    const separator = pair.indexOf('=');
    if (separator !== -1 && pair.slice(0, separator).trim() === name) {
      return decode(pair.slice(separator + 1).trim());
    }
  }
  return null;
}

function decode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    // A malformed escape (a lone "%") is kept as written rather than lost.
    return value;
  }
}
