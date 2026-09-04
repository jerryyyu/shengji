from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_dev_runner import (
    SCHEMA, WorldAfterstateV2DevRunnerError,
    reopen_value_v2_dev_d64, sigma_pair_squared_from_targets,
)
import shengji.rl.world_afterstate_v2_dev_runner as runner


def test_sigma_pair_squared_is_population_variance_of_replica_means():
    # Incumbent is all zero.  Non-incumbent mean advantages are 1 and 3.
    assert sigma_pair_squared_from_targets((
        (0, 0, 0, 0, 0, 0, 0, 0),
        (1, 1, 1, 1, 1, 1, 1, 1),
        (3, 3, 3, 3, 3, 3, 3, 3),
    )) == 1.0


def test_reopen_requires_canonical_terminal_and_exact_run_id(tmp_path: Path):
    body = {"schema": SCHEMA, "route": "D64_DEV_SEALED",
            "run_id": "run", "authority": {
        "downstream_authorized": False, "gameplay_authorized": False,
        "strength_claim_authorized": False, "merge_authorized": False,
        "deployment_authorized": False,
    }}
    value = {**body, "terminal_sha256": __import__("hashlib").sha256(
        canonical_json_bytes(body)).hexdigest()}
    path = tmp_path / "terminal.json"
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o400)
    assert reopen_value_v2_dev_d64(tmp_path, expected_run_id="run") == value
    with pytest.raises(WorldAfterstateV2DevRunnerError, match="run identity"):
        reopen_value_v2_dev_d64(tmp_path, expected_run_id="other")


def test_reopen_refuses_terminal_rehash(tmp_path: Path):
    body = {"schema": SCHEMA, "route": "D64_DEV_SEALED",
            "run_id": "run", "authority": {
        "downstream_authorized": False, "gameplay_authorized": False,
        "strength_claim_authorized": False, "merge_authorized": False,
        "deployment_authorized": False,
    }}
    path = tmp_path / "terminal.json"
    path.write_bytes(canonical_json_bytes({**body, "terminal_sha256": "0" * 64}))
    path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2DevRunnerError, match="hash drift"):
        reopen_value_v2_dev_d64(tmp_path)


def test_source_stamp_refuses_a_dirty_worktree(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    values = iter(("1" * 40 + "\n", " M server/shengji/rl/example.py\n"))
    monkeypatch.setattr(runner.subprocess, "check_output",
                        lambda *args, **kwargs: next(values))
    with pytest.raises(WorldAfterstateV2DevRunnerError,
                       match="worktree is not clean"):
        runner._git_sha(tmp_path)


def _wire_fakes(monkeypatch: pytest.MonkeyPatch, root: Path):
    materials = tuple(SimpleNamespace(deal_sha256=f"{i:064x}") for i in range(64))
    bundles = tuple(SimpleNamespace(deal_sha256=m.deal_sha256, candidates=())
                    for m in materials)
    calls: list[str] = []

    def population(*args, **kwargs):
        calls.append("population")
        receipt = {"population_sha256": "a" * 64}
        runner._publish_or_verify(
            root / "private" / "d256-population-receipt.json", receipt,
            "D256 receipt")
        kwargs["progress"]({"stage": "d256-population", "completed": 256,
                             "total": 256, "percent": 100,
                             "active_workers": 8, "elapsed_nanoseconds": 1,
                             "eta_nanoseconds": 0})
        return (SimpleNamespace(payload=lambda: receipt), materials,
                runner._sha_bytes((root / "private" / "d256-population-receipt.json").read_bytes()))

    class Subset:
        manifest_sha256 = "b" * 64
        def payload(self):
            return {"schema": "fake-subset", "manifest_sha256": self.manifest_sha256}
    Subset.materials = materials

    def subset(value):
        calls.append("subset")
        return Subset()

    def labels(root_path, name, values, **kwargs):
        calls.append(name)
        receipt = SimpleNamespace(payload=lambda: {"manifest_sha256": name[0] * 64})
        runner._publish(root_path / "private" / "labels" / name / "receipt.json",
                        receipt.payload())
        return receipt, tuple(bundles[i] for i in range(len(values)))

    def train(root_path, run_id, values, bundles, epoch_values, epoch_bundles,
              sigma, **kwargs):
        calls.append("training")
        private = root_path / "private" / "training"
        for i in range(4):
            runner._publish(private / f"checkpoint-{i}.bin", f"checkpoint-{i}".encode())
        body = {"schema": runner.SCHEMA, "checkpoints": [
            {"member": i, "sha256": runner._sha_bytes(f"checkpoint-{i}".encode())}
            for i in range(4)]}
        receipt = {**body, "receipt_sha256": runner._sha(body)}
        runner._publish(private / "receipt.json", receipt)
        (private / "recovery").mkdir(mode=0o700, parents=True)
        return (tuple(object() for _ in range(4)), {}, "c" * 64,
                {"prior": {"fake": True}, "checkpoints": body["checkpoints"]})

    monkeypatch.setattr(runner, "_population", population)
    monkeypatch.setattr(runner, "_git_sha", lambda repo: "1" * 40)
    monkeypatch.setattr(runner, "build_value_v2_dev_protocol", subset)
    monkeypatch.setattr(runner, "_label_stage", labels)
    monkeypatch.setattr(runner, "_train", train)
    monkeypatch.setattr(runner, "_sigma_from_outcomes", lambda outcomes: 1.0)
    monkeypatch.setattr(runner, "reopen_jeffreys_prior_v2", lambda value: object())
    monkeypatch.setattr(runner, "build_inference_root_v2", lambda material: material)
    monkeypatch.setattr(runner, "predict_roots_v2", lambda *args, **kwargs: ())
    def manifest(*args, **kwargs):
        split = kwargs["split"]
        return {"manifest_sha256": ("p" if split == "select" else "q") * 64}
    monkeypatch.setattr(runner, "prediction_population_manifest_v2", manifest)
    monkeypatch.setattr(runner, "evaluate_v2", lambda *args, **kwargs:
                        SimpleNamespace(payload=lambda: {"metric": "sealed"}))
    return calls


def test_runner_wires_order_and_defers_audit_until_calibration(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch):
    calls = _wire_fakes(monkeypatch, tmp_path)
    original_labels = runner._label_stage
    original_manifest = runner.prediction_population_manifest_v2
    # The seam records fit-select and audit labels while evaluation is observed
    # by replacing the already patched evaluator for this ordering assertion.
    events: list[str] = []
    def labels(*args, **kwargs):
        events.append(args[1])
        return original_labels(*args, **kwargs)
    def manifest(*args, **kwargs):
        events.append(f"prediction-{kwargs['split']}")
        return original_manifest(*args, **kwargs)
    monkeypatch.setattr(runner, "_label_stage", labels)
    monkeypatch.setattr(runner, "prediction_population_manifest_v2", manifest)
    monkeypatch.setattr(runner, "evaluate_v2", lambda *args, **kwargs:
                        (events.append("evaluation") or SimpleNamespace(
                            payload=lambda: {"metric": "sealed"})))
    runner.run_value_v2_dev_d64(tmp_path, repo=tmp_path, run_id="wire")
    assert events == ["fit-epoch", "prediction-select", "precision-select",
                      "evaluation", "audit", "prediction-audit",
                      "evaluation"]
    assert calls[:4] == ["population", "subset", "fit-epoch", "training"]


def test_runner_persists_score_free_progress_and_resumes(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    calls = _wire_fakes(monkeypatch, tmp_path)
    seen: list[dict] = []
    runner.run_value_v2_dev_d64(tmp_path, repo=tmp_path, run_id="resume",
                                progress=seen.append)
    first_calls = list(calls)
    assert seen and all(set(item) == {"stage", "completed", "total", "percent",
                                      "active_workers", "elapsed_nanoseconds",
                                      "eta_nanoseconds"} for item in seen)
    assert list((tmp_path / "private" / "progress").glob("event-*.json"))
    runner.run_value_v2_dev_d64(tmp_path, repo=tmp_path, run_id="resume",
                                progress=seen.append)
    assert calls == first_calls


def test_runner_terminal_binds_incomplete_coverage_without_fabricating_d256(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Witness the partial controller result at the terminal wiring altitude."""
    _wire_fakes(monkeypatch, tmp_path)
    materials = tuple(SimpleNamespace(deal_sha256=f"{i:064x}")
                      for i in range(64))
    missing = {"slot_sha256": "f" * 64, "ordinal": 144}
    partial_path = (tmp_path / "population-controller" /
                    "partial-coverage.json")
    partial_value = {"schema": "fixture-partial-coverage",
                     "coverage_complete": False,
                     "accepted_slots": 255, "missing_slots": [missing]}
    runner._publish(partial_path, partial_value)
    partial_hash = runner._sha_bytes(partial_path.read_bytes())
    receipt = SimpleNamespace(
        accepted_slots=255, missing_slots=(missing,),
        selected_materials=materials)

    def population(*_args, **kwargs):
        kwargs["progress"]({"stage": "d256-population", "completed": 255,
                             "total": 256, "percent": 99,
                             "active_workers": 0, "elapsed_nanoseconds": 1,
                             "eta_nanoseconds": None})
        return receipt, materials, partial_hash

    class PartialSubset:
        manifest_sha256 = "b" * 64

        def __init__(self):
            self.materials = materials

        def payload(self):
            return {"schema": "fixture-d64-partial",
                    "coverage_complete": False,
                    "manifest_sha256": self.manifest_sha256}

    monkeypatch.setattr(runner, "_population", population)
    monkeypatch.setattr(runner, "build_value_v2_dev_partial_protocol",
                        lambda value: PartialSubset())

    terminal = runner.run_value_v2_dev_d64(
        tmp_path, repo=tmp_path, run_id="partial-terminal")

    assert terminal["population"] == {
        "partial_coverage_sha256": partial_hash,
        "coverage_complete": False, "accepted_slots": 255,
        "missing_slot_count": 1, "missing_slots": [missing],
    }
    assert terminal["d64_subset"]["artifact"] \
        == "d64-partial-coverage.json"
    assert not (tmp_path / "private" /
                "d256-population-receipt.json").exists()
    assert reopen_value_v2_dev_d64(
        tmp_path, expected_run_id="partial-terminal") == terminal


def test_runner_reopen_refuses_bound_checkpoint_drop(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch):
    _wire_fakes(monkeypatch, tmp_path)
    runner.run_value_v2_dev_d64(tmp_path, repo=tmp_path, run_id="bound")
    (tmp_path / "private" / "training" / "checkpoint-0.bin").unlink()
    with pytest.raises(WorldAfterstateV2DevRunnerError, match="bound checkpoint"):
        reopen_value_v2_dev_d64(tmp_path, expected_run_id="bound")


def test_runner_resume_refuses_tampered_d64_subset_receipt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _wire_fakes(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner, "_label_stage",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            WorldAfterstateV2DevRunnerError("stop after subset")))
    with pytest.raises(WorldAfterstateV2DevRunnerError,
                       match="stop after subset"):
        runner.run_value_v2_dev_d64(
            tmp_path, repo=tmp_path, run_id="subset-resume")

    subset_path = tmp_path / "private" / "d64-subset.json"
    subset_path.chmod(0o600)
    subset_path.write_bytes(canonical_json_bytes({"schema": "forged"}))
    subset_path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2DevRunnerError,
                       match="D64 subset receipt drift"):
        runner.run_value_v2_dev_d64(
            tmp_path, repo=tmp_path, run_id="subset-resume")
