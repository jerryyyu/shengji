"""Fail-closed boundaries for the S3a complete-round screen packet."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_duel_screen as SUP  # noqa: E402


def _config() -> SUP.Config:
    return SUP.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )


def _paths(tmp_path: Path) -> SUP.Paths:
    namespace = tmp_path / SUP.RUN_ID
    shards = tuple(namespace / name for name in SUP.SHARD_NAMES)
    shard_logs = tuple(
        namespace / f"shard-{index:02d}.log"
        for index in range(SUP.SHARD_COUNT)
    )
    shard_exits = tuple(
        namespace / f"exit-shard-{index:02d}.json"
        for index in range(SUP.SHARD_COUNT)
    )
    return SUP.Paths(
        namespace=namespace,
        runner=tmp_path / "runner.py",
        controller=tmp_path / "controller.py",
        packet=namespace / SUP.PACKET_NAME,
        review_copy=namespace / SUP.REVIEW_NAME,
        admission=namespace / SUP.ADMISSION_NAME,
        receipt=namespace / SUP.RECEIPT_NAME,
        progress_partial=namespace / f"{SUP.PROGRESS_NAME}.partial",
        progress_final=namespace / SUP.PROGRESS_NAME,
        final=namespace / SUP.FINAL_NAME,
        shards=shards,
        shard_logs=shard_logs,
        shard_exits=shard_exits,
        aggregate=namespace / SUP.AGGREGATE_NAME,
    )


def _parent() -> dict:
    return {
        "schema": "live-champion-parent-v1",
        "champion_policy": "mc-s0-report-lcb",
    }


def _runtime() -> dict:
    return {
        "git": "a" * 40,
        "tree_dirty": False,
        "host": SUP.EXPECTED_HOST,
        "python": SUP.EXPECTED_PYTHON,
        "fast_engine": True,
        "require_voids": True,
        "experimental_flags": [],
        "source_sha256s": {"runner": "d" * 64},
        "fast_binary_sha256": "e" * 64,
        "policy_contract_sha256s": {"mc-s0-report-lcb": "f" * 64},
        "stream_digests": {
            "preflight": "1" * 64,
            "screen": "2" * 64,
            "confirm": "3" * 64,
        },
    }


def _preflight() -> dict:
    return {
        "receipt": {"path": "/evidence/receipt.json", "sha256": "4" * 64},
        "preflight": {"path": "/evidence/preflight.json", "sha256": "5" * 64},
        "progress": {"path": "/evidence/progress.jsonl", "sha256": "6" * 64},
        "final": {"path": "/evidence/final.json", "sha256": "7" * 64},
        "contract_sha256": "8" * 64,
        "terminal_status": "AUTHORIZE_SCREEN_PACKET_REVIEW",
        "screen_projection": {
            "fleet_hours": 72.6,
            "max_shard_hours": 9.1,
        },
        "screen_budgets": {
            "fleet_hours": 192.0,
            "max_shard_hours": 24.0,
        },
        "strength_launch_authorized": False,
    }


def _packet(paths: SUP.Paths) -> dict:
    return SUP.packet_contract(
        _config(), paths, parent=_parent(), runtime=_runtime(),
        preflight=_preflight())


def _keys(value) -> set[str]:
    keys = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_keys(item))
    return keys


def _review_record(packet_sha256: str, config: SUP.Config) -> bytes:
    claim = {
        "schema": SUP.PACKET_REVIEW_SCHEMA,
        "git": config.expected_git,
        "run_id": SUP.RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_final_sha256": SUP.PREFLIGHT_FINAL_SHA256,
        "independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    return (
        "review prose\n"
        + SUP.PACKET_REVIEW_MARKER
        + json.dumps(claim, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def test_packet_freezes_full_game_geometry_commands_and_no_authority(tmp_path):
    paths = _paths(tmp_path)
    packet = _packet(paths)
    assert packet["run_id"] == "s3a-bury-duel-screen-153m-v1"
    assert packet["phase"] == "screen"
    assert packet["host"] == "Jerrys-Mac-mini.local"
    assert packet["python"]["version"] == "3.14.3"
    assert packet["mechanism"]["clusters"] == 2_048
    assert packet["mechanism"]["shard_count"] == 8
    assert packet["mechanism"]["clusters_per_shard"] == 256
    assert packet["mechanism"]["seed0"] == 153_000_003
    assert packet["mechanism"]["labels"] == SUP.DUEL.LABELS
    assert packet["preflight_evidence"] == _preflight()
    assert len(packet["commands"]["shards"]) == 8
    for index, argv in enumerate(packet["commands"]["shards"]):
        assert argv == list(SUP.shard_argv(
            _config(), index, paths.shards[index]))
        assert argv[0] == sys.executable
        assert argv[argv.index("--phase") + 1] == "screen"
        assert argv[argv.index("--progress-every") + 1] == "1"
    assert packet["screen_launch_authorized"] is False
    assert packet["confirmation_authorized"] is False
    assert packet["strength_claim"] is False
    assert packet["production_promotion"] is False
    assert packet["retry_or_resume_authorized"] is False
    assert not (_keys(packet) & {
        "won", "level_utility", "stats", "criteria", "mean",
        "lcb_95", "ucb_95", "winner", "outcome", "duel_result",
    })


def test_preflight_evidence_reopens_exact_terminal_authority(
        tmp_path, monkeypatch):
    root = tmp_path / "preflight"
    root.mkdir()
    receipt = root / "receipt.json"
    progress = root / "supervisor.jsonl"
    output = root / "preflight.json"
    final_path = root / "supervisor-final.json"
    receipt.write_text("{}\n")
    progress.write_text('{"event":"terminal"}\n')
    output_payload = {
        "schema": SUP.DUEL.PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "capacity_pass": True,
        "problems": [],
        "strength_launch_authorized": False,
        "production_promotion": False,
        "projections": {
            "screen": {"fleet_hours": 72.0, "max_shard_hours": 9.0},
        },
        "budgets": {
            "screen_fleet_hours": 192.0,
            "screen_max_shard_hours": 24.0,
        },
    }
    output.write_text(json.dumps(output_payload))
    contract_sha = "9" * 64
    final_payload = {
        "schema": "s3a-bury-duel-preflight-final-v1",
        "complete": True,
        "contract_sha256": contract_sha,
        "receipt_sha256": SUP.sha256_file(receipt),
        "progress_sha256": SUP.sha256_file(progress),
        "preflight": {"sha256": SUP.sha256_file(output)},
        "status": "AUTHORIZE_SCREEN_PACKET_REVIEW",
        "screen_packet_review_authorized": True,
        "strength_launch_authorized": False,
        "retry_or_resume_authorized": False,
        "production_promotion": False,
    }
    final_path.write_text(json.dumps(final_payload))
    monkeypatch.setattr(SUP, "PREFLIGHT_ROOT", root)
    monkeypatch.setattr(
        SUP, "PREFLIGHT_RECEIPT_SHA256", SUP.sha256_file(receipt))
    monkeypatch.setattr(SUP, "PREFLIGHT_SHA256", SUP.sha256_file(output))
    monkeypatch.setattr(
        SUP, "PREFLIGHT_PROGRESS_SHA256", SUP.sha256_file(progress))
    monkeypatch.setattr(
        SUP, "PREFLIGHT_FINAL_SHA256", SUP.sha256_file(final_path))
    monkeypatch.setattr(SUP, "PREFLIGHT_CONTRACT_SHA256", contract_sha)
    evidence = SUP.preflight_evidence()
    assert evidence["terminal_status"] == "AUTHORIZE_SCREEN_PACKET_REVIEW"
    assert evidence["strength_launch_authorized"] is False

    final_payload["screen_packet_review_authorized"] = False
    final_path.write_text(json.dumps(final_payload))
    monkeypatch.setattr(
        SUP, "PREFLIGHT_FINAL_SHA256", SUP.sha256_file(final_path))
    with pytest.raises(SUP.SupervisorRefusal, match="terminal authority"):
        SUP.preflight_evidence()


def test_freeze_is_deterministic_exclusive_and_does_not_authorize(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    packet = _packet(paths)
    monkeypatch.setattr(SUP, "paths_for", lambda: paths)
    monkeypatch.setattr(
        SUP, "_expected_packet",
        lambda *_args: (packet, _parent(), _runtime()))
    ref = SUP.freeze_packet(_config())
    assert ref["sha256"] == SUP.sha256_file(paths.packet)
    assert ref["screen_launch_authorized"] is False
    assert SUP._load_json(paths.packet) == packet
    with pytest.raises(SUP.SupervisorRefusal, match="absent or empty"):
        SUP.freeze_packet(_config())


def test_verify_packet_refuses_content_drift(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    packet = _packet(paths)
    paths.packet.write_text(json.dumps(packet))
    monkeypatch.setattr(
        SUP, "_expected_packet",
        lambda *_args: (packet, _parent(), _runtime()))
    assert SUP.verify_packet(_config(), paths) == packet
    changed = copy.deepcopy(packet)
    changed["screen_launch_authorized"] = True
    paths.packet.write_text(json.dumps(changed))
    with pytest.raises(SUP.SupervisorRefusal, match="packet drift"):
        SUP.verify_packet(_config(), paths)


def test_review_marker_is_exact_unique_and_narrow():
    config = _config()
    packet_sha = "d" * 64
    raw = _review_record(packet_sha, config)
    claim = SUP._review_claim(
        raw, packet_sha256=packet_sha, config=config)
    assert claim["screen_launch_authorized"] is True
    assert claim["confirmation_authorized"] is False
    assert claim["strength_claim"] is False

    with pytest.raises(SUP.SupervisorRefusal, match="exactly one"):
        SUP._review_claim(
            raw + raw, packet_sha256=packet_sha, config=config)
    changed = raw.replace(b'"verdict":"PASS"', b'"verdict":"HOLD"')
    with pytest.raises(SUP.SupervisorRefusal, match="narrow"):
        SUP._review_claim(
            changed, packet_sha256=packet_sha, config=config)


def test_admission_binds_external_review_and_packet_bytes(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    packet = _packet(paths)
    paths.packet.write_text(json.dumps(packet))
    config = _config()
    packet_sha = SUP.sha256_file(paths.packet)
    review = tmp_path / "external-review.md"
    review.write_bytes(_review_record(packet_sha, config))
    review_sha = SUP.sha256_file(review)
    monkeypatch.setattr(SUP, "paths_for", lambda: paths)
    monkeypatch.setattr(SUP, "verify_packet", lambda *_args: packet)
    ref = SUP.admit_packet(
        config, review, review_sha, packet_sha)
    assert ref["screen_launch_authorized"] is True
    assert paths.review_copy.read_bytes() == review.read_bytes()
    _, admission = SUP._require_admission(config, paths)
    assert admission["screen_launch_authorized"] is True
    assert admission["confirmation_authorized"] is False

    paths.admission.write_text(paths.admission.read_text().replace(
        '"confirmation_authorized":false',
        '"confirmation_authorized":true'))
    with pytest.raises(SUP.SupervisorRefusal, match="admission drift"):
        SUP._require_admission(config, paths)


def test_admission_refuses_internal_review_source(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    packet = _packet(paths)
    paths.packet.write_text(json.dumps(packet))
    packet_sha = SUP.sha256_file(paths.packet)
    internal = paths.namespace / "self-review.md"
    internal.write_bytes(_review_record(packet_sha, _config()))
    monkeypatch.setattr(SUP, "paths_for", lambda: paths)
    monkeypatch.setattr(SUP, "verify_packet", lambda *_args: packet)
    with pytest.raises(SUP.SupervisorRefusal, match="external"):
        SUP.admit_packet(
            _config(), internal, SUP.sha256_file(internal), packet_sha)


def test_launch_preflight_requires_exact_three_frozen_files_and_empty_targets(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    packet = _packet(paths)
    admission = {"screen_launch_authorized": True}
    for path, payload in (
            (paths.packet, packet),
            (paths.review_copy, {"review": True}),
            (paths.admission, admission)):
        path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        SUP, "_expected_packet",
        lambda *_args: (packet, _parent(), _runtime()))
    monkeypatch.setattr(
        SUP, "_require_admission",
        lambda *_args: (packet, admission))
    got = SUP.launch_preflight(_config(), paths)
    assert got == (packet, _parent(), _runtime(), admission)

    unknown = paths.namespace / "unknown.bin"
    unknown.write_bytes(b"x")
    with pytest.raises(SUP.SupervisorRefusal, match="unknown bytes"):
        SUP.launch_preflight(_config(), paths)
    unknown.unlink()
    paths.receipt.write_text("{}")
    with pytest.raises(SUP.SupervisorRefusal, match="collision"):
        SUP.launch_preflight(_config(), paths)


def test_launch_cannot_publish_receipt_before_admission_gate(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    monkeypatch.setattr(SUP, "paths_for", lambda: paths)
    monkeypatch.setattr(
        SUP, "launch_preflight",
        lambda *_args: (_ for _ in ()).throw(
            SUP.SupervisorRefusal("review admission missing")))
    with pytest.raises(SUP.SupervisorRefusal, match="admission missing"):
        SUP.launch(_config())
    assert not paths.receipt.exists()
    assert not paths.progress_partial.exists()


def test_receipt_recomputes_all_authority_fields():
    receipt = {
        "schema": SUP.RECEIPT_SCHEMA,
        "run_id": SUP.RUN_ID,
        "complete": True,
        "created_time_ns": 1,
        "nonce": "e" * 64,
        "packet_sha256": "1" * 64,
        "admission_sha256": "2" * 64,
        "preflight_final_sha256": SUP.PREFLIGHT_FINAL_SHA256,
        "screen_launch_authorized": True,
        "confirmation_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    assert SUP.receipt_problems(
        receipt, packet_sha256="1" * 64,
        admission_sha256="2" * 64) == []
    changed = copy.deepcopy(receipt)
    changed["confirmation_authorized"] = True
    assert "receipt full recomputation drift" in SUP.receipt_problems(
        changed, packet_sha256="1" * 64,
        admission_sha256="2" * 64)


def test_terminal_job_evidence_binds_all_eight_commands_and_hashes(tmp_path):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    config = _config()
    for name, argv, output, log, exit_path in SUP._job_specs(config, paths):
        output.write_text(f"{name} output\n")
        log.write_text(f"{name} log\n")
        exit_path.write_text(json.dumps({
            "schema": SUP.EXIT_SCHEMA,
            "run_id": SUP.RUN_ID,
            "job": name,
            "argv": list(argv),
            "returncode": 0,
            "output": str(output),
            "output_regular_unlinked": True,
            "output_sha256": SUP.sha256_file(output),
            "log": str(log),
            "log_sha256": SUP.sha256_file(log),
        }))
    evidence, problems = SUP.terminal_job_evidence(config, paths)
    assert problems == []
    assert len(evidence) == 8
    paths.shard_logs[0].write_text("mutated\n")
    _, problems = SUP.terminal_job_evidence(config, paths)
    assert problems == [
        "shard-00 exit receipt full recomputation drift",
        "terminal child evidence population",
    ]


def test_aggregate_reopens_shards_and_binds_ordered_paths_and_hashes(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.namespace.mkdir()
    for index, path in enumerate(paths.shards):
        path.write_text(json.dumps({"index": index}))
    seen = {}

    monkeypatch.setattr(
        SUP.DUEL, "shard_problems", lambda *_args, **_kwargs: [])
    def fake_build(**kwargs):
        seen.update(kwargs)
        return {"status": "SELECT_NONE"}
    monkeypatch.setattr(SUP.DUEL, "build_aggregate", fake_build)
    aggregate = SUP._recompute_aggregate(
        paths, parent=_parent(), runtime=_runtime())
    assert aggregate == {"status": "SELECT_NONE"}
    assert [item["shard_index"] for item in seen["inputs"]] == list(range(8))
    assert len({item["sha256"] for item in seen["inputs"]}) == 8
    assert seen["phase"] == "screen"
    assert seen["screen_parent"] is None


def test_progress_snapshot_reports_clusters_without_outcomes(tmp_path):
    log = tmp_path / "shard.log"
    log_partial = SUP.partial(log)
    log_partial.write_text(
        "noise\n"
        + json.dumps({
            "event": "s3a-bury-duel-progress-v1",
            "phase": "screen",
            "shard_index": 0,
            "clusters_complete": 7,
            "clusters_total": 256,
        })
        + "\n"
    )
    job = SUP.Job(
        name="shard-00",
        argv=("python",),
        output=tmp_path / "out.json",
        log_partial=log_partial,
        log_final=log,
        exit_final=tmp_path / "exit.json",
        handle=None,
        process=SimpleNamespace(returncode=None),
    )
    assert SUP._job_progress(job) == {
        "job": "shard-00",
        "clusters_complete": 7,
        "clusters_total": 256,
        "finished": False,
    }


def test_terminal_final_recomputes_status_and_never_launches_confirmation(
        tmp_path):
    paths = _paths(tmp_path)
    aggregate = {"status": "AUTHORIZE_CONFIRM_PACKET_REVIEW"}
    job_evidence = [{"job": str(i)} for i in range(8)]
    kwargs = {
        "packet_sha256": "1" * 64,
        "admission_sha256": "2" * 64,
        "receipt_sha256": "3" * 64,
        "progress_sha256": "4" * 64,
        "shard_sha256s": [f"{index:064x}" for index in range(8)],
        "aggregate_sha256": "5" * 64,
        "aggregate": aggregate,
        "job_evidence": job_evidence,
        "paths": paths,
    }
    final = {
        "schema": SUP.FINAL_SCHEMA,
        "run_id": SUP.RUN_ID,
        "complete": True,
        "packet_sha256": "1" * 64,
        "admission_sha256": "2" * 64,
        "receipt_sha256": "3" * 64,
        "progress_sha256": "4" * 64,
        "jobs": job_evidence,
        "shards": [
            {
                "path": str(paths.shards[index]),
                "sha256": f"{index:064x}",
                "shard_index": index,
            }
            for index in range(8)
        ],
        "aggregate": {
            "path": str(paths.aggregate),
            "sha256": "5" * 64,
            "status": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
        },
        "screen_gate_passed": True,
        "confirm_packet_review_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    assert SUP.final_problems(final, **kwargs) == []
    for mutation in (
            lambda value: value.update(confirmation_launch_authorized=True),
            lambda value: value.update(production_promotion=True),
            lambda value: value["aggregate"].update(status="SELECT_NONE"),
            lambda value: value.update(extra={"outcome": 1})):
        changed = copy.deepcopy(final)
        mutation(changed)
        assert SUP.final_problems(changed, **kwargs) == [
            "supervisor final full recomputation drift"]


def test_source_host_python_and_experimental_key_guards(
        tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    paths.runner.write_text("runner")
    paths.controller.write_text("controller")
    config = SUP.Config(
        expected_git="a" * 40,
        expected_runner_sha256=SUP.sha256_file(paths.runner),
        expected_controller_sha256=SUP.sha256_file(paths.controller),
        heartbeat_seconds=30.0,
    )
    monkeypatch.setattr(
        SUP.os, "uname",
        lambda: SimpleNamespace(nodename="wrong-host"))
    with pytest.raises(SUP.SupervisorRefusal, match="pinned to"):
        SUP._identity_context(config, paths)

    bad = copy.copy(config)
    object.__setattr__(bad, "expected_runner_sha256", "not-a-sha")
    with pytest.raises(SUP.SupervisorRefusal, match="malformed"):
        SUP._identity_context(bad, paths)

    monkeypatch.setattr(
        SUP.os, "uname",
        lambda: SimpleNamespace(nodename=SUP.EXPECTED_HOST))
    monkeypatch.setattr(
        SUP, "_git",
        lambda *args: config.expected_git
        if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(
        SUP.DUEL, "require_runtime",
        lambda _git: (object(), _parent(), _runtime()))
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv("SHENGJI_UNIFORM_DEAL", "")
    with pytest.raises(SUP.SupervisorRefusal, match="must be absent"):
        SUP._identity_context(config, paths)
    monkeypatch.delenv("SHENGJI_UNIFORM_DEAL")
    wrong_runtime = _runtime()
    wrong_runtime["python"] = "3.14.6"
    monkeypatch.setattr(
        SUP.DUEL, "require_runtime",
        lambda _git: (object(), _parent(), wrong_runtime))
    with pytest.raises(SUP.SupervisorRefusal, match="host/Python"):
        SUP._identity_context(config, paths)


def test_heartbeat_bounds_and_review_arguments_are_fail_closed():
    common = [
        "freeze",
        "--expected-git", "a" * 40,
        "--expected-runner-sha256", "b" * 64,
        "--expected-controller-sha256", "c" * 64,
    ]
    with pytest.raises(SUP.SupervisorRefusal, match="heartbeat"):
        SUP.main([*common, "--heartbeat-seconds", "0"])
    with pytest.raises(SUP.SupervisorRefusal, match="heartbeat"):
        SUP.main([*common, "--heartbeat-seconds", "61"])

    with pytest.raises(SUP.SupervisorRefusal, match="only by admit"):
        SUP.main([
            "launch",
            "--expected-git", "a" * 40,
            "--expected-runner-sha256", "b" * 64,
            "--expected-controller-sha256", "c" * 64,
            "--review-record", "/tmp/review",
        ])


def test_regular_unlinked_rejects_symlink_and_extra_hardlink(tmp_path):
    original = tmp_path / "artifact.json"
    original.write_text("{}\n")
    assert SUP.is_regular_unlinked(original)
    symlink = tmp_path / "artifact-symlink.json"
    symlink.symlink_to(original)
    assert not SUP.is_regular_unlinked(symlink)
    hardlink = tmp_path / "artifact-hardlink.json"
    hardlink.hardlink_to(original)
    assert not SUP.is_regular_unlinked(original)
    assert not SUP.is_regular_unlinked(hardlink)
