import { AskOut, HistoryItemOut, HistoryPageOut, ModelOut, ModelsOut } from '../../core/api/models';

/** Builders for Ask your data test data, shared by the ask specs. */
export function modelOut(overrides: Partial<ModelOut> = {}): ModelOut {
  return {
    id: 'demo',
    label: 'Demo model',
    provider: 'demo',
    provider_label: 'Demo',
    default: false,
    ...overrides,
  };
}

export function modelsOut(): ModelsOut {
  return {
    items: [
      modelOut({ default: true }),
      modelOut({
        id: 'groq-gpt-oss-120b',
        label: 'GPT-OSS 120B',
        provider: 'groq',
        provider_label: 'Groq',
      }),
      modelOut({
        id: 'gemini-flash-lite',
        label: 'Gemini 3.5 Flash-Lite',
        provider: 'gemini',
        provider_label: 'Google Gemini',
      }),
    ],
    default_model: 'demo',
  };
}

export function askOut(overrides: Partial<AskOut> = {}): AskOut {
  return {
    id: 124,
    question: 'What was the monthly revenue over the last 12 months?',
    requested_model: 'demo',
    model: { id: 'demo', label: 'Demo model', provider: 'demo', provider_label: 'Demo' },
    fell_back: false,
    sql: 'SELECT\n  month,\n  revenue\nFROM v_orders\nLIMIT 1001',
    explanation: 'Revenue from paid orders in each of the last 12 complete months.',
    chart: 'line',
    assumptions: ['The current month is left out because it is not complete yet.'],
    columns: [
      { name: 'month', type: 'date' },
      { name: 'revenue', type: 'number' },
    ],
    rows: [
      ['2026-08-01', '7253552.97'],
      ['2026-09-01', '7512345.67'],
    ],
    row_count: 2,
    truncated: false,
    repaired: false,
    latency_ms: 214,
    prompt_version: 'v3',
    created_at: '2026-10-09T14:02:00Z',
    ...overrides,
  };
}

export function historyItemOut(overrides: Partial<HistoryItemOut> = {}): HistoryItemOut {
  return {
    id: 120,
    question: 'How many orders came from each channel this year?',
    status: 'ok',
    error_code: null,
    requested_model: 'demo',
    model: 'demo',
    provider: 'demo',
    sql: 'SELECT channel, count(*) AS orders FROM v_orders GROUP BY channel',
    explanation: 'The number of orders placed through each channel since 1 January.',
    chart: 'bar',
    assumptions: [],
    row_count: 3,
    truncated: false,
    repaired: false,
    latency_ms: 31,
    created_at: '2026-10-08T12:00:00Z',
    ...overrides,
  };
}

export function historyPageOut(
  items: HistoryItemOut[] = [historyItemOut()],
  nextCursor: string | null = null,
): HistoryPageOut {
  return { items, next_cursor: nextCursor };
}
