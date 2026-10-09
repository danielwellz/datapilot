import { ApiError } from '../../core/api/api-error';
import { JsonValue } from '../../core/api/models';
import {
  Failure,
  explainFailure,
  failureFromError,
  failureFromHistory,
  failureReceipt,
} from './ask-failure';
import { historyItemOut } from './testing';

function askError(code: string, message: string, details: Record<string, JsonValue>[] = []) {
  return new ApiError(422, code, message, details, 'req-7');
}

const RECEIPT = {
  audit_id: 125,
  requested_model: 'groq-qwen',
  model: 'groq-qwen',
  provider: 'groq',
  sql: 'DELETE FROM v_orders',
  reason: 'data_modification',
};

function failure(code: string, overrides: Partial<Failure> = {}): Failure {
  return { code, message: null, explanation: null, reason: null, ...overrides };
}

describe('failureReceipt', () => {
  it('reads the audit id, models, sql and reason of a processed question', () => {
    expect(failureReceipt(askError('sql_rejected', 'Refused.', [RECEIPT]))).toEqual({
      auditId: 125,
      requestedModel: 'groq-qwen',
      model: 'groq-qwen',
      sql: 'DELETE FROM v_orders',
      reason: 'data_modification',
    });
  });

  it('reads missing optional fields as null', () => {
    const receipt = failureReceipt(
      askError('llm_unavailable', 'No model.', [
        { audit_id: 3, requested_model: 'demo', model: null, provider: null, sql: null },
      ]),
    );

    expect(receipt).toEqual({
      auditId: 3,
      requestedModel: 'demo',
      model: null,
      sql: null,
      reason: null,
    });
  });

  it('has no receipt for an error refused before the audit', () => {
    expect(failureReceipt(askError('rate_limited', 'Slow down.'))).toBeNull();
  });

  it('has no receipt for validation details', () => {
    const error = askError('validation_failed', 'Invalid.', [
      { loc: ['question'], message: 'Too short.', type: 'string_too_short' },
    ]);

    expect(failureReceipt(error)).toBeNull();
  });

  it('has no receipt when there is more than one detail', () => {
    expect(failureReceipt(askError('sql_rejected', 'Refused.', [RECEIPT, RECEIPT]))).toBeNull();
  });
});

describe('failureFromError and failureFromHistory', () => {
  it('keeps the code, message and guard reason of a live error', () => {
    expect(failureFromError(askError('sql_rejected', 'Refused.', [RECEIPT]))).toEqual({
      code: 'sql_rejected',
      message: 'Refused.',
      explanation: null,
      reason: 'data_modification',
    });
  });

  it("keeps the code and the model's explanation of a history item", () => {
    const item = historyItemOut({
      status: 'error',
      error_code: 'question_unanswerable',
      explanation: 'The data has no marketing spend.',
    });

    expect(failureFromHistory(item)).toEqual({
      code: 'question_unanswerable',
      message: null,
      explanation: 'The data has no marketing spend.',
      reason: null,
    });
  });

  it('reads a rejected history item without a code as refused', () => {
    const item = historyItemOut({ status: 'rejected', error_code: null });

    expect(failureFromHistory(item).code).toBe('sql_rejected');
  });

  it('reads a failed history item without a code as an internal error', () => {
    const item = historyItemOut({ status: 'error', error_code: null });

    expect(failureFromHistory(item).code).toBe('internal_error');
  });
});

describe('explainFailure', () => {
  it('names the reason a query was refused and says nothing ran', () => {
    const explanation = explainFailure(
      failure('sql_rejected', { reason: 'data_modification', message: 'Server words.' }),
    );

    expect(explanation.stamp).toBe('Refused');
    expect(explanation.whatHappened).toBe(
      'The query would have changed data, and DataPilot only runs queries that read it. Nothing was run.',
    );
    expect(explanation.detail).toBeNull();
    expect(explanation.remedies).toEqual({ retry: false, otherModel: true, examples: false });
  });

  it.each([
    ['not_a_query', 'a command rather than a query'],
    ['multiple_statements', 'several statements'],
    ['forbidden_table', 'outside the sales views'],
    ['forbidden_schema', 'outside the sales views'],
    ['forbidden_function', 'database function'],
    ['database', 'read-only account'],
  ])('explains a refusal for %s', (reason, words) => {
    expect(explainFailure(failure('sql_rejected', { reason })).whatHappened).toContain(words);
  });

  it("keeps the server's specifics for a refusal it has no words for", () => {
    const explanation = explainFailure(
      failure('sql_rejected', { reason: 'too_long', message: 'The SQL is too long.' }),
    );

    expect(explanation.whatHappened).toBe(
      "The model wrote a query that DataPilot won't run, so nothing was run.",
    );
    expect(explanation.detail).toBe('The SQL is too long.');
  });

  it('explains a refusal from history, which has no reason', () => {
    expect(explainFailure(failure('sql_rejected')).whatHappened).toContain('nothing was run');
  });

  it("uses the model's explanation for an unanswerable question", () => {
    const explanation = explainFailure(
      failure('question_unanswerable', {
        message: 'The demo model only answers the example questions.',
        explanation: 'There is no marketing data.',
      }),
    );

    expect(explanation.stamp).toBe('Not answered');
    expect(explanation.whatHappened).toBe('There is no marketing data.');
    expect(explanation.remedies.examples).toBe(true);
  });

  it("falls back to the server's message, then to plain words, for an unanswerable question", () => {
    expect(
      explainFailure(failure('question_unanswerable', { message: 'Demo only.' })).whatHappened,
    ).toBe('Demo only.');
    expect(explainFailure(failure('question_unanswerable')).whatHappened).toContain(
      'no way to answer',
    );
  });

  it('suggests a narrower question after a timeout, without offering the same again', () => {
    const explanation = explainFailure(failure('query_timeout', { message: 'Took 5 s.' }));

    expect(explanation.stamp).toBe('Stopped');
    expect(explanation.whatToTry).toContain('narrower question');
    expect(explanation.remedies.retry).toBe(false);
  });

  it("shows the database's error after a failed correction", () => {
    const explanation = explainFailure(
      failure('query_failed', { message: 'Its error was: column "x" does not exist' }),
    );

    expect(explanation.whatHappened).toContain('even after the model corrected it once');
    expect(explanation.detail).toBe('Its error was: column "x" does not exist');
  });

  it('asks the user to wait when they asked too many questions this minute', () => {
    const explanation = explainFailure(failure('rate_limited', { message: 'Try in 42 seconds.' }));

    expect(explanation.stamp).toBe('Limit reached');
    expect(explanation.whatHappened).not.toContain('42');
    expect(explanation.whatToTry).toBe('Wait for the countdown to end, then ask again.');
    expect(explanation.remedies).toEqual({ retry: true, otherModel: false, examples: false });
  });

  it('suggests another model when a provider is limiting requests', () => {
    const message = 'The provider of GPT-OSS 120B is rate limiting requests. Try again later.';
    const explanation = explainFailure(failure('llm_rate_limited', { message }));

    expect(explanation.whatHappened).toBe(message);
    expect(explanation.whatToTry).toContain('another model');
    expect(explanation.remedies.otherModel).toBe(true);
  });

  it('explains a provider limit from history in its own words', () => {
    expect(explainFailure(failure('llm_rate_limited')).whatHappened).toContain('daily limit');
  });

  it.each([['llm_unavailable'], ['llm_invalid_output']])(
    'offers to try again or ask another model for %s',
    (code) => {
      const explanation = explainFailure(failure(code));

      expect(explanation.stamp).toBe('Not answered');
      expect(explanation.remedies).toEqual({ retry: true, otherModel: true, examples: false });
    },
  );

  it.each([
    ['model_not_available', "isn't available any more", false],
    ['validation_failed', "wasn't accepted", false],
    ['network_error', "can't be reached", true],
  ])('says the question was not sent for %s', (code, words, retry) => {
    const explanation = explainFailure(failure(code));

    expect(explanation.stamp).toBe('Not sent');
    expect(explanation.whatHappened).toContain(words);
    expect(explanation.remedies.retry).toBe(retry);
  });

  it.each([['internal_error'], ['http_error'], ['something_new']])(
    'explains an unexpected %s and offers to try again',
    (code) => {
      const explanation = explainFailure(failure(code));

      expect(explanation.whatHappened).toBe('DataPilot ran into a problem while answering.');
      expect(explanation.whatToTry).toContain('request ID');
      expect(explanation.remedies.retry).toBe(true);
    },
  );

  it('gives every explanation a stamp, what happened and what to try', () => {
    const codes = [
      'sql_rejected',
      'question_unanswerable',
      'query_timeout',
      'query_failed',
      'rate_limited',
      'llm_rate_limited',
      'llm_unavailable',
      'llm_invalid_output',
      'model_not_available',
      'validation_failed',
      'network_error',
      'internal_error',
    ];
    for (const code of codes) {
      const { stamp, whatHappened, whatToTry } = explainFailure(failure(code));
      expect([stamp, whatHappened, whatToTry].every((text) => text.length > 0)).toBe(true);
    }
  });
});
