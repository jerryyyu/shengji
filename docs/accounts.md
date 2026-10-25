# Accounts: optional Google sign-in

Guest play is unchanged. Signing in is optional and, until `GOOGLE_CLIENT_ID`
is set on the server, the feature does not exist: no button, no script from
Google, `POST /api/auth/google` answers 404.

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
   (`https://www.googleapis.com/oauth2/v1/certs`, cached per its `max-age`,
   refetched once on an unknown `kid`); `aud` == the client id; `exp`/`iat`
   (10 s skew); `iss` in {`accounts.google.com`, `https://accounts.google.com`};
   a `sub`; `email_verified`; and the `nonce` claim == the posted nonce.
5. On success it upserts the user, mints a session (32 random bytes), stores
   only its SHA-256, and sets the cookie `sj_session`: HttpOnly, SameSite=Lax,
   Secure (except on localhost), 30 days. The response is `{name, email, picture}`.
6. `GET /api/me` → the same object or 401. `POST /api/auth/logout` deletes the
   session and clears the cookie.
7. The `/ws` handshake carries the cookie like any same-site request. The
   server reads it once per socket: the seat remembers the account
   (`Seat.user_id`, server-only; it enters no state frame, log record or game
   decision), and a player who typed no name is called by their Google first
   name instead of "Player". Nothing about game logic or the bots changes.

Security notes: the client id is public; there is no client secret anywhere.
Tokens are never logged (refusals carry only a short reason code). The login
endpoint is rate-limited in memory per client IP (10/min; Fly's
`Fly-Client-IP` header names the client). CSRF: Lax cookies plus a JSON POST
(a cross-site form cannot send it; no CORS headers are emitted, so a
cross-origin fetch is refused by the browser) plus the nonce. In dev, Vite
proxies `/api` to `:8000` so the page and the API share one origin.

## Configuration

| variable | meaning |
|---|---|
| `GOOGLE_CLIENT_ID` | the OAuth client id (type Web). Unset or empty = feature off. `fly.toml` carries a commented placeholder. |
| `SHENGJI_DATA_DIR` | where `accounts.sqlite3` lives. `fly.toml` sets `/data` (the volume). Unset: `/data` if it exists, else the dev tree's `logs/local/`. Tests set a temp dir. |

`/healthz` shows `"accounts": {"google_sign_in": true|false}`.

## Schema (`accounts.sqlite3`, WAL)

```
schema_version(version INTEGER)                      -- currently 1
users(id INTEGER PK, google_sub TEXT UNIQUE, email, name, picture,
      created_at INTEGER, last_login_at INTEGER)    -- unix seconds
sessions(token_hash TEXT PK, user_id -> users.id ON DELETE CASCADE,
         created_at INTEGER, expires_at INTEGER)
```

Migrations are the `SCHEMA` list in `accounts.py`: version N applies entries
`[current..N)` in one transaction on first use. Database access is plain
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
   not used. Set it on Fly: `fly secrets set GOOGLE_CLIENT_ID=…` (or uncomment
   the `fly.toml` line and deploy). Locally: `GOOGLE_CLIENT_ID=… uv run
   shengji-server` with `npm run dev` on :5173.
4. Verify: `/healthz` shows `google_sign_in: true`, the lobby shows the
   button, and `/api/me` answers 200 after signing in.
