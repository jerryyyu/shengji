from __future__ import annotations

import hashlib
import json
import os

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_outcome, reopen_afterstate_audit
from shengji.rl.world_afterstate_controller import (
    build_scientific_dataset, publish_scientific_dataset,
    reopen_scientific_dataset)
from shengji.rl.world_afterstate_experiment import FOLD_COUNTS
from shengji.rl.world_afterstate_label import continuation_identity

from test_world_afterstate_population_builder import _build


def _fake_label_task(arguments):
    freeze, group, candidate, replicate, audit_raw = arguments
    audit = json.loads(audit_raw)
    rnd = reopen_afterstate_audit(audit)
    identity = continuation_identity(
        experiment_id=freeze, state_group_id=group["state_group_id"],
        fold=group["fold"], world_occurrence=0, replicate=replicate)
    outcome = build_outcome(
        audit["successor_sha256"], 120,
        rnd.is_attacker(audit["root_seat"]))
    continuation = {"continuation_identity": identity, "outcome": outcome}
    body = {
        "schema": "world-afterstate-e3-dataset-row-v0",
        "freeze_sha256": freeze, "group_sha256": group["group_sha256"],
        "state_group_id": group["state_group_id"], "fold": group["fold"],
        "candidate_index": candidate, "world_occurrence": 0,
        "replicate": replicate, "audit": audit,
        "audit_sha256": hashlib.sha256(audit_raw).hexdigest(),
        "continuation": continuation,
        "continuation_sha256": hashlib.sha256(
            canonical_json_bytes(continuation)).hexdigest(),
        "successor_sha256": audit["successor_sha256"],
        "signed_level_category": outcome["signed_level_category"],
        "authority": {
            "training_authorized": False,
            "report_opening_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
    return {**body, "row_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


def test_dataset_stage_parallel_contract_and_split_reader_are_bound(
        monkeypatch, tmp_path):
    population = _build()
    progress = []
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_controller._label_task",
        _fake_label_task)
    dataset = build_scientific_dataset(
        freeze_sha256="f" * 64,
        population_manifest=population.population_manifest,
        audit_materials={material.group["state_group_id"]:
                         material.audit_raws
                         for material in population.materials},
        repetitions_by_fold={fold: 1 for fold in FOLD_COUNTS},
        workers=1, wall_budget_nanoseconds=10**18,
        progress=lambda completed, total:
            progress.append((completed, total)))
    assert progress[-1] == (520, 520)
    root = tmp_path / "dataset"
    publish_scientific_dataset(
        root, dataset,
        population_manifest=population.population_manifest)

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_dataset_row",
        lambda value, *, group, allowed_folds: type(
            "Reopened", (), {"row_sha256": value["row_sha256"]})())
    manifest, train = reopen_scientific_dataset(
        root, population_manifest=population.population_manifest,
        allowed_folds=("train",))
    assert len(train) == manifest["fold_row_counts"]["train"]
    assert len(train) == FOLD_COUNTS["train"]

    first = root / manifest["rows"][0]["relative_path"]
    os.chmod(first, 0o600)
    with pytest.raises(Exception, match="mutable"):
        reopen_scientific_dataset(
            root, population_manifest=population.population_manifest,
            allowed_folds=(manifest["rows"][0]["fold"],))


def test_dataset_deadline_expires_before_any_result_can_seal(monkeypatch):
    population = _build()
    readings = iter((0, 2))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_controller.time.monotonic_ns",
        lambda: next(readings))
    with pytest.raises(Exception, match="dataset generation deadline expired"):
        build_scientific_dataset(
            freeze_sha256="f" * 64,
            population_manifest=population.population_manifest,
            audit_materials={material.group["state_group_id"]:
                             material.audit_raws
                             for material in population.materials},
            repetitions_by_fold={fold: 1 for fold in FOLD_COUNTS},
            workers=1, wall_budget_nanoseconds=1)
