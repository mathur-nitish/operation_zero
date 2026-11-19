# Operation Zero — REST API Contracts

Status: M0 conventions + health endpoints; M1 authentication.

FastAPI's generated OpenAPI (`/openapi.json`, `/docs`) is the source of truth for exact request/response **schemas**. This document records conventions, semantics, error codes and flows that OpenAPI cannot express. New endpoints are drafted here and approved **before** they are implemented.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | All endpoints live under `/v1`. A breaking change creates `/v2` for the affected endpoints; `/v1` keeps working until clients migrate. |
| Format | JSON request and response bodies, UTF-8. |
| Ids | Player and other UUID ids are canonical lowercase UUID strings in JSON (stored as BSON UUID in MongoDB). Item definition ids are integers. |
| Timestamps | ISO 8601 UTC strings in JSON. |
| Request id | Clients may send `X-Request-ID` (`[A-Za-z0-9._-]{1,64}`); otherwise the server generates one. Always returned in the `X-Request-ID` response header. Include it in bug reports. |
| Auth | `Authorization: Bearer <access token>` (see §3.2). |

## 2. Error envelope

Every non-2xx response (except readiness, see below) has this body:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [ { "loc": ["body", "email"], "message": "…", "type": "…" } ],
    "request_id": "7f3c…"
  }
}
```

- Clients branch on `code` (stable, machine-readable), never on `message` (human-readable, may change).
- `details` is code-specific and may be `null`.

### Common error codes

| HTTP | code | Meaning |
|---|---|---|
| 401 | `unauthorized` | Missing or invalid credentials (M1 adds more specific codes). |
| 403 | `forbidden` | Authenticated but not allowed. |
| 404 | `not_found` | Unknown route or resource. |
| 405 | `method_not_allowed` | Wrong HTTP method. |
| 422 | `validation_error` | Request failed validation. Submitted values are never echoed. |
| 500 | `internal_error` | Unexpected server error; details are only in server logs (find them by `request_id`). |

Feature-specific codes are listed with their endpoints.

## 3. Endpoints

### `GET /v1/health` — liveness
No auth. `200 {"status": "ok", "checks": {}}` while the process is running. Does not check dependencies.

### `GET /v1/health/ready` — readiness
No auth. Pings MongoDB.
- `200 {"status": "ok", "checks": {"mongodb": "ok"}}`
- `503 {"status": "unavailable", "checks": {"mongodb": "unavailable"}}` — uses the health body, not the error envelope, so load balancers and dashboards read one shape.

### 3.2 Authentication (`/v1/auth`) — M1

Implemented 2026-11-18. Schemas: OpenAPI (`AuthTokensResponse`, `RegisterRequest`, …). Mechanism: `BACKEND_ARCHITECTURE.md` §9.

**Token pair** (returned by register, login and refresh):
```json
{ "game_user_id": "uuid", "token_type": "Bearer", "access_token": "jwt", "expires_in": 900,
  "refresh_token": "opaque", "refresh_expires_in": 2592000 }
```
- Send the access token as `Authorization: Bearer <access_token>`. Treat it as opaque; do not parse it in the client.
- Store the refresh token securely. **Each refresh token works once**: `/refresh` returns a new pair and the old refresh token stops working. Presenting an already-used refresh token is treated as theft and ends that whole login.
- The client must never run two refreshes at the same time with the same refresh token. If a refresh response is lost (network failure), the login ends and the player must log in again.

**Optional `client_info`** on register/login/refresh: `{ "platform": "windows", "build": "0.1.0+1234" }` (`[A-Za-z0-9._-]`, ≤32 / ≤64 chars). Stored on the session only.

| Endpoint | Auth | Body | Success | Errors |
|---|---|---|---|---|
| `POST /register` | — | `email`, `password` (10–128 chars), `game_user_name` (3–16, `[A-Za-z0-9_]`), `client_info?` | `201` token pair | `409 email_taken`, `409 name_taken`, `422 validation_error` |
| `POST /login` | — | `email`, `password`, `client_info?` | `200` token pair | `401 invalid_credentials`, `403 account_banned`, `403 account_unavailable` |
| `POST /refresh` | — | `refresh_token`, `client_info?` | `200` new token pair | `401 invalid_refresh_token`, `401 refresh_token_expired`, `401 refresh_token_reused`, `401 session_revoked`, `403 account_banned` |
| `POST /logout` | Bearer | — | `204` | auth errors |
| `POST /logout-all` | Bearer | — | `204` | auth errors |
| `GET /me` | Bearer | — | `200 { game_user_id, account_status, created_at }` | auth errors |

Rules:
- Emails are case-insensitive (stored lower-cased). In-game names keep their casing for display but are unique case-insensitively.
- Unknown fields in request bodies are rejected (`422`).
- `401 invalid_credentials` is identical for an unknown email and a wrong password.
- Ban status is only revealed after a correct password.

**Errors on any Bearer-authenticated endpoint** (all `401` responses carry `WWW-Authenticate: Bearer`):

| HTTP | code | Client action |
|---|---|---|
| 401 | `not_authenticated` | No token sent — log in. |
| 401 | `token_expired` | Call `/refresh`, then retry the request once. |
| 401 | `invalid_token` | Discard tokens, log in. |
| 401 | `session_revoked` | Logged out (logout, logout-all elsewhere, or reuse detection) — log in. |
| 403 | `account_banned` | Show ban; `details: { reason, until }` (`until` null = permanent). |
| 403 | `account_unavailable` | Account pending deletion or deleted. |

## 4. Planned (not yet approved)

M2 profile, M3 catalog/inventory — see `MILESTONES.md` §4. Each will be drafted here for approval before implementation.
