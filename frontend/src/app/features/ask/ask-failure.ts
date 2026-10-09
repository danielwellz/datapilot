import { ApiError } from '../../core/api/api-error';
import { HistoryItemOut, JsonValue } from '../../core/api/models';

/**
 * What the backend attaches to a question it processed but could not answer:
 * the audit id, the models involved and the SQL, when there was some. It is
 * the error's single detail object; requests refused before the audit (a rate
 * limit, an invalid body) have none.
 */
export interface FailureReceipt {
  auditId: number;
  requestedModel: string;
  /** The model that answered before the failure; null when none did. */
  model: string | null;
  /** Model output: shown as text, never as HTML. */
  sql: string | null;
  /** Why the SQL guard refused the query, for `sql_rejected`. */
  reason: string | null;
}

/** The receipt detail of an Ask error, or null when the error has none. */
export function failureReceipt(error: ApiError): FailureReceipt | null {
  if (error.details.length !== 1) {
    return null;
  }
  const [{ audit_id, requested_model, model, sql, reason }] = error.details;
  if (typeof audit_id !== 'number' || typeof requested_model !== 'string') {
    return null;
  }
  return {
    auditId: audit_id,
    requestedModel: requested_model,
    model: stringOrNull(model),
    sql: stringOrNull(sql),
    reason: stringOrNull(reason),
  };
}

/** A question that was not answered, from a live error or from history. */
export interface Failure {
  code: string;
  /** The server's message for the analyst; history does not keep it. */
  message: string | null;
  /** The model's own explanation, when it gave one. */
  explanation: string | null;
  reason: string | null;
}

export function failureFromError(error: ApiError): Failure {
  return {
    code: error.code,
    message: error.message,
    explanation: null,
    reason: failureReceipt(error)?.reason ?? null,
  };
}

export function failureFromHistory(item: HistoryItemOut): Failure {
  return {
    code: item.error_code ?? (item.status === 'rejected' ? 'sql_rejected' : 'internal_error'),
    message: null,
    explanation: item.explanation,
    reason: null,
  };
}

/** The ways out a failed receipt offers, besides rephrasing the question. */
export interface Remedies {
  /** Send the same question again, to the same model. */
  retry: boolean;
  /** Send the same question to another enabled model. */
  otherModel: boolean;
  /** Point to the example questions. */
  examples: boolean;
}

/** A failure in plain words: a short stamp, what happened, and what to try next. */
export interface FailureExplanation {
  stamp: string;
  whatHappened: string;
  whatToTry: string;
  /** Specifics from the server, such as the database's error; shown in a quieter style. */
  detail: string | null;
  remedies: Remedies;
}

const NO_REMEDIES: Remedies = { retry: false, otherModel: false, examples: false };

const REFUSAL_REASONS: Partial<Record<string, string>> = {
  data_modification:
    'The query would have changed data, and DataPilot only runs queries that read it.',
  not_a_query:
    'The model wrote a command rather than a query, and DataPilot only runs queries that read data.',
  multiple_statements: 'The model wrote several statements, and only a single query may run.',
  forbidden_table:
    'The query reads a table outside the sales views (orders, order items, customers and products).',
  forbidden_schema:
    'The query reads outside the sales views (orders, order items, customers and products).',
  forbidden_function: 'The query uses a database function that is not allowed.',
  database: "The database's read-only account refused the query.",
};

const GENERIC_REFUSAL = "The model wrote a query that DataPilot won't run, so nothing was run.";

/**
 * Explains a failed question for the analyst. Each code gets its own words,
 * written here rather than taken from the server, so a question recalled from
 * history (which keeps only the code) reads the same as a live one; the
 * server's message is used where it adds specifics the code cannot carry.
 */
export function explainFailure(failure: Failure): FailureExplanation {
  const { code, message, explanation, reason } = failure;
  switch (code) {
    case 'sql_rejected': {
      const refusal = reason === null ? undefined : REFUSAL_REASONS[reason];
      return {
        stamp: 'Refused',
        whatHappened: refusal === undefined ? GENERIC_REFUSAL : `${refusal} Nothing was run.`,
        whatToTry: 'Ask for figures to read rather than changes to make, or ask another model.',
        // The server's message repeats a known reason; it only adds to an unknown one.
        detail: refusal === undefined ? message : null,
        remedies: { ...NO_REMEDIES, otherModel: true },
      };
    }
    case 'question_unanswerable':
      return {
        stamp: 'Not answered',
        whatHappened:
          explanation ?? message ?? 'The model found no way to answer this from the sales data.',
        whatToTry:
          "Ask about orders, revenue, customers' countries or products. The example questions show what the data covers.",
        detail: null,
        remedies: { ...NO_REMEDIES, otherModel: true, examples: true },
      };
    case 'query_timeout':
      return {
        stamp: 'Stopped',
        whatHappened: 'The query ran past the time limit and was stopped before it finished.',
        whatToTry: 'Ask a narrower question, for example over a shorter period or for one country.',
        detail: null,
        remedies: NO_REMEDIES,
      };
    case 'query_failed':
      return {
        stamp: 'Failed',
        whatHappened:
          "The database couldn't run the model's query, even after the model corrected it once.",
        whatToTry: 'Rephrase the question, or ask another model.',
        detail: message,
        remedies: { ...NO_REMEDIES, otherModel: true },
      };
    case 'rate_limited':
      return {
        stamp: 'Limit reached',
        whatHappened:
          "You've asked as many questions as one minute allows, so this one wasn't sent to a model.",
        whatToTry: 'Wait for the countdown to end, then ask again.',
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true },
      };
    case 'llm_rate_limited':
      return {
        stamp: 'Limit reached',
        whatHappened:
          message ?? "The model's provider is limiting requests or has reached its daily limit.",
        whatToTry: 'Ask the same question with another model, or try this one again later.',
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true, otherModel: true },
      };
    case 'llm_unavailable':
      return {
        stamp: 'Not answered',
        whatHappened: "No model could answer: the provider didn't respond or reported an error.",
        whatToTry: 'Try again in a moment, or ask another model.',
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true, otherModel: true },
      };
    case 'llm_invalid_output':
      return {
        stamp: 'Not answered',
        whatHappened:
          'The model replied, but not with an answer DataPilot could read, even when asked to fix it.',
        whatToTry:
          "Try again, since models don't always answer the same way, or ask another model.",
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true, otherModel: true },
      };
    case 'model_not_available':
      return {
        stamp: 'Not sent',
        whatHappened: "That model isn't available any more, so the question wasn't sent.",
        whatToTry: 'The list of models has been updated. Pick a model and ask again.',
        detail: null,
        remedies: NO_REMEDIES,
      };
    case 'validation_failed':
      return {
        stamp: 'Not sent',
        whatHappened: "The question wasn't accepted, so it wasn't sent to a model.",
        whatToTry: 'Write a question of 3 to 500 characters.',
        detail: null,
        remedies: NO_REMEDIES,
      };
    case 'network_error':
      return {
        stamp: 'Not sent',
        whatHappened: "DataPilot can't be reached, so the question may not have been sent.",
        whatToTry: 'Check your connection, then try again.',
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true },
      };
    default:
      return {
        stamp: 'Not answered',
        whatHappened: 'DataPilot ran into a problem while answering.',
        whatToTry: 'Try again in a moment. If it keeps happening, mention the request ID.',
        detail: null,
        remedies: { ...NO_REMEDIES, retry: true },
      };
  }
}

function stringOrNull(value: JsonValue | undefined): string | null {
  return typeof value === 'string' ? value : null;
}
