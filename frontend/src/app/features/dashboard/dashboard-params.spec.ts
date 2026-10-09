import { convertToParamMap } from '@angular/router';

import { DEFAULT_PARAMS, paramsFromQuery, paramsToQuery } from './dashboard-params';

describe('dashboard params', () => {
  it('reads every selector from the query string', () => {
    expect(
      paramsFromQuery(convertToParamMap({ days: '7', country: 'de', category: 'Home & Kitchen' })),
    ).toEqual({ days: 7, country: 'DE', category: 'Home & Kitchen' });
  });

  it('uses the defaults for an empty query string', () => {
    expect(paramsFromQuery(convertToParamMap({}))).toEqual(DEFAULT_PARAMS);
  });

  it.each([
    [{ days: '14' }, 'a period the selector does not offer'],
    [{ days: 'week' }, 'a period that is not a number'],
    [{ country: 'DEU' }, 'a three-letter country'],
    [{ country: 'D1' }, 'a country with a digit'],
    [{ category: '   ' }, 'a blank category'],
    [{ category: 'x'.repeat(51) }, 'a category longer than the API accepts'],
  ])('drops %o (%s)', (query, reason) => {
    expect(paramsFromQuery(convertToParamMap(query)), reason).toEqual(DEFAULT_PARAMS);
  });

  it('trims a category', () => {
    expect(paramsFromQuery(convertToParamMap({ category: ' Books ' })).category).toBe('Books');
  });

  it('removes defaults from the URL and keeps the rest', () => {
    expect(paramsToQuery(DEFAULT_PARAMS)).toEqual({ days: null, country: null, category: null });
    expect(paramsToQuery({ days: 90, country: 'GB', category: 'Books' })).toEqual({
      days: 90,
      country: 'GB',
      category: 'Books',
    });
  });

  it('round-trips through the URL', () => {
    const params = { days: 7, country: 'US', category: 'Toys & Games' } as const;
    const query = Object.fromEntries(
      Object.entries(paramsToQuery(params)).map(([key, value]) => [key, String(value)]),
    );
    expect(paramsFromQuery(convertToParamMap(query))).toEqual(params);
  });
});
