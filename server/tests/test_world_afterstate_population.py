from __future__ import annotations

import copy
import hashlib
import json
import os
import random
from collections import Counter

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import (
    actor_visible_root_identity, build_afterstate_audit, root_replay)
from shengji.rl.world_afterstate_experiment import (
    FOLD_COUNTS, SOURCE_COUNTS, SOURCE_FOLD_COUNTS)
from shengji.rl.world_afterstate_population import (
    GROUP_SCHEMA, MANIFEST_SCHEMA, WorldAfterstatePopulationError,
    build_population_audit_manifest, build_population_group,
    build_population_manifest, fold_for_deal_group,
    reopen_population_audit_manifest, select_population_groups,
    validate_population_audit_manifest, validate_population_group,
    validate_population_manifest)


def _sha(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _deal_group(fold: str, index: int) -> str:
    nonce = index
    while True:
        value = hashlib.sha256(f"deal-{fold}-{nonce}".encode()).hexdigest()
        if fold_for_deal_group(value) == fold:
            return value
        nonce += 1


def _natural_group():
    seed = 884_100_001
    rnd = Round("7", 0, random.Random(seed))
    bot = make_bot("smart", seed=seed + 1)
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    burial = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    root = rnd.turn
    assert root is not None
    source = root_replay(
        deal_seed=seed, initial_banker=0, trump_rank="7",
        declarations=[], buried=burial, plays=[], root_seat=root)
    cards = list(dict.fromkeys(rnd.hands[root]))[:2]
    candidates = [[card] for card in cards]
    hands = {seat: list(rnd.hands[seat]) for seat in range(4)}
    audits = [canonical_json_bytes(build_afterstate_audit(
        source, hands, rnd.buried, action)) for action in candidates]
    identity = actor_visible_root_identity(rnd, root, candidates)
    deal = _deal_group("train", 1)
    return build_population_group(
        deal_group_sha256=deal, source="production-policy",
        fold="train", actor_identity=identity, audit_raws=audits), audits


def _synthetic_group(index: int, fold: str, source: str):
    deal = _deal_group(fold, index + 10_000)
    decision = hashlib.sha256(f"decision-{index}".encode()).hexdigest()
    candidate = {
        "candidate_index": 0,
        "action_sha256": hashlib.sha256(f"action-{index}".encode()).hexdigest(),
        "audit_sha256": hashlib.sha256(f"audit-{index}".encode()).hexdigest(),
        "successor_sha256":
            hashlib.sha256(f"successor-{index}".encode()).hexdigest(),
        "protected_incumbent": True,
    }
    body = {
        "schema": GROUP_SCHEMA,
        "state_group_id": _sha({
            "deal_group_sha256": deal, "decision_sha256": decision}),
        "deal_group_sha256": deal,
        "decision_sha256": decision,
        "selection_priority_sha256": _sha({
            "namespace": MANIFEST_SCHEMA, "decision_sha256": decision}),
        "source": source,
        "fold": fold,
        "trump_rank": RANKS[index % len(RANKS)],
        "trump_mode": ("C", "D", "H", "S", "NT")[index % 5],
        "root_role": ("attacker", "defender")[index % 2],
        "play_phase": ("early", "middle", "late")[index % 3],
        "position": ("lead", "follow")[index % 2],
        "points_bucket": (
            "0-39", "40-79", "80-119", "120-159", "160+")[index % 5],
        "mechanics_hard_reasons": (
            ["wide-ballot"] if source == "mechanics-hard" else []),
        "candidate_count": 1,
        "candidates": [candidate],
        "complete_ballot": True,
        "protected_incumbent_index": 0,
        "outcome_opened": False,
        "model_input_contains_metadata": False,
    }
    return {**body, "group_sha256": _sha(body)}


def _manifest_groups():
    fold_sources = [
        (fold, source)
        for fold, counts in SOURCE_FOLD_COUNTS.items()
        for source, count in counts.items()
        for _ in range(count)
    ]
    return [_synthetic_group(index, fold, source)
            for index, (fold, source) in enumerate(fold_sources)]


def _oversubscribed_inventory():
    rows = []
    index = 100_000
    for fold in FOLD_COUNTS:
        # Production must carry every required axis in each fold. Cycling a
        # 390-row block makes all axis combinations available well beyond the
        # largest 219-row quota without relying on PT/mechanics rows.
        for offset in range(390):
            rows.append(_synthetic_group(index + offset, fold,
                                         "production-policy"))
        index += 1_000
        for source in ("reviewed-pt-sol0", "mechanics-hard"):
            required = SOURCE_FOLD_COUNTS[fold][source]
            for offset in range(required + 7):
                rows.append(_synthetic_group(index + offset, fold, source))
            index += 1_000
    return rows


def test_group_binds_actor_visible_ballot_to_exact_engine_audits():
    group, audits = _natural_group()
    validate_population_group(group)
    assert group["candidate_count"] == 2
    assert group["candidates"][0]["protected_incumbent"] is True
    assert group["outcome_opened"] is False

    forged = list(audits)
    forged.reverse()
    with pytest.raises(WorldAfterstatePopulationError,
                       match="action/audit binding drift"):
        # Identity retains the original candidate order.
        first, _ = _natural_group()
        # Recovering it from a group is intentionally impossible; use the
        # wrong audit order against a fresh actor identity instead.
        seed = 884_100_001
        rnd = Round("7", 0, random.Random(seed))
        bot = make_bot("smart", seed=seed + 1)
        while rnd.phase == "deal":
            rnd.deal_next()
        rnd.finalize_declare()
        burial = bot.decide_bury(rnd, rnd.banker)
        rnd.bury(rnd.banker, burial)
        candidates = [[card] for card in list(
            dict.fromkeys(rnd.hands[rnd.turn]))[:2]]
        identity = actor_visible_root_identity(rnd, rnd.turn, candidates)
        build_population_group(
            deal_group_sha256=first["deal_group_sha256"],
            source="production-policy", fold="train",
            actor_identity=identity, audit_raws=forged)


def test_manifest_closes_population_quota_coverage_and_metadata():
    groups = _manifest_groups()
    manifest = build_population_manifest(groups)
    validate_population_manifest(manifest)
    assert manifest["group_count"] == sum(FOLD_COUNTS.values())
    assert manifest["candidate_count"] == manifest["group_count"]
    raw = canonical_json_bytes(manifest)
    assert b"deal_seed" not in raw
    assert b"attacker_points" not in raw

    with pytest.raises(WorldAfterstatePopulationError, match="quota drift"):
        build_population_manifest(groups[:-1])
    forged = copy.deepcopy(manifest)
    forged["groups"][0]["fold"] = "report"
    with pytest.raises(WorldAfterstatePopulationError):
        validate_population_manifest(forged)

    forged = copy.deepcopy(groups)
    left = next(row for row in forged if row["fold"] == "report"
                and row["source"] == "production-policy")
    right = next(row for row in forged if row["fold"] == "train"
                 and row["source"] == "reviewed-pt-sol0")
    left["source"], right["source"] = right["source"], left["source"]
    # Preserve global source counts while breaking the preregistered
    # source-by-fold population.
    left["group_sha256"] = _sha({key: value for key, value in left.items()
                                  if key != "group_sha256"})
    right["group_sha256"] = _sha({key: value for key, value in right.items()
                                   if key != "group_sha256"})
    with pytest.raises(WorldAfterstatePopulationError,
                       match="source/fold quota drift"):
        build_population_manifest(forged)


def test_selector_is_order_invariant_and_production_covers_each_fold():
    inventory = _oversubscribed_inventory()
    selected = select_population_groups(inventory)
    reversed_selected = select_population_groups(list(reversed(inventory)))
    assert selected == reversed_selected
    manifest = build_population_manifest(selected)
    assert manifest["group_count"] == sum(FOLD_COUNTS.values())
    for fold in FOLD_COUNTS:
        production = [row for row in selected
                      if row["fold"] == fold
                      and row["source"] == "production-policy"]
        assert {row["trump_rank"] for row in production} == set(RANKS)
        assert {row["trump_mode"] for row in production} \
            == {"C", "D", "H", "S", "NT"}
        assert {row["root_role"] for row in production} \
            == {"attacker", "defender"}
        assert {row["play_phase"] for row in production} \
            == {"early", "middle", "late"}
        assert {row["position"] for row in production} == {"lead", "follow"}


def test_selector_refuses_when_only_nonproduction_rows_cover_no_trump():
    inventory = _oversubscribed_inventory()
    forged = []
    for row in inventory:
        value = copy.deepcopy(row)
        if value["fold"] == "report" \
                and value["source"] == "production-policy" \
                and value["trump_mode"] == "NT":
            value["trump_mode"] = "C"
            value["group_sha256"] = _sha({
                key: item for key, item in value.items()
                if key != "group_sha256"})
        forged.append(value)
    with pytest.raises(WorldAfterstatePopulationError,
                       match="report axis coverage"):
        select_population_groups(forged)


def test_private_audit_manifest_binds_exact_once_read_bytes(tmp_path):
    _group, audits = _natural_group()
    plain_raw = audits[0]
    plain_audit = json.loads(plain_raw)
    seed = 884_100_051
    rnd = Round("7", 0, random.Random(seed))
    bot = make_bot("smart", seed=seed + 1)
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    burial = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, burial)
    pair = next(card for card, count in Counter(rnd.hands[rnd.turn]).items()
                if count >= 2)
    source = root_replay(
        deal_seed=seed, initial_banker=0, trump_rank="7",
        declarations=[], buried=burial, plays=[], root_seat=rnd.turn)
    pair_raw = canonical_json_bytes(build_afterstate_audit(
        source, {seat: list(rnd.hands[seat]) for seat in range(4)},
        rnd.buried, [pair, pair]))
    pair_audit = json.loads(pair_raw)
    groups = _manifest_groups()
    raw_by_group = {}
    for group in groups:
        raw = pair_raw if group["source"] == "mechanics-hard" else plain_raw
        audit = pair_audit if group["source"] == "mechanics-hard" \
            else plain_audit
        if group["source"] == "mechanics-hard":
            group["mechanics_hard_reasons"] = ["multi-card-action"]
        group["candidates"][0].update({
            "action_sha256": _sha(audit["attempted_action"]),
            "audit_sha256": hashlib.sha256(raw).hexdigest(),
            "successor_sha256": audit["successor_sha256"],
        })
        group["group_sha256"] = _sha({
            key: value for key, value in group.items()
            if key != "group_sha256"})
        raw_by_group[group["state_group_id"]] = raw
    manifest = build_population_manifest(groups)
    materials = [(group, (raw_by_group[group["state_group_id"]],))
                 for group in manifest["groups"]]
    private = build_population_audit_manifest(manifest, materials)
    validate_population_audit_manifest(private, manifest)
    forged = copy.deepcopy(private)
    forged["rows"].pop()
    with pytest.raises(WorldAfterstatePopulationError,
                       match="reconstruction drift"):
        validate_population_audit_manifest(forged, manifest)
    root = tmp_path / "audits"
    for row in private["rows"]:
        path = root / row["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_by_group[row["state_group_id"]])
        os.chmod(path, 0o400)
    reopened = reopen_population_audit_manifest(private, manifest, root)
    assert len(reopened) == len(groups)
    assert all(values == (raw_by_group[key],)
               for key, values in reopened.items())

    extra = root / "unexpected.json"
    extra.write_bytes(plain_raw)
    os.chmod(extra, 0o400)
    with pytest.raises(WorldAfterstatePopulationError,
                       match="file population drift"):
        reopen_population_audit_manifest(private, manifest, root)
