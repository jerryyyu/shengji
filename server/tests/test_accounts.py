"""Optional Google sign-in (``shengji.api.accounts``).

Tokens are signed here with a generated RSA key and verified against a mocked
certificate set, so the suite never talks to Google. The websocket tests ride
the real protocol through ``TestClient``: a cookie-carrying socket gets the
account on its seat and the first name as its default; a guest socket is
unchanged.
"""
from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt as google_crypt
from google.auth import jwt as google_jwt

from tests.test_server_ws import _drain, client  # noqa: F401

CLIENT_ID = "1234567890-test.apps.googleusercontent.com"
KID = "kid-test-1"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private_pem, public_pem


@pytest.fixture(scope="module")
def other_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()


def _sign(private_pem: str, claims: dict, kid: str = KID) -> str:
    signer = google_crypt.RSASigner.from_string(private_pem, key_id=kid)
    return google_jwt.encode(signer, claims).decode()


def _claims(**over) -> dict:
    now = int(time.time())
    base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "10987654321",
            "email": "jerry@example.com", "email_verified": True,
            "name": "Jerry Yu", "given_name": "Jerry", "picture": "https://img.example/jy.png",
            "iat": now - 5, "exp": now + 3600}
    base.update(over)
    return base


@pytest.fixture()
def accounts_on(tmp_path, monkeypatch, keypair):
    """Sign-in configured, a private database, Google's certs mocked."""
    from shengji.api import accounts

    _private, public_pem = keypair
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    store = accounts.Store(tmp_path / "data" / "accounts.sqlite3")
    certs = accounts.GoogleCerts(fetch=lambda: ({KID: public_pem}, 3600.0))
    limiter = accounts.RateLimiter()
    monkeypatch.setattr(accounts, "STORE", store)
    monkeypatch.setattr(accounts, "CERTS", certs)
    monkeypatch.setattr(accounts, "LIMITER", limiter)
    return accounts


def _login(client, token, nonce=None, **kw):
    body = {"credential": token}
    if nonce is not None:
        body["nonce"] = nonce
    return client.post("/api/auth/google", json=body, **kw)


# ------------------------------------------------------------ verification
def test_a_valid_token_yields_its_claims(accounts_on, keypair):
    private_pem, _ = keypair
    claims = accounts_on.verify_google_id_token(_sign(private_pem, _claims()), CLIENT_ID)
    assert claims["sub"] == "10987654321" and claims["email"] == "jerry@example.com"


@pytest.mark.parametrize("over, reason", [
    ({"aud": "someone-else.apps.googleusercontent.com"}, "bad_audience"),
    ({"iss": "https://evil.example"}, "bad_issuer"),
    ({"exp": int(time.time()) - 600, "iat": int(time.time()) - 4200}, "expired"),
    ({"email_verified": False}, "email_unverified"),
    ({"sub": ""}, "no_subject"),
])
def test_bad_claims_are_refused_with_a_reason(accounts_on, keypair, over, reason):
    private_pem, _ = keypair
    with pytest.raises(accounts_on.AuthError) as info:
        accounts_on.verify_google_id_token(_sign(private_pem, _claims(**over)), CLIENT_ID)
    assert info.value.reason == reason


def test_both_google_issuer_spellings_pass(accounts_on, keypair):
    private_pem, _ = keypair
    for iss in ("accounts.google.com", "https://accounts.google.com"):
        accounts_on.verify_google_id_token(_sign(private_pem, _claims(iss=iss)), CLIENT_ID)


def test_a_token_signed_by_another_key_or_mangled_is_refused(accounts_on, keypair, other_keypair):
    private_pem, _ = keypair
    with pytest.raises(accounts_on.AuthError) as info:
        accounts_on.verify_google_id_token(_sign(other_keypair, _claims()), CLIENT_ID)
    assert info.value.reason == "bad_signature"
    good = _sign(private_pem, _claims())
    head, body, sig = good.split(".")
    with pytest.raises(accounts_on.AuthError):
        accounts_on.verify_google_id_token(f"{head}.{body}x.{sig}", CLIENT_ID)
    for junk in ("", "not.a.jwt", "a" * 9000):
        with pytest.raises(accounts_on.AuthError) as info:
            accounts_on.verify_google_id_token(junk, CLIENT_ID)
        assert info.value.reason == "malformed"


def test_an_unknown_kid_refetches_the_certs_once_then_refuses(accounts_on, keypair):
    private_pem, public_pem = keypair
    calls = []

    def fetch():
        calls.append(1)
        return ({KID: public_pem}, 3600.0)

    certs = accounts_on.GoogleCerts(fetch=fetch)
    certs.get()
    assert calls == [1]
    with pytest.raises(accounts_on.AuthError):
        accounts_on.verify_google_id_token(_sign(private_pem, _claims(), kid="rotated"), CLIENT_ID, certs)
    assert calls == [1, 1]   # one forced refresh for the miss, no loop


def test_certs_are_cached_until_their_max_age_and_survive_a_failed_refresh(accounts_on, keypair):
    _, public_pem = keypair
    state = {"fail": False, "calls": 0}

    def fetch():
        state["calls"] += 1
        if state["fail"]:
            raise OSError("google unreachable")
        return ({KID: public_pem}, 60.0)

    certs = accounts_on.GoogleCerts(fetch=fetch)
    assert certs.get() == {KID: public_pem}
    certs.get()
    assert state["calls"] == 1
    state["fail"] = True
    assert certs.get(force=True) == {KID: public_pem}   # stale set beats no set
    certs.reset()
    with pytest.raises(accounts_on.AuthError) as info:
        certs.get()
    assert info.value.reason == "certs_unavailable"


# -------------------------------------------------------------- HTTP flow
def test_login_creates_a_user_sets_the_cookie_and_me_reads_it_back(accounts_on, keypair, client):
    private_pem, _ = keypair
    assert client.get("/api/auth/config").json() == {"google_client_id": CLIENT_ID}
    assert client.get("/api/me").status_code == 401

    resp = _login(client, _sign(private_pem, _claims()), nonce="n-1" )
    assert resp.status_code == 401        # the token carries no nonce claim
    resp = _login(client, _sign(private_pem, _claims(nonce="n-1")), nonce="n-1")
    assert resp.status_code == 200
    assert resp.json() == {"name": "Jerry Yu", "email": "jerry@example.com",
                           "picture": "https://img.example/jy.png"}
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("sj_session=")
    low = cookie.lower()
    assert "httponly" in low and "samesite=lax" in low and "secure" in low
    assert "max-age=2592000" in low
    token = cookie.split(";")[0].split("=", 1)[1]
    assert len(token) >= 40
    # The database holds the hash, never the token.
    with accounts_on.closing(accounts_on.sqlite3.connect(accounts_on.STORE.path)) as db:
        rows = db.execute("SELECT token_hash FROM sessions").fetchall()
        users = db.execute("SELECT google_sub, email, name FROM users").fetchall()
    assert rows == [(accounts_on._hash_token(token),)]
    assert users == [("10987654321", "jerry@example.com", "Jerry Yu")]
    assert accounts_on.STORE.schema_version() == 1

    # The cookie is Secure, so httpx's jar withholds it from the http test
    # origin; the browser sends it, and here the header is passed by hand.
    session = {"cookie": cookie.split(";")[0]}
    me = client.get("/api/me", headers=session)
    assert me.status_code == 200 and me.json()["name"] == "Jerry Yu"

    # A second login by the same Google account is the same user, refreshed.
    resp = _login(client, _sign(private_pem, _claims(name="Jerry Y.", picture=None)))
    assert resp.status_code == 200
    assert accounts_on.STORE.user(1) is not None
    with accounts_on.closing(accounts_on.sqlite3.connect(accounts_on.STORE.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
        assert db.execute("SELECT name, picture FROM users").fetchone() == (
            "Jerry Y.", "https://img.example/jy.png")   # a missing picture keeps the old one

    # Logout deletes the session and the cookie.
    out = client.post("/api/auth/logout", headers=session)
    assert out.status_code == 200
    assert "sj_session=" in out.headers["set-cookie"] and 'max-age=0' in out.headers["set-cookie"].lower()
    assert client.get("/api/me", headers=session).status_code == 401
    assert accounts_on.STORE.count_sessions(1) == 1   # the second login's session stays


def test_the_cookie_is_not_secure_on_localhost_only(accounts_on, keypair, client):
    private_pem, _ = keypair
    resp = _login(client, _sign(private_pem, _claims()), headers={"host": "localhost"})
    assert resp.status_code == 200
    assert "secure" not in resp.headers["set-cookie"].lower()


def test_rejected_tokens_answer_401_without_echoing_them(accounts_on, keypair, client):
    private_pem, _ = keypair
    bad = _sign(private_pem, _claims(aud="other"))
    resp = _login(client, bad)
    assert resp.status_code == 401
    assert "bad_audience" in resp.json()["detail"]
    assert bad[:40] not in resp.text
    assert client.get("/api/me").status_code == 401
    assert "set-cookie" not in resp.headers


def test_the_login_endpoint_is_rate_limited_per_ip(accounts_on, keypair, client, monkeypatch):
    private_pem, _ = keypair
    monkeypatch.setattr(accounts_on, "LIMITER", accounts_on.RateLimiter(limit=2, window=60))
    bad = _sign(private_pem, _claims(aud="other"))
    assert _login(client, bad).status_code == 401
    assert _login(client, bad).status_code == 401
    assert _login(client, bad).status_code == 429
    # another client (Fly stamps the real address) has its own budget
    assert _login(client, bad, headers={"fly-client-ip": "203.0.113.9"}).status_code == 401
    limiter = accounts_on.RateLimiter(limit=1, window=10)
    assert limiter.allow("a", now=100.0) and not limiter.allow("a", now=105.0)
    assert limiter.allow("a", now=110.5)


def test_feature_off_when_the_client_id_is_unset(accounts_on, keypair, client, monkeypatch):
    private_pem, _ = keypair
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert client.get("/api/auth/config").json() == {"google_client_id": None}
    assert _login(client, _sign(private_pem, _claims())).status_code == 404
    assert client.get("/api/me").status_code == 401
    assert client.get("/healthz").json()["accounts"] == {"google_sign_in": False}
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "   ")
    assert client.get("/api/auth/config").json() == {"google_client_id": None}
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    assert client.get("/healthz").json()["accounts"] == {"google_sign_in": True}


# -------------------------------------------------------------- websocket
def _session_cookie(accounts_on, client, private_pem, **claims) -> str:
    resp = _login(client, _sign(private_pem, _claims(**claims)))
    assert resp.status_code == 200
    return resp.headers["set-cookie"].split(";")[0]


def test_a_cookie_carrying_socket_gets_the_account_and_its_first_name(accounts_on, keypair, client):
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "create_room"})           # no name typed
        room = _drain(a, "room")
        assert room["players"][0]["name"] == "Jerry"
        seat = srv.rooms[room["room"]].seats[0]
        assert seat.user_id == 1 and not seat.is_bot
        # A typed name still wins.
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as b:
            b.send_json({"type": "join_room", "room": room["room"], "name": "JY"})
            joined = _drain(b, "room")
            names = {p["seat"]: p["name"] for p in joined["players"]}
            assert names[1] == "JY"
            assert srv.rooms[room["room"]].seats[1].user_id == 1
        # Nothing about the account reaches the wire.
        assert "user_id" not in str(joined) and "jerry@example.com" not in str(joined)


def test_a_guest_socket_is_unchanged(accounts_on, client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as a:
        a.send_json({"type": "create_room"})
        room = _drain(a, "room")
        assert room["players"][0]["name"] == "Player"
        assert srv.rooms[room["room"]].seats[0].user_id is None
    # A stale or forged cookie is a guest too, not an error.
    with client.websocket_connect("/ws", headers={"cookie": "sj_session=" + "x" * 43}) as a:
        a.send_json({"type": "create_room", "name": "Guest"})
        room = _drain(a, "room")
        assert room["players"][0]["name"] == "Guest"
        assert srv.rooms[room["room"]].seats[0].user_id is None


def test_an_expired_session_is_a_guest(accounts_on, keypair, client):
    private_pem, _ = keypair
    store = accounts_on.STORE
    user = store.upsert_user(_claims())
    token = store.create_session(user["id"], now=time.time() - accounts_on.SESSION_SECONDS - 1)
    assert store.session_user(token) is None
    live = store.create_session(user["id"])
    assert store.session_user(live)["id"] == user["id"]
    assert store.count_sessions(user["id"]) == 1   # the expired row was purged


def test_first_name_default():
    from shengji.api.accounts import first_name

    assert first_name("Jerry Yu") == "Jerry"
    assert first_name("  Yu  ") == "Yu"
    assert first_name("") == "" and first_name(None) == ""
    assert len(first_name("x" * 40)) == 20
