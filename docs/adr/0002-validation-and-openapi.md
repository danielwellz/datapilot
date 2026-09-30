# 2. Request validation and OpenAPI with spectree

- Status: Accepted
- Date: 2026-09-30

## Context

Every request body and query string must be validated with Pydantic v2 models, and every endpoint must appear in an OpenAPI 3 document served at `/api/openapi.json`, with Swagger UI at `/api/docs`. Validation errors must use the application's error envelope (`{"error": {"code", "message", "details", "request_id"}}`), not a library's own format.

The locked stack is Flask 3.1.3, Werkzeug 3.1.9 and Pydantic 2.13.5. The options considered were:

- **spectree**: decorates Flask views with Pydantic models, validates the query, body and response, and generates OpenAPI from the same models.
- **flask-openapi3**: also Pydantic-based, but replaces `Flask` and `Blueprint` with its own subclasses, which spreads the library through the app factory and every blueprint.
- **flask-smorest**: mature, but built on marshmallow. Using it would mean maintaining two schema systems next to Pydantic.
- **A custom decorator**: a small `@validate(query=..., body=...)` that builds the document from `model_json_schema()`. It gives full control, but we would have to write and maintain path parameters, response documentation and the document structure ourselves.

spectree 3.0.0 was released on 2026-09-10. Before choosing it, we checked it in an isolated environment against the locked versions, with warnings treated as errors. Valid and invalid query and body validation, typed handler arguments (`def view(query: Q, json: B)`), response models and OpenAPI 3.1 generation all worked without warnings, and code using it passed `mypy --strict` (the package ships `py.typed`).

The same check found four behaviours that needed handling:

1. With the documentation path set to `api`, spectree leaves every route under `/api` out of the document. It filters out routes that share its own path prefix.
2. A malformed JSON body, or a body sent with a non-JSON content type, is read as `{}`. The client then gets a misleading "field required" error.
3. When a response does not match its declared model, spectree answers 500 with the validation errors, including the offending data, in the body.
4. Its validation errors use spectree's own format.

## Decision

Use spectree (`spectree[flask]`, pinned through `uv.lock`) for request validation, response validation and OpenAPI generation, configured in `backend/app/api/spec.py`:

- `mode="strict"`: only endpoints decorated with `@spec.validate` appear in the document, so internal routes never leak into it.
- The `before` hook raises `ValidationFailed` (422), built from the Pydantic error without the submitted input. The standard error handler renders it. `validation_error_model=ErrorOut` documents that envelope as the 422 response.
- The `after` hook raises when a response breaks its schema. The generic handler turns that into a 500 that shows only the request id and logs the details.
- Schema names are the plain model class names instead of spectree's default of name plus module hash, which keeps the document readable. Model names must therefore be unique across the API.
- `spec.register()` is not called. Two routes of our own serve `/api/openapi.json` (from `spec.spec`) and `/api/docs` (spectree's Swagger UI template), which avoids the path filtering in point 1.
- An app-wide `before_request` guard answers 400 for malformed JSON and 415 for non-JSON bodies on `POST`, `PUT` and `PATCH`, before spectree reads the body (point 2). Bodies over 1 MiB are refused with 413.

## Consequences

- One Pydantic model per input or output drives validation, typed handler arguments and documentation, so they cannot drift apart.
- spectree validates the query string before the body and stops at the first part that fails. A request with both an invalid query and an invalid body reports only the query errors. The client sees the body errors after fixing the query. We accept this rather than patching the library.
- `spec.spec` is generated on first use and cached for the life of the process. That is correct for a server, whose routes are fixed at startup, but tests that compare documents across differently configured apps must clear the cache.
- The Swagger UI page loads `swagger-ui-dist` 5.11.0 from unpkg. That is acceptable for development. The production Content Security Policy (Stage 11) must allow it, or serve the assets locally, or disable `/api/docs` in production.
- spectree 3.0 is a new major version. If it proves unstable, the fallback is the custom decorator described above. Views depend only on `@spec.validate` and on receiving Pydantic models as arguments, so the swap stays inside `app/api/`.
