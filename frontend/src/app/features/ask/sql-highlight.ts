export type SqlTokenKind = 'keyword' | 'string' | 'number' | 'comment' | 'plain';

export interface SqlToken {
  kind: SqlTokenKind;
  text: string;
}

/** One line of SQL as tokens, so the receipt can number its lines. */
export type SqlLine = readonly SqlToken[];

// Reserved words a reader scans for. Words that change data are included, so
// a refused query shows its DELETE as plainly as a SELECT. Function names
// (sum, date_trunc) stay plain: they read as names, not structure.
const KEYWORDS = new Set(
  `all and as asc between by case cast cross delete desc distinct drop else end except exists
  false filter first from full group having ilike in inner insert intersect interval into is join
  lateral left like limit not null nulls offset on or order outer over partition range recursive
  right rows select set table then true truncate union update using values when where window with`
    .split(/\s+/)
    .filter(Boolean),
);

// Order matters: comments and quoted text first, so a keyword inside them
// stays part of them.
const TOKEN = new RegExp(
  [
    String.raw`(?<comment>--[^\n]*|/\*[\s\S]*?(?:\*/|$))`,
    String.raw`(?<string>'(?:[^']|'')*(?:'|$))`,
    String.raw`(?<quoted>"(?:[^"]|"")*(?:"|$))`,
    String.raw`(?<number>\b\d+(?:\.\d+)?\b)`,
    String.raw`(?<word>[A-Za-z_][A-Za-z0-9_$]*)`,
  ].join('|'),
  'g',
);

/**
 * Splits SQL into tokens for light highlighting. Every character of the input
 * is in exactly one token, so joining the texts gives back the SQL. The SQL
 * is model output: the receipt renders these as text, never as HTML.
 */
export function tokenizeSql(sql: string): SqlToken[] {
  const tokens: SqlToken[] = [];
  const push = (kind: SqlTokenKind, text: string): void => {
    const last = tokens.at(-1);
    if (last?.kind === kind && kind === 'plain') {
      last.text += text;
    } else if (text !== '') {
      tokens.push({ kind, text });
    }
  };
  let position = 0;
  for (const match of sql.matchAll(TOKEN)) {
    push('plain', sql.slice(position, match.index));
    push(kindOf(match), match[0]);
    position = match.index + match[0].length;
  }
  push('plain', sql.slice(position));
  return tokens;
}

/** The tokens of `sql`, one array per line; a token across lines is split at each break. */
export function highlightSql(sql: string): SqlLine[] {
  const lines: SqlToken[][] = [[]];
  for (const token of tokenizeSql(sql)) {
    token.text.split('\n').forEach((part, index) => {
      if (index > 0) {
        lines.push([]);
      }
      if (part !== '') {
        lines.at(-1)?.push({ kind: token.kind, text: part });
      }
    });
  }
  return lines;
}

function kindOf(match: RegExpExecArray): SqlTokenKind {
  // An unmatched group is undefined at run time, whatever the lib types say.
  const groups: Partial<Record<string, string>> = match.groups ?? {};
  if (groups['comment'] !== undefined) {
    return 'comment';
  }
  if (groups['string'] !== undefined) {
    return 'string';
  }
  if (groups['number'] !== undefined) {
    return 'number';
  }
  if (groups['word'] !== undefined && KEYWORDS.has(match[0].toLowerCase())) {
    return 'keyword';
  }
  return 'plain';
}
