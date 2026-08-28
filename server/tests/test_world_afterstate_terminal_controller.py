from __future__ import annotations

import hashlib
import json
import stat

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import (
    actor_visible_root_identity, build_outcome, reopen_afterstate_audit,
    replay_root_state)
from shengji.rl.world_afterstate_dataset import (
    build_dataset_row, reopen_dataset_row_static)
from shengji.rl.world_afterstate_label import continuation_identity
from shengji.rl.world_afterstate_model import (
    CAPACITY_SHAPES, new_world_afterstate_model)
from shengji.rl.world_afterstate_population import build_population_group
from shengji.rl.world_afterstate_terminal_controller import (
    WorldAfterstateTerminalControllerError, derive_terminal_evidence,
    run_open_report, validate_terminal_evidence, verify_terminal_artifact)

from test_world_afterstate_population import _deal_group, _natural_group


def _group(fold: str, index: int):
    _base, audits = _natural_group()
    records = [json.loads(raw) for raw in audits]
    source = records[0]["source_state"]
    rnd = replay_root_state(source)
    candidates = [record["attempted_action"] for record in records]
    identity = actor_visible_root_identity(
        rnd, source["root_seat"], candidates)
    return build_population_group(
        deal_group_sha256=_deal_group(fold, 80_000 + index),
        source="production-policy", fold=fold, actor_identity=identity,
        audit_raws=audits), audits


def _rows(monkeypatch, fold: str, *, group_count: int, repetitions: int,
          offset: int):
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_afterstate_continuation",
        lambda _audit, value: value)
    groups = []
    rows = []
    for group_index in range(group_count):
        group, audits = _group(fold, offset + group_index * 1_000)
        groups.append(group)
        for candidate, audit_raw in enumerate(audits):
            audit = json.loads(audit_raw)
            rnd = reopen_afterstate_audit(audit)
            for replicate in range(repetitions):
                points = 70 + group_index * 35 + candidate * 55 + replicate * 5
                identity = continuation_identity(
                    experiment_id="f" * 64,
                    state_group_id=group["state_group_id"], fold=fold,
                    world_occurrence=0, replicate=replicate)
                continuation = {
                    "continuation_identity": identity,
                    "outcome": build_outcome(
                        audit["successor_sha256"], points,
                        rnd.is_attacker(audit["root_seat"])),
                }
                row = build_dataset_row(
                    freeze_sha256="f" * 64, group=group,
                    candidate_index=candidate, world_occurrence=0,
                    replicate=replicate, audit_raw=audit_raw,
                    continuation_raw=canonical_json_bytes(continuation))
                raw = canonical_json_bytes(row)
                reopened = reopen_dataset_row_static(
                    row, group=group, allowed_folds=(fold,))
                rows.append(({
                    "fold": fold,
                    "external_sha256": hashlib.sha256(raw).hexdigest(),
                    "row_sha256": row["row_sha256"],
                }, reopened))
    return groups, rows


def test_terminal_controller_executes_natural_and_control_paths(monkeypatch):
    train_groups, train_rows = _rows(
        monkeypatch, "train", group_count=2, repetitions=1, offset=0)
    report_groups, report_rows = _rows(
        monkeypatch, "report", group_count=2, repetitions=4, offset=10)
    provider_groups, provider_rows = _rows(
        monkeypatch, "provider-audit", group_count=2, repetitions=8,
        offset=20)
    population = {"groups": [
        *train_groups, *report_groups, *provider_groups]}
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "validate_population_manifest", lambda _value: None)
    models = tuple(new_world_afterstate_model(
        700 + index, CAPACITY_SHAPES["small"]) for index in range(8))
    freeze = {
        "freeze_sha256": "f" * 64,
        "learner": {"member_count": 8, "batch_size": 16},
        "gates": {"report_wall_cap_seconds": 3600,
                  "independent_verification_wall_cap_seconds": 3600},
        "labels": {"workers": 1},
    }
    derived = derive_terminal_evidence(
        freeze=freeze, population_manifest=population, models=models,
        train_rows=train_rows, report_rows=report_rows,
        provider_rows=provider_rows)
    validate_terminal_evidence(derived.evidence, terminal=derived.terminal)
    assert derived.evidence["report_decision_consumption_count"] == 1
    assert len(derived.evidence["rotation_pairs"]) == 4
    assert derived.evidence["controls"]["rotation_passed"] is True
    assert [row["name"] for row in derived.evidence[
        "mutation_evidence"]["rows"]] == [
            "ballot", "continuation", "perspective", "transition",
            "utility"]
    assert set(derived.terminal["authority"].values()) == {False}


def test_attempt_is_durable_before_held_out_open_and_immediately_reopens(
        monkeypatch, tmp_path):
    train_groups, train_rows = _rows(
        monkeypatch, "train", group_count=2, repetitions=1, offset=100)
    report_groups, report_rows = _rows(
        monkeypatch, "report", group_count=2, repetitions=4, offset=110)
    provider_groups, provider_rows = _rows(
        monkeypatch, "provider-audit", group_count=2, repetitions=8,
        offset=120)
    population = {"groups": [
        *train_groups, *report_groups, *provider_groups]}
    models = tuple(new_world_afterstate_model(
        900 + index, CAPACITY_SHAPES["small"]) for index in range(8))
    freeze = {
        "freeze_sha256": "f" * 64,
        "learner": {"member_count": 8, "batch_size": 16},
        "gates": {"report_wall_cap_seconds": 3600,
                  "independent_verification_wall_cap_seconds": 3600},
        "labels": {"workers": 1},
    }
    dataset_manifest = {"manifest_sha256": "d" * 64}
    training_manifest = {
        "freeze_sha256": "f" * 64,
        "dataset_manifest_sha256": "d" * 64,
        "manifest_sha256": "a" * 64,
    }
    target = tmp_path / "terminal"
    first_held_open = []

    def reopen(_root, *, population_manifest, allowed_folds,
               reconstruct_continuations=False, progress=None, **_kwargs):
        assert population_manifest is population
        fold = allowed_folds[0]
        if fold in ("report", "provider-audit") and not first_held_open:
            attempt = tmp_path / ".terminal.partial" / "attempt.json"
            assert attempt.exists()
            assert stat.S_IMODE(attempt.stat().st_mode) == 0o400
            first_held_open.append(fold)
        if progress is not None:
            progress(1, 1)
        return dataset_manifest, {
            "train": train_rows,
            "calibration": train_rows,
            "report": report_rows,
            "provider-audit": provider_rows,
        }[fold]

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_scientific_dataset", reopen)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_training_build", lambda _root: (training_manifest, models))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "validate_population_manifest", lambda _value: None)
    result = run_open_report(
        target, freeze=freeze, population_manifest=population,
        dataset_root=tmp_path / "dataset",
        training_root=tmp_path / "training")
    assert result["verified"] is True
    assert result["continuations_reconstructed"] is False
    assert first_held_open == ["report"]
    assert {path.name for path in target.iterdir()} == {
        "attempt.json", "evidence.json", "terminal.json", "manifest.json"}

    observed_progress = []
    independent = verify_terminal_artifact(
        target, freeze=freeze, population_manifest=population,
        dataset_root=tmp_path / "dataset",
        training_root=tmp_path / "training",
        reconstruct_continuations=True,
        progress=lambda phase, completed, total: observed_progress.append(
            (phase, completed, total)))
    assert independent["verified"] is True
    assert {phase for phase, _completed, _total in observed_progress} \
        >= {"reconstruct-train", "reconstruct-calibration",
            "reconstruct-report", "reconstruct-provider-audit"}


def test_failed_held_out_derivation_spends_the_slot(monkeypatch, tmp_path):
    target = tmp_path / "terminal-failure"
    freeze = {"freeze_sha256": "f" * 64,
              "learner": {"member_count": 8, "batch_size": 16},
              "gates": {"report_wall_cap_seconds": 3600,
                        "independent_verification_wall_cap_seconds": 3600},
              "labels": {"workers": 1}}
    dataset_manifest = {"manifest_sha256": "d" * 64}
    training_manifest = {
        "freeze_sha256": "f" * 64,
        "dataset_manifest_sha256": "d" * 64,
        "manifest_sha256": "a" * 64,
    }

    def reopen(_root, *, population_manifest, allowed_folds,
               reconstruct_continuations=False, **_kwargs):
        if allowed_folds == ("train",):
            return dataset_manifest, ("train-row",)
        assert (tmp_path / ".terminal-failure.partial" /
                "attempt.json").exists()
        raise RuntimeError("injected held-out failure")

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_scientific_dataset", reopen)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_training_build", lambda _root: (training_manifest, ()))
    with __import__("pytest").raises(RuntimeError,
                                      match="injected held-out failure"):
        run_open_report(
            target, freeze=freeze, population_manifest={"groups": []},
            dataset_root=tmp_path / "dataset",
            training_root=tmp_path / "training")
    partial = tmp_path / ".terminal-failure.partial"
    assert {path.name for path in partial.iterdir()} == {"attempt.json"}
    with __import__("pytest").raises(
            WorldAfterstateTerminalControllerError,
            match="decision slot occupied"):
        run_open_report(
            target, freeze=freeze, population_manifest={"groups": []},
            dataset_root=tmp_path / "dataset",
            training_root=tmp_path / "training")


def test_report_deadline_expires_after_attempt_but_before_held_out_open(
        monkeypatch, tmp_path):
    target = tmp_path / "terminal-deadline"
    freeze = {"freeze_sha256": "f" * 64,
              "learner": {"member_count": 8, "batch_size": 16},
              "gates": {"report_wall_cap_seconds": 1,
                        "independent_verification_wall_cap_seconds": 3600},
              "labels": {"workers": 1}}
    dataset_manifest = {"manifest_sha256": "d" * 64}
    training_manifest = {
        "freeze_sha256": "f" * 64,
        "dataset_manifest_sha256": "d" * 64,
        "manifest_sha256": "a" * 64,
    }

    def reopen(_root, *, population_manifest, allowed_folds,
               reconstruct_continuations=False, **_kwargs):
        if allowed_folds == ("train",):
            return dataset_manifest, ("train-row",)
        raise AssertionError("held-out bytes opened after deadline")

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_scientific_dataset", reopen)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller."
        "reopen_training_build", lambda _root: (training_manifest, ()))
    readings = iter((0, 1_000_000_000))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_terminal_controller.time.monotonic_ns",
        lambda: next(readings))
    with __import__("pytest").raises(
            WorldAfterstateTerminalControllerError,
            match="terminal deadline expired"):
        run_open_report(
            target, freeze=freeze, population_manifest={"groups": []},
            dataset_root=tmp_path / "dataset",
            training_root=tmp_path / "training")
    partial = tmp_path / ".terminal-deadline.partial"
    assert {path.name for path in partial.iterdir()} == {"attempt.json"}
