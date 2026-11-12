"""Sign in with Apple (``shengji.api.apple_auth``) and the v6 accounts schema.

Identity tokens are signed here with a generated RSA key and verified against
a mocked JWKS; the token exchange and the revocation go through a recording
stand-in for ``post_form``, so the suite never talks to Apple.
"""
from __future__ import annotations

import base64
import sqlite3
import time
from contextlib import closing

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from google.auth import crypt as google_crypt
from google.auth import jwt as google_jwt

from tests.test_server_ws import client  # noqa: F401

KID = "apple-kid-1"
BUNDLE = "com.jerryyu.shengji"
RAW_NONCE = "0123456789abcdef0123456789abcdef"


def _pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(rsa_key):
    numbers = rsa_key.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
                      "n": _b64(numbers.n), "e": _b64(numbers.e)}]}


def _sign(key, claims: dict, kid: str = KID) -> str:
    signer = google_crypt.RSASigner.from_string(_pem(key), key_id=kid)
    return google_jwt.encode(signer, claims).decode()


def _claims(**over) -> dict:
    from shengji.api import apple_auth

    now = int(time.time())
    base = {"iss": "https://appleid.apple.com", "aud": BUNDLE, "sub": "001234.apple.abcd",
            "email": "x7k2@privaterelay.appleid.com", "email_verified": True,
            "nonce": apple_auth.nonce_digest(RAW_NONCE), "nonce_supported": True,
            "iat": now - 5, "exp": now + 600}
    base.update(over)
    return base


class FakeApple:
    """Stands in for ``post_form``: records each call (without letting a
    test read secrets out of it beyond what it asserts) and answers from a
    script."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.revoke_raises = False

    def __call__(self, url, fields):
        self.calls.append((url, dict(fields)))
        if url.endswith("/auth/token"):
            return 200, {"access_token": "at", "refresh_token": "rt-secret-1",
                         "id_token": "x", "token_type": "Bearer", "expires_in": 3600}
        if url.endswith("/auth/revoke"):
            if self.revoke_raises:
                raise OSError("network down")
            return 200, {}
        raise AssertionError(f"unexpected url {url}")

    def urls(self):
        return [url.rsplit("/", 1)[-1] for url, _ in self.calls]


@pytest.fixture()
def apple_on(tmp_path, monkeypatch, jwks):
    """A private database, Apple's keys mocked, the network replaced, and no
    APPLE_* secrets (tests that need them set them)."""
    from shengji.api import accounts, apple_auth

    for name in ("APPLE_SIGNIN_KEY", "APPLE_KEY_ID", "APPLE_TEAM_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(accounts, "STORE", accounts.Store(tmp_path / "data" / "accounts.sqlite3"))
    monkeypatch.setattr(accounts, "LIMITER", accounts.RateLimiter())
    monkeypatch.setattr(apple_auth, "KEYS", accounts.GoogleCerts(
        fetch=lambda: (apple_auth.jwks_to_pem(jwks), 3600.0)))
    fake = FakeApple()
    monkeypatch.setattr(apple_auth, "post_form", fake)
    monkeypatch.setattr(apple_auth, "COUNTERS", {k: 0 for k in apple_auth.COUNTERS})
    return apple_auth, fake


@pytest.fixture()
def secrets_on(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv("APPLE_SIGNIN_KEY", _pem(key).replace("\n", "\\n"))
    monkeypatch.setenv("APPLE_KEY_ID", "KEYID12345")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAMTEST01")
    return key


def _post(client, token, nonce=RAW_NONCE, **extra):
    return client.post("/api/auth/apple", json={"identity_token": token, "nonce": nonce, **extra})


def _users(apple_auth):
    from shengji.api import accounts

    with closing(sqlite3.connect(accounts.STORE.path)) as db:
        return db.execute("SELECT google_sub, apple_sub, email, name FROM users ORDER BY id").fetchall()


def _has_users_table(apple_auth) -> bool:
    from shengji.api import accounts

    if not accounts.STORE.path.exists():
        return False
    return accounts.STORE.schema_version() > 0


# ------------------------------------------------------------ verification
def test_jwks_keys_verify_a_valid_token(apple_on, rsa_key):
    apple_auth, _ = apple_on
    claims = apple_auth.verify_apple_identity_token(_sign(rsa_key, _claims()), RAW_NONCE)
    assert claims["sub"] == "001234.apple.abcd" and claims["aud"] == BUNDLE


@pytest.mark.parametrize("over, nonce, reason", [
    ({"aud": "com.example.other"}, RAW_NONCE, "bad_audience"),
    ({"iss": "https://accounts.google.com"}, RAW_NONCE, "bad_issuer"),
    ({"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, RAW_NONCE, "expired"),
    ({}, "another-nonce", "nonce"),
    ({"nonce": RAW_NONCE}, RAW_NONCE, "nonce"),     # the raw nonce is not its digest
    ({"nonce": None}, RAW_NONCE, "nonce"),
    ({"sub": ""}, RAW_NONCE, "no_subject"),
])
def test_bad_tokens_are_refused_with_a_reason(apple_on, rsa_key, over, nonce, reason):
    apple_auth, _ = apple_on
    claims = {k: v for k, v in _claims(**over).items() if v is not None}
    with pytest.raises(apple_auth.AuthError) as exc:
        apple_auth.verify_apple_identity_token(_sign(rsa_key, claims), nonce)
    assert exc.value.reason == reason


def test_a_token_signed_by_another_key_or_mangled_is_refused(apple_on, rsa_key, other_key):
    apple_auth, _ = apple_on
    with pytest.raises(apple_auth.AuthError) as exc:
        apple_auth.verify_apple_identity_token(_sign(other_key, _claims()), RAW_NONCE)
    assert exc.value.reason == "bad_signature"
    good = _sign(rsa_key, _claims())
    head, body, sig = good.split(".")
    forged = ".".join([head, body, sig[:-4] + ("AAAA" if sig[-4:] != "AAAA" else "BBBB")])
    with pytest.raises(apple_auth.AuthError) as exc:
        apple_auth.verify_apple_identity_token(forged, RAW_NONCE)
    assert exc.value.reason == "bad_signature"
    for junk in ("", "not-a-jwt", "a.b.c"):
        with pytest.raises(apple_auth.AuthError):
            apple_auth.verify_apple_identity_token(junk, RAW_NONCE)


def test_only_rs256_is_accepted(apple_on):
    apple_auth, _ = apple_on
    key = ec.generate_private_key(ec.SECP256R1())
    signer = google_crypt.ES256Signer.from_string(_pem(key), key_id=KID)
    token = google_jwt.encode(signer, _claims()).decode()
    with pytest.raises(apple_auth.AuthError) as exc:
        apple_auth.verify_apple_identity_token(token, RAW_NONCE)
    assert exc.value.reason == "malformed"


# -------------------------------------------------------------- HTTP flow
@pytest.mark.parametrize("over, nonce", [
    ({"aud": "com.example.other"}, RAW_NONCE),
    ({"iss": "https://example.com"}, RAW_NONCE),
    ({"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}, RAW_NONCE),
    ({}, "mismatched-nonce"),
])
def test_rejected_tokens_answer_401_and_create_no_user(apple_on, rsa_key, other_key, client,
                                                       over, nonce):
    apple_auth, fake = apple_on
    resp = _post(client, _sign(rsa_key, _claims(**over)), nonce=nonce,
                 authorization_code="code-1", given_name="Ann")
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers
    assert not _has_users_table(apple_auth) or _users(apple_auth) == []
    assert fake.calls == []


def test_a_bad_signature_answers_401_and_creates_no_user(apple_on, other_key, client):
    apple_auth, _ = apple_on
    resp = _post(client, _sign(other_key, _claims()))
    assert resp.status_code == 401 and "bad_signature" in resp.json()["detail"]
    assert not _has_users_table(apple_auth) or _users(apple_auth) == []


def test_a_valid_token_creates_the_user_and_a_session(apple_on, rsa_key, client):
    apple_auth, fake = apple_on
    resp = _post(client, _sign(rsa_key, _claims()), authorization_code="code-1",
                 given_name="Ann", family_name="Lee")
    assert resp.status_code == 200
    assert resp.json() == {"name": "Ann Lee", "email": "x7k2@privaterelay.appleid.com",
                           "picture": None, "display_name": None, "name_shown": "Ann"}
    cookie = resp.headers["set-cookie"]
    low = cookie.lower()
    assert cookie.startswith("sj_session=") and "httponly" in low and "samesite=lax" in low
    assert _users(apple_auth) == [(None, "001234.apple.abcd", "x7k2@privaterelay.appleid.com",
                                   "Ann Lee")]
    me = client.get("/api/me", headers={"cookie": cookie.split(";")[0]})
    assert me.status_code == 200 and me.json()["name_shown"] == "Ann"
    # No secrets configured: sign-in works, nothing is sent to Apple.
    assert fake.calls == []
    assert apple_auth.COUNTERS["exchange_unconfigured"] == 1


def test_a_later_sign_in_without_a_name_or_email_keeps_the_stored_ones(apple_on, rsa_key, client):
    apple_auth, _ = apple_on
    assert _post(client, _sign(rsa_key, _claims()), given_name="Ann", family_name="Lee"
                 ).status_code == 200
    claims = _claims()
    del claims["email"]
    resp = _post(client, _sign(rsa_key, claims), given_name="", family_name="")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Ann Lee"
    assert _users(apple_auth) == [(None, "001234.apple.abcd", "x7k2@privaterelay.appleid.com",
                                   "Ann Lee")]


def test_with_secrets_the_code_is_exchanged_and_the_refresh_token_stays_server_side(
        apple_on, rsa_key, client, secrets_on):
    apple_auth, fake = apple_on
    from shengji.api import accounts

    resp = _post(client, _sign(rsa_key, _claims()), authorization_code="code-1", given_name="Ann")
    assert resp.status_code == 200
    assert "rt-secret-1" not in resp.text
    assert fake.urls() == ["token"]
    _url, fields = fake.calls[0]
    assert fields["client_id"] == BUNDLE and fields["code"] == "code-1"
    assert fields["grant_type"] == "authorization_code"
    # The client secret is an ES256 JWT signed with the configured key.
    header, payload, _signed, _sig = google_jwt._unverified_decode(fields["client_secret"])
    assert header["alg"] == "ES256" and header["kid"] == "KEYID12345"
    assert payload["iss"] == "TEAMTEST01" and payload["sub"] == BUNDLE
    assert payload["aud"] == "https://appleid.apple.com"
    assert 0 < payload["exp"] - payload["iat"] <= 180 * 86400
    verifier = google_crypt.ES256Verifier(secrets_on.public_key())
    signed, sig = fields["client_secret"].rsplit(".", 1)
    assert verifier.verify(signed.encode(), base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
    user_id = accounts.STORE.session_user(resp.headers["set-cookie"].split(";")[0].split("=", 1)[1])["id"]
    assert accounts.STORE.apple_refresh_token(user_id) == "rt-secret-1"
    assert "refresh_token" not in accounts.STORE.user(user_id)
    assert apple_auth.COUNTERS["exchanged"] == 1


def test_a_failed_exchange_still_signs_in(apple_on, rsa_key, client, secrets_on, monkeypatch):
    apple_auth, _ = apple_on

    def refuse(url, fields):
        return 400, {"error": "invalid_grant"}
    monkeypatch.setattr(apple_auth, "post_form", refuse)
    resp = _post(client, _sign(rsa_key, _claims()), authorization_code="code-1")
    assert resp.status_code == 200
    assert apple_auth.COUNTERS["exchange_failed"] == 1


def _signed_in(client, rsa_key, **extra):
    resp = _post(client, _sign(rsa_key, _claims()), **extra)
    assert resp.status_code == 200
    return {"cookie": resp.headers["set-cookie"].split(";")[0]}


def test_deleting_an_apple_account_revokes_its_refresh_token(apple_on, rsa_key, client, secrets_on):
    apple_auth, fake = apple_on
    session = _signed_in(client, rsa_key, authorization_code="code-1")
    resp = client.delete("/api/me", headers=session)
    assert resp.status_code == 204
    assert fake.urls() == ["token", "revoke"]
    _url, fields = fake.calls[1]
    assert fields["token"] == "rt-secret-1" and fields["token_type_hint"] == "refresh_token"
    assert fields["client_id"] == BUNDLE
    assert _users(apple_auth) == []
    with closing(sqlite3.connect(apple_auth.accounts.STORE.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM apple_tokens").fetchone() == (0,)
    assert apple_auth.COUNTERS["revoked"] == 1


def test_deletion_still_happens_when_the_revoke_raises(apple_on, rsa_key, client, secrets_on):
    apple_auth, fake = apple_on
    session = _signed_in(client, rsa_key, authorization_code="code-1")
    fake.revoke_raises = True
    resp = client.delete("/api/me", headers=session)
    assert resp.status_code == 204
    assert fake.urls() == ["token", "revoke"]
    assert _users(apple_auth) == []
    assert client.get("/api/me", headers=session).status_code == 401
    assert apple_auth.COUNTERS["revoke_failed"] == 1


def test_without_secrets_deletion_sends_nothing_to_apple(apple_on, rsa_key, client):
    apple_auth, fake = apple_on
    session = _signed_in(client, rsa_key, authorization_code="code-1")
    assert client.delete("/api/me", headers=session).status_code == 204
    assert fake.calls == [] and _users(apple_auth) == []
    assert apple_auth.COUNTERS["revoke_no_token"] == 1


def test_the_apple_endpoint_is_rate_limited_per_ip(apple_on, rsa_key, client, monkeypatch):
    apple_auth, _ = apple_on
    from shengji.api import accounts

    monkeypatch.setattr(accounts, "LIMITER", accounts.RateLimiter(limit=2, window=60))
    token = _sign(rsa_key, _claims())
    assert [_post(client, token).status_code for _ in range(3)] == [200, 200, 429]


@pytest.mark.parametrize("given, family, stored", [
    ("Ann", "Lee", "Ann Lee"), ("  Ann ", None, "Ann"), (None, "Lee", "Lee"),
    ("", "", None), (None, None, None), ("A\nB", None, None), ("x" * 101, None, None),
])
def test_first_authorization_names(apple_on, given, family, stored):
    apple_auth, _ = apple_on
    assert apple_auth.first_authorization_name(given, family) == stored


# ---------------------------------------------------------------- schema v6
def _v5_database(path):
    """A database at schema version 5, built by the shipped steps 1..5, with
    Google users, sessions, saved-game links and rating events in it, and an
    account (id 3) already deleted, so the sequences sit above the kept ids."""
    from shengji.api import accounts

    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        for step in accounts.SCHEMA[:5]:
            if callable(step):
                step(db)
            else:
                for statement in filter(None, (s.strip() for s in step.split(";"))):
                    db.execute(statement)
        db.execute("DELETE FROM schema_version")
        db.execute("INSERT INTO schema_version(version) VALUES (5)")
        for i, sub in enumerate(("g-1", "g-2", "g-3"), start=1):
            db.execute("""INSERT INTO users(google_sub, email, name, picture, created_at,
                                            last_login_at, display_name, rating)
                          VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                       (sub, f"{sub}@example.com", f"User {i}", i, i,
                        "Champ" if i == 1 else None, 1000.0 + i))
        db.execute("INSERT INTO sessions VALUES ('hash-1', 1, 1, 9999999999)")
        db.execute("INSERT INTO sessions VALUES ('hash-2', 2, 1, 9999999999)")
        db.execute("""INSERT INTO games(id, room_code, log_file, log_offset, started_at)
                      VALUES ('g1', 'ABCD', 'ABCD.jsonl', 0, ?)""", (int(time.time()),))
        db.execute("INSERT INTO game_players(game_id, user_id, seat, from_round) VALUES ('g1', 1, 0, 1)")
        db.execute("INSERT INTO game_players(game_id, user_id, seat, from_round) VALUES ('g1', 2, 1, 1)")
        for event_id, user_id in ((1, 1), (2, 2), (3, 3)):
            db.execute("""INSERT INTO rating_events(id, game_id, round_no, user_id, created_at, team,
                              banker_team, won, levels, expected, actual, k, rating_before,
                              rating_after, delta)
                          VALUES (?, 'g1', 1, ?, 1, 0, 0, 1, 1, 0.5, 1.0, 20, 1000, 1010, 10)""",
                       (event_id, user_id))
        db.execute("DELETE FROM users WHERE id = 3")     # its event goes by cascade
        db.execute("COMMIT")


def _sql(path, name):
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None


def test_a_v5_database_upgrades_to_v6_and_keeps_every_row(apple_on, tmp_path, rsa_key):
    from shengji.api import accounts

    path = tmp_path / "v5" / "accounts.sqlite3"
    _v5_database(path)
    with closing(sqlite3.connect(path)) as db:
        before_users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
        before_sessions = sorted(db.execute("SELECT * FROM sessions"))
        before_links = sorted(db.execute("SELECT * FROM game_players"))
        before_events = sorted(db.execute("SELECT * FROM rating_events"))
    store = accounts.Store(path)
    assert store.schema_version() == len(accounts.SCHEMA) == 6
    with closing(sqlite3.connect(path)) as db:
        after_users = db.execute(
            f"SELECT {accounts._USER_COLUMNS_V5} FROM users ORDER BY id").fetchall()
        assert after_users == before_users
        assert db.execute("SELECT apple_sub FROM users").fetchall() == [(None,), (None,)]
        assert sorted(db.execute("SELECT * FROM sessions")) == before_sessions
        assert sorted(db.execute("SELECT * FROM game_players")) == before_links
        assert sorted(db.execute("SELECT * FROM rating_events")) == before_events
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert not {"users_v5", "sessions_v6", "game_players_v6", "rating_events_v6"} & names
    assert {"sessions_user", "sessions_expires", "game_players_user", "rating_events_user",
            "rating_events_created", "apple_tokens"} <= names
    for child in ("sessions", "game_players", "rating_events"):
        assert "REFERENCES users(id) ON DELETE CASCADE" in _sql(path, child)
    users_sql = _sql(path, "users")
    assert "AUTOINCREMENT" in users_sql and "CHECK" in users_sql
    # The schema refuses an account with neither identity.
    with closing(sqlite3.connect(path)) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO users(created_at, last_login_at) VALUES (1, 1)")
    # Sessions still sign their users in, and the cascades follow the new table.
    assert store.session_user("x" * 10) is None
    assert store.user(1)["display_name"] == "Champ"
    # Google sign-in finds the existing row; the deleted id 3 is never reused.
    again = store.upsert_user({"sub": "g-1", "email": "g-1@example.com", "name": "User 1"})
    assert again["id"] == 1 and again["rating"] == 1001.0
    newcomer = store.upsert_apple_user("apple-new", None, "New Person")
    assert newcomer["id"] > 3 and newcomer["google_sub"] is None
    google_new = store.upsert_user({"sub": "g-new", "email": "n@example.com", "name": "N"})
    assert google_new["id"] > newcomer["id"] and google_new["apple_sub"] is None
    assert store.delete_user(2) is True
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT user_id FROM sessions").fetchall() == [(1,)]
        assert db.execute("SELECT user_id FROM game_players").fetchall() == [(1,)]
        assert db.execute("SELECT user_id FROM rating_events").fetchall() == [(1,)]
        # rating-event ids keep their high-water mark too
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'rating_events'"
                          ).fetchone()[0] >= 3
    # The step re-runs harmlessly and a new Store does nothing.
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        accounts._migrate_v6(db)
        db.commit()
    assert accounts.Store(path).schema_version() == 6
    assert accounts.Store(path).user(1)["display_name"] == "Champ"


def test_a_fresh_database_has_the_same_users_table_as_a_migrated_one(apple_on, tmp_path):
    from shengji.api import accounts

    migrated = tmp_path / "v5" / "accounts.sqlite3"
    _v5_database(migrated)
    accounts.Store(migrated).schema_version()
    fresh = tmp_path / "fresh" / "accounts.sqlite3"
    accounts.Store(fresh).schema_version()
    for table in ("users", "sessions", "game_players", "rating_events", "apple_tokens"):
        with closing(sqlite3.connect(migrated)) as a, closing(sqlite3.connect(fresh)) as b:
            assert (a.execute(f"PRAGMA table_info({table})").fetchall()
                    == b.execute(f"PRAGMA table_info({table})").fetchall()), table


def test_google_sign_in_is_unchanged_after_the_migration(apple_on, tmp_path, monkeypatch, client):
    """A Google user from a v5 database signs in through ``/api/auth/google``
    and gets the same response body as before the upgrade."""
    from shengji.api import accounts
    from tests import test_accounts as ga

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    path = tmp_path / "v5g" / "accounts.sqlite3"
    _v5_database(path)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", ga.CLIENT_ID)
    monkeypatch.setattr(accounts, "STORE", accounts.Store(path))
    monkeypatch.setattr(accounts, "CERTS", accounts.GoogleCerts(
        fetch=lambda: ({ga.KID: public_pem}, 3600.0)))
    resp = client.post("/api/auth/google", json={
        "credential": ga._sign(_pem(key), ga._claims(sub="g-1", nonce="n"), kid=ga.KID),
        "nonce": "n"})
    assert resp.status_code == 200
    assert resp.json() == {"name": "Jerry Yu", "email": "jerry@example.com",
                           "picture": "https://img.example/jy.png",
                           "display_name": "Champ", "name_shown": "Champ"}
    assert accounts.STORE.user(1)["google_sub"] == "g-1"
