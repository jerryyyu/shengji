from __future__ import annotations

import copy
import hashlib
import inspect
import itertools
import json

import pytest
import torch

from shengji.rl import world_afterstate_population as POPULATION
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import (
    actor_visible_root_identity, build_afterstate_audit, replay_root_state)
from shengji.rl.world_afterstate_population import (
    AUDIT_MANIFEST_SCHEMA, MANIFEST_SCHEMA, POPULATION_AUTHORITY,
    WorldAfterstatePopulationError, build_population_manifest,
    reopen_population_audit_fold, validate_population_audit_manifest)
from shengji.rl.world_afterstate_v1_evaluation import (
    inference_population_sha256)
from shengji.rl.world_afterstate_v1_inference import (
    AUTHORITY, COHORT_INPUT_NAMES, INFERENCE_INPUT_NAMES,
    WorldAfterstateV1InferenceError,
    build_calibration_inference_batch,
    validate_calibration_inference_build,
    validate_calibration_inference_manifest)

from test_world_afterstate_population import (
    _manifest_groups, _natural_group)


def _sha(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fixture(tmp_path):
    _natural, seed_raws = _natural_group()
    seed_audit = json.loads(seed_raws[0])
    source = seed_audit["source_state"]
    root_seat = seed_audit["root_seat"]
    hands = {int(seat): cards for seat, cards in
             seed_audit["complete_world_pre_action"]["hands"].items()}
    buried = seed_audit["complete_world_pre_action"]["buried"]
    rnd = replay_root_state(source)
    cards = sorted(set(hands[root_seat]))
    ballots = itertools.permutations(cards, 2)
    groups = copy.deepcopy(_manifest_groups())
    raw_by_state = {}
    for group in groups:
        if group["fold"] != "calibration":
            continue
        left, right = next(ballots)
        actions = ([left], [right])
        raws = tuple(canonical_json_bytes(build_afterstate_audit(
            source, hands, buried, action)) for action in actions)
        audits = [json.loads(raw) for raw in raws]
        actor = actor_visible_root_identity(rnd, root_seat, actions)
        group["decision_sha256"] = actor["decision_sha256"]
        group["state_group_id"] = _sha({
            "deal_group_sha256": group["deal_group_sha256"],
            "decision_sha256": group["decision_sha256"],
        })
        group["selection_priority_sha256"] = _sha({
            "namespace": MANIFEST_SCHEMA,
            "decision_sha256": group["decision_sha256"],
        })
        group["candidate_count"] = len(raws)
        group["candidates"] = [{
            "candidate_index": index,
            "action_sha256": _sha(audit["attempted_action"]),
            "audit_sha256": hashlib.sha256(raw).hexdigest(),
            "successor_sha256": audit["successor_sha256"],
            "protected_incumbent": index == 0,
        } for index, (raw, audit) in enumerate(zip(
            raws, audits, strict=True))]
        group["group_sha256"] = _sha({
            key: value for key, value in group.items()
            if key != "group_sha256"})
        raw_by_state[group["state_group_id"]] = raws
    population = build_population_manifest(groups)

    rows = []
    for group in population["groups"]:
        for index, candidate in enumerate(group["candidates"]):
            byte_count = len(raw_by_state[group["state_group_id"]][index]) \
                if group["fold"] == "calibration" else 1
            rows.append({
                "state_group_id": group["state_group_id"],
                "candidate_index": index,
                "relative_path": (
                    f"{group['state_group_id']}/{index:03d}.json"),
                "byte_count": byte_count,
                "audit_sha256": candidate["audit_sha256"],
            })
    rows.sort(key=lambda row: (
        row["state_group_id"], row["candidate_index"]))
    body = {
        "schema": AUDIT_MANIFEST_SCHEMA,
        "population_manifest_sha256": population["manifest_sha256"],
        "group_count": population["group_count"],
        "audit_count": len(rows),
        "total_bytes": sum(row["byte_count"] for row in rows),
        "rows": rows,
        "contains_private_complete_worlds": True,
        "outcome_opened": False,
        "authority": dict(POPULATION_AUTHORITY),
    }
    audit_manifest = {**body, "manifest_sha256": _sha(body)}
    validate_population_audit_manifest(audit_manifest, population)

    root = tmp_path / "audits"
    root.mkdir()
    for group in population["groups"]:
        if group["fold"] != "calibration":
            continue
        directory = root / group["state_group_id"]
        directory.mkdir()
        for index, raw in enumerate(raw_by_state[group["state_group_id"]]):
            path = directory / f"{index:03d}.json"
            path.write_bytes(raw)
            path.chmod(0o400)
    return population, audit_manifest, root, raw_by_state


def _rehash_audit_manifest(value, population):
    value["population_manifest_sha256"] = population["manifest_sha256"]
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    value["manifest_sha256"] = _sha(body)
    return value


def test_fold_reader_opens_only_calibration_and_builds_target_free_pairs(
        tmp_path, monkeypatch):
    population, audit_manifest, root, _raws = _fixture(tmp_path)
    opened = []
    original = POPULATION._stable_audit_read

    def observe(path):
        opened.append(path)
        return original(path)

    monkeypatch.setattr(POPULATION, "_stable_audit_read", observe)
    materials = reopen_population_audit_fold(
        audit_manifest, population, root, fold="calibration")
    calibration = {group["state_group_id"]
                   for group in population["groups"]
                   if group["fold"] == "calibration"}
    assert len(materials) == len(calibration) == 52
    assert opened
    assert {path.parent.name for path in opened} == calibration

    batches, manifest = build_calibration_inference_batch(
        population, audit_manifest, materials)
    assert set(batches) == set(INFERENCE_INPUT_NAMES)
    natural = batches["natural"]
    identical = batches["identical-successor"]
    assert len(natural.state_group_ids) == 52
    assert not hasattr(natural, "targets")
    assert not hasattr(natural, "advantage_levels")
    assert natural.state_group_ids == identical.state_group_ids
    assert natural.candidate_successor_sha256s \
        == identical.candidate_successor_sha256s
    assert not torch.equal(
        natural.candidate.public, identical.candidate.public)
    assert all(torch.equal(
        getattr(identical.incumbent, field),
        getattr(identical.candidate, field))
        for field in (
            "public", "history", "history_lengths", "world",
            "perspective"))
    assert manifest["pair_count"] == 52
    assert manifest["audit_count"] == 104
    assert manifest["inference_population_sha256s"] == {
        name: inference_population_sha256(batches[name])
        for name in INFERENCE_INPUT_NAMES
    }
    assert manifest["cohort_input_names"] == COHORT_INPUT_NAMES
    assert manifest["identical_successor_changed_pair_count"] == 52
    assert manifest["identical_successor_dose_ppm"] == 1_000_000
    assert manifest["authority"] == AUTHORITY
    assert set(manifest["authority"].values()) == {False}
    assert b'"advantage_levels"' not in canonical_json_bytes(manifest)
    assert b'"signed_level_category"' not in canonical_json_bytes(manifest)
    validate_calibration_inference_build(
        batches, manifest, population, audit_manifest, materials)
    validate_calibration_inference_manifest(manifest)

    forged = copy.deepcopy(manifest)
    forged["pair_count"] += 1
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="control dose drift"):
        validate_calibration_inference_manifest(forged)
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="build reconstruction drift"):
        validate_calibration_inference_build(
            batches, forged, population, audit_manifest, materials)

    mutated = copy.deepcopy(batches)
    mutated["natural"].candidate.public[0, 0] += 1.0
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="build reconstruction drift"):
        validate_calibration_inference_build(
            mutated, manifest, population, audit_manifest, materials)

    lost_control = copy.deepcopy(batches)
    lost_control["identical-successor"] = lost_control["natural"]
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="build reconstruction drift"):
        validate_calibration_inference_build(
            lost_control, manifest, population, audit_manifest, materials)


def test_calibration_builder_refuses_wrong_population_missing_and_swapped(
        tmp_path):
    population, audit_manifest, root, _raws = _fixture(tmp_path)
    materials = reopen_population_audit_fold(
        audit_manifest, population, root, fold="calibration")
    state = sorted(materials)[0]

    wrong_fold = dict(materials)
    wrong_fold["f" * 64] = wrong_fold.pop(state)
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="audit population drift"):
        build_calibration_inference_batch(
            population, audit_manifest, wrong_fold)

    missing = dict(materials)
    missing[state] = missing[state][:-1]
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="ballot population drift"):
        build_calibration_inference_batch(
            population, audit_manifest, missing)

    swapped = dict(materials)
    swapped[state] = tuple(reversed(swapped[state]))
    with pytest.raises(WorldAfterstateV1InferenceError,
                       match="candidate binding drift"):
        build_calibration_inference_batch(
            population, audit_manifest, swapped)


def test_calibration_successor_binding_and_selected_file_population_fail(
        tmp_path):
    population, audit_manifest, root, _raws = _fixture(tmp_path)
    forged_population = copy.deepcopy(population)
    group = next(group for group in forged_population["groups"]
                 if group["fold"] == "calibration")
    group["candidates"][1]["successor_sha256"] = "f" * 64
    group["group_sha256"] = _sha({
        key: value for key, value in group.items()
        if key != "group_sha256"})
    forged_population = build_population_manifest(
        forged_population["groups"])
    forged_audit = _rehash_audit_manifest(
        copy.deepcopy(audit_manifest), forged_population)
    with pytest.raises(WorldAfterstatePopulationError,
                       match="successor binding drift"):
        reopen_population_audit_fold(
            forged_audit, forged_population, root, fold="calibration")

    state = next(group["state_group_id"]
                 for group in population["groups"]
                 if group["fold"] == "calibration")
    extra = root / state / "extra.json"
    extra.write_bytes(b"{}\n")
    extra.chmod(0o400)
    with pytest.raises(WorldAfterstatePopulationError,
                       match="file population drift"):
        reopen_population_audit_fold(
            audit_manifest, population, root, fold="calibration")


def test_calibration_inference_api_has_no_label_or_fold_selection_surface():
    assert tuple(inspect.signature(
        build_calibration_inference_batch).parameters) == (
            "population_manifest", "audit_manifest", "materials")
