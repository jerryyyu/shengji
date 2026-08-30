import dataclasses
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl import world_afterstate_v2_training_stage_adapters as adapters
from test_world_afterstate_v2_training_controller import _build


class _Freeze:
    evidence_root = "/tmp/evidence"
    deadline_seconds = 120

    def sha256(self):
        return "a" * 64


class _Admission:
    def sha256(self):
        return "b" * 64


class _Supervisor:
    admission = _Admission()
    root = Path("/tmp")
    state = SimpleNamespace(completed_stages=("block-1-natural",))

    def verified_shards(self, stage):
        return ()


def test_factories_are_closed_and_bind_the_reviewed_producers():
    freeze = _Freeze()
    repo = Path("/tmp")
    natural = adapters.block_1_natural_adapter(freeze=freeze, repo=repo)
    assert natural.__world_afterstate_v2_stage_adapter__ == adapters.ABI
    assert natural.producer is adapters.train_named_cohort
    assert adapters.block_1_controls_adapter(
        freeze=freeze, repo=repo).control_names == (
            "action-association-permutation", "label-permutation",
            "complete-world-shuffle")
    assert adapters.block_2_controls_adapter(
        freeze=freeze, repo=repo).control_names == ("complete-world-shuffle",)
    nested = adapters.nested_curve_training_adapter(freeze=freeze, repo=repo)
    assert nested.producer is adapters.produce_nested_curve_v2
    with pytest.raises(adapters.TrainingStageAdapterUnavailable):
        adapters.training_stage_adapter("unknown", freeze=freeze, repo=repo)


def test_closed_mapping_contains_exact_six_ordered_cohorts_and_rejects_drift():
    freeze = _Freeze()
    repo = Path("/tmp")
    adapters_by_stage = tuple(
        adapters.training_stage_adapter(stage, freeze=freeze, repo=repo)
        for stage in ("block-1-natural", "block-1-controls",
                      "block-2-natural", "block-2-controls"))
    observed = tuple(
        (adapter.stage, *(adapter.control_names or ("natural",)))
        for adapter in adapters_by_stage)
    assert observed == (
        ("block-1-natural", "natural"),
        ("block-1-controls", "action-association-permutation",
         "label-permutation", "complete-world-shuffle"),
        ("block-2-natural", "natural"),
        ("block-2-controls", "complete-world-shuffle"),
    )
    assert sum(len(row) - 1 for row in observed) == 6

    drifted = dataclasses.replace(
        adapters_by_stage[1],
        control_names=("action-association-permutation", "label-permutation"))
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="cohort mapping"):
        drifted(_Supervisor(), ())

    misclassified = dataclasses.replace(
        adapters_by_stage[3], control_names=("label-permutation",))
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="cohort mapping"):
        misclassified(_Supervisor(), ())


def test_cohort_artifacts_publish_and_reopen_with_mutation_resistance(tmp_path):
    build = _build()
    supervisor = SimpleNamespace(root=tmp_path)
    metadata = adapters._publish_cohort_artifacts(
        supervisor, "natural", 1, build)
    row = {"name": "natural", "manifest": build.manifest, **metadata}
    adapters._validate_cohort_artifacts(
        supervisor, row, expected_name="natural", expected_seed_block=1)

    mutated = dict(row)
    mutated["checkpoint_manifest_sha256"] = "0" * 64
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="checkpoint manifest digest"):
        adapters._validate_cohort_artifacts(
            supervisor, mutated, expected_name="natural", expected_seed_block=1)

    mutated = dict(row)
    mutated["checkpoint_root"] = metadata["checkpoint_root"] + "/.."
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="path drift|root binding"):
        adapters._validate_cohort_artifacts(
            supervisor, mutated, expected_name="natural", expected_seed_block=1)


def _publish_cohort_manifest_prefix(root, build):
    path = root / "cohort-manifests" / "natural" / "manifest.json"
    path.parent.mkdir(parents=True)
    adapters.publish_exclusive_bytes(path, adapters.canonical_json_bytes(build.manifest))


def _publish_checkpoint_prefix(root, build, count):
    checkpoint_root = root / "checkpoints"
    checkpoint_root.mkdir()
    selected_epoch = build.manifest["common_epoch"]["selected_epoch"]
    for index, raw in enumerate(build.selected_checkpoint_raws[:count]):
        adapters.publish_checkpoint_shard(
            checkpoint_root, raw, cohort="natural", seed_block=1,
            member_index=index, epoch=selected_epoch)


def test_cohort_artifacts_resume_after_cohort_manifest_crash(tmp_path):
    build = _build()
    _publish_cohort_manifest_prefix(tmp_path, build)
    metadata = adapters._publish_cohort_artifacts(
        SimpleNamespace(root=tmp_path), "natural", 1, build)
    assert metadata["cohort_manifest_sha256"] == adapters._sha(
        adapters.canonical_json_bytes(build.manifest))


def test_cohort_artifacts_resume_after_subset_checkpoint_shards(tmp_path):
    build = _build()
    _publish_cohort_manifest_prefix(tmp_path, build)
    _publish_checkpoint_prefix(tmp_path, build, 2)
    metadata = adapters._publish_cohort_artifacts(
        SimpleNamespace(root=tmp_path), "natural", 1, build)
    assert len(metadata["checkpoint_shard_sha256s"]) == 4


def test_cohort_artifacts_resume_after_complete_artifacts_before_receipt(tmp_path):
    build = _build()
    supervisor = SimpleNamespace(root=tmp_path)
    first = adapters._publish_cohort_artifacts(supervisor, "natural", 1, build)
    second = adapters._publish_cohort_artifacts(supervisor, "natural", 1, build)
    assert second == first


def test_cohort_artifacts_resume_refuses_mutated_existing_byte(tmp_path):
    build = _build()
    supervisor = SimpleNamespace(root=tmp_path)
    metadata = adapters._publish_cohort_artifacts(supervisor, "natural", 1, build)
    target = tmp_path / metadata["cohort_manifest_path"]
    os.chmod(target, 0o600)
    target.write_bytes(target.read_bytes() + b"mutated")
    os.chmod(target, 0o400)
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="cohort manifest byte drift"):
        adapters._publish_cohort_artifacts(supervisor, "natural", 1, build)


def test_nested_curve_refuses_before_training_without_exact_prior_checkpoint():
    adapter = adapters.nested_curve_training_adapter(
        freeze=_Freeze(), repo=Path("/tmp"))
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="sealed block-1-natural checkpoint"):
        adapter(_Supervisor(), ())


def test_nested_curve_requires_prior_stage_even_when_shards_are_present():
    supervisor = _Supervisor()
    supervisor.state = SimpleNamespace(completed_stages=())
    adapter = adapters.nested_curve_training_adapter(
        freeze=_Freeze(), repo=Path("/tmp"))
    with pytest.raises(adapters.TrainingStageAdapterUnavailable,
                       match="completed prior stage"):
        adapter(supervisor, ())


def test_prediction_receipts_bind_capacity_cap_for_cohort_and_nested_paths(
        monkeypatch):
    observed = []

    class StopPrediction(Exception):
        pass

    def stop_roots(*args, **kwargs):
        del args
        observed.append(("roots", kwargs["inference_batch_cap"]))
        raise StopPrediction

    monkeypatch.setattr(adapters, "predict_roots_v2", stop_roots)
    with pytest.raises(StopPrediction):
        adapters._prediction_receipts(
            object(), "stage", (object(),), (object(),), split="fit",
            control_name="natural", seed_block=1, inference_batch_cap=64)

    def stop_nested(*args, **kwargs):
        del args
        observed.append(("nested", kwargs["inference_batch_cap"]))
        raise StopPrediction

    monkeypatch.setattr(adapters, "predict_nested_curve_v2", stop_nested)
    with pytest.raises(StopPrediction):
        adapters._prediction_receipts(
            object(), "stage", (object(),), (object(),), split="select",
            control_name="natural", seed_block=1,
            nested_fraction_ppm=250_000, inference_batch_cap=32)

    assert observed == [("roots", 64), ("nested", 32)]


def test_nested_score_binds_capacity_cap(monkeypatch):
    observed = []

    class StopPrediction(Exception):
        pass

    def stop_nested(*args, **kwargs):
        del args
        observed.append(kwargs["inference_batch_cap"])
        raise StopPrediction

    monkeypatch.setattr(adapters, "predict_nested_curve_v2", stop_nested)
    with pytest.raises(adapters.TrainingStageAdapterUnavailable):
        adapters._nested_score(
            object(), "nested-curve", object(), (object(),), (), split="fit",
            fraction_ppm=250_000, inference_batch_cap=128)
    assert observed == [128]
