"""App Store purchases: StoreKit 2 signed transactions and App Store Server
Notifications V2, verified on the server before an entitlement changes.

Every input is a JWS (compact form, ES256) whose header carries an ``x5c``
chain: the signing leaf, Apple's WWDR intermediate and Apple Root CA - G3.
A JWS is trusted only when

- the chain's last certificate is byte-for-byte a pinned Apple root
  (``APPLE_ROOTS``), each certificate is signed by the next, the intermediate
  is a CA, and leaf and intermediate carry Apple's marker extensions
  (``LEAF_OID``, ``INTERMEDIATE_OID``);
- every certificate is valid at the payload's ``signedDate``, as Apple's own
  App Store Server Library checks offline;
- the ES256 signature over ``header.payload`` verifies with the leaf's key.

Only then are its fields read: the bundle id must be the app's, the
environment one ``STORE_ENVIRONMENTS`` accepts, the product one of
``accounts.COMPANION_PRODUCTS`` and the storefront not China mainland. The
client sends only the JWS and its storefront; nothing it says about a product
is used unless the signature covers it.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import accounts

log = logging.getLogger("shengji.purchases")

# Apple Root CA - G3 (https://www.apple.com/certificateauthority/), SHA-256
# fingerprint 63:34:3A:BF:B8:9A:6A:03:EB:B5:7E:9B:3F:5F:A7:BE:7C:4F:5C:75:6F:30:17:B3:A8:C4:88:C3:65:3E:91:79.
APPLE_ROOT_CA_G3_PEM = b"""-----BEGIN CERTIFICATE-----
MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwS
QXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9u
IEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcN
MTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBS
b290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9y
aXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49
AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtf
TjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517
IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySr
MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gA
MGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4
at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM
6BgD56KyKA==
-----END CERTIFICATE-----
"""
# The DER bytes of every root a chain may end in. Tests swap in their own.
APPLE_ROOTS: tuple[bytes, ...] = (
    x509.load_pem_x509_certificate(APPLE_ROOT_CA_G3_PEM).public_bytes(serialization.Encoding.DER),
)
# Apple's marker extensions: the App Store receipt-signing leaf, and the
# Apple Worldwide Developer Relations intermediate that issues it.
LEAF_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.11.1")
INTERMEDIATE_OID = x509.ObjectIdentifier("1.2.840.113635.100.6.2.1")

# The App Store environments whose purchases grant an entitlement,
# comma-separated. Production is the live store; Sandbox is TestFlight and
# App Review, which tests purchases against the production server.
STORE_ENVIRONMENTS_ENV = "STORE_ENVIRONMENTS"
DEFAULT_ENVIRONMENTS = ("Production", "Sandbox")
# The China mainland storefront sells nothing: its purchases are refused.
BLOCKED_STOREFRONTS = frozenset({"CHN"})
NON_CONSUMABLE = "Non-Consumable"
# Notification types that take a purchase away, and the one that gives it back.
REVOKING_NOTIFICATIONS = frozenset({"REFUND", "REVOKE"})
RESTORING_NOTIFICATIONS = frozenset({"REFUND_REVERSED"})
MAX_JWS_BYTES = 64 * 1024


class VerificationError(Exception):
    """A JWS or its payload failed a check; ``code`` is the client's detail."""

    def __init__(self, code: str, why: str = ""):
        super().__init__(why or code)
        self.code = code


def allowed_environments() -> frozenset[str]:
    raw = os.environ.get(STORE_ENVIRONMENTS_ENV)
    if raw is None:
        return frozenset(DEFAULT_ENVIRONMENTS)
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _b64url(part: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError) as exc:
        raise VerificationError("bad_signature", "not base64url") from exc


def _json(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise VerificationError("bad_signature", "not JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError("bad_signature", "not an object")
    return value


def _has_extension(cert: x509.Certificate, oid: x509.ObjectIdentifier) -> bool:
    try:
        cert.extensions.get_extension_for_oid(oid)
    except x509.ExtensionNotFound:
        return False
    return True


def _is_ca(cert: x509.Certificate) -> bool:
    try:
        return bool(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
    except x509.ExtensionNotFound:
        return False


def verify_jws(token: Any, roots: Sequence[bytes] | None = None) -> dict:
    """The payload of ``token`` once its chain and signature verify (the
    module docstring's checks); raises ``VerificationError`` otherwise."""
    if not isinstance(token, str) or not token or len(token) > MAX_JWS_BYTES:
        raise VerificationError("bad_signature", "missing or oversized")
    parts = token.split(".")
    if len(parts) != 3:
        raise VerificationError("bad_signature", "not a compact JWS")
    header = _json(_b64url(parts[0]))
    if header.get("alg") != "ES256":
        raise VerificationError("bad_signature", "alg is not ES256")
    chain = header.get("x5c")
    if not isinstance(chain, list) or len(chain) != 3 or not all(isinstance(c, str) for c in chain):
        raise VerificationError("bad_signature", "x5c is not a three-certificate chain")
    try:
        certs = [x509.load_der_x509_certificate(base64.b64decode(c, validate=True)) for c in chain]
    except (binascii.Error, ValueError) as exc:
        raise VerificationError("bad_signature", "unreadable certificate") from exc
    leaf, intermediate, root = certs
    trusted = APPLE_ROOTS if roots is None else tuple(roots)
    if base64.b64decode(chain[2]) not in trusted:
        raise VerificationError("bad_signature", "chain does not end in a pinned root")
    try:
        leaf.verify_directly_issued_by(intermediate)
        intermediate.verify_directly_issued_by(root)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise VerificationError("bad_signature", "chain does not verify") from exc
    if not _is_ca(intermediate) or not _has_extension(intermediate, INTERMEDIATE_OID):
        raise VerificationError("bad_signature", "intermediate is not Apple's")
    if not _has_extension(leaf, LEAF_OID):
        raise VerificationError("bad_signature", "leaf is not an App Store signing certificate")
    key = leaf.public_key()
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise VerificationError("bad_signature", "leaf key is not P-256")
    signature = _b64url(parts[2])
    if len(signature) != 64:
        raise VerificationError("bad_signature", "signature is not 64 bytes")
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    try:
        key.verify(der, f"{parts[0]}.{parts[1]}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise VerificationError("bad_signature", "signature does not verify") from exc
    payload = _json(_b64url(parts[1]))
    signed = payload.get("signedDate")
    if not isinstance(signed, (int, float)) or isinstance(signed, bool):
        raise VerificationError("bad_signature", "no signedDate")
    at = datetime.fromtimestamp(signed / 1000, tz=timezone.utc)
    for cert in certs:
        if not cert.not_valid_before_utc <= at <= cert.not_valid_after_utc:
            raise VerificationError("bad_signature", "a certificate was not valid when it signed")
    return payload


def _ms(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise VerificationError("bad_transaction", f"no {field}")
    return value / 1000


def transaction(payload: dict) -> dict:
    """The fields an entitlement keeps, from a verified transaction payload
    (``JWSTransactionDecodedPayload``); raises ``VerificationError`` for one
    of another app, an environment not accepted or a product not sold."""
    if payload.get("bundleId") != accounts.STORE_BUNDLE_ID:
        raise VerificationError("wrong_app")
    environment = payload.get("environment")
    if environment not in allowed_environments():
        raise VerificationError("wrong_environment")
    product = payload.get("productId")
    if product not in accounts.COMPANION_PRODUCTS.values():
        raise VerificationError("unknown_product")
    if payload.get("type") != NON_CONSUMABLE:
        raise VerificationError("unknown_product", "not a non-consumable")
    original, current = payload.get("originalTransactionId"), payload.get("transactionId")
    if not isinstance(original, str) or not original or not isinstance(current, str) or not current:
        raise VerificationError("bad_transaction", "no transaction id")
    storefront = payload.get("storefront")
    revoked = payload.get("revocationDate")
    return {"product_id": product, "original_transaction_id": original,
            "transaction_id": current, "environment": environment,
            "storefront": storefront if isinstance(storefront, str) else None,
            "purchased_at": _ms(payload.get("purchaseDate"), "purchaseDate"),
            "revoked_at": None if revoked is None else _ms(revoked, "revocationDate")}


def companion_of(product_id: str) -> str | None:
    return next((c for c, p in accounts.COMPANION_PRODUCTS.items() if p == product_id), None)


def _forget_look(user_id: int | None, companion: str | None) -> None:
    """Drop a revoked companion from the seat cache of the process's store."""
    if user_id is None or companion is None:
        return
    seen = accounts.STORE.seen_looks.get(user_id)
    if seen is not None and seen.partition("/")[0] == companion:
        accounts.STORE.seen_looks[user_id] = accounts.DEFAULT_LOOK


router = APIRouter(prefix="/api/store")


class VerifyBody(BaseModel):
    jws: str
    storefront: str | None = None


class NotifyBody(BaseModel):
    signedPayload: str


@router.post("/verify")
async def verify(body: VerifyBody, request: Request) -> dict:
    """Grant the purchase in a StoreKit 2 signed transaction to the signed-in
    account; the account payload (``accounts.account_payload``) with the
    product in ``products``. Presenting the same purchase again is a no-op.
    Refused: a guest (401), an account without the store (404), a JWS that
    fails verification or names another app or product (400), the China
    mainland storefront by the client's word or the signed one (403), and a
    purchase that was refunded or that another account holds (409)."""
    store = accounts.STORE
    if not accounts.LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests; try again in a minute.")
    user = await store.run(store.session_user, request.cookies.get(accounts.COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    user_id = int(user["id"])
    if not accounts.store_for(user_id):
        raise HTTPException(status_code=404, detail="Not found.")
    if (body.storefront or "").upper() in BLOCKED_STOREFRONTS:
        raise HTTPException(status_code=403, detail="storefront")
    try:
        txn = transaction(verify_jws(body.jws))
    except VerificationError as exc:
        log.info("store verify refused: %s", exc.code)
        raise HTTPException(status_code=400, detail=exc.code) from None
    if (txn["storefront"] or "").upper() in BLOCKED_STOREFRONTS:
        raise HTTPException(status_code=403, detail="storefront")
    if txn["storefront"] is None and body.storefront:
        txn["storefront"] = body.storefront.upper()[:3]
    if txn["revoked_at"] is not None:
        raise HTTPException(status_code=409, detail="revoked")
    outcome = await store.run(store.claim_entitlement, user_id, txn)
    if outcome != "granted":
        log.info("store verify refused: %s", outcome)
        raise HTTPException(status_code=409, detail=outcome)
    log.info("store purchase granted: %s %s", txn["product_id"], txn["environment"])
    return await accounts.account_payload(store, user)


@router.post("/notify")
async def notify(body: NotifyBody) -> dict:
    """App Store Server Notifications V2 (the URL set in App Store
    Connect). A REFUND or REVOKE revokes the purchase it names and unequips
    its companion; a REFUND_REVERSED gives it back; any other type is
    acknowledged and ignored. A payload that fails verification, or names
    another app or environment, is refused with 400 and changes nothing.
    Runs whether or not the store is on, so a refund always applies."""
    store = accounts.STORE
    try:
        payload = verify_jws(body.signedPayload)
        kind = payload.get("notificationType")
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        if data.get("bundleId") != accounts.STORE_BUNDLE_ID:
            raise VerificationError("wrong_app")
        if data.get("environment") not in allowed_environments():
            raise VerificationError("wrong_environment")
        if kind not in REVOKING_NOTIFICATIONS and kind not in RESTORING_NOTIFICATIONS:
            return {}
        txn = transaction(verify_jws(data.get("signedTransactionInfo")))
    except VerificationError as exc:
        if exc.code == "unknown_product":
            # Signed by Apple for this app, about a product nothing here sells.
            return {}
        log.info("store notification refused: %s", exc.code)
        raise HTTPException(status_code=400, detail=exc.code) from None
    if kind in REVOKING_NOTIFICATIONS:
        companion = companion_of(txn["product_id"])
        when = txn["revoked_at"] if txn["revoked_at"] is not None else time.time()
        user_id = await store.run(store.revoke_entitlement, txn, when, companion)
        _forget_look(user_id, companion)
        log.info("store purchase revoked: %s %s", kind, txn["product_id"])
    else:
        await store.run(store.restore_entitlement, txn["original_transaction_id"])
        log.info("store purchase restored: %s %s", kind, txn["product_id"])
    return {}
