import { Params, convertToParamMap } from '@angular/router';

import {
  NO_FILTERS,
  activeFilterCount,
  OrderFilters,
  compareTotals,
  filtersFromParams,
  filtersToParams,
  filtersToQuery,
  hasFilters,
  sameFilters,
  validDate,
} from './order-filters';

const EVERYTHING: OrderFilters = {
  statuses: ['paid', 'cancelled'],
  country: 'DE',
  channel: 'mobile',
  customerId: 7,
  dateFrom: '2026-01-01',
  dateTo: '2026-03-31',
  minTotal: '10',
  maxTotal: '250.50',
  sort: 'total',
};

function fromParams(params: Params): OrderFilters {
  return filtersFromParams(convertToParamMap(params));
}

describe('order filters', () => {
  describe('filtersFromParams', () => {
    it('reads no filters from an empty query string', () => {
      expect(fromParams({})).toEqual(NO_FILTERS);
    });

    it('reads every filter back from the parameters it wrote', () => {
      expect(fromParams(filtersToParams(EVERYTHING))).toEqual(EVERYTHING);
    });

    it('keeps known statuses once each, in a fixed order', () => {
      expect(fromParams({ status: ['cancelled', 'paid', 'shipped', 'paid'] }).statuses).toEqual([
        'paid',
        'cancelled',
      ]);
    });

    it('accepts a lowercase country and stores it uppercase', () => {
      expect(fromParams({ country: 'de' }).country).toBe('DE');
    });

    it.each<[string, Params]>([
      ['an unknown channel', { channel: 'phone' }],
      ['a country that is not two letters', { country: 'DEU' }],
      ['a customer id of zero', { customer_id: '0' }],
      ['a customer id with a sign', { customer_id: '-7' }],
      ['a customer id beyond exact integers', { customer_id: '9007199254740993' }],
      ['an impossible date', { date_from: '2026-02-30' }],
      ['a date in another format', { date_to: '01/02/2026' }],
      ['year zero', { date_from: '0000-01-01' }],
      ['a total with three decimals', { min_total: '1.234' }],
      ['a negative total', { max_total: '-5' }],
      ['a total with eleven whole digits', { max_total: '12345678901' }],
      ['an unknown sort', { sort: 'customer' }],
    ])('drops %s', (_case, params) => {
      expect(fromParams(params)).toEqual(NO_FILTERS);
    });

    it('drops both ends of an inverted date range', () => {
      const filters = fromParams({ date_from: '2026-03-01', date_to: '2026-02-01' });
      expect([filters.dateFrom, filters.dateTo]).toEqual([null, null]);
    });

    it('compares totals as amounts, not as text', () => {
      const kept = fromParams({ min_total: '9.5', max_total: '10' });
      expect([kept.minTotal, kept.maxTotal]).toEqual(['9.5', '10']);

      const inverted = fromParams({ min_total: '100', max_total: '99.99' });
      expect([inverted.minTotal, inverted.maxTotal]).toEqual([null, null]);
    });

    it('keeps a one-sided range', () => {
      expect(fromParams({ date_to: '2026-02-01', min_total: '5' })).toEqual({
        ...NO_FILTERS,
        dateTo: '2026-02-01',
        minTotal: '5',
      });
    });
  });

  describe('filtersToParams', () => {
    it('writes nothing for no filters and the default sort', () => {
      expect(filtersToParams(NO_FILTERS)).toEqual({});
    });

    it('writes each filter under the API name', () => {
      expect(filtersToParams(EVERYTHING)).toEqual({
        status: ['paid', 'cancelled'],
        country: 'DE',
        channel: 'mobile',
        customer_id: 7,
        date_from: '2026-01-01',
        date_to: '2026-03-31',
        min_total: '10',
        max_total: '250.50',
        sort: 'total',
      });
    });
  });

  describe('filtersToQuery', () => {
    it('always sends the sort and limit, and the cursor when there is one', () => {
      expect(filtersToQuery(NO_FILTERS, 50)).toEqual({ sort: 'created_at', limit: 50 });
      expect(filtersToQuery(NO_FILTERS, 50, 'next')).toEqual({
        sort: 'created_at',
        limit: 50,
        cursor: 'next',
      });
    });

    it('maps every filter to its API field', () => {
      expect(filtersToQuery(EVERYTHING, 25)).toEqual({
        sort: 'total',
        limit: 25,
        status: ['paid', 'cancelled'],
        country: 'DE',
        channel: 'mobile',
        customer_id: 7,
        date_from: '2026-01-01',
        date_to: '2026-03-31',
        min_total: '10',
        max_total: '250.50',
      });
    });
  });

  describe('sameFilters and hasFilters', () => {
    it('treats equal values as the same filters', () => {
      expect(sameFilters(EVERYTHING, { ...EVERYTHING, statuses: ['paid', 'cancelled'] })).toBe(
        true,
      );
      expect(sameFilters(EVERYTHING, { ...EVERYTHING, statuses: ['paid'] })).toBe(false);
      expect(sameFilters(EVERYTHING, { ...EVERYTHING, maxTotal: '250.5' })).toBe(false);
    });

    it('does not count the sort as a filter', () => {
      expect(hasFilters({ ...NO_FILTERS, sort: 'total' })).toBe(false);
      expect(hasFilters({ ...NO_FILTERS, customerId: 7 })).toBe(true);
    });
  });

  it('counts each control group once', () => {
    expect(activeFilterCount(NO_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...NO_FILTERS, sort: 'total' })).toBe(0);
    expect(activeFilterCount(EVERYTHING)).toBe(6);
    expect(
      activeFilterCount({ ...NO_FILTERS, statuses: ['paid', 'refunded'], dateTo: '2026-01-01' }),
    ).toBe(2);
  });

  it('compares totals by value', () => {
    expect(compareTotals('10', '10.00')).toBe(0);
    expect(compareTotals('9.99', '10')).toBeLessThan(0);
    expect(compareTotals('1000.5', '999.99')).toBeGreaterThan(0);
  });

  it('accepts leap days and the outermost years', () => {
    expect(validDate('2024-02-29')).toBe('2024-02-29');
    expect(validDate('2026-02-29')).toBeNull();
    expect(validDate('0001-01-01')).toBe('0001-01-01');
    expect(validDate('9999-12-31')).toBe('9999-12-31');
    expect(validDate(null)).toBeNull();
  });
});
