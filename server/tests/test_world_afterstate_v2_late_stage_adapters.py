"""Closed late-stage adapter guard witnesses."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl import world_afterstate_v2_late_stage_adapters as adapters
from shengji.rl import world_afterstate_v2_label_controller as label_controller
from shengji.rl import world_afterstate_v2_stage_adapters as stage_adapters
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_audit_attempt import build_audit_attempt_bytes
from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from test_world_afterstate_v2_inference import _root
from test_world_afterstate_v2_capacity import _receipt
from test_world_afterstate_v2_result import _canary, _evaluation, _p0, _power


LABELS = (
    "natural:block-1", "action-association-permutation:block-1",
    "label-permutation:block-1", "complete-world-shuffle:block-1",
    "natural:block-2", "complete-world-shuffle:block-2",
)


class _Supervisor:
    def __init__(self, root: Path):
        self.root = root
        self.freeze = SimpleNamespace(sha256=lambda: "a" * 64)
        self.admission = SimpleNamespace(sha256=lambda: "b" * 64)
        self.shards = {}

    def verified_shards(self, stage):
        return tuple(self.shards.get(stage, ()))

    def register_verified_shard(self, stage, shard, raw):
        self.shards.setdefault(stage, {})[shard] = raw


def _manifest(label):
    control, block = label.rsplit(":", 1)[0], int(label.rsplit("-", 1)[1])
    return {"split": "select", "control_name": control, "seed_block": block}


def test_prediction_resume_reopens_without_inference_and_binds_roots_models(
        tmp_path, monkeypatch):
    root = _root()
    models = tuple(new_world_afterstate_v2_model(900 + index)
                   for index in range(4))
    supervisor = SimpleNamespace(root=tmp_path)
    first, path = adapters._prediction(
        supervisor, (root,), models, split="audit", control="natural",
        block=1, subfold=None)
    monkeypatch.setattr(
        adapters, "predict_root_v2",
        lambda *_args, **_kwargs: pytest.fail(
            "sealed predictions must reopen without inference"))
    reopened, reopened_path = adapters._prediction(
        supervisor, (root,), models, split="audit", control="natural",
        block=1, subfold=None)
    assert reopened == first
    assert reopened_path == path

    changed_root = dataclasses.replace(root, points_bucket="40-79")
    with pytest.raises(adapters.LateStageAdapterUnavailable,
                       match="prediction resume refused"):
        adapters._prediction(
            supervisor, (changed_root,), models, split="audit",
            control="natural", block=1, subfold=None)
    changed_models = tuple(new_world_afterstate_v2_model(950 + index)
                           for index in range(4))
    with pytest.raises(adapters.LateStageAdapterUnavailable,
                       match="prediction resume refused"):
        adapters._prediction(
            supervisor, (root,), changed_models, split="audit",
            control="natural", block=1, subfold=None)


def _capacity_bound_fixture(tmp_path, *, selected_arms=None, receipt=None):
    if receipt is None:
        receipt = _receipt(selected_arms=selected_arms) if selected_arms else _receipt()
    raw = canonical_json_bytes(receipt.payload())
    path = tmp_path / "capacity.json"
    path.write_bytes(raw)
    path.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    freeze = SimpleNamespace(
        evidence_root=str(tmp_path), population_tier="D256",
        capacity_sha256=digest,
        artifact_bindings=(("capacity", "capacity.json", digest),),
        deadline_seconds=300,
        sha256=lambda: "a" * 64,
    )
    supervisor = SimpleNamespace(
        root=tmp_path,
        admission=SimpleNamespace(sha256=lambda: "b" * 64),
    )
    return freeze, supervisor, receipt, path


def test_production_precision_and_audit_predictions_bind_selected_capacity_arm(
        tmp_path, monkeypatch):
    freeze, supervisor, _receipt_value, _path = _capacity_bound_fixture(tmp_path)
    monkeypatch.setattr(adapters, "_identity", lambda *args: None)
    monkeypatch.setattr(adapters, "_prefix", lambda *args: None)
    monkeypatch.setattr(adapters, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(adapters, "publish_audit_attempt", lambda _supervisor: {
        "attempt_sha256": "c" * 64,
    })
    root = _root()
    monkeypatch.setattr(adapters, "_materials", lambda *args: (object(),))
    monkeypatch.setattr(adapters, "build_inference_root_v2", lambda value: root)
    monkeypatch.setattr(
        adapters, "_cohort_builds",
        lambda *args: tuple((label, (object(),) * 4)
                            for label, *_rest in adapters._COHORTS))

    observed = []

    class StopPrediction(Exception):
        pass

    def stop_prediction(*args, **kwargs):
        del args
        observed.append(kwargs["inference_batch_cap"])
        raise StopPrediction

    monkeypatch.setattr(adapters, "_prediction", stop_prediction)
    with pytest.raises(StopPrediction):
        adapters.PrecisionSelectPowerAdapterV2(freeze, tmp_path)(supervisor, ())
    with pytest.raises(StopPrediction):
        adapters.AuditAttemptAdapterV2(freeze, tmp_path)(supervisor, ())
    assert observed == [32, 32]


@pytest.mark.parametrize("failure", ("missing", "digest", "duplicate"))
def test_production_prediction_refuses_capacity_binding_failures(
        tmp_path, failure):
    freeze, supervisor, receipt, path = _capacity_bound_fixture(tmp_path)
    if failure == "missing":
        path.unlink()
    elif failure == "digest":
        path.chmod(0o600); path.write_bytes(b"{}"); path.chmod(0o400)
    else:
        freeze.artifact_bindings = (
            ("capacity", "capacity.json", freeze.capacity_sha256),
            ("capacity", "capacity.json", freeze.capacity_sha256),
        )
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="capacity"):
        adapters._inference_batch_cap(supervisor, freeze, tmp_path)


def test_production_prediction_refuses_duplicate_selected_capacity_arm(tmp_path):
    freeze, supervisor, original, path = _capacity_bound_fixture(tmp_path)
    payload = json.loads(path.read_bytes())
    payload["selected_arms"].append(payload["selected_arms"][-1])
    raw = canonical_json_bytes(payload)
    path.chmod(0o600)
    path.write_bytes(raw)
    path.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    freeze.capacity_sha256 = digest
    freeze.artifact_bindings = (("capacity", "capacity.json", digest),)
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="capacity"):
        adapters._inference_batch_cap(supervisor, freeze, tmp_path)


def test_reconstruction_arm_reopens_from_repository_when_evidence_has_no_copy(
        tmp_path):
    repo = tmp_path / "repo"
    evidence = tmp_path / "evidence"
    repo.mkdir(); evidence.mkdir()
    receipt = _receipt()
    raw = canonical_json_bytes(receipt.payload())
    capacity_path = repo / "capacity.json"
    capacity_path.write_bytes(raw)
    capacity_path.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    freeze = SimpleNamespace(
        evidence_root=str(evidence), population_tier="D256",
        capacity_sha256=digest,
        artifact_bindings=(("capacity", "capacity.json", digest),),
        deadline_seconds=300, sha256=lambda: "a" * 64)
    supervisor = SimpleNamespace(
        root=evidence,
        admission=SimpleNamespace(sha256=lambda: "b" * 64))
    expected = next(arm.variant for arm in receipt.selected_arms
                    if arm.stage == "reconstruction")
    assert adapters._reconstruction_workers(
        supervisor, freeze, repo) == expected


def test_reconstruction_arm_32_is_the_upper_frozen_width():
    assert adapters.TERMINAL_INPUTS_SCHEMA == "world-afterstate-v2-terminal-inputs-v2"
    assert adapters._reconstruction_workers
    assert 32 in stage_adapters.CONTINUATION_WORKER_ARMS
    assert 32 in label_controller.CONTINUATION_WORKER_ARMS
    assert 33 not in stage_adapters.CONTINUATION_WORKER_ARMS
    assert 33 not in label_controller.CONTINUATION_WORKER_ARMS


@pytest.mark.parametrize("configured, accepted", ((32, True), (33, False)))
def test_audit_label_workers_bind_exact_selected_continuation_arm(
        tmp_path, configured, accepted):
    baseline = _receipt()
    arms = tuple(
        dataclasses.replace(
            arm, wall_ns=1_000_000_000, wall_seconds=1,
            busy_core_ns=14_000_000_000, busy_core_seconds=14,
            mean_cpu_utilization_ppm=875_000)
        if arm.stage == "continuation-mechanics" and arm.variant == 32
        else arm
        for arm in baseline.arms)
    selected = tuple(
        next(arm for arm in arms
             if arm.stage == "continuation-mechanics" and arm.variant == 32)
        if arm.stage == "continuation-mechanics" else arm
        for arm in baseline.selected_arms)
    receipt = _receipt(arms=arms, selected_arms=selected)
    freeze, supervisor, _receipt_value, _path = _capacity_bound_fixture(
        tmp_path, receipt=receipt)
    config = {
        "schema": "world-afterstate-v2-early-stage-adapters-input-v2",
        "label_workers": configured,
        "label_deadline_seconds": 120,
    }
    raw = canonical_json_bytes(config)
    config_path = tmp_path / "config.json"
    config_path.write_bytes(raw)
    config_path.chmod(0o400)
    digest = hashlib.sha256(raw).hexdigest()
    freeze.artifact_bindings = (*freeze.artifact_bindings,
                                ("config", "config.json", digest))
    if accepted:
        assert adapters._label_resources(
            supervisor, freeze, tmp_path) == (32, 120)
    else:
        with pytest.raises(adapters.LateStageAdapterUnavailable,
                           match="worker/capacity"):
            adapters._label_resources(supervisor, freeze, tmp_path)


def test_precision_requires_all_prediction_cohorts_before_label_opening(monkeypatch):
    monkeypatch.setattr(adapters, "validate_prediction_population_manifest_v2",
                        lambda value: None)
    values = tuple((label, _manifest(label)) for label in LABELS[:-1])
    inputs = adapters.PrecisionSelectInputV2(
        values, (), object(), 64, (object(),), Path("labels"))
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="population"):
        inputs.validate()


def test_precision_opens_labels_only_after_all_prediction_manifests(monkeypatch,
                                                                     tmp_path):
    events = []

    def validate(value):
        events.append("prediction")

    class Receipt:
        def payload(self):
            return {"receipt": True}

    class Result:
        def payload(self):
            return {"result": True}

    class Power:
        stop_underpowered = False

        def payload(self):
            return {"power": True}

    monkeypatch.setattr(adapters, "validate_prediction_population_manifest_v2",
                        validate)
    monkeypatch.setattr(adapters, "build_continuation_population_v2",
                        lambda *args, **kwargs: events.append("labels") or Receipt())
    monkeypatch.setattr(adapters, "reopen_continuation_manifest",
                        lambda *args, **kwargs: (SimpleNamespace(candidates=()),))
    monkeypatch.setattr(adapters, "evaluate_precision_select_v2",
                        lambda *args, **kwargs: events.append("evaluate") or
                        (Result(), Power()))
    inputs = adapters.PrecisionSelectInputV2(
        tuple((label, _manifest(label)) for label in LABELS), (), object(), 48,
        (object(),), tmp_path)
    supervisor = _Supervisor(tmp_path)
    adapters.PrecisionSelectPowerAdapterV2(inputs)(supervisor, ())
    assert events[:6] == ["prediction"] * 6
    assert events.index("labels") > max(i for i, x in enumerate(events)
                                         if x == "prediction")
    assert events.index("evaluate") > events.index("labels")


def test_precision_refuses_incomplete_member_population(monkeypatch):
    def validate(value):
        if value["control_name"] == "label-permutation":
            raise ValueError("member population incomplete")

    monkeypatch.setattr(adapters, "validate_prediction_population_manifest_v2",
                        validate)
    inputs = adapters.PrecisionSelectInputV2(
        tuple((label, _manifest(label)) for label in LABELS), (), object(), 48,
        (object(),), Path("labels"))
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="label-permutation"):
        inputs.validate()


def test_audit_adapter_rejects_before_label_builder_without_durable_marker(tmp_path,
                                                                            monkeypatch):
    called = []
    monkeypatch.setattr(adapters, "build_continuation_population_v2",
                        lambda *args, **kwargs: called.append(args))
    inputs = SimpleNamespace(audit_materials=(object(),), audit_label_root=tmp_path,
                             workers=1, deadline_monotonic_ns=2**63 - 1)
    supervisor = _Supervisor(tmp_path)
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="marker"):
        adapters.AuditAttemptAdapterV2(inputs)(supervisor, ())
    assert called == []


def _audit_preflight_fixture(tmp_path):
    class Supervisor:
        root = tmp_path
        state = SimpleNamespace(
            completed_stages=(*adapters._WORK_PREFIX,
                              adapters.PRECISION_STAGE))
        admission = SimpleNamespace(sha256=lambda: "b" * 64)

        def verified_shards(self, stage):
            return ("receipt",)

    for stage in (*adapters._WORK_PREFIX, adapters.PRECISION_STAGE):
        path = tmp_path / "shards" / stage / "receipt.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(canonical_json_bytes({"stage": stage}))
        path.chmod(0o400)
    freeze = SimpleNamespace(
        evidence_root=str(tmp_path), population_tier="D256",
        sha256=lambda: "a" * 64)
    return freeze, Supervisor()


def test_audit_preflight_producer_binds_upstream_receipts_before_any_audit_path(
        tmp_path):
    freeze, supervisor = _audit_preflight_fixture(tmp_path)
    adapter = adapters.AuditAttemptAdapterV2(freeze, tmp_path)
    payload = adapter.prepare_stage_payload(supervisor)
    assert payload["preflight_relative_path"] == "audit-preflight.json"
    value = json.loads((tmp_path / "audit-preflight.json").read_bytes())
    assert value["completed_stages"] == list(supervisor.state.completed_stages)
    assert [row[0] for row in value["upstream_receipt_sha256s"]] == list(
        supervisor.state.completed_stages)
    assert value["audit_paths_absent"] == [
        "audit-attempt.json", "audit-continuations", "terminal-inputs.json"]
    assert not (tmp_path / "audit-attempt.json").exists()
    assert not (tmp_path / "audit-continuations").exists()
    assert adapter.prepare_stage_payload(supervisor) == payload


def test_audit_preflight_producer_refuses_preopened_label_path(tmp_path):
    freeze, supervisor = _audit_preflight_fixture(tmp_path)
    (tmp_path / "audit-continuations").mkdir()
    adapter = adapters.AuditAttemptAdapterV2(freeze, tmp_path)
    with pytest.raises(adapters.LateStageAdapterUnavailable,
                       match="opened before"):
        adapter.prepare_stage_payload(supervisor)
    assert not (tmp_path / "audit-preflight.json").exists()


def test_audit_adapter_does_not_publish_second_marker(tmp_path, monkeypatch):
    marker = tmp_path / "audit-attempt.json"
    marker.write_bytes(build_audit_attempt_bytes(
        freeze_sha256="a" * 64, admission_sha256="b" * 64,
        preflight={"preflight_sha256": "c" * 64}))
    marker.chmod(0o400)
    called = []

    class Receipt:
        def payload(self):
            return {"receipt": True}

    monkeypatch.setattr(adapters, "build_continuation_population_v2",
                        lambda *args, **kwargs: called.append(args) or Receipt())
    inputs = SimpleNamespace(audit_materials=(object(),), audit_label_root=tmp_path,
                             workers=1, deadline_monotonic_ns=2**63 - 1)
    supervisor = _Supervisor(tmp_path)
    result = adapters.AuditAttemptAdapterV2(inputs)(supervisor, ())
    assert called and marker.read_bytes()
    assert result["schema"] == "world-afterstate-v2-audit-attempt-receipt-v1"
    assert not (tmp_path / "audit-attempt.json.tmp").exists()


def test_reconstruction_adapter_is_receipt_only_and_rescore_false(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(adapters.TerminalInputPathsV2, "validate_shape",
                        lambda self: None)
    monkeypatch.setattr(adapters, "verify_terminal_artifact_v2",
                        lambda *args, **kwargs: observed.append((args, kwargs)) or {
                            "matched": True})
    inputs = object.__new__(adapters.TerminalInputPathsV2)
    adapter = adapters.ReconstructionAdapterV2(tmp_path, inputs)
    supervisor = SimpleNamespace(root=tmp_path)
    assert adapter(supervisor, ()) == {"matched": True}
    assert observed == [((tmp_path / "terminal", inputs), {"rescore": False})]


def test_production_factories_bind_before_upstream_artifacts_exist(tmp_path):
    freeze = SimpleNamespace(population_tier="D256")
    for name in ("sha256",):
        setattr(freeze, name, lambda: "a" * 64)
    for stage, factory in (
            ("precision-select-power", adapters.precision_select_power_adapter),
            ("audit-attempt", adapters.audit_attempt_adapter),
            ("terminal", adapters.terminal_adapter),
            ("reconstruction", adapters.reconstruction_adapter)):
        operation = factory(freeze=freeze, repo=tmp_path)
        assert operation.stage == stage
        assert not tuple(tmp_path.iterdir())


def test_late_factories_reject_unsupported_tier(tmp_path):
    freeze = SimpleNamespace(population_tier="D512")
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="D256"):
        adapters.precision_select_power_adapter(freeze=freeze, repo=tmp_path)


def test_terminal_factory_refuses_without_upstream_immutable_index(tmp_path):
    freeze = SimpleNamespace(population_tier="D256", evidence_root=str(tmp_path),
                             sha256=lambda: "a" * 64)
    operation = adapters.terminal_adapter(freeze=freeze, repo=tmp_path)
    supervisor = SimpleNamespace(root=tmp_path,
                                 admission=SimpleNamespace(sha256=lambda: "b" * 64))
    with pytest.raises(adapters.LateStageAdapterUnavailable,
                       match="index|precision stage"):
        operation(supervisor, ())


def _seal_early_shard(root, stage, name, payload):
    path = root / "shards" / stage / f"{name}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(
        payload if type(payload) is dict else payload.payload()))
    path.chmod(0o400)
    return name


@pytest.mark.parametrize(
    "route,resource_stage,completed,p0,canary,precision,power",
    (
        ("STOP_NO_REPRODUCIBLE_VALUE_LABEL", None,
         ("population", "p0-labels-gates"),
         _p0(sibling_advantage_correlation_bootstrap_lower_ppm=0,
             statistical_gates_passed=False,
             decision="STOP_NO_REPRODUCIBLE_VALUE_LABEL"),
         None, None, None),
        ("REFUSE_TRAINING_RECIPE", None,
         ("population", "p0-labels-gates", "optimizer-canary"),
         _p0(), _canary(passed=False), None, None),
        ("SELECT_NONE_PREAUDIT_LEARNING", None,
         ("population", "p0-labels-gates", "optimizer-canary",
          "precision-select-power"),
         _p0(), _canary(), _evaluation(population="d" * 64, rps=-1),
         _power("d" * 64)),
        ("REFUSE_RESOURCE_INCOMPLETE", "optimizer-canary",
         ("population", "p0-labels-gates"),
         _p0(), None, None, None),
        ("REFUSE_RESOURCE_INCOMPLETE", "population", (),
         None, None, None, None),
    ),
)
def test_production_terminal_adapter_seals_early_routes_without_audit(
        tmp_path, route, resource_stage, completed, p0, canary, precision,
        power):
    freeze = SimpleNamespace(
        evidence_root=str(tmp_path), population_tier="D256",
        sha256=lambda: "a" * 64)
    admission = SimpleNamespace(sha256=lambda: "b" * 64)
    shard_rows = {}
    if p0 is not None:
        shard_rows["p0-labels-gates"] = (
            _seal_early_shard(
                tmp_path, "p0-labels-gates", "receipt", p0),)
    if canary is not None:
        shard_rows["optimizer-canary"] = (
            _seal_early_shard(
                tmp_path, "optimizer-canary", "receipt", canary),)
    if precision is not None:
        shard_rows[adapters.PRECISION_STAGE] = tuple(
            _seal_early_shard(tmp_path, adapters.PRECISION_STAGE, name, value)
            for name, value in (("result", precision), ("power", power)))

    payload = {"route": route, "resource_stage": resource_stage}
    event = {
        "schema": "world-afterstate-v2-stage-event-v1", "index": 0,
        "stage": resource_stage or completed[-1],
        "status": "terminal-pending", "split": None,
        "freeze_sha256": "a" * 64, "admission_sha256": "b" * 64,
        "payload": payload,
        "authority": {"terminal_authorized": False},
    }
    event["event_sha256"] = hashlib.sha256(
        canonical_json_bytes(event)).hexdigest()
    event_path = tmp_path / "events" / "00000000.json"
    event_path.parent.mkdir()
    event_path.write_bytes(canonical_json_bytes(event))
    event_path.chmod(0o400)

    class Supervisor:
        def __init__(self):
            self.root = tmp_path
            self.state = SimpleNamespace(
                completed_stages=completed, terminal_route=route,
                audit_opened=False)
            self.freeze = freeze
            self.admission = admission

        def verified_shards(self, stage):
            return shard_rows.get(stage, ())

    supervisor = Supervisor()
    terminal_adapter = adapters.TerminalAdapterV2(freeze, tmp_path)
    receipt = terminal_adapter(supervisor, ())
    assert receipt["matched"] is True
    result = json.loads(
        (tmp_path / "terminal" / "terminal.json").read_bytes())
    assert result["decision"] == route
    assert result["audit_opened_count"] == 0
    assert not (tmp_path / "audit-attempt.json").exists()
    assert not (tmp_path / "terminal-inputs.json").exists()
    assert adapters.ReconstructionAdapterV2(
        freeze, tmp_path)(supervisor, ())["matched"] is True


def test_terminal_index_producer_refuses_missing_sixth_upstream_cohort(tmp_path,
                                                                        monkeypatch):
    class Supervisor:
        root = tmp_path
        state = SimpleNamespace(completed_stages=(*adapters._WORK_PREFIX,
                                                   adapters.PRECISION_STAGE))
        admission = SimpleNamespace(sha256=lambda: "b" * 64)

        def verified_shards(self, stage):
            return ("receipt",)

    freeze = SimpleNamespace(sha256=lambda: "a" * 64)
    names = {
        "block-1-natural": "natural",
        "block-1-controls": "action-association-permutation",
        "block-2-natural": "natural",
        "block-2-controls": "complete-world-shuffle",
    }

    def receipt(_supervisor, stage):
        name = names.get(stage)
        rows = [] if name is None else [{"name": name,
                                         "cohort_manifest_path": "cohort.json",
                                         "checkpoint_root": "checkpoints",
                                         "checkpoint_manifest_path": "checkpoints/manifest.json"}]
        return {"cohorts": rows}, tmp_path / "receipt.bin", "c" * 64

    monkeypatch.setattr(adapters, "_upstream_receipt", receipt)
    monkeypatch.setattr(adapters, "_COHORTS", (
        ("complete-world-shuffle:block-1", "block-1-controls",
         "complete-world-shuffle", 1),))
    with pytest.raises(adapters.LateStageAdapterUnavailable, match="complete-world-shuffle"):
        adapters._published_terminal_inputs(
            Supervisor(), freeze, tmp_path, ())
    assert not (tmp_path / "terminal-inputs.json").exists()


def test_terminal_index_wiring_refuses_divergent_cross_block_world_dose(
        tmp_path, monkeypatch):
    class Supervisor:
        root = tmp_path
        state = SimpleNamespace(completed_stages=(*adapters._WORK_PREFIX,
                                                   adapters.PRECISION_STAGE))
        admission = SimpleNamespace(sha256=lambda: "b" * 64)

        def verified_shards(self, stage):
            return ("receipt",)

    freeze = SimpleNamespace(sha256=lambda: "a" * 64)
    cohorts = (
        ("complete-world-shuffle:block-1", "block-1-controls",
         "complete-world-shuffle", 1),
        ("complete-world-shuffle:block-2", "block-2-controls",
         "complete-world-shuffle", 2),
    )
    monkeypatch.setattr(adapters, "_COHORTS", cohorts)

    def upstream(_supervisor, stage):
        block = 1 if stage == "block-1-controls" else 2
        return {"cohorts": [{
            "name": "complete-world-shuffle",
            "cohort_manifest_path": f"cohort-{block}.json",
            "checkpoint_root": f"checkpoints-{block}",
            "checkpoint_manifest_path": f"checkpoints-{block}/manifest.json",
        }]}, tmp_path / "receipt.bin", "c" * 64

    monkeypatch.setattr(adapters, "_upstream_receipt", upstream)
    monkeypatch.setattr(adapters, "_path",
                        lambda root, relative, _label: root / relative)
    monkeypatch.setattr(adapters, "_directory",
                        lambda root, relative, _label: root / relative)

    def relative(root, path, _label):
        rel = path.relative_to(root).as_posix()
        digest = ("1" * 64 if "block-1-controls" in rel else
                  "2" * 64 if "block-2-controls" in rel else "d" * 64)
        return rel, digest

    monkeypatch.setattr(adapters, "_relative", relative)
    for _label, stage, name, _block in cohorts:
        path = tmp_path / "shards" / stage / f"control-evidence-{name}.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"sealed")

    with pytest.raises(adapters.LateStageAdapterUnavailable,
                       match="cross-block control-dose drift"):
        adapters._published_terminal_inputs(
            Supervisor(), freeze, tmp_path, ())
    assert not (tmp_path / "terminal-inputs.json").exists()


def test_terminal_index_publishes_and_reopens_all_six_canonical_inputs(
        tmp_path, monkeypatch):
    def seal(relative, value):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = value if type(value) is bytes else canonical_json_bytes(value)
        path.write_bytes(raw)
        path.chmod(0o400)
        return path

    cohort_rows = {}
    predictions = []
    world_evidence = canonical_json_bytes({"control_name": "complete-world-shuffle"})
    for label, stage, name, block in adapters._COHORTS:
        slug = label.replace(":", "-")
        cohort_path = seal(f"cohorts/{slug}.json", {"label": label})
        checkpoint_root = tmp_path / f"checkpoint-roots/{slug}"
        checkpoint_root.mkdir(parents=True)
        checkpoint_path = seal(
            f"checkpoint-roots/{slug}/manifest.json", {"label": label})
        cohort_rows.setdefault(stage, []).append({
            "name": name,
            "cohort_manifest_path": cohort_path.relative_to(tmp_path).as_posix(),
            "checkpoint_root": checkpoint_root.relative_to(tmp_path).as_posix(),
            "checkpoint_manifest_path": checkpoint_path.relative_to(tmp_path).as_posix(),
        })
        prediction = {"label": label}
        prediction_path = seal(f"predictions/{slug}.json", prediction)
        predictions.append((label, prediction, prediction_path))
        if name != "natural":
            evidence = (world_evidence if name == "complete-world-shuffle"
                        else canonical_json_bytes({"control_name": name}))
            seal(f"shards/{stage}/control-evidence-{name}.bin", evidence)

    population = {
        "freeze_sha256": "a" * 64, "admission_sha256": "b" * 64,
        "population_namespace_sha256": "c" * 64, "tier": "D256",
    }
    receipts = {stage: {"cohorts": rows}
                for stage, rows in cohort_rows.items()}
    receipts["population"] = population
    for stage in (*adapters._WORK_PREFIX, adapters.PRECISION_STAGE):
        seal(f"shards/{stage}/receipt.bin", receipts.get(stage, {}))
    for name in ("result", "power", "prior"):
        seal(f"shards/{adapters.PRECISION_STAGE}/{name}.bin", {"name": name})
    seal("audit-attempt.json", {"attempt": True})
    seal("audit-continuations/continuations/manifest.json", {"audit": True})

    class Supervisor:
        root = tmp_path
        state = SimpleNamespace(completed_stages=(*adapters._WORK_PREFIX,
                                                   adapters.PRECISION_STAGE))
        admission = SimpleNamespace(sha256=lambda: "b" * 64)

        def verified_shards(self, stage):
            if stage == adapters.PRECISION_STAGE:
                return ("prior", "result", "power", "receipt")
            if stage == adapters.AUDIT_STAGE:
                return ("receipt",)
            return ("receipt",)

    supervisor = Supervisor()
    freeze, _capacity_supervisor, _capacity_receipt_value, _capacity_path = \
        _capacity_bound_fixture(tmp_path)
    freeze_raw = b"terminal-freeze-fixture\n"
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_bytes(freeze_raw)
    freeze_path.chmod(0o400)
    freeze_digest = hashlib.sha256(freeze_raw).hexdigest()
    freeze.sha256 = lambda: freeze_digest
    population["freeze_sha256"] = freeze_digest
    population_receipt_path = tmp_path / "shards/population/receipt.bin"
    population_receipt_path.chmod(0o600)
    population_receipt_path.write_bytes(canonical_json_bytes(population))
    population_receipt_path.chmod(0o400)
    index, digest = adapters._published_terminal_inputs(
        supervisor, freeze, tmp_path, tuple(predictions))
    assert index == tmp_path / "terminal-inputs.json"
    assert len(digest) == 64

    supervisor.state = SimpleNamespace(
        completed_stages=(*adapters._WORK_PREFIX, adapters.PRECISION_STAGE,
                          adapters.AUDIT_STAGE))
    monkeypatch.setattr(
        adapters, "reopen_population_receipt_v2",
        lambda value: SimpleNamespace(
            population_namespace_sha256=value["population_namespace_sha256"],
            tier=value["tier"]))
    result = adapters._terminal_paths(supervisor, freeze, tmp_path)
    result.validate_shape()
    assert tuple(label for label, _ in result.prediction_manifest_paths) == LABELS
    assert tuple(label for label, _ in result.cohort_manifest_paths) == LABELS
    assert tuple(label for label, _ in result.checkpoint_roots) == LABELS
    assert tuple(label for label, _ in result.control_dose_receipt_paths) == (
        "association", "label", "world")
