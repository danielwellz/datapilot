# 3. Authentication tokens for the single-page app

- Status: Accepted
- Date: 2026-09-30

## Context

The Angular app (Stage 7) and the API are served from the same origin in production. Analysts must be able to register, log in, stay logged in across page reloads and browser restarts, and log out. The roadmap asks for short-lived access tokens, a refresh token in an httpOnly cookie, argon2 password hashing and rate-limited login.

The options considered were:

- **Server-side sessions** (a session id cookie with state in Redis): simple and revocable, but every API request then needs a cookie, and so CSRF protection on every state-changing endpoint, plus a Redis lookup per request.
- **A single long-lived JWT in `localStorage`**: simple, but any script injected into the page (XSS) can read it and use it from anywhere until it expires, and it cannot be revoked.
- **A short-lived access token in memory plus a refresh token in an httpOnly cookie**: the pattern chosen here.

### Threat model

- **XSS (script injected into our page).** Script can read anything in JavaScript memory or `localStorage`, and can send requests as the user while the page is open. It cannot read httpOnly cookies. The goal is to limit what it can take away: an access token that expires within 15 minutes, never the refresh token.
- **CSRF (another site makes the user's browser send a request to our API).** The browser attaches our cookies automatically. Any endpoint that authenticates with a cookie is exposed, so the cookie must be useless on its own.
- **Token theft (a token copied from a device, log, proxy or backup).** A stolen access token works until it expires. A stolen refresh token would work for days unless rotation and revocation catch it.

## Decision

**Two tokens, each accepted from one place only** (flask-jwt-extended, HS256, configured in `backend/app/extensions.py` and `backend/app/api/security.py`):

- The **access token** (15 minutes) is returned in the JSON body of login and refresh. The client keeps it in memory only and sends it as `Authorization: Bearer`. Protected endpoints read it only from that header (`@require_access_token`), so a cross-site request cannot authenticate with cookies.
- The **refresh token** (7 days) is set as the `refresh_token_cookie` cookie with these attributes:
  - `HttpOnly`, so page scripts cannot read it.
  - `SameSite=Strict`, so the browser does not send it on cross-site requests.
  - `Path=/api/auth`, so it is sent only to the authentication endpoints.
  - `Secure` in production.
  - `Max-Age` equal to the token's lifetime, so a session survives a browser restart. The extension would otherwise set one year.

  Refresh and logout read the refresh token only from this cookie (`@require_refresh_token`), and it never appears in a response body.
- `JWT_SECRET_KEY` must be at least 32 characters in every environment. RFC 7518 requires HS256 keys at least as long as the hash output, and a shorter key can be brute-forced offline from any token it signed.

**CSRF: double-submit, on top of SameSite.**
- The refresh token carries a random `csrf` claim. The same value is set in a second cookie, `csrf_refresh_token`, which is not httpOnly.
- Refresh and logout require the `X-CSRF-TOKEN` header to equal the claim, and answer **403** when it is missing or wrong: the token was valid, the request is refused.
- Only a page on our origin can read the cookie and copy its value into a header, so a forged cross-site request fails even in a browser that ignores `SameSite`.
- The CSRF cookie uses `Path=/`, not `/api/auth`. `document.cookie` only lists cookies whose path covers the current page, and the app runs at `/`. The value is not a secret: it proves the request came from our origin, and it cannot authenticate anything on its own.

**Rotation with reuse detection.**
- Every refresh returns a new refresh token and spends the old one.
- Each login starts a token family (`fam` claim), which every rotation passes on.
- The first use of a refresh token claims it atomically in Redis (`SET auth:refresh:used:<jti> NX GET`), so two racing refreshes can never both count as the first.
- If a spent token is presented again, two parties hold it and one is probably a thief. The whole family is revoked (`auth:refresh:revoked-family:<fam>`), so both must log in again. The event is logged as a warning.
- One legitimate case looks the same: tabs restored together after a browser restart refresh at once with the same cookie. Reuse within **10 seconds** of the first use is therefore accepted. This gives a thief at most a 10-second window, right after the legitimate refresh.

**Logout** writes the refresh token's `jti` to a Redis denylist (`auth:refresh:revoked:<jti>`) and clears both cookies. Other logins of the same user are unaffected. The revocation check runs for refresh tokens only.

**Access tokens are not revoked.** Checking every API request against Redis would cost a round trip per request, to shorten a window that is already 15 minutes. On logout the client discards the token.

**Every Redis key expires when the token it describes would have,** so the store never needs cleaning up and cannot grow without bound.

**Login does not reveal whether an email exists.**
- An unknown email and a wrong password get the same 401 body, "Email or password is incorrect."
- The unknown-email path verifies the password against a dummy argon2 hash, so both paths take the same time.
- A successful login re-hashes passwords made with outdated argon2 parameters.

**Rate limiting** uses a fixed-window counter in Redis (`backend/app/services/rate_limiter.py`): `INCR` and `EXPIRE NX` in one transaction, with keys hashed so emails and IP addresses are not stored in the clear.
- Login: 5 attempts per minute per client address and email, against guessing one account's password.
- Login: 30 per minute per client address, against spraying one password across many emails.
- Registration: 10 per hour per client address.
- Limits are checked before the password is hashed, so refused attempts cost no CPU.
- The known weakness of fixed windows is a burst at the boundary: up to twice the limit within a short span around the end of a window. For these limits that is acceptable, and it avoids a sorted set per key (sliding log) or weighted counters (sliding window).

## Consequences

- **XSS** can use the in-memory access token while the page is open, but cannot take the refresh token away. A copied access token dies within 15 minutes. Content Security Policy (Stage 11) is the defence against the injection itself.
- **CSRF** needs no per-endpoint work. Data endpoints authenticate only with the header, and the two cookie endpoints are protected by SameSite plus the double-submit check. Stage 7 must send `X-CSRF-TOKEN` with the value of the `csrf_refresh_token` cookie on refresh and logout.
- **A stolen refresh token** is either spent already, so its reuse revokes the family, or it is spent by the thief first, so the legitimate user's next refresh revokes the family and both must log in again. Either way the theft ends at the next rotation.
- **Account existence is revealed by registration.** `POST /api/auth/register` answers 409 for an email that already has an account, as the roadmap specifies. This is an accepted trade-off for an internal tool: telling a colleague "you already have an account" beats a silent success. It is bounded by the per-address registration limit. A public product would instead answer 202 for every registration and send the next step by email.
- **Redis is part of authentication.** Login, registration, refresh and logout fail closed when Redis is unreachable (currently a logged 500; mapping dependency outages to 503 is a follow-up). Endpoints protected by an access token keep working, because they do not touch Redis.
- **Client addresses** come from `request.remote_addr`. Behind the Stage 11 reverse proxy every request would appear to come from the proxy, so `ProxyFix` with the exact number of trusted hops must be configured there, or all clients would share one limit.
- **Sessions slide.** Each rotation issues a fresh 7-day token, so a session that refreshes at least once a week never ends on its own. An absolute limit (for example 30 days from login, carried with the family) can be added later without changing the token format for clients.
- **Logging out does not end other sessions.** A "log out everywhere" action would need a per-user revocation marker. It is not required yet.

## Later changes

- **2026-10-09 (Stage 11):** an unreachable Redis or PostgreSQL now gives `503 service_unavailable`, and the log names the dependency. Login, registration, refresh and logout still fail closed.
- **2026-10-09 (Stage 11):** `TRUSTED_PROXY_HOPS` configures Werkzeug's `ProxyFix`. The demo stack trusts exactly one hop, Nginx, so each client has its own login limit and a forged `X-Forwarded-For` is ignored ([ADR 0008](0008-production-images-and-demo-stack.md)).
