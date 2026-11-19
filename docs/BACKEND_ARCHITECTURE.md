# Operation Zero — Backend Architecture

Status: M0 (foundation), M1 (authentication). Update this document whenever the structure, layering or cross-cutting conventions change.

## 1. Runtime and stack

| Concern | Choice |
|---|---|
| Language | Python 3.14 (native `uuid.uuid7()`) |
| Web framework | FastAPI, served by Uvicorn |
| MongoDB driver | PyMongo native async (`AsyncMongoClient`) — schema decision 15 |
| Settings | `pydantic-settings`, from environment variables and `backend/.env` |
| Tests | pytest + pytest-asyncio + httpx (in-process ASGI client) |

Dependencies are pinned in `backend/requirements.txt` (runtime) and `backend/requirements-dev.txt` (tests).

## 2. Layout

```
backend/
  app/
    main.py               create_app() factory and lifespan (Mongo client, index bootstrap)
    api/                  HTTP layer: routers and dependencies only — no business logic
      router.py           /v1 router; feature routers are included here
      deps.py             shared dependencies (settings, database)
      health.py           liveness / readiness
    schemas/              Pydantic request/response models (the REST contract)
    core/                 cross-cutting infrastructure
      config.py           Settings, load_settings(), ConfigError
      database.py         Mongo client creation, ping
      indexes.py          IndexSpec, IndexRegistry, ensure_indexes
      errors.py           AppError and the error envelope handlers
      request_context.py  X-Request-ID middleware
      logging_config.py   'app' logger with request ids
      ids.py              new_id() (UUIDv7), utc_now()
  tests/
```

Added in M1:
```
  app/
    api/auth.py           /v1/auth endpoints
    core/security.py      Argon2id hashing, access-token JWTs, refresh-token generation/hashing
    schemas/auth.py       auth request/response models
    services/auth.py      AuthService: register, login, refresh, logout, authenticate
    repositories/         one module per collection; each registers its own indexes
      users.py            user_data
      identities.py       auth_identities
      profiles.py         player_data_profile
      sessions.py         auth_sessions
```

Added in later milestones: `app/ws/` (WebSocket connection management), `app/core/constants.py` (M3, schema §2 fixed lists).

### Layering rules

- `api` → `services` → `repositories` → MongoDB. Routers never query MongoDB directly and never contain business rules.
- Services raise `AppError` for expected failures (e.g. `409 name_taken`); they do not build HTTP responses.
- Only `repositories` know collection names and query shapes.
- `core` depends on nothing in `api`/`services` (except `errors.py` using `schemas.common` for the envelope).

## 3. Configuration

- All settings come from environment variables; `backend/.env` is loaded for local development. Real environment variables win over `.env`.
- `APP_ENV` (`development` | `test` | `production`) selects the database: `MONGODB_DB_NAME_DEV` / `_TEST` / `_PROD`. Only the selected one is required. All configured names must differ, and the test database name must end in `_test`.
- `MONGODB_URI` must not contain credentials; `GAME_DATA_DB_USER` / `GAME_DATA_DB_PASSWORD` are passed to the driver separately.
- Invalid configuration raises `ConfigError` at startup, naming the variables and the problem but **never their values** (Pydantic's own errors include input values, so they are suppressed).
- `.env.example` documents every variable.

## 4. MongoDB access

- One `AsyncMongoClient` per process, created in the app lifespan and closed on shutdown; stored on `app.state` and injected with the `get_db` dependency.
- Client options: `uuidRepresentation="standard"` (Python `UUID` ↔ BSON UUID subtype 4), `tz_aware=True` (UTC-aware datetimes), timeouts from `MONGODB_TIMEOUT_MS`.
- Atlas is a replica set, so multi-document transactions are available.

### Index bootstrap

- Each feature module declares its indexes as `IndexSpec`s and registers them on `INDEX_REGISTRY`.
- On startup, `ensure_indexes` creates them; re-running with the same definitions is a no-op.
- If an index with the same name or keys already exists with a **different** definition, startup fails with `IndexConflictError`. Changing an existing index is a migration and must be done deliberately, not by a silent rebuild.
- M0 registers no indexes; collections appear only in the milestone that implements their access patterns.

## 5. Errors

Every error response uses one envelope:

```json
{ "error": { "code": "not_found", "message": "Not Found", "details": null, "request_id": "…" } }
```

- `AppError(status_code, code, message, details)` → that status and code.
- Request validation → `422 validation_error`; `details` lists `{loc, message, type}` and **never echoes submitted values** (they may be passwords).
- Framework HTTP errors → `401 unauthorized`, `403 forbidden`, `404 not_found`, `405 method_not_allowed`, otherwise `http_error`.
- Anything unexpected → `500 internal_error` with a generic message; the stack trace is logged server-side only.

## 6. Request ids and logging

- Every HTTP/WebSocket request gets an id: the client's `X-Request-ID` if it matches `[A-Za-z0-9._-]{1,64}`, otherwise a generated one. It is returned in the `X-Request-ID` response header and in error bodies.
- The `app` logger namespace writes `time level [request_id] logger: message`. Passwords, tokens and connection strings must never be logged; driver errors are logged by type only.
- Structured (JSON) logs and metrics are deferred to the deployment milestone.

## 7. Testing

- `pytest` from `backend/`, using `backend/.venv`.
- Tests run with `APP_ENV=test` against `MONGODB_DB_NAME_TEST`, which is **emptied before and after every run** (collection by collection, because `dropDatabase` needs more than the `readWrite` role). Fixtures abort if the database name does not end in `_test`.
- The `app_client` fixture runs the real app lifespan and talks to it in-process through httpx.
- Database-backed tests use the real Atlas cluster, not mocks, so transaction and unique-index behaviour is tested for real.

## 8. Running locally

```
cd backend
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload
.venv\Scripts\python -m pytest
```

OpenAPI docs: `http://127.0.0.1:8000/docs` (schema at `/openapi.json`).

## 9. Authentication (M1)

### Identity model
- An **account** is `user_data` (status, ban, `session_epoch`), keyed by `game_user_id` (UUIDv7).
- A **login method** is an `auth_identities` row: `provider` + `provider_user_id`. M1 implements only `classic` (lower-cased email + Argon2id password hash).
- Everything after "which account is this?" uses `game_user_id` only. Adding Steam later = a `steam` identity provider + a login endpoint that resolves a Steam id to a `game_user_id` and then reuses the same session/token code. No change to tokens, sessions, profiles or other endpoints.

### Registration
Validation → Argon2id hash (in a worker thread, outside the transaction) → **one transaction** inserting `user_data`, `auth_identities`, `player_data_profile` and the first `auth_sessions` row. A duplicate email or name hits a unique index, aborts the transaction (nothing is left behind) and is mapped to `409 email_taken` / `409 name_taken` from the index key. Concurrent registrations for one name are serialised by the index, not by a read-then-write check.

### Tokens
| | Access token | Refresh token |
|---|---|---|
| Form | HS256 JWT: `iss, sub (game_user_id), sid (session_id), epoch, typ="access", iat, exp` | 256-bit random, URL-safe string |
| Lifetime | 15 min (`ACCESS_TOKEN_TTL_SECONDS`) | 30 days, renewed on each refresh (`REFRESH_TOKEN_TTL_DAYS`) |
| Stored | Not stored | SHA-256 in `auth_sessions.token_hash` |

### Checking a request
`get_current_player` → decode JWT (signature, `HS256` only, issuer, expiry, required claims) → read `user_data` and the `auth_sessions` row **concurrently** → reject if the session is revoked, `session_epoch` changed, or the account is banned/unavailable. Two indexed reads per authenticated request; this is what makes logout, logout-all and bans effective immediately rather than after 15 minutes. Caching can be added later if needed.

### Refresh rotation and reuse detection
- `/refresh` finds the session by token hash, then in **one transaction** atomically marks it `rotated_at` (only if not already rotated/revoked) and inserts the next session in the same `family_id`.
- An already-rotated token presented again ⇒ assume theft ⇒ revoke the whole family (attacker and legitimate client both lose that login) ⇒ `401 refresh_token_reused`.
- Two concurrent refreshes with one token: the transaction makes at most one succeed; the loser is treated as reuse.
- Accepted trade-off: if a refresh response is lost in transit, the player must log in again. A grace window would need the server to re-issue the same new token, which means storing it; not worth it at this stage.

### Logout
- `/logout` revokes the current session's family.
- `/logout-all` increments `user_data.session_epoch` **first**, then revokes every session of the account. Incrementing first also kills a session created by a refresh racing with the logout (its epoch copy is stale).

### Other protections
- Unknown email performs a dummy Argon2 verify, so response time does not reveal whether an account exists. The error is the same as for a wrong password.
- Ban status is checked only after a correct password.
- Stored hashes with outdated Argon2 parameters are upgraded on the next successful login.
- Request bodies forbid unknown fields; passwords and refresh tokens are `SecretStr` and never echoed or logged.

### Known gaps (planned)
- **No rate limiting** on login/register yet — credential stuffing is possible. Needs Redis (M4).
- Registration reveals whether an email is registered (`409 email_taken`); unavoidable without email verification, which is deferred (D5).
- Bloom-filter pre-check for name availability (D13) is deferred to M4, when Redis exists. The unique index is the authority either way.
