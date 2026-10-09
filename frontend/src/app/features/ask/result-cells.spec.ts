import { ColumnType, JsonValue } from '../../core/api/models';
import { NULL_TEXT, formatCell, formatResult } from './result-cells';

describe('formatCell', () => {
  it.each<[JsonValue, ColumnType, string]>([
    [null, 'number', NULL_TEXT],
    ['7253552.97', 'number', '7,253,552.97'],
    [42, 'number', '42'],
    ['2026-09-01', 'date', 'Sep 1, 2026'],
    ['2026-09-01T23:30:00Z', 'datetime', 'Sep 1, 2026, 23:30 UTC'],
    [true, 'boolean', 'Yes'],
    [false, 'boolean', 'No'],
    ['DE', 'string', 'DE'],
    ['P1DT2H', 'other', 'P1DT2H'],
    [[1, 2], 'other', '[1,2]'],
    [{ a: 1 }, 'other', '{"a":1}'],
  ])('formats %j of type %s as %j', (value, type, expected) => {
    expect(formatCell(value, type)).toBe(expected);
  });

  it('leaves text that is not a number as it is in a number column', () => {
    expect(formatCell(true, 'number')).toBe('Yes');
  });

  it('shows markup in a value as text', () => {
    expect(formatCell('<img src=x>', 'string')).toBe('<img src=x>');
  });
});

describe('formatResult', () => {
  it('formats every row and measures each column by its widest value', () => {
    const result = formatResult(
      [
        { name: 'country', type: 'string' },
        { name: 'revenue', type: 'number' },
      ],
      [
        ['DE', '1234567.50'],
        ['GB', null],
      ],
    );

    expect(result.rows).toEqual([
      ['DE', '1,234,567.50'],
      ['GB', NULL_TEXT],
    ]);
    expect(result.columns).toEqual([
      { name: 'country', numeric: false, widthCh: 7 },
      { name: 'revenue', numeric: true, widthCh: 12 },
    ]);
  });

  it('caps the width of a long column', () => {
    const result = formatResult([{ name: 'name', type: 'string' }], [['x'.repeat(90)]]);

    expect(result.columns[0]?.widthCh).toBe(40);
  });

  it('reads a missing value as null', () => {
    const result = formatResult(
      [
        { name: 'a', type: 'string' },
        { name: 'b', type: 'string' },
      ],
      [['only a']],
    );

    expect(result.rows).toEqual([['only a', NULL_TEXT]]);
  });

  it('measures the header of a result without rows', () => {
    expect(formatResult([{ name: 'units', type: 'number' }], []).columns[0]?.widthCh).toBe(5);
  });
});
