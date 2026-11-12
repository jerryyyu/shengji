"""Sign in with Apple for the iOS app: identity-token verification, the
authorization-code exchange and the revocation Apple requires on account
deletion.

Trust boundary: the app's native Apple sheet hands the page an identity token
(a JWT), an authorization code and, on the first authorization only, the
person's name. The page posts them with the raw nonce it generated; the sheet
was given the nonce's SHA-256 hex, which Apple copies into the token's
``nonce`` claim. The server verifies the RS256 signature against Apple's
published keys, ``iss``, ``aud`` (the app's bundle id), the validity window
and the nonce binding before it mints a session. Verification needs no secret,
so sign-in works on any deployment.

The secrets (``APPLE_SIGNIN_KEY``, the PEM of the .p8 key; ``APPLE_KEY_ID``;
``APPLE_TEAM_ID``) are needed only to sign the client secret for Apple's token
and revoke endpoints. Without them the code exchange and the revocation are
skipped and counted in ``COUNTERS``. The refresh token the exchange returns is
stored server-side only (``apple_tokens``), never returned, never logged; a
failed exchange or revocation never fails a sign-in or an account deletion.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import accounts
from .accounts import AuthError, GoogleCerts

log = logging.getLogger(__name__)

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_REVOKE_URL = "https://appleid.apple.com/auth/revoke"
# The app's bundle id: the audience of its identity tokens and the client id
# of its token and revoke calls.
BUNDLE_ID = "com.jerryyu.shengji"
# The client secret is minted per call, so a short life suffices (Apple
# accepts up to six months).
CLIENT_SECRET_SECONDS = 300
HTTP_TIMEOUT = 5.0
# A first-authorization name longer than this is not a name; it is dropped.
NAME_MAX = 100
CODE_MAX = 2048

# Best-effort outcomes since the process started; counts only, no identities.
COUNTERS: dict[str, int] = {
    "exchanged": 0, "exchange_failed": 0, "exchange_unconfigured": 0,
    "revoked": 0, "revoke_failed": 0, "revoke_unconfigured": 0, "revoke_no_token": 0,
}


def _count(key: str) -> None:
    COUNTERS[key] = COUNTERS.get(key, 0) + 1


# ------------------------------------------------------------------ keys
def _b64url_int(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")


def jwks_to_pem(body: Any) -> dict[str, str]:
    """Apple's JWKS as PEM public keys keyed by ``kid`` (the form
    ``google.auth.jwt.decode`` verifies against); non-RSA entries are
    skipped."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(keys, list):
        raise AuthError("certs_malformed")
    out: dict[str, str] = {}
    for key in keys:
        if not isinstance(key, dict) or key.get("kty") != "RSA":
            continue
        kid, n, e = key.get("kid"), key.get("n"), key.get("e")
        if not (isinstance(kid, str) and isinstance(n, str) and isinstance(e, str)):
            continue
        public = RSAPublicNumbers(_b64url_int(e), _b64url_int(n)).public_key()
        out[kid] = public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    if not out:
        raise AuthError("certs_malformed")
    return out


def _fetch_apple_keys() -> tuple[dict, float]:
    req = urllib.request.Request(APPLE_KEYS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:   # noqa: S310 - fixed https URL
        body = json.loads(resp.read().decode("utf-8"))
        ttl = accounts.CERTS_DEFAULT_TTL
        m = re.search(r"max-age=(\d+)", resp.headers.get("Cache-Control", ""))
        if m:
            ttl = float(m.group(1))
    return jwks_to_pem(body), ttl


# The same single-flight, bounded refresh as Google's certificates.
KEYS = GoogleCerts(fetch=_fetch_apple_keys, label="apple")


def nonce_digest(raw: str) -> str:
    """What the page hands Apple's sheet for a raw nonce, and so what the
    token's ``nonce`` claim must equal."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_apple_identity_token(token: str, raw_nonce: str,
                                keys: GoogleCerts | None = None) -> dict:
    """Verify an Apple identity token and return its claims, or raise
    ``AuthError``.

    Checks, in order: a well-formed RS256 JWT whose ``kid`` names one of
    Apple's current keys (a miss asks for one bounded refresh); the
    signature; ``aud`` the bundle id; ``iat``/``exp`` within the clock skew;
    ``iss`` Apple; a ``sub``; and ``nonce`` equal to the SHA-256 hex of
    ``raw_nonce``."""
    from google.auth import exceptions as google_exceptions
    from google.auth import jwt as google_jwt

    keys = keys or KEYS
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise AuthError("malformed")
    if not isinstance(raw_nonce, str) or not raw_nonce or len(raw_nonce) > 256:
        raise AuthError("nonce")
    try:
        header, _payload, _signed, _sig = google_jwt._unverified_decode(token)  # noqa: SLF001
    except Exception as exc:            # noqa: BLE001 - any parse failure is one answer
        raise AuthError("malformed") from exc
    if header.get("alg") != "RS256":
        raise AuthError("malformed")
    kid = header.get("kid")
    current = keys.get()
    if kid is not None and str(kid) not in current:
        current = keys.get(force=True)
    try:
        claims = google_jwt.decode(token, certs=current, audience=BUNDLE_ID,
                                   clock_skew_in_seconds=accounts.CLOCK_SKEW_SECONDS)
    except google_exceptions.InvalidValue as exc:
        text = str(exc).lower()
        if "expired" in text or "too early" in text or "iat" in text:
            raise AuthError("expired") from exc
        if "audience" in text:
            raise AuthError("bad_audience") from exc
        raise AuthError("invalid") from exc
    except google_exceptions.GoogleAuthError as exc:
        raise AuthError("bad_signature") from exc
    except Exception as exc:            # noqa: BLE001 - never leak a parser traceback
        raise AuthError("malformed") from exc
    if claims.get("iss") != APPLE_ISSUER:
        raise AuthError("bad_issuer")
    if claims.get("aud") != BUNDLE_ID:
        raise AuthError("bad_audience")
    if not claims.get("sub"):
        raise AuthError("no_subject")
    claimed = claims.get("nonce")
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, nonce_digest(raw_nonce)):
        raise AuthError("nonce")
    return dict(claims)


# --------------------------------------------------- token and revoke calls
def _config() -> tuple[str, str, str] | None:
    """``(key_pem, key_id, team_id)``, or None when any is unset. A PEM given
    with literal ``\\n`` escapes (one-line secret stores) is unescaped."""
    key = os.environ.get("APPLE_SIGNIN_KEY", "").strip()
    key_id = os.environ.get("APPLE_KEY_ID", "").strip()
    team_id = os.environ.get("APPLE_TEAM_ID", "").strip()
    if not (key and key_id and team_id):
        return None
    return key.replace("\\n", "\n"), key_id, team_id


def configured() -> bool:
    return _config() is not None


def client_secret(now: float | None = None) -> str | None:
    """The ES256 client secret for Apple's token and revoke endpoints, or
    None without the secrets."""
    from google.auth import crypt as google_crypt
    from google.auth import jwt as google_jwt

    cfg = _config()
    if cfg is None:
        return None
    key_pem, key_id, team_id = cfg
    t = int(now if now is not None else time.time())
    signer = google_crypt.ES256Signer.from_string(key_pem, key_id=key_id)
    payload = {"iss": team_id, "iat": t, "exp": t + CLIENT_SECRET_SECONDS,
               "aud": APPLE_ISSUER, "sub": BUNDLE_ID}
    return google_jwt.encode(signer, payload).decode("ascii")


def post_form(url: str, fields: dict[str, str]) -> tuple[int, dict]:
    """POST a form to one of Apple's fixed endpoints; ``(status, json body)``.
    The tests replace this, so the suite never reaches Apple."""
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:   # noqa: S310 - fixed https URL
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def exchange_code(code: str) -> str | None:
    """Exchange an authorization code for a refresh token. None when the
    secrets are unset; raises when Apple refuses or returns no token."""
    secret = client_secret()
    if secret is None:
        return None
    status, body = post_form(APPLE_TOKEN_URL, {
        "client_id": BUNDLE_ID, "client_secret": secret, "code": code,
        "grant_type": "authorization_code"})
    token = body.get("refresh_token")
    if status != 200 or not isinstance(token, str) or not token:
        raise RuntimeError(f"apple token exchange refused ({status}, {body.get('error', '')})")
    return token


def revoke_token(refresh_token: str) -> bool:
    """Revoke a refresh token. False when the secrets are unset; raises when
    Apple refuses."""
    secret = client_secret()
    if secret is None:
        return False
    status, body = post_form(APPLE_REVOKE_URL, {
        "client_id": BUNDLE_ID, "client_secret": secret, "token": refresh_token,
        "token_type_hint": "refresh_token"})
    if status != 200:
        raise RuntimeError(f"apple revoke refused ({status}, {body.get('error', '')})")
    return True


async def revoke_after_delete(refresh_token: str | None) -> None:
    """Best effort, after the account row is gone: every outcome is counted
    and logged without token material, none raises."""
    if not refresh_token:
        _count("revoke_no_token")
        log.warning("apple account deleted without a stored refresh token; nothing revoked")
        return
    if not configured():
        _count("revoke_unconfigured")
        log.warning("apple account deleted but APPLE_* secrets are unset; grant not revoked")
        return
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, revoke_token, refresh_token)
        _count("revoked")
    except Exception as exc:            # noqa: BLE001 - the delete already happened
        _count("revoke_failed")
        log.warning("apple revoke failed after delete (%s)", type(exc).__name__)


# ---------------------------------------------------------------- HTTP API
router = APIRouter(prefix="/api")


class AppleLogin(BaseModel):
    identity_token: str
    nonce: str
    authorization_code: str | None = None
    given_name: str | None = None
    family_name: str | None = None


_NAME_FORBIDDEN = frozenset({"Cc", "Cs", "Co", "Zl", "Zp", "Cf"})


def first_authorization_name(given: str | None, family: str | None) -> str | None:
    """The full name Apple's sheet returned, or None when it sent none (every
    sign-in after the first) or sent something that is not a plain name."""
    parts = [p for p in (given, family) if isinstance(p, str)]
    if any(unicodedata.category(ch) in _NAME_FORBIDDEN for p in parts for ch in p):
        return None
    name = " ".join(" ".join(p.split()) for p in parts).strip()
    if not name or len(name) > NAME_MAX:
        return None
    return name


@router.post("/auth/apple")
async def auth_apple(body: AppleLogin, request: Request, response: Response) -> dict:
    if not accounts.LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again in a minute.")
    loop = asyncio.get_running_loop()
    try:
        claims = await loop.run_in_executor(
            None, verify_apple_identity_token, body.identity_token, body.nonce)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=f"Sign-in rejected ({exc.reason}).") from exc
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    name = first_authorization_name(body.given_name, body.family_name)
    store = accounts.STORE
    user = await store.run(store.upsert_apple_user, claims["sub"], email, name)
    code = body.authorization_code
    if code and len(code) <= CODE_MAX:
        if not configured():
            _count("exchange_unconfigured")
            log.warning("apple sign-in without APPLE_* secrets; code not exchanged")
        else:
            try:
                refresh = await loop.run_in_executor(None, exchange_code, code)
                if refresh:
                    await store.run(store.set_apple_refresh_token, user["id"], refresh)
                    _count("exchanged")
            except Exception as exc:    # noqa: BLE001 - the sign-in still succeeds
                _count("exchange_failed")
                log.warning("apple code exchange failed (%s)", type(exc).__name__)
    token = await store.run(store.create_session, user["id"])
    accounts._set_session_cookie(response, request, token)   # noqa: SLF001
    return accounts.public_user(user)
