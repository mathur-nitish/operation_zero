# Operation Zero — Backend Milestones

Status: M0 and M1 done. No later milestone may start until the developer approves it and its blocking decisions (§3) are answered.

Related: `DATABASE_SCHEMA.md` (data model source of truth), root and `backend/` CLAUDE.md.

## 1. Confirmed inputs

| Topic | Decision | Source |
|---|---|---|
| Database | MongoDB Atlas, MongoDB 8.0 replica set — multi-document transactions available. Answers `DATABASE_SCHEMA.md` open question 7.1 for dev. | Developer, verified 2026-11-15 |
| Configuration | All settings from environment variables loaded from `backend/.env`; `MONGODB_URI` holds no credentials; `GAME_DATA_DB_USER` / `GAME_DATA_DB_PASSWORD` are passed to the driver separately. | Developer |
| Databases | One per environment on the same cluster: `MONGODB_DB_NAME_PROD`, `_DEV`, `_TEST`, chosen by `APP_ENV`; must all differ. Tests empty `_TEST` (name must end in `_test`) and never touch the others. | Developer, 2026-11-18 |
| Login method | Email + password (`auth_identities.provider = 'classic'`) only for now. Platform logins (e.g. Steam) must be addable by inserting new `auth_identities` rows only — no change to tokens, profiles, inventory or API shapes. | Developer |
| Token model | Short-lived access token + refresh token. | Developer |
| Player WebSocket | Unreal client ↔ **backend** WebSocket for presence and pushed account data. Not a connection to the dedicated server. | Developer |
| Git | No git operations for now. `.gitignore` exists. | Developer |
| Runtime | Python 3.14 (native `uuid.uuid7()`), project virtual environment in `backend/.venv`. | Developer, 2026-11-18 |
| Mongo driver | PyMongo native async (`AsyncMongoClient`). Amendment A1 approved and applied to `DATABASE_SCHEMA.md` (decision 15). | Developer, 2026-11-18 |
| In-game name | Chosen at registration; unique. Developer asked for bloom filters — see D13. | Developer, 2026-11-18 |

## 2. Amendments to `DATABASE_SCHEMA.md`

| # | Proposal | Status |
|---|---|---|
| A1 | PyMongo's native async API instead of `motor` | Approved, applied (schema decision 15) |
| A2 | Collection `auth_sessions` for refresh tokens | Approved, applied (schema §3.9, decision 18) |
| A3 | TTL index on `auth_sessions.expires_at` only (decision 4 is about items) | Approved, applied (decision 18) |
| A4 | Drop the earlier item `state` field idea (`stash` / `equipped` / `in_raid`); raid gear is a separate, undesigned model (schema open question 8) | Approved |
| A5 | "Transactions" convention: dev uses Atlas (a replica set); the Docker single-node note applies only to optional offline/CI setups | Approved, applied (schema §2) |
| A6 | Profile fields not known at registration (`name_changed_at`, `avatar_id`, `body_type`, `country`, `detected_region`) are nullable | Applied in M1 (schema §3.3) |
| A7 | Inventory documents are created from M3, not at registration in M1 | Applied in M1 (decision 19) — see D9 |

## 3. Decisions

| # | Question | Decision | Status |
|---|---|---|---|
| D1 | UUID storage (schema 6a) | BSON UUID binary (subtype 4) in Mongo; canonical string form in JSON/API and to Unreal. | **Resolved** 2026-11-18 |
| D2 | UUIDv7 generation | Python 3.14 `uuid.uuid7()`. | **Resolved** |
| D3 | When is the in-game name chosen? | At registration. | **Resolved** |
| D4 | Token lifetimes | Access 15 min, refresh 30 days, rotate on every refresh; reusing a rotated refresh token revokes its whole family. | **Resolved**, implemented M1 |
| D5 | Email verification | `email_verified = false`; no emails sent in this phase. Unverified accounts can play. | **Resolved**, implemented M1 |
| D6 | Password rules | 10–128 characters; no composition rules; Argon2id. | **Resolved**, implemented M1 |
| D7 | Rename cooldown and name rules | Name rules (3–16, `[A-Za-z0-9_]`, case-insensitive uniqueness) implemented M1. 30-day cooldown in M2. Profanity filter later. | **Resolved** |
| D13 | Bloom filter for names (developer request). It can only answer "definitely free" / "maybe taken", so it **cannot** enforce uniqueness — the unique index stays authoritative. An in-process filter goes stale across backend instances (it could say "free" for a name registered elsewhere) and cannot remove names freed by renames. | Deferred to **M4** (needs Redis, a shared store): use it as a fast pre-check for a name-availability endpoint. M1 relies on the unique index alone. | Deferred |
| D8 | Final constants (schema 7.6): currency ids, `equipped` role keys, categories / sub-categories, outfit slot names | Use the illustrative values from the schema as the first version, flagged as confirmed by you. | M3 |
| D9 | Starter grant (`source: 'default'`) | One default character (+ empty `slots`) as `equipped.character`; zero balance per currency. The `item_def_id` and currency ids are still open (D8), so M1 creates **no** inventory documents (A7). M3 adds the starter grant at registration plus an idempotent backfill for accounts created before M3. | Open — M3 |
| D10 | Where is `detected_region` derived from? IP geolocation needs a dataset or service (new dependency). | Leave unset in this phase; fill it in the matchmaking milestone. | M2 |
| D11 | Redis for presence (schema §5: `presence:{id}`) | Use Redis from M4, matching the schema. On Windows, run it via Docker or a managed free tier — your choice. | M4 |
| D12 | One WebSocket per player? | Yes: a new connection for the same player closes the old one with a `session_replaced` event. | M4 |

## 4. Milestones

Each milestone ends with: tests run and reported, docs updated, Unreal integration notes.

### M0 — Backend foundation
**Status:** implemented 2026-11-18. Database names are per environment (`MONGODB_DB_NAME_PROD` / `_DEV` / `_TEST`, selected by `APP_ENV`) instead of the single main + test name first planned. Verified: 27/27 tests pass against Atlas; app starts with the real development configuration and `/v1/health/ready` reports MongoDB ok.

**Goal:** a running, tested FastAPI skeleton connected to Atlas, with nothing player-facing yet.

- Project layout: `app/{api,schemas,services,repositories,core,ws}`, `tests/`.
- Settings via `pydantic-settings` reading `backend/.env`; fails fast on missing values; secrets never logged.
- Mongo client (`AsyncMongoClient`, `uuidRepresentation="standard"`), lifespan startup/shutdown.
- Index bootstrap **mechanism**: a registry where each module declares its indexes, applied idempotently at startup. M0 registers no collections; each later milestone registers its own, so no collection exists before its access patterns are implemented.
- Constants module is created in M3, once D8 (final lists) is confirmed — M0 does not invent values.
- `new_id()` wrapper over `uuid.uuid7()` and a UTC time helper.
- Common error envelope `{ "error": { "code", "message", "details" } }` and request-id logging.
- `GET /v1/health` (process up) and `GET /v1/health/ready` (Mongo reachable).
- Pytest + pytest-asyncio + httpx test client; fixtures that use `operation_zero_test` and drop it after the session.

New dependencies (to approve): `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `httpx`. (`pymongo` already present.) Installed into `backend/.venv`, pinned in `requirements.txt`.

Tests: settings validation, health/ready, index bootstrap is idempotent (against a throwaway collection in the test database), test fixture refuses a database name not ending in `_test`.
Docs: `BACKEND_ARCHITECTURE.md` (layout, layering rules), `API_CONTRACTS.md` (conventions: versioning, error envelope, auth header).

### M1 — Authentication
**Status:** implemented 2026-11-18. 58/58 tests pass against Atlas (31 new auth tests; concurrency tests repeated 5× without failure). Differences from the plan below: registration creates no inventory documents (A7/D9); refresh rotation is transactional; each authenticated request also checks the session row, so single-device logout takes effect immediately. Details: `BACKEND_ARCHITECTURE.md` §9, `API_CONTRACTS.md` §3.2.

**Goal:** a player can register, log in, stay logged in, and log out; every later endpoint can rely on one auth dependency.

Collections: `user_data`, `auth_identities`, `auth_sessions` (A2), plus the starter `player_data_profile`, `player_data_inventory`, `player_inventory_items` rows created at registration.

Proposed endpoints (contracts drafted in `API_CONTRACTS.md` for approval before coding):
- `POST /v1/auth/register` — email, password, game_user_name → creates all player documents in **one transaction**; returns tokens.
- `POST /v1/auth/login` — email, password → tokens.
- `POST /v1/auth/refresh` — refresh token → new pair (rotation, reuse detection).
- `POST /v1/auth/logout` — revoke the current session.
- `POST /v1/auth/logout-all` — bump `session_epoch`, revoke all sessions.
- `GET /v1/auth/me` — account id, status.

Design points:
- Access token: JWT (HS256, secret from env), claims `sub`, `sid`, `epoch`, `exp`, `iat`. Every authenticated request checks `user_data` (`account_status`, `ban`, `session_epoch`) so bans and logout-all take effect immediately — one indexed read per request; caching later if needed.
- Refresh token: random 256-bit opaque string; only its SHA-256 is stored.
- Provider-agnostic core: services operate on `game_user_id`; the `classic` provider is one implementation behind a small interface, so `steam` later = new provider + new login endpoint only.
- Same error and timing for "unknown email" and "wrong password" (no account enumeration).
- Duplicate email / taken name → `409` with distinct error codes, enforced by unique indexes (not a read-then-write check).
- Login rate limiting: noted as a risk; proper limiting needs Redis (M4) — add then.

New dependencies (to approve): `argon2-cffi`, `PyJWT`, `email-validator` (via `pydantic[email]`).

Tests: register happy path; duplicate email and duplicate name (including **concurrent** registrations racing for the same name); registration rollback leaves no partial documents; wrong password; banned / deleted account; refresh rotation; refresh reuse revokes the family; logout; logout-all invalidates existing access tokens; expired / tampered tokens.
Docs: `API_CONTRACTS.md` (auth), `AUTH_FLOW.md` or a section in `BACKEND_ARCHITECTURE.md`, `DATABASE_SCHEMA.md` (apply A2/A3 once approved).
Unreal: login/register UI, secure token storage, refresh before expiry, handle `401` by refreshing once then returning to login.

### M2 — Player profile
**Goal:** read and edit the player's profile; view another player's public profile.

- `GET /v1/players/me/profile`
- `PATCH /v1/players/me/profile` — `avatar_id`, `body_type`, `country` (ISO 3166-1 alpha-2, validated).
- `POST /v1/players/me/rename` — enforces name rules + cooldown (D7); uniqueness by index; cooldown enforced in the update filter (atomic, not read-then-write).
- `GET /v1/players/{game_user_id}/profile` — public fields only (name, avatar, body_type, country).
- `avatar_id` / `body_type` validated against the constants module.

Tests: own-profile access; another player cannot edit your profile; public view hides private fields; rename collision; concurrent renames to the same name; cooldown; invalid country/avatar.
Docs: `API_CONTRACTS.md` (profile).
Unreal: profile screen, rename flow and its error codes.

### M3 — Item catalog and inventory
**Goal:** the player sees what they own and can equip it; currency changes are safe and audited.

- `item_warehouse` seed data (a versioned JSON/py seed file + load command) and the in-memory catalog cache.
- `GET /v1/catalog/items` — active item definitions (lets Unreal map `item_def_id` → display data).
- `GET /v1/players/me/inventory` — currency, `equipped`, owned items.
- `PUT /v1/players/me/equipped/character` — switch active character.
- `PUT /v1/players/me/equipped/{role}` — parachute / backpack (role from constants).
- `PUT /v1/players/me/characters/{character_def_id}/slots/{slot}` and `DELETE` (unequip) — per schema §4 validation.
- Internal services only (no public endpoints yet): guarded currency change + ledger row in one transaction; grant unique / stackable item. Exposed later via store and match rewards. An admin/dev grant tool for testing — to decide (D-later).
- Revoke path clears every `equipped` / `slots` reference (invariant 5) — implemented as a service even if nothing calls it yet, with tests.

Tests: equip validation (wrong category, wrong slot, incompatible character, not owned, unknown slot name injection); concurrent equips; currency never negative under concurrent spends; ledger row per change; duplicate `txn_id` rejected; grant unique twice → "already owned"; stack grant upserts.
Docs: `API_CONTRACTS.md` (catalog, inventory), `DATABASE_SCHEMA.md` (finalised constants D8).
Unreal: inventory/loadout UI driven by catalog ids; never decides ownership locally.

### M4 — Player WebSocket (presence and pushed updates)
**Goal:** a logged-in client holds one authenticated WebSocket to the backend, is shown as online, and receives account updates without polling.

- `GET /v1/ws` upgrade, authenticated with the access token in the `Authorization` header (supported by Unreal's WebSockets module; avoids tokens in URLs/logs).
- Versioned envelope (in `WEBSOCKET_PROTOCOL.md`), e.g. `{ "v": 1, "type", "id", "ts", "payload" }`.
- Client→server: `ping`, `ack`. Server→client: `welcome`, `pong`, `profile.updated`, `inventory.updated`, `session_replaced`, `session_revoked`, `error`.
- Presence in Redis `presence:{game_user_id}` (TTL 60 s, refreshed by heartbeat) — introduces Redis (D11).
- One connection per player (D12); connection closed when the access token's session is revoked or the account is banned.
- Profile/inventory services publish change events; the connection manager pushes them. Single backend instance for now; designed so cross-instance fan-out (Redis pub/sub) can be added for parties.
- Login rate limiting from M1 added here using Redis.

New dependencies (to approve): `redis` (async client).
Tests: reject missing/invalid/expired token; malformed and oversized messages; heartbeat timeout clears presence; second connection replaces the first; inventory change reaches the connected client; disconnect/reconnect.
Docs: `WEBSOCKET_PROTOCOL.md`, `DATABASE_SCHEMA.md` §5 (presence fields).
Unreal: WebSocket client subsystem, reconnect with backoff, token refresh before reconnecting.

## 5. Later milestones (not planned in detail yet)

| Milestone | Depends on |
|---|---|
| M5 Parties and invites (Redis + Lua, `PARTY_SYSTEM.md` — document not yet in repo) | M4 |
| M6 Store / purchases with currency | M3; schema open question 3 (real-money currency) |
| M7 Raid inventory design (stash vs in-raid loot, loss on death, escrow) | Schema open questions 2, 8 |
| M8 Matchmaking | M5, M7 |
| M9 Dedicated server registration, allocation, connection tickets | M8 |
| M10 Match results and reward settlement | M9; schema open question 9 |
| M11 Docker, AWS deployment, GitHub Actions | Any time after M1; needs git |

## 6. Risks

- **Shared Atlas cluster for dev and tests:** a mistake in test configuration could hit `operation_zero`. Mitigation: the test fixture refuses to run unless the database name ends in `_test`.
- **Atlas free/shared tiers** have operation and connection limits; heavy concurrency tests may be throttled.
- **Per-request account check** (M1) adds one DB read per call. Acceptable at this scale; revisit with caching if needed.
- **Raid gear is undesigned** (M7). Until then, inventory is cosmetic/currency only; gameplay loot cannot be persisted.
- **`PARTY_SYSTEM.md` is referenced but missing** from the repo.
