"""App Store purchases (``shengji.api.purchases``): StoreKit 2 signed
transactions and Server Notifications V2 in Apple's real JWS format, signed
by a throwaway certificate chain built here that mirrors Apple's (a root, an
intermediate with Apple's intermediate marker, a leaf with the App Store
signing marker). No real key is used anywhere."""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

from tests.test_accounts import (  # noqa: F401
    V1_SCHEMA, _claims, _session_cookie, accounts_on, accounts_sqlite, keypair)
from tests.test_ratings import _rounds_at
from tests.test_server_ws import _drain, client  # noqa: F401

GOAT = "com.jerryyu.shengji.companion.goat"
PANDA = "com.jerryyu.shengji.companion.panda"


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, key, issuer_key, *, ca: bool, marker: str | None,
          start=None, days=3650):
    start = start or datetime.now(timezone.utc) - timedelta(days=1)
    b = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer))
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(start).not_valid_after(start + timedelta(days=days))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if marker:
        b = b.add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier(marker), b"\x05\x00"),
                            critical=False)
    return b.sign(issuer_key, hashes.SHA384() if ca else hashes.SHA256())


class Chain:
    """A root, an Apple-style intermediate and leaf, and a JWS signer."""

    def __init__(self, leaf_marker="1.2.840.113635.100.6.11.1",
                 inter_marker="1.2.840.113635.100.6.2.1", leaf_days=3650, leaf_start=None):
        self.root_key = ec.generate_private_key(ec.SECP384R1())
        self.inter_key = ec.generate_private_key(ec.SECP384R1())
        self.leaf_key = ec.generate_private_key(ec.SECP256R1())
        self.root = _cert("Test Root", "Test Root", self.root_key, self.root_key, ca=True, marker=None)
        self.inter = _cert("Test WWDR", "Test Root", self.inter_key, self.root_key, ca=True,
                           marker=inter_marker)
        self.leaf = _cert("Test StoreKit", "Test WWDR", self.leaf_key, self.inter_key, ca=False,
                          marker=leaf_marker, start=leaf_start, days=leaf_days)

    def der(self, cert) -> bytes:
        return cert.public_bytes(serialization.Encoding.DER)

    def sign(self, payload: dict, key=None, chain=None) -> str:
        chain = chain or [self.leaf, self.inter, self.root]
        header = {"alg": "ES256", "x5c": [base64.b64encode(self.der(c)).decode() for c in chain]}
        enc = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
        signing = f"{enc(json.dumps(header).encode())}.{enc(json.dumps(payload).encode())}"
        r, s = decode_dss_signature((key or self.leaf_key).sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
        return f"{signing}.{enc(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def _txn(**over) -> dict:
    now = int(time.time() * 1000)
    base = {"transactionId": "2000000111", "originalTransactionId": "2000000111",
            "bundleId": "com.jerryyu.shengji", "productId": GOAT, "purchaseDate": now - 5000,
            "originalPurchaseDate": now - 5000, "quantity": 1, "type": "Non-Consumable",
            "inAppOwnershipType": "PURCHASED", "signedDate": now, "environment": "Sandbox",
            "transactionReason": "PURCHASE", "storefront": "USA", "storefrontId": "143441",
            "price": 3990, "currency": "USD"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _notification(chain: Chain, kind: str, txn: dict, **data) -> dict:
    body = {"bundleId": "com.jerryyu.shengji", "environment": txn.get("environment", "Sandbox"),
            "signedTransactionInfo": chain.sign(txn)}
    body.update(data)
    return {"signedPayload": chain.sign({
        "notificationType": kind, "notificationUUID": "7f0c6a1e-0000-4000-8000-000000000001",
        "data": body, "version": "2.0", "signedDate": int(time.time() * 1000)})}


@pytest.fixture
def chain(monkeypatch):
    from shengji.api import purchases

    c = Chain()
    monkeypatch.setattr(purchases, "APPLE_ROOTS", (c.der(c.root),))
    return c


@pytest.fixture
def shop(accounts_on, keypair, client, monkeypatch, chain):
    """Account 1 signed in, with the Collection and the store on for it."""
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1")
    monkeypatch.setenv("STORE_ENABLED", "1")
    private_pem, _ = keypair
    return {"cookie": _session_cookie(accounts_on, client, private_pem)}


# ------------------------------------------------------------ the JWS checks
def test_the_pinned_root_is_apple_root_ca_g3():
    from shengji.api import purchases

    root = x509.load_der_x509_certificate(purchases.APPLE_ROOTS[0])
    assert root.fingerprint(hashes.SHA256()).hex() == (
        "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179")
    assert root.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "Apple Root CA - G3"


def test_a_well_formed_transaction_verifies(chain):
    from shengji.api import purchases

    payload = purchases.verify_jws(chain.sign(_txn()))
    txn = purchases.transaction(payload)
    assert txn["product_id"] == GOAT and txn["original_transaction_id"] == "2000000111"
    assert txn["environment"] == "Sandbox" and txn["storefront"] == "USA"
    assert txn["revoked_at"] is None


@pytest.mark.parametrize("break_it", [
    "other_root", "tampered_payload", "other_key", "short_chain", "alg_none", "no_leaf_marker",
    "no_inter_marker", "expired_leaf", "garbage", "swapped_chain",
])
def test_a_bad_signature_or_chain_is_refused(chain, break_it):
    from shengji.api import purchases

    if break_it == "other_root":
        token = Chain().sign(_txn())
    elif break_it == "tampered_payload":
        head, _, sig = chain.sign(_txn()).split(".")
        forged = base64.urlsafe_b64encode(json.dumps(_txn(productId=PANDA)).encode()).rstrip(b"=").decode()
        token = f"{head}.{forged}.{sig}"
    elif break_it == "other_key":
        token = chain.sign(_txn(), key=ec.generate_private_key(ec.SECP256R1()))
    elif break_it == "short_chain":
        token = chain.sign(_txn(), chain=[chain.leaf, chain.root])
    elif break_it == "alg_none":
        head, payload, sig = chain.sign(_txn()).split(".")
        header = json.loads(base64.urlsafe_b64decode(head + "=="))
        header["alg"] = "none"
        token = ".".join([base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode(),
                          payload, sig])
    elif break_it == "no_leaf_marker":
        c = Chain(leaf_marker=None)
        with pytest.raises(purchases.VerificationError):
            purchases.verify_jws(c.sign(_txn()), roots=(c.der(c.root),))
        return
    elif break_it == "no_inter_marker":
        c = Chain(inter_marker=None)
        with pytest.raises(purchases.VerificationError):
            purchases.verify_jws(c.sign(_txn()), roots=(c.der(c.root),))
        return
    elif break_it == "expired_leaf":
        c = Chain(leaf_start=datetime.now(timezone.utc) - timedelta(days=30), leaf_days=10)
        with pytest.raises(purchases.VerificationError):
            purchases.verify_jws(c.sign(_txn()), roots=(c.der(c.root),))
        return
    elif break_it == "swapped_chain":
        token = chain.sign(_txn(), chain=[chain.inter, chain.leaf, chain.root])
    else:
        token = "not.a.jws"
    with pytest.raises(purchases.VerificationError) as exc:
        purchases.verify_jws(token)
    assert exc.value.code == "bad_signature"


@pytest.mark.parametrize("over, code", [
    ({"bundleId": "com.example.other"}, "wrong_app"),
    ({"environment": "Xcode"}, "wrong_environment"),
    ({"productId": "com.jerryyu.shengji.coins"}, "unknown_product"),
    ({"type": "Consumable"}, "unknown_product"),
    ({"originalTransactionId": None}, "bad_transaction"),
])
def test_a_verified_transaction_of_another_app_or_product_is_refused(chain, over, code):
    from shengji.api import purchases

    with pytest.raises(purchases.VerificationError) as exc:
        purchases.transaction(purchases.verify_jws(chain.sign(_txn(**over))))
    assert exc.value.code == code


def test_production_only_refuses_sandbox(chain, monkeypatch):
    from shengji.api import purchases

    monkeypatch.setenv("STORE_ENVIRONMENTS", "Production")
    with pytest.raises(purchases.VerificationError):
        purchases.transaction(purchases.verify_jws(chain.sign(_txn())))
    assert purchases.transaction(purchases.verify_jws(chain.sign(_txn(environment="Production"))))


# ------------------------------------------------------------ /api/store/verify
def test_a_purchase_unlocks_the_goat_and_shows_in_me(accounts_on, client, shop, chain):
    me = client.get("/api/me", headers=shop).json()
    assert me["features"] == {"collection": True, "store": True}
    assert me["products"] == []
    goat = {e["id"]: e for e in me["looks"] if e["id"].startswith("goat/")}
    assert len(goat) == 4 and not any(e["unlocked"] for e in goat.values())
    assert {e["product"] for e in goat.values()} == {GOAT}
    assert client.put("/api/me/look", json={"look": "goat/jade"}, headers=shop).status_code == 403

    resp = client.post("/api/store/verify", json={"jws": chain.sign(_txn()), "storefront": "USA"},
                       headers=shop)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["products"] == [GOAT]
    assert all(e["unlocked"] for e in body["looks"] if e["id"].startswith("goat/"))
    assert not any(e["unlocked"] for e in body["looks"] if e["id"].startswith("panda/"))
    resp = client.put("/api/me/look", json={"look": "goat/jade"}, headers=shop)
    assert resp.status_code == 200 and resp.json()["look"] == "goat/jade"
    assert accounts_on.account_look(1) == "goat/jade"
    with accounts_on.STORE._open() as conn:
        row = dict(conn.execute("SELECT * FROM entitlements").fetchone())
    assert (row["user_id"], row["product_id"], row["environment"], row["storefront"]) == (
        1, GOAT, "Sandbox", "USA")
    assert row["revoked_at"] is None and row["purchased_at"] > 0


def test_the_same_purchase_twice_is_one_entitlement(accounts_on, client, shop, chain):
    token = chain.sign(_txn())
    assert client.post("/api/store/verify", json={"jws": token}, headers=shop).status_code == 200
    # a replay, and a later signing of the same purchase (a restore)
    assert client.post("/api/store/verify", json={"jws": token}, headers=shop).status_code == 200
    again = chain.sign(_txn(transactionId="2000000999", transactionReason="PURCHASE"))
    assert client.post("/api/store/verify", json={"jws": again}, headers=shop).status_code == 200
    with accounts_on.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0] == 1


def test_a_purchase_held_by_another_account_is_refused(accounts_on, client, shop, chain, keypair, monkeypatch):
    token = chain.sign(_txn())
    assert client.post("/api/store/verify", json={"jws": token}, headers=shop).status_code == 200
    private_pem, _ = keypair
    client.cookies.clear()
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="222", email="b@example.com")}
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1,2")
    resp = client.post("/api/store/verify", json={"jws": token}, headers=other)
    assert resp.status_code == 409 and resp.json()["detail"] == "held_by_other"
    assert client.get("/api/me", headers=other).json()["products"] == []


def test_verify_refuses_guests_the_store_off_and_bad_input(accounts_on, client, shop, chain, monkeypatch):
    token = chain.sign(_txn())
    client.cookies.clear()
    assert client.post("/api/store/verify", json={"jws": token}).status_code == 401
    monkeypatch.setenv("STORE_ENABLED", "0")
    assert client.post("/api/store/verify", json={"jws": token}, headers=shop).status_code == 404
    assert client.get("/api/me", headers=shop).json()["features"]["store"] is False
    monkeypatch.setenv("STORE_ENABLED", "1")
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "")
    assert client.post("/api/store/verify", json={"jws": token}, headers=shop).status_code == 404
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1")
    for bad, code in ((Chain().sign(_txn()), "bad_signature"),
                      (chain.sign(_txn(bundleId="com.other")), "wrong_app"),
                      ("x" * 10, "bad_signature")):
        resp = client.post("/api/store/verify", json={"jws": bad}, headers=shop)
        assert resp.status_code == 400 and resp.json()["detail"] == code
    with accounts_on.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0] == 0


def test_the_china_storefront_buys_nothing(accounts_on, client, shop, chain):
    said = client.post("/api/store/verify", json={"jws": chain.sign(_txn()), "storefront": "CHN"},
                       headers=shop)
    assert said.status_code == 403
    signed = client.post("/api/store/verify", json={"jws": chain.sign(_txn(storefront="CHN"))},
                         headers=shop)
    assert signed.status_code == 403
    with accounts_on.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0] == 0


def test_a_guest_and_a_store_off_account_see_no_sold_companion(accounts_on, client, shop, monkeypatch):
    monkeypatch.setenv("STORE_ENABLED", "0")
    looks = client.get("/api/me", headers=shop).json()["looks"]
    assert not any(e["id"].startswith(("goat/", "panda/")) for e in looks)
    assert accounts_on.store_for(None) is False


# ------------------------------------------------------------ /api/store/notify
def test_a_refund_revokes_and_unequips(accounts_on, client, shop, chain):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    assert client.put("/api/me/look", json={"look": "goat/ink"}, headers=shop).status_code == 200
    refunded = _txn(revocationDate=int(time.time() * 1000), revocationReason=0)
    resp = client.post("/api/store/notify", json=_notification(chain, "REFUND", refunded))
    assert resp.status_code == 200
    me = client.get("/api/me", headers=shop).json()
    assert me["products"] == [] and me["look"] == "tractor/red"
    assert accounts_on.account_look(1) == "tractor/red"
    assert client.put("/api/me/look", json={"look": "goat/ink"}, headers=shop).status_code == 403
    # the old, unrevoked JWS cannot buy it back
    resp = client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop)
    assert resp.status_code == 409 and resp.json()["detail"] == "revoked"
    # a second delivery of the same notification changes nothing
    assert client.post("/api/store/notify", json=_notification(chain, "REFUND", refunded)).status_code == 200
    # a reversed refund gives it back
    assert client.post("/api/store/notify", json=_notification(chain, "REFUND_REVERSED", _txn())).status_code == 200
    assert client.get("/api/me", headers=shop).json()["products"] == [GOAT]


def test_a_revoke_applies_even_with_the_store_off(accounts_on, client, shop, chain, monkeypatch):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn(productId=PANDA))},
                       headers=shop).status_code == 200
    monkeypatch.setenv("STORE_ENABLED", "0")
    revoked = _txn(productId=PANDA, revocationDate=int(time.time() * 1000))
    assert client.post("/api/store/notify", json=_notification(chain, "REVOKE", revoked)).status_code == 200
    assert accounts_on.STORE.owned_products(1) == frozenset()


def test_a_refund_before_any_claim_blocks_the_claim(accounts_on, client, shop, chain):
    refunded = _txn(originalTransactionId="77", transactionId="77",
                    revocationDate=int(time.time() * 1000))
    assert client.post("/api/store/notify", json=_notification(chain, "REFUND", refunded)).status_code == 200
    resp = client.post("/api/store/verify",
                       json={"jws": chain.sign(_txn(originalTransactionId="77", transactionId="77"))},
                       headers=shop)
    assert resp.status_code == 409


def test_a_notification_that_fails_verification_changes_nothing(accounts_on, client, shop, chain):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    revoked = _txn(revocationDate=int(time.time() * 1000))
    forged = _notification(Chain(), "REFUND", revoked)
    assert client.post("/api/store/notify", json=forged).status_code == 400
    # an outer payload Apple signed carrying an inner transaction it did not
    outer = chain.sign({"notificationType": "REFUND", "signedDate": int(time.time() * 1000),
                        "data": {"bundleId": "com.jerryyu.shengji", "environment": "Sandbox",
                                 "signedTransactionInfo": Chain().sign(revoked)}})
    assert client.post("/api/store/notify", json={"signedPayload": outer}).status_code == 400
    wrong_app = _notification(chain, "REFUND", revoked, bundleId="com.other")
    assert client.post("/api/store/notify", json=wrong_app).status_code == 400
    assert accounts_on.STORE.owned_products(1) == frozenset({GOAT})
    # other types are acknowledged and ignored
    assert client.post("/api/store/notify", json=_notification(chain, "CONSUMPTION_REQUEST", _txn())).status_code == 200
    assert accounts_on.STORE.owned_products(1) == frozenset({GOAT})


# ------------------------------------------------------------ the table
def test_the_entitlements_migration_snapshots_first(accounts_on, tmp_path):
    path = tmp_path / "old" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    store = accounts_on.Store(path)
    assert store.schema_version() == len(accounts_on.SCHEMA) == 12
    with accounts_sqlite(path) as db:
        cols = [r[1] for r in db.execute("PRAGMA table_info(entitlements)")]
    assert cols == ["id", "user_id", "product_id", "original_transaction_id", "transaction_id",
                    "environment", "storefront", "purchased_at", "verified_at", "revoked_at", "state_at"]
    assert store.backup_path(1).exists()


def test_a_v11_database_gains_the_table_after_a_verified_backup(accounts_on, tmp_path):
    path = tmp_path / "v11" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    accounts_on.Store(path).schema_version()
    with accounts_sqlite(path) as db:
        db.execute("DROP TABLE entitlements")
        db.execute("UPDATE schema_version SET version = 11")
        db.commit()
    for p in path.parent.glob("*.bak"):
        p.unlink()
    store = accounts_on.Store(path)
    assert store.schema_version() == 12
    backup = store.backup_path(11)
    with accounts_sqlite(backup) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone() == (11,)
        assert db.execute("SELECT name FROM sqlite_master WHERE name = 'entitlements'").fetchone() is None


def test_purchases_follow_a_merged_device_account_and_outlive_a_deleted_one(accounts_on):
    store = accounts_on.STORE
    a = store.upsert_user(_claims(sub="s1", email="a@example.com", name="A"))
    b = store.upsert_user(_claims(sub="s2", email="b@example.com", name="B"))
    txn = {"product_id": GOAT, "original_transaction_id": "9", "transaction_id": "9",
           "environment": "Sandbox", "storefront": "USA", "purchased_at": 1.0}
    assert store.claim_entitlement(a["id"], txn) == "granted"
    assert store.owned_products(a["id"]) == frozenset({GOAT})
    with store._open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        store._merge_device(conn, a["id"], b["id"])
        conn.execute("COMMIT")
    assert store.owned_products(b["id"]) == frozenset({GOAT})
    assert store.claim_entitlement(b["id"], txn) == "granted"
    assert store.delete_user(b["id"])
    with store._open() as conn:
        assert [tuple(r) for r in conn.execute("SELECT user_id, revoked_at FROM entitlements")] == [(None, None)]


# ------------------------------------------------------------ lifecycle sequences
def _signed_at(ms_offset: int) -> int:
    return int(time.time() * 1000) + ms_offset


def _notify_at(chain: Chain, kind: str, txn: dict, signed: int) -> dict:
    body = {"bundleId": "com.jerryyu.shengji", "environment": txn.get("environment", "Sandbox"),
            "signedTransactionInfo": chain.sign(txn)}
    return {"signedPayload": chain.sign({
        "notificationType": kind, "notificationUUID": f"uuid-{kind}-{signed}",
        "data": body, "version": "2.0", "signedDate": signed})}


def test_a_refund_reversed_before_any_claim_still_lets_the_buyer_claim(accounts_on, client, shop, chain):
    one = _txn(originalTransactionId="41", transactionId="41")
    refunded = dict(one, revocationDate=_signed_at(-2000))
    assert client.post("/api/store/notify", json=_notify_at(chain, "REFUND", refunded, _signed_at(-2000))).status_code == 200
    assert client.post("/api/store/notify", json=_notify_at(chain, "REFUND_REVERSED", one, _signed_at(-1000))).status_code == 200
    resp = client.post("/api/store/verify", json={"jws": chain.sign(one)}, headers=shop)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=shop).json()["products"] == [GOAT]


def test_a_late_duplicate_refund_after_its_reversal_changes_nothing(accounts_on, client, shop, chain):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    refunded = _txn(revocationDate=_signed_at(-3000))
    refund = _notify_at(chain, "REFUND", refunded, _signed_at(-3000))
    assert client.post("/api/store/notify", json=refund).status_code == 200
    assert accounts_on.STORE.owned_products(1) == frozenset()
    assert client.post("/api/store/notify", json=_notify_at(chain, "REFUND_REVERSED", _txn(), _signed_at(-1000))).status_code == 200
    assert accounts_on.STORE.owned_products(1) == frozenset({GOAT})
    # Apple redelivers the first refund after its reversal: older, so ignored
    assert client.post("/api/store/notify", json=refund).status_code == 200
    assert client.get("/api/me", headers=shop).json()["products"] == [GOAT]
    # and a reversal delivered before its refund leaves the refund in force
    two = _txn(originalTransactionId="52", transactionId="52", productId=PANDA)
    assert client.post("/api/store/verify", json={"jws": chain.sign(two)}, headers=shop).status_code == 200
    late_reversal = _notify_at(chain, "REFUND_REVERSED", two, _signed_at(-5000))
    newer_refund = _notify_at(chain, "REFUND", dict(two, revocationDate=_signed_at(-4000)), _signed_at(-4000))
    assert client.post("/api/store/notify", json=newer_refund).status_code == 200
    assert client.post("/api/store/notify", json=late_reversal).status_code == 200
    assert PANDA not in client.get("/api/me", headers=shop).json()["products"]


def test_a_duplicate_refund_before_any_claim_keeps_the_purchase_unclaimable(accounts_on, client, shop, chain):
    one = _txn(originalTransactionId="63", transactionId="63")
    refund = _notify_at(chain, "REFUND", dict(one, revocationDate=_signed_at(-2000)), _signed_at(-2000))
    for _ in range(2):
        assert client.post("/api/store/notify", json=refund).status_code == 200
    assert client.post("/api/store/verify", json={"jws": chain.sign(one)}, headers=shop).status_code == 409
    assert client.get("/api/me", headers=shop).json()["products"] == []


def test_deleting_the_account_keeps_the_refund_record(accounts_on, client, shop, chain, keypair, monkeypatch):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    refund = _notify_at(chain, "REFUND", _txn(revocationDate=_signed_at(-1000)), _signed_at(-1000))
    assert client.post("/api/store/notify", json=refund).status_code == 200
    assert accounts_on.STORE.delete_user(1)
    with accounts_on.STORE._open() as conn:
        row = conn.execute("SELECT user_id, revoked_at FROM entitlements").fetchone()
    assert row["user_id"] is None and row["revoked_at"] is not None
    # a new account presenting the old, unrevoked JWS is still refused
    private_pem, _ = keypair
    client.cookies.clear()
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1,2")
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="333", email="c@example.com")}
    resp = client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=other)
    assert resp.status_code == 409 and resp.json()["detail"] == "revoked"


def test_an_unrefunded_purchase_restores_onto_a_new_account_after_deletion(accounts_on, client, shop, chain, keypair, monkeypatch):
    token = client.get("/api/me", headers=shop).json()["store_token"]
    bought = chain.sign(_txn(appAccountToken=token))
    assert client.post("/api/store/verify", json={"jws": bought}, headers=shop).status_code == 200
    assert accounts_on.STORE.delete_user(1)
    private_pem, _ = keypair
    client.cookies.clear()
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "2")
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="444", email="d@example.com")}
    resp = client.post("/api/store/verify", json={"jws": bought}, headers=other)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=other).json()["products"] == [GOAT]


def test_a_refunded_purchase_of_a_deleted_payer_is_not_released(accounts_on, client, shop, chain, keypair, monkeypatch):
    token = client.get("/api/me", headers=shop).json()["store_token"]
    bought = chain.sign(_txn(appAccountToken=token))
    assert client.post("/api/store/verify", json={"jws": bought}, headers=shop).status_code == 200
    refund = _notify_at(chain, "REFUND", _txn(appAccountToken=token, revocationDate=_signed_at(-1000)), _signed_at(-1000))
    assert client.post("/api/store/notify", json=refund).status_code == 200
    assert accounts_on.STORE.delete_user(1)
    private_pem, _ = keypair
    client.cookies.clear()
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "2")
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="445", email="f@example.com")}
    resp = client.post("/api/store/verify", json={"jws": bought}, headers=other)
    assert resp.status_code == 409 and resp.json()["detail"] == "revoked"
    assert client.get("/api/me", headers=other).json()["products"] == []


def test_a_purchase_signed_for_a_merged_device_account_reaches_the_survivor(accounts_on, client, shop, chain):
    store = accounts_on.STORE
    device = store.upsert_user(_claims(sub="dev1", email="dev@example.com", name="Dev"))
    device_token = store.store_token(device["id"])
    # bought on the device account, never delivered; then the device account links into account 1
    pending = chain.sign(_txn(originalTransactionId="101", transactionId="101", appAccountToken=device_token))
    with store._open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        store._merge_device(conn, device["id"], 1)
        conn.execute("COMMIT")
    resp = client.post("/api/store/verify", json={"jws": pending}, headers=shop)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=shop).json()["products"] == [GOAT]
    # the survivor's own token is unchanged and the device's still resolves to it
    assert store.store_token_account(device_token) == 1


def test_a_purchase_for_a_live_payer_is_settled_only_once_the_payer_has_it(accounts_on, client, shop, chain, keypair, monkeypatch):
    token = client.get("/api/me", headers=shop).json()["store_token"]
    refunded = _txn(originalTransactionId="111", transactionId="111", appAccountToken=token)
    refund = _notify_at(chain, "REFUND", dict(refunded, revocationDate=_signed_at(-1000)), _signed_at(-1000))
    assert client.post("/api/store/notify", json=refund).status_code == 200
    private_pem, _ = keypair
    client.cookies.clear()
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1,2")
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="446", email="g@example.com")}
    resp = client.post("/api/store/verify", json={"jws": chain.sign(refunded)}, headers=other)
    assert resp.status_code == 409 and resp.json()["detail"] == "revoked"
    assert accounts_on.STORE.owned_products(1) == frozenset()


def test_sandbox_grants_disappear_when_only_production_is_enabled(accounts_on, client, shop, chain, monkeypatch):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    assert client.put("/api/me/look", json={"look": "goat/jade"}, headers=shop).status_code == 200
    monkeypatch.setenv("STORE_ENVIRONMENTS", "Production")
    me = client.get("/api/me", headers=shop).json()
    assert me["products"] == [] and me["look"] == "tractor/red"
    assert client.put("/api/me/look", json={"look": "goat/ink"}, headers=shop).status_code == 403
    # a Production purchase still counts
    prod = _txn(originalTransactionId="75", transactionId="75", productId=PANDA, environment="Production")
    assert client.post("/api/store/verify", json={"jws": chain.sign(prod)}, headers=shop).status_code == 200
    assert client.get("/api/me", headers=shop).json()["products"] == [PANDA]


# ------------------------------------------------------------ round two
def test_a_reversal_before_any_claim_and_before_its_older_refund_keeps_the_purchase_claimable(
        accounts_on, client, shop, chain):
    one = _txn(originalTransactionId="81", transactionId="81")
    reversal = _notify_at(chain, "REFUND_REVERSED", one, _signed_at(-1000))
    older_refund = _notify_at(chain, "REFUND", dict(one, revocationDate=_signed_at(-2000)), _signed_at(-2000))
    assert client.post("/api/store/notify", json=reversal).status_code == 200
    assert client.post("/api/store/notify", json=older_refund).status_code == 200
    resp = client.post("/api/store/verify", json={"jws": chain.sign(one)}, headers=shop)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=shop).json()["products"] == [GOAT]


def test_a_stale_refund_leaves_the_seat_look_alone(accounts_on, client, shop, chain):
    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    refund = _notify_at(chain, "REFUND", _txn(revocationDate=_signed_at(-3000)), _signed_at(-3000))
    assert client.post("/api/store/notify", json=refund).status_code == 200
    assert client.post("/api/store/notify", json=_notify_at(chain, "REFUND_REVERSED", _txn(), _signed_at(-1000))).status_code == 200
    assert client.put("/api/me/look", json={"look": "goat/ink"}, headers=shop).status_code == 200
    assert accounts_on.account_look(1) == "goat/ink"
    assert client.post("/api/store/notify", json=refund).status_code == 200      # redelivered, older
    assert accounts_on.account_look(1) == "goat/ink"
    assert client.get("/api/me", headers=shop).json()["look"] == "goat/ink"


def test_seats_and_leaderboard_rows_show_only_an_owned_look(accounts_on, client, shop, chain, monkeypatch):
    from shengji.api import ratings

    assert client.post("/api/store/verify", json={"jws": chain.sign(_txn())}, headers=shop).status_code == 200
    assert client.put("/api/me/look", json={"look": "goat/jade"}, headers=shop).status_code == 200
    _rounds_at(accounts_on.STORE, 1, [time.time() - 60])
    board = ratings.leaderboard(accounts_on.STORE, "all", 1)
    assert board["me"]["look"] == "goat/jade"
    monkeypatch.setenv("STORE_ENVIRONMENTS", "Production")
    accounts_on.STORE.seen_looks.clear()
    with client.websocket_connect("/ws", headers=shop) as ws:
        ws.send_json({"type": "create_room"})
        assert _drain(ws, "room")["players"][0]["look"] == "tractor/red"
    assert accounts_on.account_look(1) == "tractor/red"
    board = ratings.leaderboard(accounts_on.STORE, "all", 1)
    assert board["me"]["look"] == "tractor/red"
    assert {r["look"] for r in board["players"]} <= {"tractor/red"}


def test_the_account_token_binds_a_purchase_to_its_payer(accounts_on, client, shop, chain, keypair, monkeypatch):
    payer = client.get("/api/me", headers=shop).json()["store_token"]
    assert isinstance(payer, str) and len(payer) == 36
    assert client.get("/api/me", headers=shop).json()["store_token"] == payer      # stable
    private_pem, _ = keypair
    client.cookies.clear()
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1,2")
    other = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="555", email="e@example.com")}
    assert client.get("/api/me", headers=other).json()["store_token"] != payer
    # the payer's purchase presented by another account: the payer gets it, the presenter does not
    bought = chain.sign(_txn(appAccountToken=payer))
    resp = client.post("/api/store/verify", json={"jws": bought}, headers=other)
    assert resp.status_code == 409 and resp.json()["detail"] == "held_by_other"
    assert client.get("/api/me", headers=other).json()["products"] == []
    assert accounts_on.STORE.owned_products(1) == frozenset({GOAT})
    assert client.post("/api/store/verify", json={"jws": bought}, headers=shop).status_code == 200
    # a token this server never issued grants nobody, and records nothing (retryable)
    stray = chain.sign(_txn(originalTransactionId="91", transactionId="91", productId=PANDA,
                            appAccountToken="00000000-0000-4000-8000-000000000000"))
    resp = client.post("/api/store/verify", json={"jws": stray}, headers=shop)
    assert resp.status_code == 409 and resp.json()["detail"] == "unknown_token"
    assert PANDA not in accounts_on.STORE.owned_products(1)
    with accounts_on.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entitlements WHERE original_transaction_id = '91'").fetchone()[0] == 0


def test_a_guest_or_store_off_account_gets_no_token(accounts_on, client, shop, monkeypatch):
    monkeypatch.setenv("STORE_ENABLED", "0")
    assert client.get("/api/me", headers=shop).json().get("store_token") is None


def test_the_refusal_reasons_say_which_are_permanent():
    from shengji.api import purchases

    assert purchases.PERMANENT_REFUSALS == frozenset({"held_by_other", "revoked", "wrong_app"})


# ------------------------------------------------------------ signed-in buyers only
def _device_session(accounts_on, client, monkeypatch) -> tuple[dict, int]:
    from tests.test_device_accounts import _cookie, _create

    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "1")
    resp = _create(client)
    assert resp.status_code == 200
    cookie = {"cookie": _cookie(resp)}
    device_id = max(r["id"] for r in [accounts_on.STORE.user(i) for i in range(1, 5)] if r)
    monkeypatch.setenv("COLLECTION_ACCOUNTS", f"1,{device_id}")
    return cookie, device_id


def test_a_device_account_sees_the_shop_but_gets_no_token_and_cannot_buy(accounts_on, client, shop, chain, monkeypatch):
    client.cookies.clear()
    device, device_id = _device_session(accounts_on, client, monkeypatch)
    me = client.get("/api/me", headers=device).json()
    assert me["linked"] is False and me["features"]["store"] is True
    assert "store_token" not in me
    resp = client.post("/api/store/verify", json={"jws": chain.sign(_txn(originalTransactionId="121", transactionId="121"))},
                       headers=device)
    assert resp.status_code == 409 and resp.json()["detail"] == "sign_in_required"
    with accounts_on.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM entitlements").fetchone()[0] == 0
    from shengji.api import purchases
    assert "sign_in_required" not in purchases.PERMANENT_REFUSALS


def test_a_transaction_refused_to_a_device_account_is_delivered_after_it_links(accounts_on, client, shop, chain, monkeypatch):
    store = accounts_on.STORE
    signed_in = shop
    client.cookies.clear()
    device, device_id = _device_session(accounts_on, client, monkeypatch)
    pending = chain.sign(_txn(originalTransactionId="131", transactionId="131"))
    assert client.post("/api/store/verify", json={"jws": pending}, headers=device).json()["detail"] == "sign_in_required"
    # the player signs in with Apple or Google: the device account merges into the signed-in one
    with store._open() as conn:
        conn.execute("BEGIN IMMEDIATE")
        store._merge_device(conn, device_id, 1)
        conn.execute("COMMIT")
    client.cookies.clear()
    resp = client.post("/api/store/verify", json={"jws": pending}, headers=signed_in)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/me", headers=signed_in).json()["products"] == [GOAT]
