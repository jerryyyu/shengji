from __future__ import annotations

import hashlib
import functools
import json
import multiprocessing
import os
import shutil
import subprocess
import time
from types import SimpleNamespace
from dataclasses import replace
from pathlib import Path

import pytest
import shengji.rl.world_afterstate_v2_execution as execution

pytestmark = pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded, use of fork.*:DeprecationWarning")

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_audit_attempt import (
    reopen_audit_attempt_bytes,
)
from shengji.rl.world_afterstate_v2_execution import (
    ALLOWED_SPLITS, AUTHORITY, STAGE_ORDER, ExecutionFreezeV2, PipelineAdmissionV2,
    REVIEW_PREFIX, StageSupervisorV2, WorldAfterstateV2ExecutionError,
    DurableProgressSinkV2,
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
from shengji.rl.world_afterstate_v2_protocol import SCIENTIFIC_SERVICE_SECONDS


@pytest.fixture(autouse=True)
def _unit_controller_context(monkeypatch):
    """Local callback-heavy unit tests use fork; production defaults to spawn."""
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("fork"))
    # Torch's reported thread width can change across a fork.  These local
    # callback tests exercise orchestration, not the production spawn/runtime
    # boundary, which has its own real-child witness below.
    monkeypatch.setattr(execution, "bind_runtime_expectation", lambda _sha: None)
    monkeypatch.setattr(execution, "verify_live_runtime_sha256", lambda _sha: None)


def _delayed_sentinel(path: Path, _supervisor, _shards) -> None:
    time.sleep(2)
    path.write_text("late")


def _spawn_publication(supervisor, _shards) -> str:
    supervisor.register_verified_shard(
        "population", "spawn-proof", canonical_json_bytes({"ok": True}))
    supervisor.emit_progress(
        stage="population", substage="spawn-proof", completed=1, total=1,
        sealed_shards=1, force=True)
    return "published"


def _spawn_runtime_binding(supervisor, _shards) -> bool:
    profile_sha = hashlib.sha256(
        canonical_json_bytes(execution.live_runtime_profile())).hexdigest()
    return (os.environ.get(execution.RUNTIME_EXPECTATION_ENV)
            == supervisor.freeze.runtime_sha256 == profile_sha)


class _StepClock:
    def __init__(self, values):
        self.values = tuple(values)
        self.index = 0

    def __call__(self):
        index = min(self.index, len(self.values) - 1)
        self.index += 1
        return self.values[index]


def _raise_controller_deadline(_supervisor, _shards):
    raise WorldAfterstateV2ExecutionError(
        "controller deadline expired before operation")


def test_production_controller_context_is_clean_spawn(monkeypatch):
    monkeypatch.undo()
    assert execution._controller_context().get_start_method() == "spawn"


def test_execution_freeze_accepts_the_full_scientific_service_window(tmp_path):
    """Protocol service time must be constructible at the execution boundary."""
    _repo, base_freeze, _review, _marker, _remote = _fixture(tmp_path)
    assert execution.MAX_DEADLINE_SECONDS == SCIENTIFIC_SERVICE_SECONDS \
        == 18 * 60 * 60
    assert replace(
        base_freeze, deadline_seconds=SCIENTIFIC_SERVICE_SECONDS
    ).canonical_bytes()
    with pytest.raises(
            WorldAfterstateV2ExecutionError, match="freeze deadline drift"):
        replace(
            base_freeze, deadline_seconds=SCIENTIFIC_SERVICE_SECONDS + 1
        ).canonical_bytes()


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
                  "continuation-policy", "population-rehearsal"):
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
        population_rehearsal_sha256=artifact_rows[6][2],
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
        "max_attempts_per_slot": 128, "workers": 2,
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
    # Production dispatch uses a clean ``spawn`` context.  Exercise the real
    # closed adapters with the same pickler so a callback that works only
    # under the unit suite's local ``fork`` context cannot reach a long run.
    assert all(
        multiprocessing.reduction.ForkingPickler.dumps(controller.operation)
        for controller in controllers.values())


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


def test_runtime_profile_binds_python_prefix_and_pyvenv_config(monkeypatch,
                                                                tmp_path):
    venv = tmp_path / "repaired-head-venv"
    venv.mkdir()
    monkeypatch.setattr(execution.sys, "prefix", str(venv))
    monkeypatch.setattr(execution.sys, "base_prefix", str(tmp_path / "base"))
    (tmp_path / "base").mkdir()
    (venv / "pyvenv.cfg").write_bytes(b"home = repaired-head\n")
    first = execution.live_runtime_profile()
    assert first["python_prefix"] == str(venv.resolve())
    assert first["python_base_prefix"] == str((tmp_path / "base").resolve())
    assert first["pyvenv_cfg_sha256"] != "absent"
    (venv / "pyvenv.cfg").write_bytes(b"home = different-head\n")
    second = execution.live_runtime_profile()
    assert second["pyvenv_cfg_sha256"] != first["pyvenv_cfg_sha256"]
    assert execution._sha(first) != execution._sha(second)


def test_fast_native_extension_path_and_sha_are_bound_when_present(tmp_path, monkeypatch):
    package = tmp_path / "server" / "shengji"
    (package / "rl").mkdir(parents=True)
    (package / "engine").mkdir()
    binary = package / "engine" / "_fast.cpython-314-darwin.so"
    binary.write_bytes(b"native-extension")
    monkeypatch.setattr(execution, "__file__", str(package / "rl" / "execution.py"))
    monkeypatch.setattr(
        execution.importlib.util, "find_spec",
        lambda _name: __import__("types").SimpleNamespace(origin=str(binary)))
    loaded = {"status": "verified", "device_major": 1,
              "device_minor": 2, "inode": 3}
    monkeypatch.setattr(
        execution, "_loaded_native_file_identity",
        lambda _path, _metadata: loaded)
    profile = execution._native_extension_profile()
    assert profile == {"status": "present", "path": str(binary.resolve()),
                       "sha256": __import__("hashlib").sha256(
                           b"native-extension").hexdigest(),
                       "loaded_file_identity": loaded}


def test_foreign_fast_native_extension_origin_is_refused(tmp_path, monkeypatch):
    package = tmp_path / "server" / "shengji"
    (package / "rl").mkdir(parents=True)
    (package / "engine").mkdir()
    foreign = tmp_path / "foreign" / "_fast.cpython-314-darwin.so"
    foreign.parent.mkdir()
    foreign.write_bytes(b"foreign")
    monkeypatch.setattr(execution, "__file__", str(package / "rl" / "execution.py"))
    monkeypatch.setattr(
        execution.importlib.util, "find_spec",
        lambda _name: __import__("types").SimpleNamespace(origin=str(foreign)))
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="native extension origin drift"):
        execution._native_extension_profile()


def test_linux_loaded_native_identity_refuses_atomic_replacement(
        tmp_path, monkeypatch):
    native = tmp_path / "_fast.cpython-314-x86_64-linux-gnu.so"
    native.write_bytes(b"loaded-inode")
    metadata = native.stat()
    maps = tmp_path / "maps"
    maps.write_text(
        "1000-2000 r-xp 00000000 "
        f"{os.major(metadata.st_dev):02x}:{os.minor(metadata.st_dev):02x} "
        f"{metadata.st_ino} {native.resolve()}\n")
    monkeypatch.setattr(execution.sys, "platform", "linux")
    monkeypatch.setattr(execution, "_PROC_SELF_MAPS", maps)
    monkeypatch.setenv("SHENGJI_FAST", "1")
    assert execution._loaded_native_file_identity(
        native.resolve(), metadata)["status"] == "verified"

    replacement = tmp_path / "replacement.so"
    replacement.write_bytes(b"replacement-inode")
    replacement.replace(native)
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="loaded native extension inode drift"):
        execution._loaded_native_file_identity(native.resolve(), native.stat())


def test_native_snapshot_refuses_path_replacement_during_open_read(
        tmp_path, monkeypatch):
    native = tmp_path / "_fast.cpython-314-x86_64-linux-gnu.so"
    native.write_bytes(b"opened-inode")
    original = native.stat()
    replacement = tmp_path / "replacement.so"
    replacement.write_bytes(b"replacement-inode")
    real_read = execution.os.read
    replaced = False

    def replace_then_read(descriptor, size):
        nonlocal replaced
        if not replaced:
            replaced = True
            replacement.replace(native)
        return real_read(descriptor, size)

    monkeypatch.setattr(execution.os, "read", replace_then_read)
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="native extension changed during read"):
        execution._native_file_snapshot(native)
    assert original.st_ino != native.stat().st_ino
    assert native.read_bytes() == b"replacement-inode"


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
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="resource-closed"):
        StageSupervisorV2(root, base_freeze, admission, clock=expired_clock)
    closeout = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=base_freeze, admission=admission)
    assert closeout["decision"] == "REFUSE_RESOURCE_INCOMPLETE"
    assert closeout["resource_stage"] == "population"
    monkeypatch.setattr(execution, "live_runtime_profile", lambda: {"runtime": "drift"})
    with pytest.raises(WorldAfterstateV2ExecutionError, match="runtime identity"):
        execution.reopen_supervisor(root, freeze=base_freeze, admission=admission,
                                    review_marker=_marker)


def test_frozen_heartbeat_controls_progress_throttle_and_controller_poll(
        tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    supervisor._last_progress = 10_000_000_000
    supervisor.clock = lambda: 10_000_000_000 + (
        freeze.heartbeat_seconds - 1) * 1_000_000_000
    assert supervisor.emit_progress(
        stage="population", completed=0, total=2) == {}
    supervisor.clock = lambda: 10_000_000_000 + (
        freeze.heartbeat_seconds * 1_000_000_000)
    assert supervisor.emit_progress(
        stage="population", completed=0, total=2)["stage"] == "population"

    assert supervisor._invoke_controller(
        lambda *_: "done", "population", 1) == "done"


def test_deadline_kills_controller_group_before_resource_closeout(
        tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    sentinel = tmp_path / "controller-survived"
    meta_path = root / "supervisor-meta.json"
    meta = json.loads(meta_path.read_bytes())
    meta["started_monotonic_ns"] = (
        time.monotonic_ns()
        - freeze.deadline_seconds * 1_000_000_000 + 100_000_000)
    meta["meta_sha256"] = _sha({
        key: value for key, value in meta.items() if key != "meta_sha256"})
    meta_path.chmod(0o600)
    meta_path.write_bytes(canonical_json_bytes(meta))
    meta_path.chmod(0o400)
    supervisor = StageSupervisorV2(root, freeze, admission)
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("spawn"))

    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="RESOURCE_INCOMPLETE"):
        supervisor._invoke_controller(
            functools.partial(_delayed_sentinel, sentinel),
            "population", 1)
    time.sleep(0.2)
    assert not sentinel.exists()
    closeout = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=freeze, admission=admission)
    assert closeout["resource_stage"] == "population"
    assert closeout["audit_opened_count"] == 0


@pytest.mark.parametrize("stage,completed,route", (
    ("terminal", execution.WORK_STAGE_ORDER, None),
    ("reconstruction", (*execution.WORK_STAGE_ORDER, "terminal"),
     "PASS_ABSOLUTE_VALUE_LEARNING_ONLY"),
))
def test_expired_real_terminal_dispatch_never_starts_controller(
        tmp_path, stage, completed, route):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    started = json.loads(
        (root / "supervisor-meta.json").read_text())["started_monotonic_ns"]
    sentinel = tmp_path / f"{stage}-started"
    supervisor = StageSupervisorV2(
        root, freeze, admission,
        clock=lambda: started + freeze.deadline_seconds * 1_000_000_000)
    supervisor._state = StageStateV2(
        tuple(completed), route,
        "audit-attempt" in completed, stage == "reconstruction" and False)
    controller = execution.StageControllerV2(
        stage, execution.CONTROLLER_BINDINGS[stage][0],
        functools.partial(_delayed_sentinel, sentinel), production=True)

    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="REFUSE_RESOURCE_INCOMPLETE"):
        supervisor.run_stage(
            stage, split="audit", operation=controller)
    assert not sentinel.exists()
    receipt = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=freeze, admission=admission)
    assert receipt["resource_stage"] == stage
    assert receipt["prior_terminal_route"] == route


def test_spawn_controller_reopens_child_shard_and_progress_publications(
        tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    progress = DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    supervisor = StageSupervisorV2(
        root, freeze, admission, progress_callback=progress)
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("spawn"))

    assert supervisor._invoke_controller(
        _spawn_publication, "population", 1) == "published"
    assert supervisor.verified_shards("population") == ("spawn-proof",)
    events = sorted((root / execution.PROGRESS_DIRECTORY).glob("*.json"))
    assert len(events) == 1
    event = json.loads(events[0].read_bytes())
    assert event["snapshot"]["substage"] == "spawn-proof"
    assert event["snapshot"]["sealed_shards"] == 1


def test_spawn_controller_binds_runtime_inside_actual_child(tmp_path, monkeypatch):
    monkeypatch.undo()
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("spawn"))

    assert supervisor._invoke_controller(
        _spawn_runtime_binding, "population", 1) is True


def test_spawn_expiry_race_seals_closeout_in_parent(tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    limit = freeze.deadline_seconds * 1_000_000_000
    supervisor._started = 0
    # Parent pre-spawn and first poll remain just inside the wall.  The child
    # refuses before operation; by the parent's post-result check the original
    # admission wall has expired.
    supervisor.clock = _StepClock((0, 0, 0, limit))
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("spawn"))

    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="REFUSE_RESOURCE_INCOMPLETE"):
        supervisor._invoke_controller(
            _raise_controller_deadline, "population", 1)
    receipt = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=freeze, admission=admission)
    assert receipt["resource_stage"] == "population"
    assert receipt["completed_stages"] == []


def test_postresult_expiry_closeout_binds_child_publications(
        tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    progress = DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    supervisor = StageSupervisorV2(
        root, freeze, admission, progress_callback=progress)
    limit = freeze.deadline_seconds * 1_000_000_000
    supervisor._started = 0
    supervisor.clock = _StepClock((0, 0, 0, limit))
    monkeypatch.setattr(
        execution, "_controller_context",
        lambda: multiprocessing.get_context("spawn"))

    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="REFUSE_RESOURCE_INCOMPLETE"):
        supervisor._invoke_controller(
            _spawn_publication, "population", 1)
    receipt = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=freeze, admission=admission)
    assert receipt["verified_shards"] == [[
        "population:spawn-proof",
        hashlib.sha256(canonical_json_bytes({"ok": True})).hexdigest(),
    ]]
    recovery = StageSupervisorV2(
        root, freeze, admission, resource_closeout_only=True)
    execution._validate_closeout_state(receipt, recovery)


def test_cross_boot_can_only_seal_resource_incomplete_closeout(
        tmp_path, monkeypatch):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    monkeypatch.setattr(execution, "_boot_identity", lambda: "new-boot")
    receipt = execution.seal_resource_incomplete_recovery(
        root, freeze=freeze, admission=admission,
        review_marker=marker, repo=repo)
    assert receipt["decision"] == "REFUSE_RESOURCE_INCOMPLETE"
    assert receipt["cross_boot"] is True
    assert receipt["audit_opened_count"] == 0
    assert execution.seal_resource_incomplete_recovery(
        root, freeze=freeze, admission=admission,
        review_marker=marker, repo=repo) == receipt
    assert execution.verify_resource_incomplete_recovery(
        root, freeze=freeze, admission=admission,
        review_marker=marker, repo=repo) == receipt
    recovery = StageSupervisorV2(
        root, freeze, admission, resource_closeout_only=True)
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="cannot run scientific"):
        recovery.run_stage("population", split="fit", operation=None)


def test_deadline_during_reconstruction_preserves_but_invalidates_prior_route(
        tmp_path):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    started = json.loads(
        (root / "supervisor-meta.json").read_text())["started_monotonic_ns"]
    supervisor = StageSupervisorV2(
        root, freeze, admission,
        clock=lambda: started + freeze.deadline_seconds * 1_000_000_000)
    prior = "PASS_ABSOLUTE_VALUE_LEARNING_ONLY"
    supervisor._state = StageStateV2(("terminal",), prior)
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="RESOURCE_INCOMPLETE"):
        supervisor._deadline()
    receipt = execution.reopen_resource_incomplete_closeout(
        (root / execution.RESOURCE_CLOSEOUT_RELATIVE).read_bytes(),
        freeze=freeze, admission=admission)
    assert receipt["decision"] == "REFUSE_RESOURCE_INCOMPLETE"
    assert receipt["prior_terminal_route"] == prior
    assert receipt["resource_stage"] == "reconstruction"


def test_live_telemetry_includes_process_pool_children(monkeypatch):
    own = SimpleNamespace(ru_utime=0.25, ru_stime=0.25, ru_maxrss=10)
    children = SimpleNamespace(ru_utime=0.5, ru_stime=0.5, ru_maxrss=0)
    monkeypatch.setattr(execution, "_cgroup_v2_directory", lambda: None)
    monkeypatch.setattr(execution, "_process_memory_bytes", lambda _usage: 1)
    monkeypatch.setattr(execution.resource, "getrusage",
                        lambda kind: own if kind == execution.resource.RUSAGE_SELF
                        else children)

    cpu_ppm, memory = execution._live_telemetry(
        1_000_000_000, process_cpu_baseline=0)

    assert cpu_ppm == 1_500_000
    assert memory == 1


def test_supervisor_telemetry_baselines_reset_on_resume(tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review,
                                     remote_url=str(remote))
    started = json.loads((root / "supervisor-meta.json").read_text())["started_monotonic_ns"]
    clock_values = iter((started, started + 1_000_000_000,
                         started + 2_000_000_000, started + 3_000_000_000))
    cpu_totals = iter((500_000_000, 500_000_000,
                       1_000_000_000, 1_000_000_000,
                       1_000_000_000, 1_000_000_000,
                       1_500_000_000, 1_500_000_000))
    monkeypatch.setattr(execution, "_cgroup_v2_directory", lambda: None)
    monkeypatch.setattr(execution, "_process_memory_bytes", lambda _usage: 1)
    monkeypatch.setattr(execution, "resource", SimpleNamespace(
        RUSAGE_SELF=0, RUSAGE_CHILDREN=-1,
        getrusage=lambda _kind: SimpleNamespace(
            ru_utime=next(cpu_totals) / 1_000_000_000,
            ru_stime=0, ru_maxrss=1)))
    first = StageSupervisorV2(root, freeze, admission, clock=lambda: next(clock_values))
    first_progress = first.emit_progress(stage="population", completed=0,
                                         total=1, force=True)
    resumed = StageSupervisorV2(root, freeze, admission,
                                clock=lambda: next(clock_values))
    resumed_progress = resumed.emit_progress(stage="population", completed=0,
                                             total=1, force=True)

    assert first_progress["cpu_utilization_ppm"] == 1_000_000
    assert resumed_progress["cpu_utilization_ppm"] == 1_000_000
    assert first_progress["elapsed_nanoseconds"] == 1_000_000_000
    assert resumed_progress["elapsed_nanoseconds"] == 3_000_000_000


def test_durable_progress_prefix_is_bound_and_resumes(tmp_path):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review,
                                     remote_url=str(remote))
    snapshots = []
    sink = DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    supervisor = StageSupervisorV2(root, freeze, admission,
                                   progress_callback=snapshots.append)
    snapshot = supervisor.emit_progress(stage="population", completed=0,
                                        total=1, force=True)
    sink(snapshot)
    assert sink.next_index == 1
    resumed = DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    assert resumed.next_index == 1
    resumed(snapshot)
    assert resumed.next_index == 2


@pytest.mark.parametrize("tamper", ("tamper", "gap", "foreign"))
def test_durable_progress_reopen_refuses_tamper_gap_or_foreign_admission(
        tmp_path, tamper):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review,
                                     remote_url=str(remote))
    sink = DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    supervisor = StageSupervisorV2(root, freeze, admission)
    sink(supervisor.emit_progress(stage="population", completed=0, total=1,
                                  force=True))
    path = root / "progress" / "00000000.json"
    if tamper == "tamper":
        os.chmod(path, 0o600)
        path.write_bytes(path.read_bytes().replace(b'"index":0', b'"index":1'))
        os.chmod(path, 0o400)
        with pytest.raises(WorldAfterstateV2ExecutionError):
            DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    elif tamper == "gap":
        path.rename(root / "progress" / "00000002.json")
        with pytest.raises(WorldAfterstateV2ExecutionError, match="prefix"):
            DurableProgressSinkV2(root, freeze=freeze, admission=admission)
    else:
        foreign = replace(admission, review_commit="a" * 40)
        with pytest.raises(WorldAfterstateV2ExecutionError, match="identity|binding"):
            DurableProgressSinkV2(root, freeze=freeze, admission=foreign)


def test_live_telemetry_uses_process_cgroup_v2_directory(tmp_path, monkeypatch):
    proc_cgroup = tmp_path / "proc-self-cgroup"
    cgroup_root = tmp_path / "sys-fs-cgroup"
    directory = cgroup_root / "tenant" / "worker"
    directory.mkdir(parents=True)
    proc_cgroup.write_text("0::/tenant/worker\n")
    (directory / "cpu.stat").write_text("usage_usec 2500\nuser_usec 2400\n")
    (directory / "memory.current").write_text("4096\n")
    original_resolver = execution._cgroup_v2_directory
    resolver = lambda: original_resolver(
        proc_cgroup=proc_cgroup, cgroup_root=cgroup_root)
    monkeypatch.setattr(execution, "_cgroup_v2_directory", resolver)
    stale = SimpleNamespace(ru_utime=10, ru_stime=0, ru_maxrss=1)
    monkeypatch.setattr(execution.resource, "getrusage", lambda _kind: stale)

    cpu_ppm, memory = execution._live_telemetry(
        1_000_000_000, process_cpu_baseline=20_000_000_000,
        cgroup_directory=directory,
        cgroup_cpu_baseline=2_000_000)

    assert execution._cgroup_v2_directory() == directory
    # Only the invocation-relative 500 usec delta contributes; the pre-run
    # cgroup counter is not treated as this supervisor's CPU time.
    assert cpu_ppm == 500
    assert memory == 4096


def test_live_telemetry_refuses_cross_cgroup_baseline(tmp_path, monkeypatch):
    cgroup_a = tmp_path / "a"
    cgroup_b = tmp_path / "b"
    cgroup_a.mkdir()
    cgroup_b.mkdir()
    (cgroup_b / "cpu.stat").write_text("usage_usec 9000000\n")
    (cgroup_b / "memory.current").write_text("4096\n")
    monkeypatch.setattr(execution, "_cgroup_v2_directory", lambda: cgroup_b)
    own = SimpleNamespace(ru_utime=1.25, ru_stime=0, ru_maxrss=1)
    children = SimpleNamespace(ru_utime=0.25, ru_stime=0, ru_maxrss=0)
    monkeypatch.setattr(execution.resource, "getrusage",
                        lambda kind: own if kind == execution.resource.RUSAGE_SELF
                        else children)

    cpu_ppm, memory = execution._live_telemetry(
        1_000_000_000, process_cpu_baseline=1_000_000_000,
        cgroup_directory=cgroup_a, cgroup_cpu_baseline=1_000_000)

    # The unrelated nine-second B counter must not be combined
    # with A's baseline.  Fall back to this process plus its children instead.
    assert cpu_ppm == 500_000
    assert memory == 4096


def test_live_telemetry_falls_back_on_malformed_cgroup_data(tmp_path, monkeypatch):
    proc_cgroup = tmp_path / "proc-self-cgroup"
    cgroup_root = tmp_path / "sys-fs-cgroup"
    directory = cgroup_root / "tenant"
    directory.mkdir(parents=True)
    proc_cgroup.write_text("0::/tenant\n")
    (directory / "cpu.stat").write_text("usage_usec not-an-integer\n")
    (directory / "memory.current").write_text("-1\n")
    original_resolver = execution._cgroup_v2_directory
    monkeypatch.setattr(execution, "_cgroup_v2_directory", lambda: original_resolver(
        proc_cgroup=proc_cgroup, cgroup_root=cgroup_root))
    own = SimpleNamespace(ru_utime=0.1, ru_stime=0.1, ru_maxrss=1)
    children = SimpleNamespace(ru_utime=0, ru_stime=0, ru_maxrss=0)
    monkeypatch.setattr(execution.resource, "getrusage",
                        lambda kind: own if kind == execution.resource.RUSAGE_SELF
                        else children)
    monkeypatch.setattr(execution, "_process_memory_bytes", lambda _usage: 77)

    cpu_ppm, memory = execution._live_telemetry(
        1_000_000_000, process_cpu_baseline=0)

    assert cpu_ppm == 200_000
    assert memory == 77


def test_reopen_requires_exact_completed_prefix_and_live_telemetry(tmp_path, monkeypatch):
    repo, freeze, review, marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(root, freeze_raw=freeze.canonical_bytes(),
                                     repo=repo, review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    monkeypatch.setattr(execution, "_live_telemetry",
                        lambda _elapsed, **_baselines: (_ for _ in ()).throw(
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

    def invoke(stage, operation_supervisor, _shards):
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
        def bound(operation_supervisor, shards, *, stage=stage):
            return invoke(stage, operation_supervisor, shards)
        if stage in execution.COHORT_TRAINING_WAVE:
            bound.cohort_workers = 4
        operations[stage] = execution.StageControllerV2(
            stage, name, bound, True,
            stage_payload_factory=(prepare_audit
                                   if stage == "audit-attempt" else None))
    execution.run_v2_pipeline(supervisor, operations)
    assert (root / "terminal" / "independent-reconstruction.json").read_bytes() \
        == receipt_raw
    assert supervisor.state.reconstruction_completed is True
    resumed = execution.reopen_supervisor(
        root, freeze=freeze, admission=admission, review_marker=marker)
    execution.run_v2_pipeline(resumed, operations)
    assert resumed.state.reconstruction_completed is True


def _advance_to_cohort_training_wave(supervisor):
    completed = []
    for stage in STAGE_ORDER[:STAGE_ORDER.index("block-1-controls")]:
        raw = canonical_json_bytes({"stage": stage})
        supervisor.register_verified_shard(stage, "receipt", raw)
        supervisor._event(stage, status="complete",
                          split=ALLOWED_SPLITS[stage][0])
        completed.append(stage)
    supervisor._state = StageStateV2(
        tuple(completed), verified_shards=supervisor.state.verified_shards)


@pytest.mark.parametrize("cohort_workers", (2, 4))
def test_cohort_training_wave_runs_parallel_capacity_selected_controllers(
        tmp_path, monkeypatch, cohort_workers):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    _advance_to_cohort_training_wave(supervisor)
    monkeypatch.setattr(execution.StageControllerV2, "validate",
                        lambda _self: None)
    barrier = multiprocessing.Barrier(2, timeout=2)

    def operation(stage):
        def run(operation_supervisor, _shards):
            barrier.wait()
            operation_supervisor.register_verified_shard(
                stage, "receipt", canonical_json_bytes({"stage": stage}))
            return stage
        run.cohort_workers = cohort_workers
        return run

    operations = {
        stage: StageControllerV2(
            stage, execution.CONTROLLER_BINDINGS[stage][0],
            operation(stage), True)
        for stage in execution.COHORT_TRAINING_WAVE}
    assert supervisor.run_cohort_training_wave(operations) \
        == execution.COHORT_TRAINING_WAVE
    assert supervisor.state.completed_stages[-2:] \
        == execution.COHORT_TRAINING_WAVE
    assert supervisor.verified_shards("block-1-controls") == ("receipt",)
    assert supervisor.verified_shards("block-2-natural") == ("receipt",)


def test_cohort_training_wave_terminates_sibling_on_first_refusal(
        tmp_path, monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    _advance_to_cohort_training_wave(supervisor)
    monkeypatch.setattr(execution.StageControllerV2, "validate",
                        lambda _self: None)
    sentinel = tmp_path / "slow-sibling-finished"

    def refuse(_supervisor, _shards):
        raise WorldAfterstateV2ExecutionError("cohort refused")
    refuse.cohort_workers = 4

    def slow(_supervisor, _shards):
        time.sleep(3)
        sentinel.write_text("late")
    slow.cohort_workers = 4

    operations = {
        "block-1-controls": StageControllerV2(
            "block-1-controls",
            execution.CONTROLLER_BINDINGS["block-1-controls"][0],
            refuse, True),
        "block-2-natural": StageControllerV2(
            "block-2-natural",
            execution.CONTROLLER_BINDINGS["block-2-natural"][0],
            slow, True),
    }
    started = time.monotonic()
    with pytest.raises(WorldAfterstateV2ExecutionError,
                       match="cohort refused"):
        supervisor.run_cohort_training_wave(operations)
    assert time.monotonic() - started < 2
    assert not sentinel.exists()


def test_cohort_training_width_one_runs_serially_and_seals_prefix(tmp_path,
                                                                  monkeypatch):
    repo, freeze, review, _marker, remote = _fixture(tmp_path)
    root = tmp_path / "evidence"
    admission = initialize_admission(
        root, freeze_raw=freeze.canonical_bytes(), repo=repo,
        review_commit=review, remote_url=str(remote))
    supervisor = StageSupervisorV2(root, freeze, admission)
    _advance_to_cohort_training_wave(supervisor)
    monkeypatch.setattr(execution.StageControllerV2, "validate",
                        lambda _self: None)
    first_done = tmp_path / "first-cohort-stage.done"

    def controls(operation_supervisor, _shards):
        operation_supervisor.register_verified_shard(
            "block-1-controls", "receipt",
            canonical_json_bytes({"stage": "block-1-controls"}))
        first_done.write_text("done")
        return "block-1-controls"
    controls.cohort_workers = 1

    def natural(operation_supervisor, _shards):
        assert first_done.is_file()
        operation_supervisor.register_verified_shard(
            "block-2-natural", "receipt",
            canonical_json_bytes({"stage": "block-2-natural"}))
        return "block-2-natural"
    natural.cohort_workers = 1

    operations = {
        "block-1-controls": StageControllerV2(
            "block-1-controls",
            execution.CONTROLLER_BINDINGS["block-1-controls"][0],
            controls, True),
        "block-2-natural": StageControllerV2(
            "block-2-natural",
            execution.CONTROLLER_BINDINGS["block-2-natural"][0],
            natural, True),
    }
    assert supervisor.run_cohort_training_wave(operations) \
        == execution.COHORT_TRAINING_WAVE
    assert supervisor.state.completed_stages[-2:] \
        == execution.COHORT_TRAINING_WAVE


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
    assert state.completed_stages == (
        "population", "p0-labels-gates", "terminal", "reconstruction")
    assert state.terminal_route == route
    assert state.reconstruction_completed is True
    resumed = execution.reopen_supervisor(
        root, freeze=freeze, admission=admission, review_marker=marker)
    assert resumed.state == state
