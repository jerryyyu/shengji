from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import shengji.rl.world_afterstate_v2_execution as execution

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_audit_attempt import (
    reopen_audit_attempt_bytes,
)
from shengji.rl.world_afterstate_v2_execution import (
    ALLOWED_SPLITS, AUTHORITY, STAGE_ORDER, ExecutionFreezeV2, PipelineAdmissionV2,
    REVIEW_PREFIX, StageSupervisorV2, WorldAfterstateV2ExecutionError,
    StageStateV2,
    SourceBindingV2, MissingStageError, bind_stage_controller,
    authenticate_review_commit, build_admission, consumption_tombstone_path,
    execution_freeze_from_bytes, expected_review_claim, initialize_admission,
    pipeline_consumption_tombstone_bytes, source_manifest_sha256,
    live_runtime_profile,
    validate_production_stage_set, bind_production_stage_controller,
    production_stage_controllers, StageControllerV2,
)
import shengji.rl.world_afterstate_v2_stage_adapters as stage_adapters
from shengji.rl.world_afterstate_v2_stage_adapters import (
    StageAdapterUnavailable, population_reopen_adapter,
)


def _sha(value) -> str:
    raw = value.encode() if isinstance(value, str) else canonical_json_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _controller(stage, callback, name):
    return bind_stage_controller(stage, callback, controller_name=name)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(("git", *args), cwd=repo, check=True,
                          capture_output=True, text=True, env=env).stdout.strip()


def _fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Jerry")
    _git(repo, "config", "user.email", "jerry@example.com")
    (repo / "payload.py").write_text("PAYLOAD = 1\n")
    artifact_rows = []
    for label in ("protocol", "capacity", "population", "config", "seed",
                  "continuation-policy"):
        path = f"{label}.json"
        raw = (label + " artifact\n").encode()
        (repo / path).write_bytes(raw)
        artifact_rows.append((label, path, hashlib.sha256(raw).hexdigest()))
    (repo / "HANDOFF_REVIEW.md").write_text("# review\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    source_binding = SourceBindingV2("payload.py", 12, _sha("PAYLOAD = 1\n"))
    freeze = ExecutionFreezeV2(
        source_git=base, source_manifest_sha256=source_manifest_sha256(
            base, (source_binding,)),
        boot_identity=live_runtime_profile()["boot_identity"],
        runtime_sha256=_sha(live_runtime_profile()), protocol_sha256=artifact_rows[0][2],
        capacity_sha256=artifact_rows[1][2], population_sha256=artifact_rows[2][2],
        config_sha256=artifact_rows[3][2], seed_sha256=artifact_rows[4][2],
        continuation_policy_sha256=artifact_rows[5][2],
        evidence_root=str(tmp_path / "evidence"),
        source_bindings=(source_binding,),
        runtime_profile=live_runtime_profile(), artifact_bindings=tuple(artifact_rows),
    )
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(expected_review_claim(freeze))
    with (repo / "HANDOFF_REVIEW.md").open("ab") as handle:
        handle.write(marker)
    env = os.environ.copy()
    review_env = {**env, "GIT_AUTHOR_NAME": "Claude",
                  "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
                  "GIT_COMMITTER_NAME": "Claude",
                  "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "commit", "-qm", "Reviewed V2\n\nClaude-Session: https://claude.ai/code/session_fixture", env=review_env)
    review = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", review)
    remote = tmp_path / "canonical.git"
    subprocess.run(("git", "init", "--bare", "-q", str(remote)), check=True)
    _git(repo, "push", str(remote), f"{review}:refs/heads/main")
    return repo, freeze, review, marker, remote


def test_freeze_serialization_binds_all_identity_hashes_and_authority(tmp_path):
    _repo, freeze, _review, _marker, _remote = _fixture(tmp_path)
    raw = freeze.canonical_bytes()
    assert execution_freeze_from_bytes(raw) == freeze
    json_keys = set(__import__("json").loads(raw))
    assert json_keys
    assert "authority" in json_keys
    assert all(value is False for value in AUTHORITY.values())
    changed = replace(freeze, continuation_policy_sha256=_sha("other"))
    with pytest.raises(WorldAfterstateV2ExecutionError, match="artifact"):
        changed.sha256()


def test_stage_order_seals_primary_cohort_before_nested_curve():
    assert STAGE_ORDER == (
        "population", "p0-labels-gates", "optimizer-canary",
        "fit-select-labels", "block-1-natural", "nested-curve",
        "block-1-controls", "block-2-natural", "block-2-controls",
        "precision-select-power", "audit-attempt", "terminal",
        "reconstruction")


def test_production_stage_set_requires_frozen_inputs():
    with pytest.raises(TypeError):
        validate_production_stage_set()
    with pytest.raises(TypeError):
        production_stage_controllers()
    with pytest.raises(TypeError):
        bind_production_stage_controller("nested-curve")


def test_production_binding_dispatches_every_stage_through_closed_factory(
        monkeypatch):
    producers = {
        name: (lambda *args, _name=name, **kwargs: (_name, args, kwargs))
        for names in execution.CONTROLLER_BINDINGS.values() for name in names}
    calls = []

    class Adapter:
        __world_afterstate_v2_stage_adapter__ = execution.STAGE_ADAPTER_ABI
        __module__ = "shengji.rl.world_afterstate_v2_stage_adapters"

        def __init__(self, producer):
            self.producer = producer

        def __call__(self, *_args, **_kwargs):
            return None

    class AuditAdapter(Adapter):
        __module__ = "shengji.rl.world_afterstate_v2_stage_adapters"

        def prepare_stage_payload(self, _supervisor):
            return {"preflight_relative_path": "audit-preflight.json",
                    "preflight_sha256": "a" * 64}

    def factory(stage, *, freeze, repo):
        calls.append((stage, freeze, repo))
        kind = AuditAdapter if stage == "audit-attempt" else Adapter
        return kind(producers[execution.CONTROLLER_BINDINGS[stage][0]])

    monkeypatch.setattr(stage_adapters, "production_stage_adapter", factory,
                        raising=False)
    monkeypatch.setattr(execution, "_production_callable",
                        lambda name: producers.get(name))
    freeze = object()
    repo = Path("/sealed/repository")
    missing = validate_production_stage_set(freeze=freeze, repo=repo)
    assert missing == ()
    assert [(stage, frozen, checked_repo) for stage, frozen, checked_repo in calls] == [
        (stage, freeze, repo) for stage in STAGE_ORDER]


def test_actual_production_factory_binds_the_complete_reviewed_stage_set(
        tmp_path):
    """Exercise the real cross-module factories, not a monkeypatched twin."""
    repo, freeze, _review, _marker, _remote = _fixture(tmp_path)
    evidence = Path(freeze.evidence_root)
    evidence.mkdir()
    population_raw = canonical_json_bytes({
        "schema": stage_adapters.INPUT_SCHEMA,
        "population_namespace_sha256": "c" * 64,
        "max_attempts_per_slot": 2, "workers": 2,
        "deadline_seconds": 120, "heartbeat_seconds": 30,
    })
    config_raw = canonical_json_bytes({
        "schema": stage_adapters.STAGE_INPUT_SCHEMA,
        "artifact_root": str(evidence),
        "population_namespace_sha256": "c" * 64,
        "label_workers": 1, "label_deadline_seconds": 120,
        "p0-labels-gates": {}, "optimizer-canary": {}, "nested-curve": {},
    })
    replacements = {
        "population": (population_raw, hashlib.sha256(population_raw).hexdigest()),
        "config": (config_raw, hashlib.sha256(config_raw).hexdigest()),
    }
    bindings = []
    for label, relative, digest in freeze.artifact_bindings:
        if label in replacements:
            raw, digest = replacements[label]
            path = repo / relative
            path.write_bytes(raw)
            path.chmod(0o400)
        bindings.append((label, relative, digest))
    freeze = replace(
        freeze, artifact_bindings=tuple(bindings),
        population_sha256=replacements["population"][1],
        config_sha256=replacements["config"][1])
    assert validate_production_stage_set(freeze=freeze, repo=repo) == ()
    controllers = production_stage_controllers(freeze=freeze, repo=repo)
    assert tuple(controllers) == STAGE_ORDER
    assert all(controller.production for controller in controllers.values())


def test_direct_low_level_controller_is_not_a_production_adapter(monkeypatch):
    producer = lambda *_args, **_kwargs: None
    monkeypatch.setattr(execution, "_production_callable",
                        lambda name: producer if name == "collect_population_v2"
                        else None)
    with pytest.raises(MissingStageError, match="stage adapter ABI"):
        StageControllerV2("population", "collect_population_v2", producer,
                          production=True).validate()


def test_population_adapter_refuses_untyped_frozen_input(tmp_path):
    repo, freeze, _review, _marker, _remote = _fixture(tmp_path)
    with pytest.raises(StageAdapterUnavailable, match="adapter input"):
        population_reopen_adapter(freeze=freeze, repo=repo)


def test_marker_authentication_and_source_mutation_fail_before_admission(tmp_path):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    assert authenticate_review_commit(freeze, repo=repo, review_commit=review,
                                     remote_url=str(remote)) == marker
    (repo / "payload.py").write_text("PAYLOAD = 2\n")
    with pytest.raises(WorldAfterstateV2ExecutionError, match="source checkout"):
        initialize_admission(tmp_path / "evidence", freeze_raw=freeze.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))
    assert not consumption_tombstone_path(tmp_path / "evidence").exists()


def test_review_marker_appends_after_prior_freeze_without_reusing_it(tmp_path):
    repo, first_freeze, _first_review, first_marker, remote = _fixture(tmp_path)
    second_freeze = replace(
        first_freeze, evidence_root=str(tmp_path / "second-evidence"))
    second_marker = (REVIEW_PREFIX.encode()
                     + canonical_json_bytes(expected_review_claim(second_freeze)))
    assert second_marker != first_marker
    with (repo / "HANDOFF_REVIEW.md").open("ab") as handle:
        handle.write(second_marker)
    review_env = {**os.environ, "GIT_AUTHOR_NAME": "Claude",
                  "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
                  "GIT_COMMITTER_NAME": "Claude",
                  "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "commit", "-qm",
         "Reviewed repaired V2\n\nClaude-Session: https://claude.ai/code/session_fixture_2",
         env=review_env)
    second_review = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", second_review)
    _git(repo, "push", str(remote), f"{second_review}:refs/heads/main")

    assert authenticate_review_commit(
        second_freeze, repo=repo, review_commit=second_review,
        remote_url=str(remote)) == second_marker
    with pytest.raises(WorldAfterstateV2ExecutionError, match="marker"):
        authenticate_review_commit(
            first_freeze, repo=repo, review_commit=second_review,
            remote_url=str(remote))


def test_ignored_pep552_bytecode_is_refused_before_admission(tmp_path):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    cache = repo / "__pycache__"
    cache.mkdir()
    # Magic/version/flags/hash-shaped bytes are sufficient to witness the
    # ignored-bytecode class; the source scan must refuse before import/use.
    (cache / "payload.cpython-314.pyc").write_bytes(b"\xa7\r\r\n" + b"\0" * 28)
    with pytest.raises(WorldAfterstateV2ExecutionError, match="bytecode"):
        initialize_admission(tmp_path / "evidence", freeze_raw=freeze.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))
    assert not consumption_tombstone_path(tmp_path / "evidence").exists()


def test_reviewed_boot_identity_drift_refuses_admission(tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    monkeypatch.setattr(execution, "_boot_identity", lambda: "different-boot")
    with pytest.raises(WorldAfterstateV2ExecutionError, match="runtime identity"):
        initialize_admission(tmp_path / "evidence", freeze_raw=freeze.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))


def test_runtime_executable_and_native_claim_mutation_refuses(tmp_path):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    profile = dict(freeze.runtime_profile)
    profile["python_executable_sha256"] = "0" * 64
    mutated = replace(freeze, runtime_profile=profile, runtime_sha256=_sha(profile))
    with pytest.raises(WorldAfterstateV2ExecutionError, match="runtime identity"):
        initialize_admission(tmp_path / "evidence", freeze_raw=mutated.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))


def test_fast_native_extension_path_and_sha_are_bound_when_present(tmp_path, monkeypatch):
    binary = tmp_path / "_fast.cpython-314-darwin.so"
    binary.write_bytes(b"native-extension")
    real_find_spec = execution.importlib.util.find_spec

    def find_spec(name):
        if name == "shengji.engine._fast":
            return __import__("types").SimpleNamespace(origin=str(binary))
        return real_find_spec(name)

    monkeypatch.setattr(execution.importlib.util, "find_spec", find_spec)
    profile = execution._native_extension_profile()
    assert profile == {"status": "present", "path": str(binary.resolve()),
                       "sha256": __import__("hashlib").sha256(
                           b"native-extension").hexdigest()}


def test_tombstone_prevents_rerun_after_root_deletion(tmp_path):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    assert admission.freeze_sha256 == freeze.sha256()
    shutil.rmtree(root)
    with pytest.raises(WorldAfterstateV2ExecutionError, match="occupied"):
        initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))


def test_audit_marker_precedes_first_audit_byte_and_only_one_open(tmp_path):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    # A non-scientific adapter cannot advance a reviewed admission, even when
    # its caller supplies a matching protocol name.
    with pytest.raises(MissingStageError, match="typed controller"):
        supervisor.run_stage("population", split="fit",
                             operation=_controller("population", lambda *_: None,
                               "collect_population_v2"))
    assert not (root / "audit-attempt.json").exists()
    supervisor._state = StageStateV2(
        STAGE_ORDER[:STAGE_ORDER.index("audit-attempt")])
    with pytest.raises(MissingStageError, match="pre-open"):
        supervisor.run_stage("audit-attempt", split="audit",
                             operation=_controller("audit-attempt", lambda *_: None,
                               "publish_audit_attempt"),
                             payload={"preflight_complete": True})
    assert not (root / "audit-attempt.json").exists()
    supervisor._open_audit_marker({"preflight_complete": True})
    assert (root / "audit-attempt.json").exists()
    reopened = reopen_audit_attempt_bytes(
        (root / "audit-attempt.json").read_bytes(),
        expected_freeze_sha256=freeze.sha256(),
        expected_admission_sha256=admission.sha256())
    assert reopened["preflight"] == {"preflight_complete": True}
    with pytest.raises(WorldAfterstateV2ExecutionError, match="already"):
        supervisor._open_audit_marker({"preflight_complete": True})


def test_interrupted_verified_shard_reopens_without_replacement(tmp_path):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    first = StageSupervisorV2(root, freeze, admission)
    first.register_verified_shard("population", "deal-0", b"sealed")
    second = StageSupervisorV2(root, freeze, admission)
    assert second.verified_shards("population") == ("deal-0",)
    with pytest.raises(WorldAfterstateV2ExecutionError, match="replacement"):
        second.register_verified_shard("population", "deal-0", b"changed")


def test_reconstruction_callback_is_independent_and_no_training_reentry(tmp_path):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    calls = []
    with pytest.raises(MissingStageError, match="typed controller"):
        supervisor.run_stage("population", split="fit",
                             operation=_controller("reconstruction",
                               lambda *_: calls.append("reconstruct"),
                               "verify_terminal_artifact_v2"))
    assert calls == []
    assert supervisor.state.reconstruction_completed is False


def test_deadline_and_telemetry_are_persistent_across_resume(tmp_path, monkeypatch):
    repo, base_freeze, review, _marker, remote = _fixture(tmp_path)
    freeze = replace(base_freeze, deadline_seconds=1)
    # The marker must bind this exact candidate freeze.
    (repo / "HANDOFF_REVIEW.md").write_bytes(
        (repo / "HANDOFF_REVIEW.md").read_bytes())
    # A changed freeze cannot reuse the prior review marker.
    with pytest.raises(WorldAfterstateV2ExecutionError, match="marker"):
        initialize_admission(tmp_path / "evidence", freeze_raw=freeze.canonical_bytes(),
                             repo=repo, review_commit=review, remote_url=str(remote))

    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=base_freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, base_freeze, admission,
                                  clock=lambda: json.loads(
                                      (root / "supervisor-meta.json").read_text())[
                                          "started_monotonic_ns"])
    progress = supervisor.emit_progress(stage="population", completed=0,
                                        total=1, force=True)
    assert progress["cpu_utilization_ppm"] >= 0
    assert progress["cgroup_memory_bytes"] > 0
    started = json.loads((root / "supervisor-meta.json").read_text())["started_monotonic_ns"]
    expired_clock = lambda: started + base_freeze.deadline_seconds * 1_000_000_000
    expired = StageSupervisorV2(root, base_freeze, admission, clock=expired_clock)
    with pytest.raises(WorldAfterstateV2ExecutionError, match="RESOURCE_INCOMPLETE"):
        expired.run_stage("population", split="fit", operation=None)
    resumed = StageSupervisorV2(root, base_freeze, admission, clock=expired_clock)
    with pytest.raises(WorldAfterstateV2ExecutionError, match="RESOURCE_INCOMPLETE"):
        resumed.run_stage("population", split="fit", operation=None)
    monkeypatch.setattr(execution, "live_runtime_profile", lambda: {"runtime": "drift"})
    with pytest.raises(WorldAfterstateV2ExecutionError, match="runtime identity"):
        execution.reopen_supervisor(root, freeze=base_freeze, admission=admission,
                                    review_marker=_marker)


def test_reopen_requires_exact_completed_prefix_and_live_telemetry(tmp_path, monkeypatch):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    monkeypatch.setattr(execution, "_live_telemetry",
                        lambda _elapsed: (_ for _ in ()).throw(
                            WorldAfterstateV2ExecutionError("telemetry unavailable")))
    with pytest.raises(WorldAfterstateV2ExecutionError, match="telemetry"):
        supervisor.emit_progress(stage="population", completed=0, total=1, force=True)
    monkeypatch.undo()
    supervisor._event("p0-labels-gates", status="complete", split="fit")
    with pytest.raises(WorldAfterstateV2ExecutionError, match="prefix"):
        execution.reopen_supervisor(root, freeze=freeze, admission=admission,
                                    review_marker=marker)


def test_reconstruction_receipt_must_cross_bind_terminal_bytes():
    terminal = canonical_json_bytes({"result_sha256": "a" * 64,
                                     "decision": "REFUSE_RESOURCE_INCOMPLETE"})
    receipt = canonical_json_bytes({"sealed_terminal_result_sha256": "b" * 64,
                                    "matched": True})
    with pytest.raises(WorldAfterstateV2ExecutionError, match="cross-binding"):
        execution._verify_reconstruction_binding(terminal, receipt)


def test_pipeline_runs_receipt_only_reconstruction_after_terminal(tmp_path, monkeypatch):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    # This is an orchestration-only witness.  Production adapters remain
    # closed; the callbacks below stand in for a composed adapter ABI.
    monkeypatch.setattr(execution.StageControllerV2, "validate", lambda _self: None)
    monkeypatch.setattr(execution, "_production_callable", lambda _name: object())
    result_sha = "a" * 64
    terminal_raw = canonical_json_bytes({
        "decision": "REFUSE_RESOURCE_INCOMPLETE", "result_sha256": result_sha})
    receipt_raw = canonical_json_bytes({
        "matched": True, "sealed_terminal_result_sha256": result_sha})
    calls = []

    def invoke(operation_supervisor, _shards):
        stage = operation_supervisor.next_stage
        if stage not in ("terminal", "reconstruction"):
            operation_supervisor.register_verified_shard(
                stage, "receipt", canonical_json_bytes({"stage": stage}))
        elif stage == "terminal":
            target = root / "terminal"
            target.mkdir()
            (target / "terminal.json").write_bytes(terminal_raw)
            os.chmod(target / "terminal.json", 0o400)
            (target / "independent-reconstruction.json").write_bytes(receipt_raw)
            os.chmod(target / "independent-reconstruction.json", 0o400)
        elif stage == "reconstruction":
            def verify_receipt(_root, _inputs, *, rescore=False):
                calls.append(("verify", rescore))
                assert rescore is False
                execution._verify_reconstruction_binding(terminal_raw, receipt_raw)
                assert (root / "terminal" / "independent-reconstruction.json").read_bytes() == receipt_raw
            # The composed adapter's contract is receipt-only verification;
            # it passes the reviewed producer an explicit rescore=False.
            verify_receipt(root / "terminal", object(), rescore=False)

    def prepare_audit(operation_supervisor):
        preflight_body = {
            "schema": execution.AUDIT_PREFLIGHT_SCHEMA,
            "freeze_sha256": freeze.sha256(),
            "admission_sha256": admission.sha256(),
            "completed_stages": list(execution.AUDIT_PREFLIGHT_STAGES),
            "upstream_receipt_sha256s": [
                [stage, __import__("hashlib").sha256(canonical_json_bytes(
                    {"stage": stage})).hexdigest()]
                for stage in execution.AUDIT_PREFLIGHT_STAGES],
            "audit_paths_absent": list(execution.AUDIT_UNOPENED_PATHS),
        }
        preflight_body["preflight_sha256"] = _sha(preflight_body)
        (root / "audit-preflight.json").write_bytes(
            canonical_json_bytes(preflight_body))
        os.chmod(root / "audit-preflight.json", 0o400)
        return {"preflight_relative_path": "audit-preflight.json",
                "preflight_sha256": preflight_body["preflight_sha256"]}

    operations = {}
    for stage in STAGE_ORDER:
        name = execution.CONTROLLER_BINDINGS[stage][0]
        operations[stage] = execution.StageControllerV2(
            stage, name, invoke, True,
            stage_payload_factory=(prepare_audit
                                   if stage == "audit-attempt" else None))
    execution.run_v2_pipeline(supervisor, operations)
    assert calls == [("verify", False)]
    assert supervisor.state.reconstruction_completed is True
    resumed = execution.reopen_supervisor(
        root, freeze=freeze, admission=admission, review_marker=marker)
    execution.run_v2_pipeline(resumed, operations)
    assert calls == [("verify", False)]


def test_interrupted_audit_stage_reuses_exact_marker_on_resume(tmp_path):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    completed = []
    receipt_rows = []
    for stage in execution.AUDIT_PREFLIGHT_STAGES:
        raw = canonical_json_bytes({"stage": stage})
        supervisor.register_verified_shard(stage, "receipt", raw)
        supervisor._event(stage, status="complete",
                          split=execution.ALLOWED_SPLITS[stage][0])
        completed.append(stage)
        receipt_rows.append([stage, __import__("hashlib").sha256(raw).hexdigest()])
    supervisor._state = StageStateV2(
        tuple(completed), verified_shards=supervisor.state.verified_shards)
    body = {
        "schema": execution.AUDIT_PREFLIGHT_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "completed_stages": completed,
        "upstream_receipt_sha256s": receipt_rows,
        "audit_paths_absent": list(execution.AUDIT_UNOPENED_PATHS),
    }
    value = {**body, "preflight_sha256": _sha(body)}
    (root / execution.AUDIT_PREFLIGHT_RELATIVE).write_bytes(
        canonical_json_bytes(value))
    os.chmod(root / execution.AUDIT_PREFLIGHT_RELATIVE, 0o400)
    payload = {"preflight_relative_path": execution.AUDIT_PREFLIGHT_RELATIVE,
               "preflight_sha256": value["preflight_sha256"]}
    supervisor._validate_audit_preflight(payload)
    supervisor._open_audit_marker(payload)

    resumed = execution.reopen_supervisor(
        root, freeze=freeze, admission=admission, review_marker=marker)
    assert resumed.state.audit_opened is True
    resumed._validate_audit_preflight(payload)
    before = (root / "audit-attempt.json").read_bytes()
    resumed._open_audit_marker(payload)
    assert (root / "audit-attempt.json").read_bytes() == before


def test_p0_stop_skips_training_and_seals_terminal_then_reconstruction(
        tmp_path, monkeypatch):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    monkeypatch.setattr(execution.StageControllerV2, "validate",
                        lambda _self: None)
    monkeypatch.setattr(execution, "_production_callable", lambda _name: object())
    route = "STOP_NO_REPRODUCIBLE_VALUE_LABEL"
    result_sha = "c" * 64
    terminal_raw = canonical_json_bytes({
        "decision": route, "result_sha256": result_sha})
    receipt_raw = canonical_json_bytes({
        "matched": True, "sealed_terminal_result_sha256": result_sha})
    calls = []

    def invoke(operation_supervisor, _shards):
        stage = operation_supervisor.next_stage
        calls.append(stage)
        if stage == "p0-labels-gates":
            operation_supervisor.terminal(route)
        elif stage == "terminal":
            target = root / "terminal"
            target.mkdir()
            (target / "terminal.json").write_bytes(terminal_raw)
            os.chmod(target / "terminal.json", 0o400)
            (target / "independent-reconstruction.json").write_bytes(
                receipt_raw)
            os.chmod(target / "independent-reconstruction.json", 0o400)
        elif stage == "reconstruction":
            execution._verify_reconstruction_binding(terminal_raw, receipt_raw)

    operations = {
        stage: execution.StageControllerV2(
            stage, execution.CONTROLLER_BINDINGS[stage][0], invoke, True)
        for stage in STAGE_ORDER}
    state = execution.run_v2_pipeline(supervisor, operations)
    assert calls == ["population", "p0-labels-gates", "terminal",
                     "reconstruction"]
    assert state.completed_stages == (
        "population", "p0-labels-gates", "terminal", "reconstruction")
    assert state.terminal_route == route
    assert state.reconstruction_completed is True
    resumed = execution.reopen_supervisor(
        root, freeze=freeze, admission=admission, review_marker=marker)
    assert resumed.state == state
