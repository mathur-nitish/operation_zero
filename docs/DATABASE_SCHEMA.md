# Operation Zero — Database Schema (MongoDB + Redis)

Status: design agreed in discussion, **not yet implemented**. This is the source of truth for data modelling. Read it before writing any model, repository or migration code. Party behaviour is in `PARTY_SYSTEM.md`.

> Amendments proposed during milestone planning are tracked in `MILESTONES.md` §2. A1–A3 are applied here (decisions 15, 18, §3.9).

## 0. How to use this document

Every decision carries a tag:

- **[Confirmed]** — explicitly decided by the developer.
- **[Adopted]** — proposed during the design discussion and accepted without objection. Treat as the plan, but raise it if implementation shows a problem.
- **[Open]** — not decided. Ask the developer before coding anything that depends on it.

Rules for the implementer:

- The backend is **Python 3.14 / FastAPI**. The design discussion used JavaScript-style pseudo-code; implement with **PyMongo's native async API** (`AsyncMongoClient`; not `motor`, which is deprecated — decision 15) and `redis.asyncio`. Do not copy snippets literally.
- Do not add, rename or remove a collection, field, index or Redis key without flagging it and updating this file (see CLAUDE.md §9).
- Do not invent fields, categories or currency ids that are not listed here. If something is missing, ask.

## 1. Decision log

| # | Decision | Tag |
|---|---|---|
| 1 | MongoDB for persistent data, Redis for transient lobby/presence state | Confirmed |
| 2 | Currency balance stays inside `player_data_inventory.currency`; a separate `currency_ledger` collection records every change | Confirmed |
| 3 | Two-level equipped: `player_data_inventory.equipped` = what is active now; each character item holds what that character wears | Confirmed |
| 3a | The character-level field is named `slots` (not `equipped`) and is a map, not a list of dicts | Adopted |
| 4 | **No time-limited items.** No `expires_at`, no `can_be_expired`, no TTL index, no cleanup job | Confirmed |
| 5 | `game_user_name` lives **only** in `player_data_profile` | Confirmed |
| 6 | Player ids are UUID strings (UUIDv7); item ids are integers | Confirmed |
| 6a | UUIDs are stored as **BSON UUID binary (subtype 4)** everywhere; APIs and Unreal use the canonical string form | Confirmed (2026-11-18) |
| 7 | `item_warehouse` uses `category` + `sub_category` instead of `item_type`; `allowed_slots` removed (for outfits the sub_category *is* the slot) | Confirmed (7), Adopted (allowed_slots removal) |
| 8 | A player owns **at most one copy** of each unique item; no `instance_id`; `slots` and `equipped` store `item_def_id` | Adopted |
| 9 | Logins live in `auth_identities`, separate from `user_data` (one account can have several logins) | Adopted |
| 10 | `account_status`, ban info and `session_epoch` on `user_data` | Adopted |
| 11 | Party rules (see `PARTY_SYSTEM.md`): no party at login; a party is created only when an invite is accepted; a party always has 2+ members; if the invitee already has a party the **inviter joins it**; both in different parties is rejected | Confirmed |
| 12 | Invite text is always "X invited you to a party"; the message after accept depends on the outcome returned by the server | Confirmed |
| 13 | Lobby state is Redis-only, mutated by atomic Lua scripts | Adopted |
| 14 | Finished matches go to `match_results`; rewards are paid through the ledger and are idempotent on `(reason, ref_id, game_user_id)` | Adopted |
| 15 | Async MongoDB access uses PyMongo's native async API (`AsyncMongoClient`), not `motor` | Confirmed (2026-11-18) |
| 16 | UUIDv7 ids are generated with Python 3.14's built-in `uuid.uuid7()` | Confirmed (2026-11-18) |
| 17 | `game_user_name` is chosen at registration and must be unique (case-insensitive, enforced by the unique index on `game_user_name_lower`) | Confirmed (2026-11-18) |
| 18 | Refresh-token sessions live in `auth_sessions` (§3.9) with a TTL index on `expires_at`; decision 4's "no TTL index" applies to items only | Confirmed (2026-11-18) |
| 19 | Registration creates `user_data`, `auth_identities`, `player_data_profile` and the first `auth_sessions` row in **one transaction**. Inventory documents are created from M3, once the starter items and constants (open question 6) are final | Confirmed (2026-11-18) |

## 2. Conventions

- **IDs:** `game_user_id` = UUIDv7. `item_def_id` = Int32, grouped by range for readability (1xxx characters, 2xxx outfits, 5xxx consumables — illustrative), but code must **always check `category`**, never infer type from the number. `txn_id` = client-generated UUID (idempotency key).
- **Timestamps:** native BSON `Date`, UTC. Never strings.
- **Money:** integers only, never floats.
- **PyMongo:** create the client with `uuidRepresentation="standard"` or UUID fields will raise errors.
- **Transactions:** MongoDB multi-document transactions need a replica set. Dev, test and prod use MongoDB Atlas, which is always a replica set. Any optional offline/CI setup must run a single-node replica set (e.g. in Docker), not a bare standalone `mongod`.
- **Warehouse cache:** `item_warehouse` changes only when new items are published. Load it into memory at startup and refresh on publish.
- **Fixed lists in one constants module:** categories, sub_categories, outfit slot names, currency ids. Validate against them everywhere. Never put a raw client string into a Mongo update key (`slots.<x>`).

## 3. MongoDB collections

### 3.1 `user_data`
```
game_user_id    UUID
account_status  'active' | 'banned' | 'pending_deletion' | 'deleted'
ban             { reason: str, until: Date } | null
session_epoch   int        # bump to invalidate every issued token / force logout
last_logged_in  Date
created_at      Date
updated_at      Date
Indexes: unique(game_user_id)
```

### 3.2 `auth_identities`
```
game_user_id      UUID
provider          'classic' | 'steam'        # extendable
provider_user_id  str     # steam id, or lowercased email for 'classic'
password_hash     str     # 'classic' only
hash_algo         str     # e.g. 'argon2id'
email_verified    bool    # 'classic' only
linked_at         Date
last_used_at      Date
Indexes: unique(provider, provider_user_id); (game_user_id)
```
Replaces the draft's `account_method`, `platform_name`, `platform_user_id`, `registered_email_id`, `password_hash` on `user_data`.

### 3.3 `player_data_profile`
```
game_user_id          UUID
game_user_name        str      # single source of truth for the name
game_user_name_lower  str
name_changed_at       Date | null   # for a rename cooldown; null until the first rename
avatar_id             str | null    # null until chosen (M2)
body_type             str | null    # replaces game_user_gender if it only selects a model
country               str | null    # ISO code, chosen by the user
detected_region       str | null    # from IP, used for matchmaking; filled from the matchmaking milestone
created_at, updated_at
Indexes: unique(game_user_id); unique(game_user_name_lower)
```
A rename is one update on this collection; the unique index rejects taken names. Name rule: 3–16 ASCII letters, digits or `_`; `game_user_name_lower` is `game_user_name.lower()`.

### 3.4 `player_data_inventory` (one document per player)
```
game_user_id  UUID
currency      { <currency_id>: int }          # e.g. { gold: 1200, gems: 50 }
equipped      { character: int,               # item_def_id of the active character
                parachute: int | null,
                backpack:  int | null }       # role keys are illustrative — finalise before coding
updated_at    Date
Indexes: unique(game_user_id)
```

### 3.5 `currency_ledger` (append-only)
```
txn_id         str      # unique; idempotency key
game_user_id   UUID
currency_id    str
delta          int      # +500 / -200
balance_after  int
reason         'iap' | 'store_purchase' | 'match_reward' | 'admin_grant' | 'refund'
ref_id         str      # order id / match id / item_def_id
status         'committed' | 'failed'
created_at     Date
Indexes:
  unique(txn_id)
  (game_user_id, created_at desc)
  unique(reason, ref_id, game_user_id) with partialFilterExpression { reason: 'match_reward' }   # no double payout
```

### 3.6 `item_warehouse` (catalog of item definitions)
```
item_def_id        int
item_display_name  str
category           str          # see table
sub_category       str | null
stackable          bool
compatible_chars   [int] | null # null = fits every character
attribute_schema   object       # allowed attribute keys for owned copies
active             bool
Indexes: unique(item_def_id); (category, sub_category)
```

| category | sub_category | Where it is equipped |
|---|---|---|
| `character` | null | `player_data_inventory.equipped.character` |
| `outfit` | `torso`, `bottom`, `shoes`, `headgear` | `slots.<sub_category>` on a character item |
| `parachute` | null | `equipped.parachute` |
| `backpack` | null | `equipped.backpack` |
| `weapon_skin` | `ar`, `smg`, `sniper`, `shotgun` | undecided (Open) |
| `consumable` | `medkit`, `booster`, `grenade` | not equipped; stackable |

These values are illustrative; the final list is defined in the constants module and confirmed with the developer.

### 3.7 `player_inventory_items` (one document per owned item)
```
game_user_id   UUID
item_def_id    int
kind           'stack' | 'unique'
quantity       int         # stack: n;  unique: always 1
item_nickname  str | null  # unique only; length-limited and filtered; UI falls back to item_display_name
attributes     object      # unique only, e.g. { wear: 0.12, kills: 340 }
slots          { torso, bottom, shoes, headgear: int | null }   # ONLY on category == 'character'; values are item_def_id
source         'store' | 'battle_pass' | 'drop' | 'admin' | 'default'
source_ref     str | null  # order id / txn_id / match id
locked         bool
acquired_at, updated_at
Indexes: unique(game_user_id, item_def_id); (game_user_id, kind)
```
Optional: copy `category` onto each owned item if "inventory filtered by category" must be served straight from Mongo. Category never changes, so the copy cannot go stale.

### 3.8 `match_results` (written once when a match ends)
```
match_id, mode_id, map_id, region, started_at, ended_at
players: [ { game_user_id, team_id, party_id, <outcome fields>, rewards: [ { currency_id, amount, txn_id } ] } ]
Indexes: unique(match_id); (players.game_user_id, ended_at desc)
```
**Open:** the outcome fields (`placement`, `kills`, …) came from a battle-royale template. Operation Zero is an extraction shooter — reshape them (extracted?, survival time, loot value, …) before implementing.

### 3.9 `auth_sessions` (refresh-token sessions)
```
session_id     UUID          # also the "sid" claim in access tokens
game_user_id   UUID
token_hash     str           # SHA-256 hex of the opaque refresh token; the raw token is never stored
family_id      UUID          # all rotations of one login share a family
session_epoch  int           # copy of user_data.session_epoch at issue time
created_at     Date
expires_at     Date          # TTL index: MongoDB deletes the document after this time
rotated_at     Date | null   # set when this refresh token was exchanged for a new one
revoked_at     Date | null   # set by logout, logout-all, or refresh-token reuse detection
client_info    { platform: str, build: str } | null
Indexes: unique(session_id); unique(token_hash); (game_user_id); (family_id); TTL(expires_at, expireAfterSeconds 0)
```
Rotated sessions are kept until `expires_at` so that a replayed old refresh token is recognised as reuse (whole family revoked). Behaviour: `BACKEND_ARCHITECTURE.md` §9.

## 4. Core operations (behavioural spec)

**Spend currency.** One guarded atomic update: filter `{game_user_id, "currency.<id>": {$gte: cost}}`, `$inc` by `-cost`. Zero matched documents = insufficient funds. Never read the balance, compute in code and write it back.

**Purchase with currency.** One MongoDB transaction: (1) guarded spend, (2) insert ledger row (unique `txn_id`), (3) grant item. If the item is already owned, the duplicate-key error aborts the transaction — nothing is charged. A retried request fails on the `txn_id` unique index. Without transactions (not recommended): insert ledger row first as the idempotency key, then spend, then grant; mark `failed` on error.

**Grant unique item.** Insert; on `DuplicateKeyError` treat as "already owned" (convert to currency or ignore). Create `slots` only when the warehouse category is `character`.

**Grant stackable item.** Upsert with `$inc: {quantity: n}` and `$setOnInsert` for `kind`, `source`, `acquired_at`.

**Equip gear on a character.** Server validates: slot name is in the fixed list; warehouse def has `category == 'outfit'` and `sub_category == slot`; `compatible_chars` is null or contains the character; player owns the gear; player owns the character (the character's item document must exist and be `category == 'character'`). Then `$set: { "slots.<slot>": item_def_id }` on the character item. Unequip = `$set` to null.

**Switch active character.** Validate ownership, then `$set: { "equipped.character": id }` on `player_data_inventory`.

**Load a player's look** (login, joining a party): read inventory → active character id; read that character item → `slots`; resolve ids via the cached warehouse. The resulting `{character, torso, bottom, shoes, headgear}` snapshot is copied into the Redis party member entry so teammates do not each trigger inventory reads.

**Match reward.** Insert a ledger row with `reason='match_reward'`, `ref_id=match_id`. A duplicate-key error means it was already paid — skip the `$inc`. Never pay a reward before the ledger insert succeeds.

## 5. Redis (transient)

Keys (full fields and flows in `PARTY_SYSTEM.md`):

```
party:{party_id}                JSON string, TTL ~2h refreshed on activity
party:code:{join_code}          → party_id            (reserved; custom rooms not in scope yet)
presence:{game_user_id}         HASH, TTL 60s, refreshed by heartbeat
invite:{invite_id}              HASH, TTL 120s
invites:to:{game_user_id}       SET of invite ids
mm:ticket:{ticket_id}           HASH
mm:queue:{mode_id}:{region}     ZSET  ticket_id → enqueue time
match:{match_id}                JSON string while live; deleted after persisted to match_results
```
`party:{id}` is stored as a JSON **string** (not RedisJSON) so Lua can use `cjson`.

## 6. Invariants — do not break these

1. Currency never goes negative and changes only through the guarded atomic update **plus** a ledger row.
2. Every currency change has a ledger row with a unique `txn_id`.
3. The player name exists only in `player_data_profile`; uniqueness is enforced by the unique index on `game_user_name_lower`.
4. A player is in at most one party. This is enforced **inside** the Lua script, never by a check in app code followed by a write.
5. `equipped` and `slots` reference only owned items. Since items cannot expire, they disappear only through refund / revoke / admin action — those code paths **must** clear every reference in `equipped` and in every character's `slots`.
6. Never trust the client for ownership, currency or rewards (project CLAUDE.md §7). The server validates every equip.
7. Slot names, categories and currency ids come from the constants module; never build update keys from raw client input.
8. Redis never holds the only copy of anything that must survive a restart.

## 7. Open questions (ask before coding the affected parts)

1. ~~Is MongoDB deployed with a replica set in dev and prod (transactions)?~~ Resolved: Atlas replica set; transactions are used from M1.
2. Will players ever need duplicate copies of an item, or trading / gifting? If yes, reintroduce `instance_id` (decision 8 changes).
3. Is any currency bought with real money? (Would add an orders collection and stricter audit rules.)
4. Cross-platform parties (Steam + standalone)? The current design makes no distinction.
5. Custom rooms with a join code? `join_code` is reserved but not designed.
6. Final lists: currency ids, `equipped` role keys, categories / sub_categories, outfit slot names, default party `max_size`.
7. ~~UUID storage type (decision 6a)~~ (resolved: BSON UUID) and rename-cooldown policy (recommended 30 days, M2).
8. **Extraction-shooter inventory:** how do items found in a raid enter or leave `player_inventory_items` (stash vs in-raid loot, loss on death)? Not designed yet.
9. Reshape `match_results` for extraction outcomes (see 3.8).

## 8. Mapping from the original draft

| Original | Now |
|---|---|
| `user_data.account_method / platform_name / platform_user_id / registered_email_id / password_hash` | `auth_identities` |
| `user_data.game_user_name` | removed; only in `player_data_profile` |
| `game_user_avatar_id`, `game_user_gender`, `game_user_country` | `avatar_id`, `body_type`, `country` (Adopted rename) |
| `player_data_inventory.equipped` | kept (active selection) |
| item `item_id or sku_id` | `item_def_id` (int) |
| item `can_be_expired`, `expires_at` | removed (decision 4) |
| item `equipped: [{...}]` | `slots` map, character items only |
| item `attributes: [{}]` | `attributes` map |
| warehouse `item_type` | `category` + `sub_category` |
