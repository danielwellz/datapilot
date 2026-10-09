import { SqlToken, highlightSql, tokenizeSql } from './sql-highlight';

function kinds(tokens: readonly SqlToken[]): string[] {
  return tokens.map((token) => `${token.kind}:${token.text}`);
}

describe('tokenizeSql', () => {
  it('marks keywords in any case and leaves names plain', () => {
    expect(kinds(tokenizeSql('select channel FROM v_orders'))).toEqual([
      'keyword:select',
      'plain: channel ',
      'keyword:FROM',
      'plain: v_orders',
    ]);
  });

  it('keeps function names plain', () => {
    expect(kinds(tokenizeSql('sum(total)'))).toEqual(['plain:sum(total)']);
  });

  it('marks strings, with doubled quotes inside', () => {
    expect(kinds(tokenizeSql("status = 'it''s paid'"))).toEqual([
      'plain:status = ',
      "string:'it''s paid'",
    ]);
  });

  it('does not mark keywords inside strings, quoted names or comments', () => {
    expect(kinds(tokenizeSql(`'select' "order" -- from here`))).toEqual([
      "string:'select'",
      'plain: "order" ',
      'comment:-- from here',
    ]);
  });

  it('marks line and block comments', () => {
    expect(kinds(tokenizeSql('/* a\nb */ 1 -- end'))).toEqual([
      'comment:/* a\nb */',
      'plain: ',
      'number:1',
      'plain: ',
      'comment:-- end',
    ]);
  });

  it('marks numbers but not digits inside names', () => {
    expect(kinds(tokenizeSql('LIMIT 1001 OFFSET 2.5 v2'))).toEqual([
      'keyword:LIMIT',
      'plain: ',
      'number:1001',
      'plain: ',
      'keyword:OFFSET',
      'plain: ',
      'number:2.5',
      'plain: v2',
    ]);
  });

  it('marks the words that change data, so a refused query reads plainly', () => {
    expect(kinds(tokenizeSql('DELETE FROM v_orders'))[0]).toBe('keyword:DELETE');
  });

  it('keeps an unterminated string or comment to the end', () => {
    expect(kinds(tokenizeSql("x = 'open"))).toEqual(['plain:x = ', "string:'open"]);
    expect(kinds(tokenizeSql('/* open'))).toEqual(['comment:/* open']);
  });

  it('gives back every character of the input', () => {
    const sql = "WITH t AS (\n  SELECT 'a''b' AS \"x\", 1.5 -- c\n)\nSELECT * FROM t /* d */";

    expect(
      tokenizeSql(sql)
        .map((token) => token.text)
        .join(''),
    ).toBe(sql);
  });

  it('returns no tokens for no SQL', () => {
    expect(tokenizeSql('')).toEqual([]);
  });
});

describe('highlightSql', () => {
  it('splits the tokens into lines', () => {
    const lines = highlightSql('SELECT\n  month\nFROM v_orders');

    expect(lines.map(kinds)).toEqual([
      ['keyword:SELECT'],
      ['plain:  month'],
      ['keyword:FROM', 'plain: v_orders'],
    ]);
  });

  it('splits a comment that spans lines', () => {
    expect(highlightSql('/* a\nb */').map(kinds)).toEqual([['comment:/* a'], ['comment:b */']]);
  });

  it('keeps blank lines', () => {
    expect(highlightSql('SELECT 1\n\nSELECT 2')).toHaveLength(3);
  });
});
