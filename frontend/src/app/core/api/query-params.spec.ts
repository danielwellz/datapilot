import { toHttpParams } from './query-params';

describe('toHttpParams', () => {
  it('repeats a key for each list value and keeps the order of fields', () => {
    const params = toHttpParams({
      status: ['paid', 'refunded'],
      country: 'DE',
      customer_id: 7,
      min_total: '10.00',
      cursor: 'abc',
    });
    expect(params.toString()).toBe(
      'status=paid&status=refunded&country=DE&customer_id=7&min_total=10.00&cursor=abc',
    );
  });

  it('leaves out absent fields and empty lists', () => {
    expect(toHttpParams({ status: [], country: undefined, category: null }).toString()).toBe('');
  });
});
