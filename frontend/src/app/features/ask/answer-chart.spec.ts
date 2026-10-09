import { AnswerChart as Suggestion, JsonValue, ResultColumnOut } from '../../core/api/models';
import { ChartInput, MAX_BARS, MIN_LINE_POINTS, answerChart } from './answer-chart';

function input(
  chart: Suggestion,
  columns: [string, ResultColumnOut['type']][],
  rows: JsonValue[][],
  truncated = false,
): ChartInput {
  return { chart, columns: columns.map(([name, type]) => ({ name, type })), rows, truncated };
}

const MONTHS = [
  ['2026-07-01', '7100000.10'],
  ['2026-08-01', '7253552.97'],
  ['2026-09-01', '7512345.67'],
];

function chartOf(value: ChartInput) {
  const chart = answerChart(value);
  if (chart === null) {
    throw new Error('Expected a chart');
  }
  return chart;
}

describe('answerChart', () => {
  describe('the example questions', () => {
    // The column types the backend reports for each example's SQL.
    const examples: [string, Suggestion, [string, ResultColumnOut['type']][], JsonValue[][]][] = [
      [
        'monthly revenue',
        'line',
        [
          ['month', 'date'],
          ['revenue', 'number'],
        ],
        MONTHS,
      ],
      [
        'top countries',
        'bar',
        [
          ['country', 'string'],
          ['revenue', 'number'],
        ],
        [['DE', '10.00']],
      ],
      [
        'top products',
        'bar',
        [
          ['name', 'string'],
          ['revenue', 'number'],
        ],
        [['Lamp', '5.50']],
      ],
      [
        'orders by channel',
        'bar',
        [
          ['channel', 'string'],
          ['orders', 'number'],
        ],
        [['web', 9]],
      ],
      [
        'average order value by country',
        'bar',
        [
          ['country', 'string'],
          ['average_order_value', 'number'],
        ],
        [['GB', '108.09']],
      ],
      [
        'monthly refund rate',
        'line',
        [
          ['month', 'date'],
          ['refund_rate_percent', 'number'],
        ],
        [
          ['2026-08-01', '3.10'],
          ['2026-09-01', '2.90'],
        ],
      ],
      [
        'units by category',
        'bar',
        [
          ['category', 'string'],
          ['units', 'number'],
        ],
        [['Books', 41]],
      ],
      [
        'monthly signups',
        'line',
        [
          ['month', 'date'],
          ['new_customers', 'number'],
        ],
        [
          ['2026-08-01', 1200],
          ['2026-09-01', 1350],
        ],
      ],
    ];

    it.each(examples)('draws a chart for %s', (_, chart, columns, rows) => {
      expect(answerChart(input(chart, columns, rows))?.spec.kind).toBe(chart);
    });
  });

  describe('a line chart', () => {
    it('plots each date against its value, labelled by month', () => {
      const { spec, height } = chartOf(
        input(
          'line',
          [
            ['month', 'date'],
            ['revenue', 'number'],
          ],
          MONTHS,
        ),
      );

      expect(spec.horizontal).toBe(false);
      expect(spec.labels).toEqual(['Jul 2026', 'Aug 2026', 'Sep 2026']);
      expect(spec.series).toEqual([
        { label: 'revenue', values: [7100000.1, 7253552.97, 7512345.67], color: 1 },
      ]);
      expect(spec.formatTick(7_500_000)).toBe('7.5M');
      expect(height).toBe(280);
    });

    it('shows the exact value in the tooltip', () => {
      const { spec } = chartOf(
        input(
          'line',
          [
            ['month', 'date'],
            ['revenue', 'number'],
          ],
          MONTHS,
        ),
      );

      expect(spec.tooltipLabel?.(0, 1)).toBe('revenue: 7,253,552.97');
      expect(spec.tooltipLabel?.(0, 9)).toBe('');
    });

    it('labels days that are not month starts as dates', () => {
      const { spec } = chartOf(
        input(
          'line',
          [
            ['day', 'date'],
            ['orders', 'number'],
          ],
          [
            ['2026-09-01', 1],
            ['2026-09-02', 2],
          ],
        ),
      );

      expect(spec.labels).toEqual(['Sep 1, 2026', 'Sep 2, 2026']);
    });

    it('labels instants with their UTC time', () => {
      const { spec } = chartOf(
        input(
          'line',
          [
            ['hour', 'datetime'],
            ['orders', 'number'],
          ],
          [
            ['2026-09-01T10:00:00Z', 1],
            ['2026-09-01T11:00:00Z', 2],
          ],
        ),
      );

      expect(spec.labels).toEqual(['Sep 1, 2026, 10:00', 'Sep 1, 2026, 11:00']);
    });

    it('sorts the points by date, whatever order the SQL returned', () => {
      const { spec } = chartOf(
        input(
          'line',
          [
            ['month', 'date'],
            ['revenue', 'number'],
          ],
          [MONTHS[2], MONTHS[0], MONTHS[1]],
        ),
      );

      expect(spec.labels).toEqual(['Jul 2026', 'Aug 2026', 'Sep 2026']);
      expect(spec.tooltipLabel?.(0, 0)).toBe('revenue: 7,100,000.10');
    });

    it('accepts the value column first', () => {
      const { spec } = chartOf(
        input(
          'line',
          [
            ['revenue', 'number'],
            ['month', 'date'],
          ],
          MONTHS.map(([month, revenue]) => [revenue, month]),
        ),
      );

      expect(spec.labels).toEqual(['Jul 2026', 'Aug 2026', 'Sep 2026']);
    });

    it(`needs at least ${String(MIN_LINE_POINTS)} points`, () => {
      expect(
        answerChart(
          input(
            'line',
            [
              ['month', 'date'],
              ['revenue', 'number'],
            ],
            [['2026-09-01', '1.00']],
          ),
        ),
      ).toBeNull();
    });

    it('needs a date column, not text', () => {
      expect(
        answerChart(
          input(
            'line',
            [
              ['country', 'string'],
              ['revenue', 'number'],
            ],
            [
              ['DE', '1'],
              ['GB', '2'],
            ],
          ),
        ),
      ).toBeNull();
    });
  });

  describe('a bar chart', () => {
    it('draws text categories as horizontal bars with short axis labels', () => {
      const name = 'Noise-cancelling headphones for travel';
      const { spec, height } = chartOf(
        input(
          'bar',
          [
            ['name', 'string'],
            ['revenue', 'number'],
          ],
          [
            [name, '2500000.00'],
            ['Lamp', '10.00'],
          ],
        ),
      );

      expect(spec.horizontal).toBe(true);
      expect(spec.labels).toEqual([name, 'Lamp']);
      expect(spec.formatLabel?.(name)).toBe('Noise-cancelling head…');
      expect(spec.tooltipLabel?.(0, 0)).toBe('revenue: 2,500,000.00');
      // Never shorter than four bars, so one bar does not fill the whole receipt.
      expect(height).toBe(4 * 28 + 40);
    });

    it('grows with the number of bars', () => {
      const rows = Array.from({ length: 10 }, (_, index) => [`C${String(index)}`, index]);
      const { height } = chartOf(
        input(
          'bar',
          [
            ['category', 'string'],
            ['units', 'number'],
          ],
          rows,
        ),
      );

      expect(height).toBe(10 * 28 + 40);
    });

    it('draws dates as vertical bars', () => {
      const { spec } = chartOf(
        input(
          'bar',
          [
            ['month', 'date'],
            ['revenue', 'number'],
          ],
          MONTHS,
        ),
      );

      expect(spec.horizontal).toBe(false);
      expect(spec.formatLabel).toBeUndefined();
      expect(spec.labels).toEqual(['Jul 2026', 'Aug 2026', 'Sep 2026']);
    });

    it('keeps the order of the SQL, which ranks the bars', () => {
      const { spec } = chartOf(
        input(
          'bar',
          [
            ['country', 'string'],
            ['revenue', 'number'],
          ],
          [
            ['US', '30'],
            ['DE', '20'],
            ['GB', '10'],
          ],
        ),
      );

      expect(spec.labels).toEqual(['US', 'DE', 'GB']);
    });

    it(`draws up to ${String(MAX_BARS)} bars and no more`, () => {
      const rows = (count: number) =>
        Array.from({ length: count }, (_, index) => [`C${String(index)}`, index]);
      const columns: [string, ResultColumnOut['type']][] = [
        ['category', 'string'],
        ['units', 'number'],
      ];

      expect(answerChart(input('bar', columns, rows(MAX_BARS)))).not.toBeNull();
      expect(answerChart(input('bar', columns, rows(MAX_BARS + 1)))).toBeNull();
    });

    it('needs at least one row', () => {
      expect(
        answerChart(
          input(
            'bar',
            [
              ['category', 'string'],
              ['units', 'number'],
            ],
            [],
          ),
        ),
      ).toBeNull();
    });
  });

  describe('no chart', () => {
    const fits: [string, ResultColumnOut['type']][] = [
      ['country', 'string'],
      ['revenue', 'number'],
    ];

    it('when the model suggested none, even if the shape fits', () => {
      expect(answerChart(input('none', fits, [['DE', '1']]))).toBeNull();
    });

    it('when the result was truncated', () => {
      expect(answerChart(input('bar', fits, [['DE', '1']], true))).toBeNull();
    });

    it.each<[string, [string, ResultColumnOut['type']][]]>([
      ['one column', [['revenue', 'number']]],
      [
        'three columns',
        [
          ['country', 'string'],
          ['channel', 'string'],
          ['revenue', 'number'],
        ],
      ],
      [
        'no number column',
        [
          ['country', 'string'],
          ['channel', 'string'],
        ],
      ],
      [
        'two number columns',
        [
          ['year', 'number'],
          ['revenue', 'number'],
        ],
      ],
      [
        'a boolean category',
        [
          ['paid', 'boolean'],
          ['orders', 'number'],
        ],
      ],
      [
        'an unknown category type',
        [
          ['span', 'other'],
          ['orders', 'number'],
        ],
      ],
    ])('when the result has %s', (_, columns) => {
      expect(answerChart(input('bar', columns, [['DE', '1', '2']]))).toBeNull();
    });

    it.each<[string, JsonValue[]]>([
      ['a missing value', ['DE', null]],
      ['a missing label', [null, '1']],
      ['a value that is not a number', ['DE', 'n/a']],
      ['an empty value', ['DE', '']],
      ['an infinite value', ['DE', 'Infinity']],
    ])('when a row has %s', (_, row) => {
      expect(answerChart(input('bar', fits, [['GB', '2'], row]))).toBeNull();
    });
  });
});
