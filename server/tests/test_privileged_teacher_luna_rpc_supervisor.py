"""Focused witnesses for the PT-Luna population supervisor boundary."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from shengji.rl import privileged_teacher_luna_rpc_supervisor as supervisor
from shengji.rl import privileged_teacher_luna_rpc_io as rpc_io
from shengji.rl import privileged_teacher_luna_rpc_collection as collection
from shengji.rl import privileged_teacher_luna_rpc_transport as rpc_transport
from shengji.rl.privileged_teacher_luna_rpc_collection import AttemptReopen
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SECRET = b"pt-luna-supervisor-test-secret!!"
assert len(SECRET) == 32
RUNTIME = {"schema": "pt-luna-turn-rpc-runtime-v1",
           "boot_identity_sha256": "b" * 64}


def _freeze_payload(**updates):
    body = {
        "schema": supervisor.FREEZE_SCHEMA,
        "execution_git": "1" * 40,
        "source_set_sha256": "2" * 64,
        "design_sha256": "3" * 64,
        "seed_commitment_sha256": "4" * 64,
        "schedule_sha256": "5" * 64,
        "census_sha256": "6" * 64,
        "capacity_receipt_sha256": "7" * 64,
        "runtime_sha256": "8" * 64,
        "capacity_route": supervisor.FULL_104_ELIGIBLE,
        "selected_game_count": 104,
        "selected_deal_cluster_count": 52,
        "selected_workers": 2,
        "per_game_deadline_nanoseconds": 1_000_000_000,
        "per_game_token_cap": 100,
        "per_call_token_reserve": 50,
        "per_call_wall_reserve_milliseconds": 100,
        "scientific_wall_nanoseconds": 10_000_000_000,
        "scientific_token_budget": 10_000,
        "private_root": "/private/test",
        "public_root": "/public/test",
        "namespace": "test",
        "authenticated": False,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "authority": dict(supervisor.selfplay.AUTHORITY),
    }
    body.update(updates)
    return {**body, "freeze_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


class FakeRunner:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
        self.attempts_root = root / "attempts"
        self.attempts_root.mkdir(parents=True, exist_ok=True)
        self.stop_event = threading.Event()
        self.calls = 0
        self.saw_admission = False

    def __call__(self, coordinate, mirror):
        self.calls += 1
        self.saw_admission = (self.attempts_root.parent.parent
                              / "public" / "admission.json").exists()
        return object()


def _make(tmp_path, *, schedule=None, full=False):
    runner = FakeRunner(tmp_path / "private")
    if schedule is None:
        schedule = [(('2', 0, 0), 0)]
    return supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=tmp_path / "private",
        public_root=tmp_path / "public", runtime=RUNTIME,
        admission={"freeze": "freeze", "admission": "admission"},
        capacity_receipt={"route": supervisor.FULL_104_ELIGIBLE,
                          "selected_workers": 1},
        runner=runner, schedule=schedule, require_full_population=full), runner


def test_schedule_rejects_duplicate_and_default_is_exact():
    with pytest.raises(supervisor.RPCSupervisorError):
        supervisor.validate_schedule([(('2', 0, 0), 0), (('2', 0, 0), 0)],
                                     require_full_population=False)
    assert len(supervisor.validate_schedule()) == 104


def test_pilot_schedule_is_first_sixteen_root_hashes_with_both_mirrors():
    rows = supervisor.selfplay.root_census(SECRET).serialized()["coordinates"]
    expected_coordinates = [
        tuple(row["coordinate"])
        for row in sorted(rows, key=lambda row: (
            row["root_sha256"], tuple(row["coordinate"])))[:16]
    ]
    schedule = supervisor.schedule_for_capacity_route(
        SECRET, supervisor.PILOT_32_ELIGIBLE)
    assert len(schedule) == 32
    assert list(dict.fromkeys(coordinate for coordinate, _ in schedule)) == \
        expected_coordinates
    assert all(
        [mirror for coordinate, mirror in schedule if coordinate == expected]
        == [0, 1]
        for expected in expected_coordinates)


def test_pilot_freeze_shape_and_review_claim_bind_selected_population():
    freeze = _freeze_payload(
        capacity_route=supervisor.PILOT_32_ELIGIBLE,
        selected_game_count=32, selected_deal_cluster_count=16,
        scientific_wall_nanoseconds=12_000_000_000_000)
    supervisor.validate_launch_freeze_shape(freeze)
    claim = supervisor.freeze_review_claim(freeze)
    assert claim["capacity_route"] == supervisor.PILOT_32_ELIGIBLE
    assert claim["selected_game_count"] == 32
    assert claim["selected_deal_cluster_count"] == 16

    forged = _freeze_payload(
        capacity_route=supervisor.PILOT_32_ELIGIBLE,
        selected_game_count=104, selected_deal_cluster_count=52,
        scientific_wall_nanoseconds=12_000_000_000_000)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="capacity route population"):
        supervisor.validate_launch_freeze_shape(forged)


def test_scientific_namespace_lock_refuses_second_live_controller(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    first = supervisor._acquire_scientific_run_lock(root)
    try:
        with pytest.raises(supervisor.RPCSupervisorError,
                           match="already active"):
            supervisor._acquire_scientific_run_lock(root)
    finally:
        supervisor.fcntl.flock(first, supervisor.fcntl.LOCK_UN)
        supervisor.os.close(first)
    resumed = supervisor._acquire_scientific_run_lock(root)
    supervisor.fcntl.flock(resumed, supervisor.fcntl.LOCK_UN)
    supervisor.os.close(resumed)


def test_review_claim_seal_is_checked_before_remote_authentication():
    claim = {"schema": supervisor.SOURCE_REVIEW_SCHEMA,
             "claim_sha256": "0" * 64}
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="review claim seal drift"):
        supervisor.authenticate_review_claim(
            claim=claim, prefix=supervisor.SOURCE_REVIEW_PREFIX,
            review_commit="1" * 40)


def test_review_authentication_requires_exact_append_only_canonical_marker(
        tmp_path, monkeypatch):
    repo = tmp_path / "review"
    repo.mkdir()
    subprocess.run(("git", "init", "-b", "main"), cwd=repo,
                   check=True, stdout=subprocess.PIPE)
    subprocess.run(("git", "config", "user.name", "review-test"),
                   cwd=repo, check=True)
    subprocess.run(("git", "config", "user.email", "review@test.invalid"),
                   cwd=repo, check=True)
    ledger = repo / "HANDOFF_REVIEW.md"
    ledger.write_bytes(b"base\n")
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-m", "base"), cwd=repo,
                   check=True, stdout=subprocess.PIPE)
    body = {"schema": supervisor.SOURCE_REVIEW_SCHEMA,
            "execution_git": "a" * 40,
            "source_set_sha256": "b" * 64,
            "design_sha256s": {
                "PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md": "c" * 64,
                "PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md": "d" * 64,
            },
            "score_free_canary_authorized": True,
            "score_free_capacity_authorized": True,
            "scientific_execution_authorized": False,
            "outcome_opening_authorized": False,
            "merge_authorized": False,
            "deployment_authorized": False,
            "strength_claim_authorized": False,
            "authority": dict(supervisor.selfplay.AUTHORITY)}
    body["design_sha256"] = supervisor._sha(body["design_sha256s"])
    claim = {**body, "claim_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    marker = (supervisor.SOURCE_REVIEW_PREFIX.encode() + b" "
              + canonical_json_bytes(claim))
    with ledger.open("ab") as handle:
        handle.write(marker)
    subprocess.run(("git", "add", "HANDOFF_REVIEW.md"), cwd=repo, check=True)
    subprocess.run(("git", "commit", "-m", "review marker"), cwd=repo,
                   check=True, stdout=subprocess.PIPE)
    review_commit = subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=repo, text=True).strip()
    monkeypatch.setattr(supervisor, "CANONICAL_REMOTE_URL", str(repo))
    auth = supervisor.authenticate_review_claim(
        claim=claim, prefix=supervisor.SOURCE_REVIEW_PREFIX,
        review_commit=review_commit)
    assert auth["review_commit"] == review_commit
    assert auth["review_claim"] == claim


def test_launch_freeze_deadline_must_round_trip_to_exact_seconds():
    freeze = _freeze_payload(
        per_game_deadline_nanoseconds=1_000_000_001)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="deadline granularity"):
        supervisor.validate_launch_freeze_shape(freeze)


def test_coordinated_freeze_budget_rehash_fails_live_rederivation(monkeypatch):
    expected = _freeze_payload()
    forged = _freeze_payload(scientific_token_budget=20_000)
    monkeypatch.setattr(
        supervisor, "launch_freeze_payload", lambda **_kwargs: expected)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="launch freeze binding drift"):
        supervisor.validate_launch_freeze(
            forged, repo_root=Path("."), seed_secret=SECRET,
            census={}, capacity_receipt={}, runtime={},
            private_root=Path("/private/test"),
            public_root=Path("/public/test"), namespace="test")


def test_public_admission_binds_authenticated_freeze_sha(tmp_path):
    instance, _runner = _make(tmp_path)
    instance.admission = {
        "review_commit": "1" * 40,
        "review_marker_sha256": "2" * 64,
        "review_claim": {"freeze_sha256": "3" * 64},
    }
    assert instance._admission_body()["freeze_sha256"] == "3" * 64


def test_full_controller_authenticates_freeze_before_creating_namespace(
        tmp_path, monkeypatch):
    def refuse(**_kwargs):
        raise supervisor.RPCSupervisorError("sentinel freeze auth")
    monkeypatch.setattr(supervisor, "authenticate_review_claim", refuse)
    private_root = tmp_path / "not-created-private"
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="sentinel freeze auth"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private_root,
            public_root=tmp_path / "not-created-public", runtime=RUNTIME,
            admission={"review_commit": "1" * 40},
            capacity_receipt={
                "route": supervisor.FULL_104_ELIGIBLE,
                "selected_workers": 2,
                "runtime": RUNTIME, "receipt_sha256": "7" * 64},
            runner=object(), launch_freeze=_freeze_payload(),
            require_full_population=True)
    assert not private_root.exists()


def test_formal_controller_internally_owns_bound_runner_ledger_and_timeout(
        tmp_path, monkeypatch):
    schedule = supervisor.validate_schedule()
    census = supervisor.build_root_census(SECRET, schedule)
    private_root = (tmp_path / "private").resolve()
    public_root = (tmp_path / "public").resolve()
    runtime = {
        "schema": "pt-luna-turn-rpc-runtime-v1",
        "boot_identity_sha256": "b" * 64,
        "source_set_sha256": "2" * 64,
        "codex_tool_catalog": {
            "schema": "pt-luna-codex-tool-catalog-v1"},
    }
    capacity = {
        "route": supervisor.FULL_104_ELIGIBLE, "selected_workers": 1,
        "selected_game_count": 104,
        "selected_deal_cluster_count": 52,
        "selected_population_wall_nanoseconds": 10_000_000_000,
        "runtime": runtime, "receipt_sha256": "7" * 64,
        "scientific_wall_nanoseconds": 10_000_000_000,
        "scientific_token_budget": 10_000,
        "arms": [{"workers": 1, "per_call_token_reserve": 50,
                  "per_call_wall_reserve_milliseconds": 1_000}],
    }
    freeze = _freeze_payload(
        source_set_sha256=runtime["source_set_sha256"],
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest(),
        schedule_sha256=supervisor._schedule_sha(schedule),
        census_sha256=census["census_sha256"],
        runtime_sha256=supervisor._sha(runtime), selected_workers=1,
        per_game_deadline_nanoseconds=600_000_000_000,
        per_game_token_cap=1_000, per_call_token_reserve=50,
        per_call_wall_reserve_milliseconds=1_000,
        scientific_wall_nanoseconds=10_000_000_000,
        scientific_token_budget=10_000,
        private_root=str(private_root), public_root=str(public_root),
        namespace=supervisor.SCHEMA)
    admission = {
        "review_commit": "1" * 40,
        "review_marker_sha256": "9" * 64,
        "review_claim": supervisor.freeze_review_claim(freeze),
    }
    monkeypatch.setattr(
        supervisor, "authenticate_review_claim",
        lambda **_kwargs: admission)
    monkeypatch.setattr(
        collection, "source_identity", lambda _path: dict(runtime))
    instance = supervisor.PTLunaRPCSupervisor(
        seed_secret=SECRET, private_root=private_root,
        public_root=public_root, runtime=runtime,
        admission=admission, capacity_receipt=capacity,
        codex_binary=Path("/usr/bin/true"), launch_freeze=freeze,
        schedule=schedule, expected_schedule=schedule,
        root_census=census, require_full_population=True)
    assert instance._run_lock_fd is None
    assert type(instance.runner) is collection.RPCGameAttemptRunner
    assert type(instance.ledger) is collection.ScientificBudgetLedger
    assert instance.runner.seed_secret == SECRET
    assert instance.runner.attempts_root == private_root / "attempts"
    assert instance.runner.per_call_timeout_seconds == 1
    assert instance.ledger.root == private_root / "ledger"
    assert instance.runner.scientific_binding is not None
    assert instance.runner.scientific_binding["freeze_sha256"] \
        == freeze["freeze_sha256"]
    assert instance.runner.scientific_binding["ledger_genesis_sha256"] \
        == instance.ledger.payload()["genesis_sha256"]

    def refuse_ledger(**_kwargs):
        raise collection.RPCCollectionError("injected constructor failure")

    monkeypatch.setattr(
        collection.ScientificBudgetLedger, "open_or_create", refuse_ledger)
    monkeypatch.setattr(
        supervisor.ScientificBudgetLedger, "open_or_create", refuse_ledger)
    with pytest.raises(collection.RPCCollectionError,
                       match="injected constructor failure"):
        supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private_root,
            public_root=public_root, runtime=runtime,
            admission=admission, capacity_receipt=capacity,
            codex_binary=Path("/usr/bin/true"), launch_freeze=freeze,
            schedule=schedule, expected_schedule=schedule,
            root_census=census, require_full_population=True)
    descriptor = supervisor._acquire_scientific_run_lock(private_root)
    supervisor.fcntl.flock(descriptor, supervisor.fcntl.LOCK_UN)
    supervisor.os.close(descriptor)


def test_same_supervisor_refuses_concurrent_run(tmp_path, monkeypatch):
    instance, _runner = _make(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocked_run():
        entered.set()
        assert release.wait(timeout=2)
        return supervisor.SupervisorResult(
            supervisor.CASUAL_INCOMPLETE_ROUTE, {"sentinel": True})

    monkeypatch.setattr(instance, "_run_locked", blocked_run)
    results = []
    thread = threading.Thread(target=lambda: results.append(instance.run()))
    thread.start()
    assert entered.wait(timeout=1)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="run already active"):
        instance.run()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert results[0].receipt == {"sentinel": True}


def test_terminal_publication_death_recovers_complete_staged_bytes(
        tmp_path, monkeypatch):
    target = tmp_path / "terminal.json"
    payload = {"schema": "terminal-sentinel", "complete": True}
    real_link = rpc_io.os.link
    died = False

    def die_once(source, destination, **kwargs):
        nonlocal died
        if not died:
            died = True
            raise KeyboardInterrupt("synthetic publication death")
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(rpc_io.os, "link", die_once)
    with pytest.raises(KeyboardInterrupt):
        supervisor._publish(target, payload)
    assert not target.exists()
    supervisor._publish(target, payload)
    assert json.loads(target.read_text()) == payload
    assert not rpc_io.partial_path(target).exists()


def test_terminal_death_after_link_restarts_without_second_runner_call(
        tmp_path, monkeypatch):
    class ProcessDeath(BaseException):
        pass

    instance, first_runner = _make(tmp_path)
    terminal = tmp_path / "public" / "terminal.json"
    real_link = rpc_io.os.link
    real_fsync = rpc_io._fsync_dir
    linked_terminal = False
    died = False

    def observe_terminal_link(source, destination, **kwargs):
        nonlocal linked_terminal
        value = real_link(source, destination, **kwargs)
        if Path(destination) == terminal:
            linked_terminal = True
        return value

    def die_after_terminal_link(path):
        nonlocal died
        if linked_terminal and not died:
            died = True
            raise ProcessDeath()
        return real_fsync(path)

    monkeypatch.setattr(rpc_io.os, "link", observe_terminal_link)
    monkeypatch.setattr(rpc_io, "_fsync_dir", die_after_terminal_link)
    with pytest.raises(ProcessDeath):
        instance.run()
    assert first_runner.calls == 1
    assert terminal.exists() and rpc_io.partial_path(terminal).exists()
    assert terminal.stat().st_ino == rpc_io.partial_path(terminal).stat().st_ino

    restarted, second_runner = _make(tmp_path)
    result = restarted.run()
    assert result.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert second_runner.calls == 0
    assert not rpc_io.partial_path(terminal).exists()
    assert terminal.stat().st_nlink == 1


@pytest.mark.parametrize(
    ("capacity_route", "expected_games", "expected_clusters", "selected_wall"),
    [
        (supervisor.FULL_104_ELIGIBLE, 104, 52,
         28_800_000_000_000),
        (supervisor.PILOT_32_ELIGIBLE, 32, 16,
         12_000_000_000_000),
    ])
def test_collection_cli_runs_route_bound_population_and_restart_through_public_entry(
        tmp_path, monkeypatch, capsys, capacity_route, expected_games,
        expected_clusters, selected_wall):
    from scripts import privileged_teacher_luna_rpc_collection as cli

    schedule = supervisor.schedule_for_capacity_route(SECRET, capacity_route)
    census = (supervisor.selfplay.root_census(SECRET).serialized()
              if capacity_route == supervisor.FULL_104_ELIGIBLE
              else supervisor.build_root_census(SECRET, schedule))
    private_root = (tmp_path / "private").resolve()
    public_root = (tmp_path / "public").resolve()
    runtime = {
        "schema": "pt-luna-turn-rpc-runtime-v1",
        "boot_identity_sha256": "b" * 64,
        "source_set_sha256": "2" * 64,
        "codex_tool_catalog": {
            "schema": "pt-luna-codex-tool-catalog-v1"},
    }
    source_claim_body = {
        "schema": supervisor.SOURCE_REVIEW_SCHEMA,
        "execution_git": "1" * 40,
        "source_set_sha256": runtime["source_set_sha256"],
        "design_sha256s": {
            "PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md": "3" * 64,
            "PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md": "4" * 64,
        },
        "score_free_canary_authorized": True,
        "score_free_capacity_authorized": True,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "strength_claim_authorized": False,
        "authority": dict(supervisor.selfplay.AUTHORITY),
    }
    source_claim_body["design_sha256"] = supervisor._sha(
        source_claim_body["design_sha256s"])
    source_claim = {**source_claim_body, "claim_sha256": hashlib.sha256(
        canonical_json_bytes(source_claim_body)).hexdigest()}
    source_auth = {
        "review_commit": "4" * 40,
        "review_marker_sha256": "5" * 64,
        "review_claim": source_claim,
    }
    capacity = {
        "route": capacity_route, "selected_workers": 1,
        "selected_game_count": expected_games,
        "selected_deal_cluster_count": expected_clusters,
        "selected_population_wall_nanoseconds": selected_wall,
        "runtime": runtime, "receipt_sha256": "7" * 64,
        "source_review": source_auth,
        "scientific_wall_nanoseconds": 10_000_000_000,
        "scientific_token_budget": 10_000,
        "arms": [{"workers": 1, "passed": True,
                  "per_game_token_cap": 1_000,
                  "per_call_token_reserve": 50,
                  "per_call_wall_reserve_milliseconds": 1_000}],
    }
    freeze = _freeze_payload(
        source_set_sha256=runtime["source_set_sha256"],
        seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest(),
        schedule_sha256=supervisor._schedule_sha(schedule),
        census_sha256=census["census_sha256"],
        capacity_receipt_sha256=capacity["receipt_sha256"],
        runtime_sha256=supervisor._sha(runtime), selected_workers=1,
        capacity_route=capacity_route,
        selected_game_count=expected_games,
        selected_deal_cluster_count=expected_clusters,
        per_game_deadline_nanoseconds=600_000_000_000,
        per_game_token_cap=1_000, per_call_token_reserve=50,
        per_call_wall_reserve_milliseconds=1_000,
        scientific_wall_nanoseconds=selected_wall,
        scientific_token_budget=10_000,
        private_root=str(private_root), public_root=str(public_root),
        namespace="formal-cli-test")
    freeze_auth = {
        "review_commit": "6" * 40,
        "review_marker_sha256": "8" * 64,
        "review_claim": supervisor.freeze_review_claim(freeze),
    }
    secret_path = tmp_path / "secret.bin"
    secret_path.write_bytes(SECRET)
    secret_path.chmod(0o600)
    for path, value in ((tmp_path / "capacity.json", capacity),
                        (tmp_path / "freeze.json", freeze),
                        (tmp_path / "census.json", census)):
        path.write_bytes(canonical_json_bytes(value))
        path.chmod(0o400)

    monkeypatch.setattr(cli, "validate_capacity_receipt", lambda _value: None)
    monkeypatch.setattr(supervisor, "validate_capacity_receipt",
                        lambda _value: None)
    monkeypatch.setattr(cli, "source_identity",
                        lambda _path: dict(runtime))
    monkeypatch.setattr(collection, "source_identity",
                        lambda _path: dict(runtime))
    monkeypatch.setattr(cli, "source_review_claim",
                        lambda _repo: source_claim)
    monkeypatch.setattr(cli, "validate_launch_freeze",
                        lambda *_args, **_kwargs: None)

    def authenticate(*, prefix, **_kwargs):
        return source_auth if prefix == supervisor.SOURCE_REVIEW_PREFIX \
            else freeze_auth

    monkeypatch.setattr(cli, "authenticate_review_claim", authenticate)
    monkeypatch.setattr(supervisor, "authenticate_review_claim", authenticate)
    calls = []

    def complete_without_provider(self, coordinate, mirror):
        calls.append((coordinate, mirror))
        path = supervisor._attempt_path(self.attempts_root, coordinate, mirror)
        path.mkdir(mode=0o700)
        manifest = path / "manifest.json"
        manifest.write_bytes(b"{}\n")
        manifest.chmod(0o400)
        return object()

    monkeypatch.setattr(
        collection.RPCGameAttemptRunner, "__call__", complete_without_provider)
    monkeypatch.setattr(
        supervisor, "reopen_attempt",
        lambda path, **_kwargs: AttemptReopen(
            "complete", hashlib.sha256(str(path).encode()).hexdigest(),
            None, None, None, {"total_tokens": 0,
                               "response_count": 0}))
    monkeypatch.setattr(
        collection.ScientificBudgetLedger, "reconcile_attempt_journals",
        lambda self, paths: None)
    args = [
        "run", "--repo-root", str(tmp_path),
        "--seed-secret-file", str(secret_path),
        "--capacity-receipt", str(tmp_path / "capacity.json"),
        "--codex-binary", "/usr/bin/true",
        "--private-root", str(private_root),
        "--public-root", str(public_root),
        "--namespace", "formal-cli-test",
        "--freeze", str(tmp_path / "freeze.json"),
        "--census", str(tmp_path / "census.json"),
        "--review-commit", freeze_auth["review_commit"],
    ]
    assert cli.main(args) == 0
    first_output = json.loads(capsys.readouterr().out)
    terminal = json.loads((public_root / "terminal.json").read_text())
    assert first_output["route"] == supervisor.COMPLETE_STATE_SOURCE_ACQUISITION
    assert terminal["completed_games"] == expected_games
    assert terminal["completed_deal_clusters"] == expected_clusters
    assert len(calls) == expected_games

    assert cli.main(args) == 0
    second_output = json.loads(capsys.readouterr().out)
    assert second_output == first_output
    assert len(calls) == expected_games


def test_launch_receipts_precede_provider_and_public_progress_has_no_score(
        tmp_path):
    instance, runner = _make(tmp_path)
    first = instance.run()
    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert runner.calls == 1
    assert runner.saw_admission
    admission = json.loads((tmp_path / "public" / "admission.json").read_text())
    assert admission["authority"]["gameplay_authorized"] is False
    progress = list((tmp_path / "public" / "progress").glob("*.json"))
    assert progress
    for path in progress:
        value = json.loads(path.read_text())
        assert not supervisor._forbidden(value)


def test_explicit_full_population_rejects_small_injected_schedule(tmp_path):
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="exact formal schedule"):
        supervisor.validate_schedule(
            [(("2", 0, 0), 0)], require_full_population=True)


def test_partial_attempt_without_manifest_is_resumed_then_terminal_is_final(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)

    def seal(coordinate, mirror):
        runner.calls += 1
        path = runner.attempts_root / (
            f"{coordinate[0]}-{coordinate[1]}-{coordinate[2]}-mirror-{mirror}")
        (path / "manifest.json").write_text("{}")
        return object()

    monkeypatch.setattr(
        FakeRunner, "__call__",
        lambda self, coordinate, mirror: seal(coordinate, mirror))
    monkeypatch.setattr(
        supervisor, "reopen_attempt",
        lambda *args, **kwargs: AttemptReopen(
            "complete", "a" * 64, None, None, None,
            {"total_tokens": 7, "response_count": 1}))
    first = instance.run()
    assert first.route == supervisor.CASUAL_COMPLETE_ROUTE
    assert runner.calls == 1
    second = instance.run()
    assert second.receipt == first.receipt
    assert runner.calls == 1


def test_self_sealed_complete_terminal_cannot_bypass_private_reconstruction(
        tmp_path):
    instance, runner = _make(tmp_path)
    body = {"schema": supervisor.TERMINAL_SCHEMA,
            "route": supervisor.COMPLETE_STATE_SOURCE_ACQUISITION,
            "schedule_sha256": "1" * 64,
            "census_sha256": "2" * 64,
            "admission_sha256": "3" * 64,
            "attempt_manifest": [{"index": 0, "coordinate": ["2", 0, 0],
                                  "mirror": 0, "status": "complete",
                                  "manifest_sha256": "4" * 64}],
            "completed_games": 1,
            "completed_deal_clusters": 1, "failed_games": 0,
            "pending_games": 0, "resource_totals": {},
            "ledger_terminal_accept_sha256": None,
            "authority": dict(supervisor.selfplay.AUTHORITY)}
    terminal = {**body, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    path = tmp_path / "public" / "terminal.json"
    path.write_bytes(canonical_json_bytes(terminal))
    path.chmod(0o400)
    with pytest.raises(supervisor.RPCSupervisorError,
                       match="casual terminal"):
        instance.run()
    assert runner.calls == 0


def test_unsealed_controller_death_is_restart_stable_incomplete(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    def die(_self, _coordinate, _mirror):
        runner.calls += 1
        raise KeyboardInterrupt("synthetic controller death")
    monkeypatch.setattr(FakeRunner, "__call__", die)
    first = instance.run()
    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert first.receipt["failed_games"] == 0
    assert first.receipt["pending_games"] == 1
    assert runner.calls == 1


def test_main_thread_interrupt_stops_and_cancels_pending_games(
        tmp_path, monkeypatch):
    schedule = [(('2', 0, 0), mirror) for mirror in (0, 1)] \
        + [(('3', 0, 0), 0)]
    instance, runner = _make(tmp_path, schedule=schedule)
    instance.workers = 1
    started = threading.Event()
    def wait_for_stop(self, _coordinate, _mirror):
        self.calls += 1
        started.set()
        self.stop_event.wait(timeout=2)
        time.sleep(0.05)
        raise RuntimeError("stopped")
    monkeypatch.setattr(FakeRunner, "__call__", wait_for_stop)
    def interrupt(_futures):
        assert started.wait(timeout=1)
        raise KeyboardInterrupt("controller interrupt")
    monkeypatch.setattr(supervisor, "as_completed", interrupt)
    first = instance.run()
    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert runner.calls == 1


def test_main_interrupt_kills_a_real_active_provider_group(
        tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    manager = rpc_transport.ActiveCallManager()
    runner.terminate_active_calls = manager.terminate
    pid_path = tmp_path / "active-provider.pid"
    def active_call(self, _coordinate, _mirror):
        self.calls += 1
        result = rpc_transport._default_run(
            (sys.executable, "-c",
             "import os,pathlib,sys,time; "
             "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
             "time.sleep(60)", str(pid_path)),
            b"", tmp_path, 60, _active_call_manager=manager)
        raise RuntimeError(f"provider stopped {result.returncode}")
    monkeypatch.setattr(FakeRunner, "__call__", active_call)
    def interrupt(_futures):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_path.exists():
            time.sleep(0.01)
        assert pid_path.exists()
        raise KeyboardInterrupt("controller interrupt")
    monkeypatch.setattr(supervisor, "as_completed", interrupt)
    started = time.monotonic()
    first = instance.run()
    assert time.monotonic() - started < 5
    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert runner.calls == 1
    provider_pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        supervisor.os.kill(provider_pid, 0)
    second = instance.run()
    assert second.receipt == first.receipt
    assert runner.calls == 1


@pytest.mark.parametrize("failure_class,route", [
    ("mechanics-privacy", supervisor.REFUSE_MECHANICS_OR_PRIVACY),
    ("resource-provider", supervisor.REFUSE_RESOURCE_OR_PROVIDER),
])
def test_existing_incomplete_attempt_routes_without_provider_retry(
        failure_class, route, tmp_path, monkeypatch):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")
    monkeypatch.setattr(
        supervisor, "reopen_attempt",
        lambda *args, **kwargs: AttemptReopen(
            "incomplete", "b" * 64, None, "SyntheticFailure",
            failure_class, {"total_tokens": 9, "response_count": 1}))
    result = instance.run()
    assert result.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert instance._derive_route() == route
    assert runner.calls == 0


def test_corrupt_sealed_manifest_routes_mechanics_stably_without_retry(
        tmp_path):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")
    first = instance.run()
    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0

    second = instance.run()
    assert second.receipt == first.receipt
    assert instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0


def test_corrupt_first_manifest_prevents_all_other_provider_dispatches(
        tmp_path):
    schedule = [(('2', 0, 0), 0), (('3', 0, 0), 0)]
    instance, runner = _make(tmp_path, schedule=schedule)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").write_text("{}")

    result = instance.run()

    assert result.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0


def test_corrupt_partial_attempt_is_durable_mechanics_without_provider_call(
        tmp_path):
    class CountingFactory:
        calls = 0
        def __call__(self, _path):
            self.calls += 1
            raise AssertionError("provider transport must not be constructed")
    factory = CountingFactory()
    private = tmp_path / "private"
    public = tmp_path / "public"
    private.mkdir(mode=0o700)
    schedule = [(('2', 0, 0), 0)]

    def make_instance():
        runner = collection.RPCGameAttemptRunner(
            seed_secret=SECRET, attempts_root=private / "attempts",
            codex_binary=None, runtime=RUNTIME,
            per_game_deadline_seconds=600, per_game_token_cap=1_000,
            transport_factory=factory)
        return supervisor.PTLunaRPCSupervisor(
            seed_secret=SECRET, private_root=private, public_root=public,
            runtime=RUNTIME,
            admission={"freeze": "freeze", "admission": "admission"},
            capacity_receipt={"route": supervisor.FULL_104_ELIGIBLE,
                              "selected_workers": 1},
            runner=runner, schedule=schedule,
            require_full_population=False)

    first_instance = make_instance()
    attempt = private / "attempts" / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "attempt.json").write_bytes(canonical_json_bytes({}))
    (attempt / "attempt.json").chmod(0o400)

    first = first_instance.run()

    assert first.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert first_instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert factory.calls == 0
    refusal = attempt / "controller-refusal.json"
    assert refusal.is_file()
    assert json.loads(refusal.read_text())["failure_class"] \
        == "mechanics-privacy"

    second_instance = make_instance()
    second = second_instance.run()
    assert second.receipt == first.receipt
    assert second_instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert factory.calls == 0


def test_broken_manifest_symlink_is_occupied_and_never_retried(tmp_path):
    instance, runner = _make(tmp_path)
    attempt = runner.attempts_root / "2-0-0-mirror-0"
    attempt.mkdir(mode=0o700)
    (attempt / "manifest.json").symlink_to(attempt / "missing-target")
    result = instance.run()
    assert result.route == supervisor.CASUAL_INCOMPLETE_ROUTE
    assert instance._derive_route() \
        == supervisor.REFUSE_MECHANICS_OR_PRIVACY
    assert runner.calls == 0
