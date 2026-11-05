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


def _clock(start=1_000_000.0):
    state = {"t": start}

    def now():
        return state["t"]

    def advance(seconds):
        state["t"] += seconds

    return now, advance


def test_unknown_kids_do_not_repeat_network_fetches(accounts_on, keypair):
    """Codex's review1155 reproducer: a warm cache plus three untrusted kids
    is at most ONE forced refresh, not one download per request."""
    private_pem, public_pem = keypair
    calls = []

    def fetch():
        calls.append(1)
        return ({KID: public_pem}, 3600.0)

    certs = accounts_on.GoogleCerts(fetch=fetch)
    certs.get()
    for i in range(3):
        with pytest.raises(accounts_on.AuthError):
            accounts_on.verify_google_id_token(
                _sign(private_pem, _claims(), kid=f"unknown-{i}"), CLIENT_ID, certs)
    # the warm-up download started the cooldown, so the three misses buy no download
    assert len(calls) <= 2 and len(calls) == 1


def test_key_rotation_still_works_after_the_cooldown(accounts_on, keypair, other_keypair):
    """A new Google key: the first unknown kid refreshes; a flood of unknown kids
    inside the cooldown does not; after the cooldown the rotated key is picked up."""
    from cryptography.hazmat.primitives import serialization

    private_pem, public_pem = keypair
    other_private = other_keypair
    other_public = serialization.load_pem_private_key(other_private.encode(), None).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now, advance = _clock()
    published = {KID: public_pem}
    calls = []

    def fetch():
        calls.append(1)
        return (dict(published), 3600.0)

    certs = accounts_on.GoogleCerts(fetch=fetch, clock=now)
    accounts_on.verify_google_id_token(_sign(private_pem, _claims()), CLIENT_ID, certs)
    assert len(calls) == 1
    for i in range(5):                        # scanning kids inside the cooldown
        with pytest.raises(accounts_on.AuthError):
            accounts_on.verify_google_id_token(_sign(private_pem, _claims(), kid=f"x{i}"), CLIENT_ID, certs)
    assert len(calls) == 1                    # the warm-up fetch set the cooldown; no extra download
    advance(accounts_on.GoogleCerts.REFRESH_COOLDOWN + 1)
    published["rotated"] = other_public       # Google rotates
    claims = accounts_on.verify_google_id_token(_sign(other_private, _claims(), kid="rotated"), CLIENT_ID, certs)
    assert claims["sub"] == "10987654321" and len(calls) == 2
    # the known key keeps verifying without any fetch
    accounts_on.verify_google_id_token(_sign(private_pem, _claims()), CLIENT_ID, certs)
    assert len(calls) == 2


def test_concurrent_unknown_kids_share_one_refresh_and_never_block_on_the_lock(accounts_on, keypair):
    import threading

    private_pem, public_pem = keypair
    now, advance = _clock()
    calls = []
    gate = threading.Event()

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)                      # the forced refresh is SLOW
        return ({KID: public_pem}, 3600.0)

    certs = accounts_on.GoogleCerts(fetch=fetch, clock=now)
    certs.get()
    advance(accounts_on.GoogleCerts.REFRESH_COOLDOWN + 1)
    results, errors = [], []

    def attempt(i):
        try:
            accounts_on.verify_google_id_token(_sign(private_pem, _claims(), kid=f"u{i}"), CLIENT_ID, certs)
        except accounts_on.AuthError as exc:
            errors.append(exc.reason)
        results.append(i)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    # While one thread sits in the slow fetch, everyone else is served from the cache.
    deadline = time.time() + 3
    while len(results) < 7 and time.time() < deadline:
        time.sleep(0.01)
    assert len(results) == 7
    assert accounts_on.verify_google_id_token(_sign(private_pem, _claims()), CLIENT_ID, certs)["sub"]
    gate.set()
    for t in threads:
        t.join(5)
    assert len(results) == 8 and len(calls) == 2
    assert set(errors) == {"bad_signature"}   # unknown kids: refused, never a 5xx


def test_failed_refreshes_back_off_and_keep_the_last_good_set(accounts_on, keypair):
    _, public_pem = keypair
    now, advance = _clock()
    state = {"fail": False, "calls": 0}

    def fetch():
        state["calls"] += 1
        if state["fail"]:
            raise OSError("google unreachable")
        return ({KID: public_pem}, 60.0)

    G = accounts_on.GoogleCerts
    certs = G(fetch=fetch, clock=now)
    assert certs.get() == {KID: public_pem}
    certs.get()
    assert state["calls"] == 1
    advance(61)                               # max-age passed: a plain get refreshes
    state["fail"] = True
    assert certs.get() == {KID: public_pem}   # stale set beats no set
    assert state["calls"] == 2
    certs.get(force=True); certs.get(force=True)
    assert state["calls"] == 2                # inside the failure backoff: no attempt
    advance(G.FAIL_BACKOFF + 1)
    certs.get(force=True)
    assert state["calls"] == 3                # one attempt, fails, backoff doubles
    advance(G.FAIL_BACKOFF + 1)
    certs.get(force=True)
    assert state["calls"] == 3
    advance(G.FAIL_BACKOFF + 1)
    certs.get(force=True)
    assert state["calls"] == 4
    state["fail"] = False
    advance(4 * G.FAIL_BACKOFF + 1)
    assert certs.get(force=True) == {KID: public_pem} and state["calls"] == 5
    assert certs._fail_backoff == G.FAIL_BACKOFF   # success resets the backoff
    # cold start with Google down: an error, bounded by the same backoff
    cold = G(fetch=fetch, clock=now)
    state["fail"] = True
    with pytest.raises(accounts_on.AuthError) as info:
        cold.get()
    assert info.value.reason == "certs_unavailable"
    with pytest.raises(accounts_on.AuthError):
        cold.get()
    assert state["calls"] == 6                # the second cold call did not hit the network


def test_cold_start_under_contention_waits_for_the_one_fetch(accounts_on, keypair):
    import threading

    _, public_pem = keypair
    calls = []
    gate = threading.Event()

    def fetch():
        calls.append(1)
        gate.wait(5)
        return ({KID: public_pem}, 3600.0)

    certs = accounts_on.GoogleCerts(fetch=fetch)
    got = []
    threads = [threading.Thread(target=lambda: got.append(certs.get())) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1 and len(got) == 4 and all(g == {KID: public_pem} for g in got)


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
                           "picture": "https://img.example/jy.png",
                           "display_name": None, "name_shown": "Jerry"}
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
    assert accounts_on.STORE.schema_version() == len(accounts_on.SCHEMA)

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


# ------------------------------------------- auth transitions and the socket
def test_page_open_then_login_then_create_room_binds_the_account(accounts_on, keypair, client):
    """Codex's review1155 flow: the lobby socket is open BEFORE sign-in. The
    client reconnects after a successful login (ws.ts), so the create_room
    travels on a cookie-carrying socket and the seat gets the account."""
    from shengji.api import server as srv

    private_pem, _ = keypair
    with client.websocket_connect("/ws") as guest:        # page open, no account
        cookie = _session_cookie(accounts_on, client, private_pem)
        # the stale socket keeps its handshake identity until it is replaced
        guest.send_json({"type": "peek_room", "room": "NONE"})
        assert _drain(guest, "error")["code"] == "room_not_found"
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:   # the reconnect
        a.send_json({"type": "create_room", "name": "Jerry"})
        room = _drain(a, "room")
        assert srv.rooms[room["room"]].seats[0].user_id == 1
        # and a join from another freshly signed-in device
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as b:
            b.send_json({"type": "join_room", "room": room["room"], "name": "Phone"})
            _drain(b, "room")
            assert srv.rooms[room["room"]].seats[1].user_id == 1


def test_sign_in_switch_and_sign_out_mid_game_keep_the_seat_and_follow_the_socket(
        accounts_on, keypair, client):
    from shengji.api import server as srv
    from tests.test_server_ws import _room_with_bots

    private_pem, _ = keypair
    with client.websocket_connect("/ws") as guest:
        code = _room_with_bots(guest)
        # the resume token the client saved from its first frame (ws.ts)
        token = srv.rooms[code].seats[0].token
        guest.send_json({"type": "start_game"})
        _drain(guest, "state", tries=60)
        seat = srv.rooms[code].seats[0]
        assert seat.user_id is None

    # Sign in: the client reconnects and resumes the saved room with its token.
    cookie = _session_cookie(accounts_on, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "join_room", "room": code, "name": "Jerry", "token": token})
        st = _drain(a, "state", tries=60)
        assert st["you"] == 0 and srv.rooms[code].seats[0] is seat
        assert seat.user_id == 1 and seat.connected

    # Switch accounts: a different Google sub, same seat, new identity.
    cookie2 = _session_cookie(accounts_on, client, private_pem, sub="222", email="other@example.com")
    with client.websocket_connect("/ws", headers={"cookie": cookie2}) as b:
        b.send_json({"type": "join_room", "room": code, "name": "Jerry", "token": token})
        assert _drain(b, "state", tries=60)["you"] == 0
        assert seat.user_id == 2 and srv.rooms[code].seats[0] is seat

    # Sign out: the reconnect carries no cookie; the seat stays, the account clears.
    with client.websocket_connect("/ws") as c:
        c.send_json({"type": "join_room", "room": code, "name": "Jerry", "token": token})
        assert _drain(c, "state", tries=60)["you"] == 0
        assert seat.user_id is None and srv.rooms[code].seats[0] is seat
        assert len(srv.rooms[code].seats) == 4


# ----------------------------------------------------------- display name
V1_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT,
    name TEXT,
    picture TEXT,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER NOT NULL
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX sessions_expires ON sessions(expires_at);
INSERT INTO schema_version(version) VALUES (1);
INSERT INTO users(google_sub, email, name, picture, created_at, last_login_at)
    VALUES ('sub-v1', 'old@example.com', 'Old Timer', NULL, 1, 1);
"""


def _columns(path, table):
    with accounts_sqlite(path) as db:
        return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


def accounts_sqlite(path):
    import sqlite3
    from contextlib import closing

    return closing(sqlite3.connect(path))


def test_a_v1_database_upgrades_to_v2_once_and_keeps_its_rows(accounts_on, tmp_path):
    """The version-1 layout is written by hand here (the first entry of
    ``SCHEMA`` is that layout, so the two must agree) and then opened by the
    current store, which must add the column, keep the row, and leave a
    second open with nothing to do."""
    path = tmp_path / "old" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    assert "display_name" not in _columns(path, "users")
    # The hand-written v1 matches SCHEMA[0]: a fresh store built from SCHEMA[0]
    # alone has the same user columns.
    fresh = tmp_path / "fresh.sqlite3"
    with accounts_sqlite(fresh) as db:
        for statement in filter(None, (s.strip() for s in accounts_on.SCHEMA[0].split(";"))):
            db.execute(statement)
    assert _columns(fresh, "users") == _columns(path, "users")

    store = accounts_on.Store(path)
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert "display_name" in _columns(path, "users")
    row = store.user(1)
    assert row["name"] == "Old Timer" and row["display_name"] is None
    assert accounts_on.effective_name(row) == "Old"
    # Re-opening (a new Store on the same file) is a no-op, and the migration
    # step itself tolerates a re-run on an already-migrated table.
    again = accounts_on.Store(path)
    assert again.schema_version() == len(accounts_on.SCHEMA)
    with accounts_sqlite(path) as db:
        db.row_factory = accounts_on.sqlite3.Row
        accounts_on._migrate_v2(db)
    assert _columns(path, "users").count("display_name") == 1
    # A brand-new database lands at the current version directly.
    assert accounts_on.STORE.schema_version() == len(accounts_on.SCHEMA)
    assert "display_name" in _columns(accounts_on.STORE.path, "users")


@pytest.mark.parametrize("raw, stored", [
    ("Jerry", "Jerry"),
    ("  Jerry   Yu  ", "Jerry Yu"),
    ("小明", "小明"),
    ("José Ñandú", "José Ñandú"),
    ("a　b", "a b"),                 # ideographic space collapses too
    ("x" * 20, "x" * 20),
    ("Robot", "Robot"),                   # only a whole-word bot is reserved
    ("Botany", "Botany"),
    ("Bot 1 fan", "Bot 1 fan"),
])
def test_display_names_are_normalised_and_accepted(accounts_on, raw, stored):
    assert accounts_on.validate_display_name(raw) == stored


@pytest.mark.parametrize("raw, reason", [
    ("", "empty"),
    ("   ", "empty"),
    ("　", "empty"),
    ("x" * 21, "too_long"),
    ("  " + "y" * 21 + "  ", "too_long"),
    ("a\nb", "control_chars"),
    ("a\rb", "control_chars"),
    ("tab\there", "control_chars"),
    ("nul\x00", "control_chars"),
    ("esc\x1b[31m", "control_chars"),
    (" line", "control_chars"),
    ("bot", "reserved"),
    ("BOT", "reserved"),
    ("Bot 1", "reserved"),
    ("bot3", "reserved"),
    ("  Bot   2  ", "reserved"),
    ("System", "reserved"),
    ("ADMIN", "reserved"),
    ("dealer", "reserved"),
    (None, "not_a_string"),
    (42, "not_a_string"),
])
def test_bad_display_names_are_refused_with_a_reason(accounts_on, raw, reason):
    with pytest.raises(accounts_on.DisplayNameError) as info:
        accounts_on.validate_display_name(raw)
    assert info.value.reason == reason


def test_the_blocklist_hook_refuses_with_not_allowed(accounts_on, monkeypatch):
    monkeypatch.setattr(accounts_on, "DISPLAY_NAME_BLOCKLIST", lambda name: "rude" in name.lower())
    assert accounts_on.validate_display_name("Polite") == "Polite"
    with pytest.raises(accounts_on.DisplayNameError) as info:
        accounts_on.validate_display_name("Rude One")
    assert info.value.reason == "not_allowed"


def test_patch_me_sets_clears_and_refuses_display_names(accounts_on, keypair, client):
    private_pem, _ = keypair
    # Unauthenticated: 401, and nothing stored.
    assert client.patch("/api/me", json={"display_name": "Nobody"}).status_code == 401
    cookie = _session_cookie(accounts_on, client, private_pem)
    session = {"cookie": cookie}

    resp = client.patch("/api/me", json={"display_name": "  Captain   Yu "}, headers=session)
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Captain Yu" and body["name_shown"] == "Captain Yu"
    assert body["name"] == "Jerry Yu"               # the Google profile is untouched
    me = client.get("/api/me", headers=session).json()
    assert me["display_name"] == "Captain Yu" and me["name_shown"] == "Captain Yu"
    assert accounts_on.STORE.user(1)["display_name"] == "Captain Yu"

    for bad, reason in [("x" * 21, "too_long"), ("", "empty"), ("a\nb", "control_chars"),
                        ("Bot 2", "reserved"), ("system", "reserved")]:
        resp = client.patch("/api/me", json={"display_name": bad}, headers=session)
        assert resp.status_code == 400, bad
        assert resp.json()["detail"] == reason
    # A refusal leaves the stored name alone.
    assert client.get("/api/me", headers=session).json()["name_shown"] == "Captain Yu"
    # A non-string body is a validation error, not a server error.
    assert client.patch("/api/me", json={"display_name": 7}, headers=session).status_code == 422

    # null clears it: back to the Google first name.
    resp = client.patch("/api/me", json={"display_name": None}, headers=session)
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None and resp.json()["name_shown"] == "Jerry"
    # A later login refreshes the profile but never touches the chosen name.
    client.patch("/api/me", json={"display_name": "Cap"}, headers=session)
    accounts_on.LIMITER.reset()    # the edits above spent the shared per-IP budget
    assert _login(client, _sign(private_pem, _claims(name="Jerome Yu"))).status_code == 200
    assert client.get("/api/me", headers=session).json() == {
        "name": "Jerome Yu", "email": "jerry@example.com", "picture": "https://img.example/jy.png",
        "display_name": "Cap", "name_shown": "Cap"}


def test_patch_me_is_rate_limited_per_ip(accounts_on, keypair, client, monkeypatch):
    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    session = {"cookie": cookie}
    monkeypatch.setattr(accounts_on, "LIMITER", accounts_on.RateLimiter(limit=2, window=60))
    assert client.patch("/api/me", json={"display_name": "A"}, headers=session).status_code == 200
    assert client.patch("/api/me", json={"display_name": "B"}, headers=session).status_code == 200
    assert client.patch("/api/me", json={"display_name": "C"}, headers=session).status_code == 429
    assert accounts_on.STORE.user(1)["display_name"] == "B"


def test_a_chosen_display_name_is_the_room_default_but_a_typed_name_wins(accounts_on, keypair, client):
    from shengji.api import server as srv

    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    assert client.patch("/api/me", json={"display_name": "Captain"},
                        headers={"cookie": cookie}).status_code == 200
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "create_room"})           # no name typed
        room = _drain(a, "room")
        assert room["players"][0]["name"] == "Captain"
        assert srv.rooms[room["room"]].seats[0].user_id == 1
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as b:
            b.send_json({"type": "join_room", "room": room["room"], "name": "JY"})
            joined = _drain(b, "room")
            names = {p["seat"]: p["name"] for p in joined["players"]}
            assert names[1] == "JY"
        with client.websocket_connect("/ws", headers={"cookie": cookie}) as c:
            c.send_json({"type": "join_room", "room": room["room"], "name": ""})
            joined = _drain(c, "room")
            names = {p["seat"]: p["name"] for p in joined["players"]}
            assert names[2] == "Captain"


# ------------------------------------------------------------ saved games
def _v2_database(path):
    """The version-2 layout: version 1 plus the display-name column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT NULL")
        db.execute("UPDATE schema_version SET version = 2")
        db.execute("UPDATE users SET display_name = 'Oldie'")
        db.commit()


def _tables(path):
    with accounts_sqlite(path) as db:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_a_v2_database_upgrades_to_v3_once_and_keeps_its_rows(accounts_on, tmp_path):
    path = tmp_path / "v2" / "accounts.sqlite3"
    _v2_database(path)
    with accounts_sqlite(path) as db:
        db.execute("""INSERT INTO users(google_sub, email, name, picture, created_at,
                                        last_login_at, display_name)
                      VALUES ('sub-v2b', 'b@example.com', 'Second', NULL, 2, 2, NULL)""")
        db.execute("INSERT INTO sessions VALUES ('hash-1', 1, 1, 9999999999)")
        db.execute("INSERT INTO sessions VALUES ('hash-2', 2, 1, 9999999999)")
        db.commit()
    assert "games" not in _tables(path)
    store = accounts_on.Store(path)
    assert store.schema_version() == 3 == len(accounts_on.SCHEMA)
    assert {"games", "game_players", "game_players_user", "games_started",
            "sessions_user", "sessions_expires"} <= _tables(path)
    assert "users_v2" not in _tables(path) and "sessions_v3" not in _tables(path)
    row = store.user(1)
    assert row["name"] == "Old Timer" and row["display_name"] == "Oldie"
    assert store.user(2)["google_sub"] == "sub-v2b"
    with accounts_sqlite(path) as db:
        users_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()[0]
        sessions_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sessions'").fetchone()[0]
        assert "AUTOINCREMENT" in users_sql.upper()
        assert "REFERENCES users(id) ON DELETE CASCADE" in sessions_sql
        assert sorted(db.execute("SELECT token_hash, user_id FROM sessions")) == [
            ("hash-1", 1), ("hash-2", 2)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _columns(path, "users") == [
        "id", "google_sub", "email", "name", "picture", "created_at", "last_login_at",
        "display_name"]
    # The sessions still follow their users, and the highest id is never
    # handed out again after its account is deleted.
    store.link_seat(_game(), 2, 0, 1)
    assert store.delete_user(2) is True
    with accounts_sqlite(path) as db:
        assert db.execute("SELECT user_id FROM sessions").fetchall() == [(1,)]
        assert db.execute("SELECT COUNT(*) FROM game_players").fetchone()[0] == 0
    newcomer = store.upsert_user(_claims(sub="after-upgrade"))
    assert newcomer["id"] == 3
    # The step re-runs harmlessly and a new Store does nothing.
    with accounts_sqlite(path) as db:
        db.row_factory = accounts_on.sqlite3.Row
        accounts_on._migrate_v3(db)
        db.commit()
    again = accounts_on.Store(path)
    assert again.schema_version() == 3
    assert again.user(1)["display_name"] == "Oldie"
    with accounts_sqlite(path) as db:
        assert db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    assert _columns(path, "game_players") == [
        "game_id", "user_id", "seat", "from_round", "to_round", "hidden"]


def test_account_ids_are_never_reused_after_a_delete(accounts_on):
    """A live seat or socket can still hold a deleted account's id; a later
    signup must not receive it, and a link write for it must be refused."""
    store = accounts_on.STORE
    a, b = _two_users(store)
    assert b > a
    assert store.delete_user(b) is True
    stranger = store.upsert_user(_claims(sub="stranger"))["id"]
    assert stranger not in (a, b) and stranger > b
    assert store.link_seat(_game("after"), b, 0, 1) is False
    assert store.list_games(stranger) == []
    with accounts_sqlite(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def _game(game_id="g1", started_at=None, **over):
    header = {"id": game_id, "room_code": "ABCD", "log_file": "ABCD.jsonl",
              "log_offset": 0, "started_at": int(started_at or time.time()),
              "last_round": 1, "incomplete": False}
    header.update(over)
    return header


def _two_users(store):
    a = store.upsert_user(_claims(sub="a", email="a@example.com"))
    b = store.upsert_user(_claims(sub="b", email="b@example.com"))
    return a["id"], b["id"]


def test_saved_game_links_open_close_and_list_per_account(accounts_on):
    store = accounts_on.STORE
    a, b = _two_users(store)
    assert store.list_games(a) == []
    assert store.link_seat(_game(), a, 0, 1) is True
    # The games row is created once; a second link reuses it.
    assert store.link_seat(_game(last_round=7), b, 2, 3) is True
    store.record_round_start("g1", 2)
    store.record_round_end("g1", 2, ["4", "2"], [0, 0], now=1234)
    [game] = store.list_games(a)
    assert game["id"] == "g1" and game["last_round"] == 2 and game["ended_at"] == 1234
    assert game["final_levels"] == ["4", "2"] and game["games_won"] == [0, 0]
    assert game["incomplete"] is False
    assert game["links"] == [{"seat": 0, "from_round": 1, "to_round": None}]
    assert store.user_game(b, "g1")["links"] == [{"seat": 2, "from_round": 3, "to_round": None}]
    # Closing a link ends its interval; a new seat opens its own row.
    assert store.close_link("g1", a, 0, 2) == 1
    assert store.close_link("g1", a, 0, 2) == 0
    store.link_seat(_game(), a, 1, 3)
    assert store.user_game(a, "g1")["links"] == [
        {"seat": 0, "from_round": 1, "to_round": 2},
        {"seat": 1, "from_round": 3, "to_round": None}]
    # Re-opening the same seat at the same round re-opens the row.
    store.close_link("g1", a, 1, 3)
    store.link_seat(_game(), a, 1, 3)
    assert store.user_game(a, "g1")["links"][-1]["to_round"] is None
    store.mark_incomplete("g1")
    assert store.user_game(a, "g1")["incomplete"] is True
    # Unknown game, unknown account: nothing.
    assert store.user_game(a, "nope") is None
    c = store.upsert_user(_claims(sub="c"))["id"]
    assert store.user_game(c, "g1") is None


def test_a_deleted_account_links_nothing(accounts_on):
    store = accounts_on.STORE
    assert store.link_seat(_game(), 99, 0, 1) is False
    with accounts_sqlite(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def test_list_is_newest_first_paged_capped_and_retained(accounts_on):
    store = accounts_on.STORE
    a, _b = _two_users(store)
    now = int(time.time())
    for i in range(accounts_on.GAMES_LIST_CAP + 5):
        store.link_seat(_game(f"g{i:03d}", started_at=now - 1000 + i), a, 0, 1)
    store.link_seat(_game("old", started_at=now - accounts_on.GAMES_RETENTION_SECONDS - 5),
                    a, 0, 1)
    first = store.list_games(a, limit=50)
    assert [g["id"] for g in first][:2] == ["g104", "g103"] and len(first) == 50
    cursor = accounts_on.Store.parse_game_cursor
    second = store.list_games(a, before=cursor(store.game_cursor(first[-1])), limit=50)
    assert second[0]["id"] == "g054" and len(second) == 50
    third = store.list_games(a, before=cursor(store.game_cursor(second[-1])), limit=50)
    # 100 games are ever listed; the five oldest (and the expired one) are not.
    assert [g["id"] for g in third] == []
    assert store.user_game(a, "g000") is not None          # still readable by id
    assert store.user_game(a, "old") is None               # past retention
    assert store.purge_games() == 1
    with accounts_sqlite(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM games WHERE id = 'old'").fetchone()[0] == 0


def test_list_pages_through_games_that_share_a_start_second(accounts_on):
    store = accounts_on.STORE
    a, _b = _two_users(store)
    now = int(time.time())
    ids = [f"t{i}" for i in range(5)]
    for game_id in ids:
        store.link_seat(_game(game_id, started_at=now - 10), a, 0, 1)
    store.link_seat(_game("older", started_at=now - 20), a, 0, 1)
    seen, before = [], None
    while True:
        page = store.list_games(a, before=before, limit=2)
        if not page:
            break
        seen += [g["id"] for g in page]
        before = accounts_on.Store.parse_game_cursor(store.game_cursor(page[-1]))
    assert seen == ["t4", "t3", "t2", "t1", "t0", "older"]
    # A bare integer cursor still means "started before that second".
    assert [g["id"] for g in store.list_games(a, before=(now - 10, ""))] == ["older"]


@pytest.mark.parametrize("raw", ["", "x", "12:", "-1:a", "1:a b", "1:" + "a" * 65, "1" * 13])
def test_bad_game_cursors_are_refused(accounts_on, raw):
    with pytest.raises(ValueError):
        accounts_on.Store.parse_game_cursor(raw)


def test_hide_and_account_delete(accounts_on):
    store = accounts_on.STORE
    a, b = _two_users(store)
    store.link_seat(_game("shared"), a, 0, 1)
    store.link_seat(_game("shared"), b, 1, 1)
    store.link_seat(_game("mine"), a, 0, 1)
    token = store.create_session(a)
    assert store.hide_game(a, "shared") == 1
    assert store.hide_game(a, "shared") == 0
    assert [g["id"] for g in store.list_games(a)] == ["mine"]
    assert store.user_game(a, "shared") is None
    assert store.user_game(b, "shared") is not None       # hiding is per account
    assert store.delete_user(a) is True
    assert store.session_user(token) is None
    assert store.user(a) is None
    with accounts_sqlite(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM game_players WHERE user_id = ?",
                          (a,)).fetchone()[0] == 0
        games = {r[0] for r in db.execute("SELECT id FROM games")}
    assert games == {"shared"}                             # b still links it
    assert store.delete_user(a) is False
