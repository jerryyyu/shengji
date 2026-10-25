# Accounts: optional Google sign-in

Guest play is unchanged. Signing in is optional. `fly.toml` sets
`GOOGLE_CLIENT_ID` (the public OAuth client id), so sign-in is ON in
production from the deploy that carries it; with the variable unset or blank
the feature does not exist: no button, no script from Google,
`POST /api/auth/google` answers 404.

## Flow

1. The page asks `GET /api/auth/config`; it returns `{"google_client_id": "<id>"}`
   or `null`. On `null` the web app does nothing more (`web/src/auth.ts`).
2. With an id, the lobby loads `https://accounts.google.com/gsi/client` lazily
   and renders the official "Sign in with Google" button
   (`web/src/components/GoogleSignIn.tsx`), with a fresh per-page nonce.
3. Google hands the page an ID token (a JWT). The page `POST`s
   `{"credential": <jwt>, "nonce": <nonce>}` as JSON to `POST /api/auth/google`.
4. The server (`server/shengji/api/accounts.py`) verifies, with `google-auth`:
   the RS256 signature against Google's current certificates
   (`https://www.googleapis.com/oauth2/v1/certs`, cached per its `max-age`;
   an unknown `kid` asks for ONE bounded refresh: single-flight, fetched
   outside the lock, at most once per 60 s, failures backing off 30 s
   doubling to 10 min while the last good set keeps serving, so a flood of
   bogus kids cannot make the server download certificates per request and
   a real key rotation is still picked up); `aud` == the client id;
   `exp`/`iat` (10 s skew); `iss` in {`accounts.google.com`,
   `https://accounts.google.com`}; a `sub`; `email_verified`; and, when the
   body carries a `nonce`, the token's `nonce` claim must equal it.
5. On success it upserts the user, mints a session (32 random bytes), stores
   only its SHA-256, and sets the cookie `sj_session`: HttpOnly, SameSite=Lax,
   Secure (except on localhost), 30 days. The response is the account object
   `{name, email, picture, display_name, name_shown}` (see "Display name").
6. `GET /api/me` → the same object or 401. `PATCH /api/me` changes the display
   name. `POST /api/auth/logout` deletes the session and clears the cookie.
7. The `/ws` handshake carries the cookie like any same-site request. The
   server reads it once per socket: the seat remembers the account
   (`Seat.user_id`, server-only; it enters no state frame, log record or game
   decision), and a player who typed no name is called by their account name
   (`name_shown`) instead of "Player". A name typed in the room always wins
   for that room. Nothing about game logic or the bots changes.

8. Because identity is read on the handshake, a sign-in or a confirmed
   sign-out while the page is open REPLACES the socket (`conn.reconnect()` in
   `web/src/ws.ts`, called from `auth.ts`): the ordinary reconnect path then
   runs, so in the lobby nothing is resent, and a player in a room rejoins
   their own seat with the saved resume token (the seat is held for them, as
   on any reconnect). The seat's `user_id` follows the socket that reclaims
   it: a sign-in sets it, an account switch replaces it, a sign-out clears it.
   Sign-out is only reported when the server confirmed it (HTTP 200); a 5xx
   or a network failure keeps the signed-in state and shows a retryable error,
   because the HttpOnly cookie is then still live.

## Display name

`name` is the Google profile name and is refreshed on every login.
`display_name` is the name the player chose for the account, or `null`;
`name_shown` is what they are called by default: `display_name` when set,
else the first word of `name` (capped at 20 characters).

`PATCH /api/me` with JSON `{"display_name": "<text>"}` sets it (`null`
clears it back to the Google first name). It needs the session cookie (401
otherwise) and shares the sign-in endpoint's per-IP budget (10/min → 429).
The server stores the name after these checks, in order, and answers 400
with the first failing reason as `detail`:

| reason | rule |
|---|---|
| `not_a_string` | the value must be a string (a non-string is also refused by the body model as 422) |
| `control_chars` | no character of Unicode category Cc (which includes every line break), Cs, Co, Zl or Zp anywhere in the raw text |
| `empty` | after trimming and collapsing every whitespace run to one space, at least 1 character |
| `too_long` | at most 20 characters after that normalisation |
| `reserved` | not, case-insensitively, `bot`, `bot N` (the server seats bots as "Bot N"), `system`, `admin`, `dealer`, `moderator` or `server` |
| `not_allowed` | refused by `DISPLAY_NAME_BLOCKLIST`, a module-level hook (`Callable[[str], bool] | None`) for a profanity or block-list filter; none is installed today |

Any script is allowed; uniqueness is not required. On success the response is
the updated account object. The web app applies the same rules first
(`checkDisplayName` in `web/src/auth.ts`) so the form can explain a refusal
without a round trip; the server stays the authority.

Where the player edits it: "Edit name" in the lobby's account chip and in the
phone's `…` menu row (`web/src/components/NameEditForm.tsx`). The lobby's
name field prefills from `name_shown` when it is empty; a signed-in player
who types a different name sees a "Save as my name" checkbox (off by
default) that sends one `PATCH` on create/join. Guests see none of this.

Security notes: the client id is public; there is no client secret anywhere.
Tokens are never logged (refusals carry only a short reason code). The login
endpoint is rate-limited in memory per client IP (10/min; Fly's
`Fly-Client-IP` header names the client). CSRF: Lax cookies plus a JSON POST
(a cross-site form cannot send it; no CORS headers are emitted, so a
cross-origin fetch is refused by the browser). The nonce is a consistency
check, not server-enforced replay binding: the page generates it, hands it
to Google and posts it with the token, so the server can only confirm the
two agree (it is optional server-side). Replay is bounded by the token's
own `exp` and by the fact that a token names one Google account. In dev,
Vite proxies `/api` to `:8000` so the page and the API share one origin.

## Configuration

| variable | meaning |
|---|---|
| `GOOGLE_CLIENT_ID` | the public OAuth client id (type Web). `fly.toml` sets it, so production has sign-in on. Unset or empty = feature off. |
| `SHENGJI_DATA_DIR` | where `accounts.sqlite3` lives. `fly.toml` sets `/data` (the volume). Unset: `/data` if it exists, else the dev tree's `logs/local/`. Tests set a temp dir. |

`/healthz` shows `"accounts": {"google_sign_in": true|false}`.

## Schema (`accounts.sqlite3`, WAL)

```
schema_version(version INTEGER)                      -- currently 2
users(id INTEGER PK, google_sub TEXT UNIQUE, email, name, picture,
      created_at INTEGER, last_login_at INTEGER,    -- unix seconds
      display_name TEXT NULL)                        -- v2; NULL = Google first name
sessions(token_hash TEXT PK, user_id -> users.id ON DELETE CASCADE,
         created_at INTEGER, expires_at INTEGER)
```

Migrations are the `SCHEMA` list in `accounts.py`: version N applies entries
`[current..N)` in one transaction on first use. An entry is either SQL
statements or a callable taking the connection; v2 is a callable that adds
`users.display_name` only when `PRAGMA table_info` lacks it, so a re-run on a
database whose version row was lost is harmless. Database access is plain
`sqlite3` on a fresh connection per call, run off the event loop via
`run_in_executor`; each call is a few indexed statements. Expired sessions are
purged on every login.

## Backup

The database is on the Fly volume next to the room logs, so a volume snapshot
covers it today. Plan: stream it off the machine with Litestream (SQLite WAL
replication to object storage) once accounts hold anything worth more than a
re-login; until then a lost volume costs each player one click.

## Jerry's one-time Google Cloud setup

1. In the Google Cloud console pick (or create) a project, then
   **APIs & Services → OAuth consent screen**: External, app name "Sheng Ji",
   your support email, no extra scopes (the ID token's `openid email profile`
   is the default), and publish it (an unpublished app only admits test users).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   type **Web application**. Authorized JavaScript origins:
   `https://shengji.fly.dev`, `http://localhost:5173` and `http://localhost`
   (Google wants both localhost forms). No redirect URIs (the button uses the
   popup flow).
3. Copy the client id (`….apps.googleusercontent.com`); the client secret is
   not used. It is set in `fly.toml` (done). Locally: `GOOGLE_CLIENT_ID=… uv
   run shengji-server` with `npm run dev` on :5173.
4. Verify: `/healthz` shows `google_sign_in: true`, the lobby shows the
   button, and `/api/me` answers 200 after signing in.
