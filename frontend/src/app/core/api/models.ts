/**
 * Request and response bodies of the DataPilot API. Each interface mirrors a
 * backend Pydantic schema of the same name field for field, so JSON keys stay
 * snake_case. Timestamps are ISO 8601 UTC strings.
 */

/** A JSON value, as the backend's `JsonValue`. */
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface UserOut {
  id: number;
  email: string;
  full_name: string;
  created_at: string;
}

export interface UserCreate {
  email: string;
  full_name: string;
  password: string;
}

export interface LoginIn {
  email: string;
  password: string;
}

export interface SessionOut {
  access_token: string;
  token_type: 'Bearer';
  /** Seconds until the access token expires. */
  expires_in: number;
  user: UserOut;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: Record<string, JsonValue>[];
  request_id: string;
}

export interface ErrorOut {
  error: ErrorBody;
}
