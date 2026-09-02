"""Typed, outcome-blind inputs for the Value-Afterstate V2 freeze.

This module is intentionally a source bridge only.  It derives the four
small inputs consumed by the reviewed stage adapters from one authenticated
capacity receipt; it never opens labels/outcomes and never publishes a freeze.
"""

from __future__ import annotations

import hashlib
import json
import os
import ctypes
import errno
import sys
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_capacity import choose_capacity_tier_v2
from .world_afterstate_v2_capacity_economics import (
    reopen_capacity_evidence_v2_bytes,
)
from .world_afterstate_v2_protocol import (
    ATTEMPT_SCHEMA, D256_MAX_ATTEMPTS_PER_SLOT, PROTOCOL_SCHEMA,
    protocol_payload,
)
from .world_afterstate_v2_schedule import SEED_BLOCKS
from .world_afterstate_v2_continuation import (
    IDENTITY_EXPERIMENT, REPLICATES, V2_CONTINUATION_POLICY,
)
from .world_afterstate_capacity import PRODUCTION_BALLOT_POLICY
from .world_afterstate_label import IDENTITY_SCHEMA


POPULATION_INPUT_SCHEMA = "world-afterstate-v2-population-adapter-input-v4"
STAGE_INPUT_SCHEMA = "world-afterstate-v2-early-stage-adapters-input-v2"
NAMESPACE_SCHEMA = "world-afterstate-v2-population-namespace-v1"
SEED_REGISTRY_SCHEMA = "world-afterstate-v2-seed-registry-input-v1"
CONTINUATION_POLICY_SCHEMA = "world-afterstate-v2-continuation-policy-input-v1"
PROTOCOL_INPUT_SCHEMA = PROTOCOL_SCHEMA
ACTOR_SEATS = (0, 1, 2, 3)
_SEED_BLOCK_PAYLOADS = tuple(block.payload() for block in SEED_BLOCKS)
AUTHORITY = {
    "data_collection_authorized": False,
    "capacity_execution_authorized": False,
    "dataset_opening_authorized": False,
    "label_opening_authorized": False,
    "training_authorized": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2FreezeInputsError(ValueError):
    """A typed freeze input or immutable publication was refused."""


FreezeInputsError = WorldAfterstateV2FreezeInputsError


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(c not in "0123456789abcdef" for c in value)):
        raise WorldAfterstateV2FreezeInputsError(f"{label} drift")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorldAfterstateV2FreezeInputsError(f"{label} drift")
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise WorldAfterstateV2FreezeInputsError("duplicate JSON key")
        result[key] = value
    return result


def _json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2FreezeInputsError(f"{label} bytes drift")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               ValueError("non-finite")))
    except WorldAfterstateV2FreezeInputsError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2FreezeInputsError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2FreezeInputsError(f"{label} is not canonical JSON")
    return value


def _source(value: object) -> str:
    return _digest(value, "source Git", length=40)


def protocol_bytes() -> bytes:
    """Return the exact authoritative protocol artifact bytes."""
    return canonical_json_bytes(protocol_payload())


def reopen_protocol_bytes(raw: bytes) -> dict[str, Any]:
    value = _json(raw, "protocol artifact")
    expected = protocol_payload()
    if value != expected:
        raise WorldAfterstateV2FreezeInputsError("protocol authoritative reopen drift")
    return value


def population_namespace(source_git: str, protocol_sha256: str,
                         capacity_sha256: str, selected_tier: str) -> str:
    body = {
        "schema": NAMESPACE_SCHEMA, "source_git": _source(source_git),
        "protocol_sha256": _digest(protocol_sha256, "protocol SHA-256"),
        "capacity_sha256": _digest(capacity_sha256, "capacity SHA-256"),
        "selected_tier": selected_tier,
    }
    if selected_tier != "D256":
        raise WorldAfterstateV2FreezeInputsError("selected capacity tier drift")
    return _sha(body)


def capacity_context(capacity_raw: bytes) -> tuple[Any, str, int, int]:
    """Reopen receipt and return it, selected tier, and measured worker arms."""
    try:
        receipt = reopen_capacity_evidence_v2_bytes(capacity_raw)
        selected = (receipt.choose_tier()
                    if hasattr(receipt, "choose_tier")
                    else choose_capacity_tier_v2(receipt))
    except Exception as exc:
        raise WorldAfterstateV2FreezeInputsError(
            "capacity receipt reopen refused") from exc
    if selected.name != "D256":
        raise WorldAfterstateV2FreezeInputsError("capacity exact-source tier unavailable")
    if not any(tier.tier == "D256" and tier.exact_source_supply
               for tier in receipt.tiers):
        raise WorldAfterstateV2FreezeInputsError("capacity exact-source tier unavailable")
    arms = {arm.stage: arm for arm in receipt.selected_arms}
    for stage in ("state-successor", "continuation-mechanics"):
        if stage not in arms:
            raise WorldAfterstateV2FreezeInputsError("selected capacity arm missing")
    return receipt, selected.name, arms["state-successor"].variant, arms[
        "continuation-mechanics"].variant


def _check_common(value: Mapping[str, Any], *, source_git: str,
                  protocol_sha256: str, capacity_sha256: str,
                  namespace: str, tier: str) -> None:
    if (value.get("source_git"), value.get("protocol_sha256"),
            value.get("capacity_sha256"), value.get("population_namespace_sha256"),
            value.get("selected_tier")) != (
                _source(source_git), protocol_sha256, capacity_sha256,
                namespace, tier):
        raise WorldAfterstateV2FreezeInputsError("freeze input binding drift")


def build_population_adapter_input_v2(*, source_git: str, protocol_sha256: str,
                                      capacity_sha256: str,
                                      selected_tier: str, workers: int,
                                      deadline_seconds: int,
                                      heartbeat_seconds: int,
                                      max_attempts_per_slot: int) -> dict[str, Any]:
    namespace = population_namespace(source_git, protocol_sha256,
                                     capacity_sha256, selected_tier)
    if workers not in (1, 2, 4, 8, 16, 32):
        raise WorldAfterstateV2FreezeInputsError("population workers drift")
    _positive(deadline_seconds, "population deadline")
    _positive(heartbeat_seconds, "population heartbeat")
    if max_attempts_per_slot != D256_MAX_ATTEMPTS_PER_SLOT:
        raise WorldAfterstateV2FreezeInputsError(
            "D256 population attempt cap drift")
    if heartbeat_seconds > 60:
        raise WorldAfterstateV2FreezeInputsError("population heartbeat drift")
    return {"schema": POPULATION_INPUT_SCHEMA,
            "population_namespace_sha256": namespace,
            "max_attempts_per_slot": max_attempts_per_slot,
            "workers": workers, "deadline_seconds": deadline_seconds,
            "heartbeat_seconds": heartbeat_seconds}


def reopen_population_adapter_input_v2_bytes(
        raw: bytes, *, expected_namespace: str | None = None,
        expected_workers: int | None = None,
        expected_deadline: int | None = None,
        expected_heartbeat: int | None = None) -> dict[str, Any]:
    value = _json(raw, "population adapter input")
    if set(value) != {"schema", "population_namespace_sha256",
                       "max_attempts_per_slot", "workers", "deadline_seconds",
                       "heartbeat_seconds"} or value["schema"] != POPULATION_INPUT_SCHEMA:
        raise WorldAfterstateV2FreezeInputsError("population adapter input schema drift")
    namespace = _digest(value["population_namespace_sha256"], "population namespace")
    if expected_namespace is not None and namespace != expected_namespace:
        raise WorldAfterstateV2FreezeInputsError("population namespace binding drift")
    for field in ("max_attempts_per_slot", "workers", "deadline_seconds", "heartbeat_seconds"):
        _positive(value[field], f"population {field}")
    if value["max_attempts_per_slot"] != D256_MAX_ATTEMPTS_PER_SLOT:
        raise WorldAfterstateV2FreezeInputsError(
            "D256 population attempt cap drift")
    if value["workers"] not in (1, 2, 4, 8, 16, 32) or value["heartbeat_seconds"] > 60:
        raise WorldAfterstateV2FreezeInputsError("population adapter resource drift")
    if expected_workers is not None and value["workers"] != expected_workers:
        raise WorldAfterstateV2FreezeInputsError("population worker binding drift")
    if expected_deadline is not None and value["deadline_seconds"] != expected_deadline:
        raise WorldAfterstateV2FreezeInputsError("population deadline binding drift")
    if expected_heartbeat is not None and value["heartbeat_seconds"] != expected_heartbeat:
        raise WorldAfterstateV2FreezeInputsError("population heartbeat binding drift")
    return value


def build_early_stage_config_v2(*, source_git: str, protocol_sha256: str,
                                capacity_sha256: str, selected_tier: str,
                                label_workers: int, evidence_root: str,
                                deadline_seconds: int) -> dict[str, Any]:
    namespace = population_namespace(source_git, protocol_sha256,
                                     capacity_sha256, selected_tier)
    if label_workers not in (1, 2, 4, 8, 12, 16, 32):
        raise WorldAfterstateV2FreezeInputsError("label workers drift")
    if not isinstance(evidence_root, str) or not evidence_root.startswith("/"):
        raise WorldAfterstateV2FreezeInputsError("evidence root drift")
    _positive(deadline_seconds, "label deadline")
    return {"schema": STAGE_INPUT_SCHEMA, "artifact_root": evidence_root,
            "population_namespace_sha256": namespace,
            "label_workers": label_workers,
            "label_deadline_seconds": deadline_seconds,
            "p0-labels-gates": {}, "optimizer-canary": {}, "nested-curve": {}}


def reopen_early_stage_config_v2_bytes(
        raw: bytes, *, expected_namespace: str | None = None,
        expected_evidence_root: str | None = None,
        expected_deadline: int | None = None,
        expected_label_workers: int | None = None) -> dict[str, Any]:
    value = _json(raw, "early-stage config")
    required = {"schema", "artifact_root", "population_namespace_sha256",
                "label_workers", "label_deadline_seconds", "p0-labels-gates",
                "optimizer-canary", "nested-curve"}
    if set(value) != required or value["schema"] != STAGE_INPUT_SCHEMA:
        raise WorldAfterstateV2FreezeInputsError("early-stage config schema drift")
    _digest(value["population_namespace_sha256"], "config namespace")
    if expected_namespace is not None and value["population_namespace_sha256"] != expected_namespace:
        raise WorldAfterstateV2FreezeInputsError("config namespace binding drift")
    if not isinstance(value["artifact_root"], str) or not value["artifact_root"].startswith("/"):
        raise WorldAfterstateV2FreezeInputsError("config evidence root drift")
    if expected_evidence_root is not None and value["artifact_root"] != expected_evidence_root:
        raise WorldAfterstateV2FreezeInputsError("config evidence root binding drift")
    if value["label_workers"] not in (1, 2, 4, 8, 12, 16, 32):
        raise WorldAfterstateV2FreezeInputsError("config label workers drift")
    _positive(value["label_deadline_seconds"], "config label deadline")
    if expected_deadline is not None and value["label_deadline_seconds"] != expected_deadline:
        raise WorldAfterstateV2FreezeInputsError("config deadline binding drift")
    if value["p0-labels-gates"] != {} or value["optimizer-canary"] != {} or value["nested-curve"] != {}:
        raise WorldAfterstateV2FreezeInputsError("config stage payload drift")
    if expected_label_workers is not None and value["label_workers"] != expected_label_workers:
        raise WorldAfterstateV2FreezeInputsError("config label worker binding drift")
    return value


def _production_ballot() -> dict[str, Any]:
    from ..ai.registry import make_bot
    from ..engine.ballot import mc_ballot
    spec = mc_ballot(make_bot(PRODUCTION_BALLOT_POLICY, seed=0))
    return {"name": spec.name, "version": spec.version, "source": spec.source,
            "config": [list(row) for row in spec.config],
            "source_digest": spec.source_digest, "digest": spec.digest}


def _continuation_ballot() -> dict[str, Any]:
    from ..ai.registry import make_bot
    from ..engine.ballot import mc_ballot
    spec = mc_ballot(make_bot(V2_CONTINUATION_POLICY, seed=0))
    return {"name": spec.name, "version": spec.version, "source": spec.source,
            "config": [list(row) for row in spec.config],
            "source_digest": spec.source_digest, "digest": spec.digest}


def _derivations() -> dict[str, Any]:
    return {
        "population_attempt": {"schema": ATTEMPT_SCHEMA,
            "function": "world_afterstate_v2_protocol.attempted_deal_identity",
            "engine_seed": "sha256(attempt identity)[:8] masked to 63 bits"},
        "production_trajectory": {"function": "world_afterstate_v2_source_driver.trajectory_policy_seed",
            "namespace": "world-afterstate-v2-source-driver-trajectory-v1",
            "actor_seats": list(ACTOR_SEATS)},
        "production_ballot": {"policy": PRODUCTION_BALLOT_POLICY,
            "function": "world_afterstate_v2_population._seed_for_deal plus world_afterstate_sources.production_ballot_identity_from_snapshot",
            "seed_derivation": "sha256({namespace: world-afterstate-v2-production-ballot-v1, deal_sha256})[:8] masked to 63 bits",
            "configuration_identity_seed": 0, "ballot": _production_ballot()},
        "continuation_identity": {"schema": IDENTITY_SCHEMA,
            "experiment_id": IDENTITY_EXPERIMENT, "world_occurrence": 0,
            "replicas": list(REPLICATES)},
        "continuation_seed": {"function": "world_afterstate_label.derive_continuation_seed",
            "purpose": "actor-visible-post-root-continuation",
            "policy": V2_CONTINUATION_POLICY, "actor_seats": list(ACTOR_SEATS)},
    }


def build_seed_registry_v2(*, source_git: str, protocol_sha256: str,
                           capacity_sha256: str, selected_tier: str) -> dict[str, Any]:
    namespace = population_namespace(source_git, protocol_sha256,
                                     capacity_sha256, selected_tier)
    return {"schema": SEED_REGISTRY_SCHEMA, "source_git": _source(source_git),
            "protocol_sha256": _digest(protocol_sha256, "protocol SHA-256"),
            "capacity_sha256": _digest(capacity_sha256, "capacity SHA-256"),
            "selected_tier": selected_tier,
            "population_namespace_sha256": namespace,
            "derivations": _derivations(),
            "seed_blocks": [dict(block) for block in _SEED_BLOCK_PAYLOADS],
            "authority": dict(AUTHORITY)}


def reopen_seed_registry_v2_bytes(raw: bytes, *, source_git: str,
                                  protocol_sha256: str, capacity_sha256: str,
                                  selected_tier: str) -> dict[str, Any]:
    value = _json(raw, "seed registry")
    expected = build_seed_registry_v2(source_git=source_git,
        protocol_sha256=protocol_sha256, capacity_sha256=capacity_sha256,
        selected_tier=selected_tier)
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise WorldAfterstateV2FreezeInputsError("seed registry authoritative reopen drift")
    return value


def build_continuation_policy_v2(*, source_git: str, protocol_sha256: str,
                                 capacity_sha256: str, selected_tier: str) -> dict[str, Any]:
    namespace = population_namespace(source_git, protocol_sha256,
                                     capacity_sha256, selected_tier)
    production_ballot = _production_ballot()
    continuation_ballot = _continuation_ballot()
    return {"schema": CONTINUATION_POLICY_SCHEMA, "source_git": _source(source_git),
            "protocol_sha256": _digest(protocol_sha256, "protocol SHA-256"),
            "capacity_sha256": _digest(capacity_sha256, "capacity SHA-256"),
            "selected_tier": selected_tier,
            "population_namespace_sha256": namespace,
            "production_ballot_policy": PRODUCTION_BALLOT_POLICY,
            "production_ballot": production_ballot,
            "production_ballot_identity": production_ballot,
            "production_ballot_digest": production_ballot["digest"],
            "continuation_policy": V2_CONTINUATION_POLICY,
            "continuation_ballot": continuation_ballot,
            "continuation_ballot_identity": continuation_ballot,
            "continuation_ballot_digest": continuation_ballot["digest"],
            "actor_seats": list(ACTOR_SEATS),
            "actor_policy_identities": [
                {"seat": seat, "policy": V2_CONTINUATION_POLICY,
                 "ballot": continuation_ballot}
                for seat in ACTOR_SEATS],
            "identity_experiment": IDENTITY_EXPERIMENT,
            "replicas": list(REPLICATES),
            "root_team_perspective": {
                "root_seat": 0, "fixed": True,
                "meaning": "team of the actor at the root decision"},
            "root_team_convention": "root seat 0; team is derived from root attacker/defender role",
            "common_random_number_convention": "one continuation identity per state group and replica, shared by every candidate",
            "authority": dict(AUTHORITY)}


def reopen_continuation_policy_v2_bytes(raw: bytes, *, source_git: str,
                                        protocol_sha256: str, capacity_sha256: str,
                                        selected_tier: str) -> dict[str, Any]:
    value = _json(raw, "continuation policy")
    expected = build_continuation_policy_v2(source_git=source_git,
        protocol_sha256=protocol_sha256, capacity_sha256=capacity_sha256,
        selected_tier=selected_tier)
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise WorldAfterstateV2FreezeInputsError(
            "continuation policy authoritative reopen drift")
    return value


def build_freeze_inputs_v2(*, source_git: str, capacity_raw: bytes,
                           evidence_root: str, deadline_seconds: int,
                           heartbeat_seconds: int,
                           max_attempts_per_slot: int) -> dict[str, bytes]:
    """Derive protocol plus all four inputs without touching outcome data."""
    _source(source_git)
    _positive(deadline_seconds, "scientific deadline")
    _positive(heartbeat_seconds, "scientific heartbeat")
    if max_attempts_per_slot != D256_MAX_ATTEMPTS_PER_SLOT:
        raise WorldAfterstateV2FreezeInputsError(
            "D256 population attempt cap drift")
    if not isinstance(evidence_root, str) or not evidence_root.startswith("/"):
        raise WorldAfterstateV2FreezeInputsError("evidence root drift")
    _receipt, tier, population_workers, label_workers = capacity_context(capacity_raw)
    protocol_raw = protocol_bytes()
    protocol_sha = _sha_bytes(protocol_raw)
    capacity_sha = _sha_bytes(capacity_raw)
    population = build_population_adapter_input_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier=tier,
        workers=population_workers, deadline_seconds=deadline_seconds,
        heartbeat_seconds=heartbeat_seconds,
        max_attempts_per_slot=max_attempts_per_slot)
    config = build_early_stage_config_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier=tier,
        label_workers=label_workers, evidence_root=evidence_root,
        deadline_seconds=deadline_seconds)
    seed = build_seed_registry_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier=tier)
    policy = build_continuation_policy_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier=tier)
    return {"protocol": protocol_raw,
            "population": canonical_json_bytes(population),
            "config": canonical_json_bytes(config),
            "seed": canonical_json_bytes(seed),
            "continuation-policy": canonical_json_bytes(policy)}


def _publish_one(path: Path, raw: bytes) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise WorldAfterstateV2FreezeInputsError("input output path occupied")
    parent = path.parent
    cursor = parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise WorldAfterstateV2FreezeInputsError("input output parent symlink")
        cursor = cursor.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    partial = parent / f".{path.name}.partial"
    if partial.exists() or partial.is_symlink():
        raise WorldAfterstateV2FreezeInputsError("input output partial path occupied")
    try:
        with partial.open("xb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(partial, 0o400)
        os.link(partial, path, follow_symlinks=False)
        partial.unlink()
        descriptor = os.open(parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    except OSError as exc:
        if partial.exists() and not partial.is_symlink():
            try: partial.unlink()
            except OSError: pass
        raise WorldAfterstateV2FreezeInputsError("input publication refused") from exc


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically install a complete input directory without replacement."""
    library = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    try:
        if sys.platform.startswith("linux"):
            operation = library.renameat2
            operation.argtypes = (ctypes.c_int, ctypes.c_char_p,
                                  ctypes.c_int, ctypes.c_char_p,
                                  ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(-100, source_raw, -100, destination_raw, 1)
        elif sys.platform == "darwin":
            operation = library.renamex_np
            operation.argtypes = (ctypes.c_char_p, ctypes.c_char_p,
                                  ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(source_raw, destination_raw, 0x00000004)
        else:
            raise WorldAfterstateV2FreezeInputsError(
                "atomic input publication is unavailable")
    except AttributeError as exc:
        raise WorldAfterstateV2FreezeInputsError(
            "atomic input publication is unavailable") from exc
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise WorldAfterstateV2FreezeInputsError("input output path occupied")
    raise WorldAfterstateV2FreezeInputsError(
        f"atomic input publication refused: errno {error}")


def publish_inputs_v2(directory: Path | str, *, protocol: bytes,
                      population: Mapping[str, Any], config: Mapping[str, Any],
                      seed: Mapping[str, Any], continuation_policy: Mapping[str, Any]) -> tuple[Path, ...]:
    root = Path(directory)
    if root.exists() or root.is_symlink():
        raise WorldAfterstateV2FreezeInputsError("input output path occupied")
    if not root.is_absolute():
        raise WorldAfterstateV2FreezeInputsError("input output directory drift")
    reopen_protocol_bytes(protocol)
    population_raw = canonical_json_bytes(dict(population))
    config_raw = canonical_json_bytes(dict(config))
    seed_raw = canonical_json_bytes(dict(seed))
    policy_raw = canonical_json_bytes(dict(continuation_policy))
    seed_value = _json(seed_raw, "seed")
    policy_value = _json(policy_raw, "continuation policy")
    common_keys = ("source_git", "protocol_sha256", "capacity_sha256",
                   "selected_tier", "population_namespace_sha256")
    if (any(seed_value.get(key) != policy_value.get(key) for key in common_keys)
            or seed_value.get("protocol_sha256") != _sha_bytes(protocol)):
        raise WorldAfterstateV2FreezeInputsError("input bundle binding drift")
    try:
        namespace = seed_value["population_namespace_sha256"]
        reopen_population_adapter_input_v2_bytes(
            population_raw, expected_namespace=namespace)
        reopen_early_stage_config_v2_bytes(
            config_raw, expected_namespace=namespace)
        for raw, opener in (
                (seed_raw, reopen_seed_registry_v2_bytes),
                (policy_raw, reopen_continuation_policy_v2_bytes)):
            opener(raw, source_git=seed_value["source_git"],
                   protocol_sha256=seed_value["protocol_sha256"],
                   capacity_sha256=seed_value["capacity_sha256"],
                   selected_tier=seed_value["selected_tier"])
    except (KeyError, WorldAfterstateV2FreezeInputsError):
        raise
    except Exception as exc:
        raise WorldAfterstateV2FreezeInputsError(
            "input bundle authoritative reopen refused") from exc
    values = (protocol, population_raw, config_raw, seed_raw, policy_raw)
    names = ("protocol.json", "population.json", "config.json", "seed.json",
             "continuation-policy.json")
    parent = root.parent
    cursor = parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise WorldAfterstateV2FreezeInputsError(
                "input output parent symlink")
        cursor = cursor.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = parent / f".{root.name}.partial"
    if staging.exists() or staging.is_symlink():
        raise WorldAfterstateV2FreezeInputsError(
            "input output partial path occupied")
    staging.mkdir(mode=0o700)
    try:
        for name, raw in zip(names, values, strict=True):
            _publish_one(staging / name, raw)
        descriptor = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _rename_noreplace(staging, root)
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        if staging.is_dir() and not staging.is_symlink():
            for child in staging.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            staging.rmdir()
        raise
    return tuple(root / name for name in names)


# Compatibility spellings used by small operator wrappers and tests.
build_population_input_v2 = build_population_adapter_input_v2
reopen_population_input_v2_bytes = reopen_population_adapter_input_v2_bytes
build_config_input_v2 = build_early_stage_config_v2
reopen_config_input_v2_bytes = reopen_early_stage_config_v2_bytes
build_seed_registry_input_v2 = build_seed_registry_v2
build_continuation_policy_input_v2 = build_continuation_policy_v2

__all__ = [
    "ACTOR_SEATS", "AUTHORITY", "CONTINUATION_POLICY_SCHEMA", "FreezeInputsError",
    "NAMESPACE_SCHEMA", "POPULATION_INPUT_SCHEMA", "PROTOCOL_INPUT_SCHEMA",
    "SEED_REGISTRY_SCHEMA", "STAGE_INPUT_SCHEMA",
    "WorldAfterstateV2FreezeInputsError", "build_config_input_v2",
    "build_continuation_policy_input_v2", "build_continuation_policy_v2",
    "build_early_stage_config_v2", "build_freeze_inputs_v2",
    "build_population_adapter_input_v2", "build_population_input_v2",
    "build_seed_registry_input_v2", "build_seed_registry_v2", "capacity_context",
    "population_namespace", "protocol_bytes", "publish_inputs_v2",
    "reopen_config_input_v2_bytes", "reopen_continuation_policy_v2_bytes",
    "reopen_early_stage_config_v2_bytes", "reopen_population_adapter_input_v2_bytes",
    "reopen_population_input_v2_bytes", "reopen_protocol_bytes",
    "reopen_seed_registry_v2_bytes",
]
