from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import review_pair_terminal as PAIR_REVIEW
from scripts import review_t4_terminal as T4_REVIEW
from scripts.terminal_review_common import ReviewRefused
from scripts import terminal_review_common as COMMON


def digest(value, newline=False):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((raw + ("\n" if newline else "")).encode()).hexdigest()


def write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker(path: Path, prefix: str, claim: dict) -> Path:
    path.write_text(prefix + json.dumps(claim, sort_keys=True,
                                        separators=(",", ":")) + "\n")
    return path


class T4Screen:
    LABELS = ("treatment", "matched_null", "champion")

    @staticmethod
    def aggregate_screen(records, **_kwargs):
        mean = sum(row["value"] for row in records["treatment"]) - sum(
            row["value"] for row in records["champion"])
        status = "AUTHORIZE_CONFIRM_PACKET_REVIEW" if mean > 0 else "SELECT_NONE"
        return {"stats": {"mean": mean}, "status": status}


def t4_fixture(tmp_path: Path, monkeypatch):
    run = tmp_path / "server/runs/logs/t4"
    locks = tmp_path / "server/runs/locks"
    ctrl = SimpleNamespace(
        RESULT_PATH="server/runs/logs/t4/aggregate.json",
        PACKET_PATH="server/runs/logs/t4/packet.json",
        RECEIPT_PATH="server/runs/logs/t4/receipt.json",
        CAPACITY_RESULT_PATH="server/runs/logs/t4/capacity.json",
        SUPERVISOR_FINAL_PATH="server/runs/logs/t4/final.json",
        SUPERVISOR_ADMISSION_PATH="server/runs/locks/t4.supervisor.json",
        AGGREGATE_ADMISSION_PATH="server/runs/locks/t4.aggregate.json",
        SHARD_PATHS=[f"server/runs/logs/t4/shard-{i}.json" for i in range(2)],
        SHARD_LOG_PATHS=[f"server/runs/logs/t4/shard-{i}.log" for i in range(2)],
        RUN_ID="t4", SCREEN_SEED0=10, SCREEN_CLUSTERS=4)
    packet = {"producer": {"git": T4_REVIEW.GIT},
              "selected_capability": {"surface": "play"},
              "model_exports_sha256": "m" * 64}
    write(tmp_path / ctrl.PACKET_PATH, packet)
    write(tmp_path / ctrl.RECEIPT_PATH, {"receipt": True})
    write(tmp_path / ctrl.CAPACITY_RESULT_PATH, {"capacity": True})
    receipt_sha = file_sha(tmp_path / ctrl.RECEIPT_PATH)
    sealed, merged = [], {label: [] for label in T4Screen.LABELS}
    for index in range(2):
        records = {label: [{"value": index + (2 if label == "treatment" else 0)}]
                   for label in T4Screen.LABELS}
        shard = {"records": records}
        shard["shard_sha256"] = digest(shard, newline=True)
        shard_path = write(tmp_path / ctrl.SHARD_PATHS[index], shard)
        log_path = write(tmp_path / ctrl.SHARD_LOG_PATHS[index], b"done\n")
        sealed.append({"external_sha256": file_sha(shard_path),
                       "internal_sha256": shard["shard_sha256"],
                       "log_sha256": file_sha(log_path)})
        for label in T4Screen.LABELS:
            merged[label].extend(records[label])
    supervisor_admission = write(
        tmp_path / ctrl.SUPERVISOR_ADMISSION_PATH, {"kind": "supervisor"})
    final = {"final_sha256": "f" * 64,
             "supervisor_admission_slot_sha256": file_sha(
                 supervisor_admission),
             "shards": sealed}
    final_path = write(tmp_path / ctrl.SUPERVISOR_FINAL_PATH, final)
    final_sha = file_sha(final_path)
    packet_review = write(tmp_path / "packet-review", b"packet\n")
    capacity_review = write(tmp_path / "capacity-review", b"capacity\n")
    supervisor_claim = {"final": final_sha, "verdict": "PASS"}
    supervisor_review = marker(tmp_path / "supervisor-review", "SUP ", supervisor_claim)
    admission = {"kind": "aggregate"}
    admission_path = write(tmp_path / ctrl.AGGREGATE_ADMISSION_PATH, admission)
    rebuilt = T4Screen.aggregate_screen(merged)
    manifest = [{"index": i, "logical_path": ctrl.SHARD_PATHS[i],
                 "external_sha256": sealed[i]["external_sha256"],
                 "internal_sha256": sealed[i]["internal_sha256"]}
                for i in range(2)]
    aggregate = {
        "schema": "t4-aggregate", "run_id": ctrl.RUN_ID,
        "git": T4_REVIEW.GIT, "controller_packet_sha256": T4_REVIEW.PACKET_SHA,
        "screen_receipt_sha256": receipt_sha,
        "supervisor_final_sha256": final_sha,
        "supervisor_final_internal_sha256": final["final_sha256"],
        "supervisor_review_record_sha256": file_sha(supervisor_review),
        "supervisor_review_claim": supervisor_claim,
        "aggregate_admission_slot": ctrl.AGGREGATE_ADMISSION_PATH,
        "aggregate_admission_slot_sha256": file_sha(admission_path),
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "shards": manifest, "screen": rebuilt, "decision": rebuilt["status"],
        "confirmation_packet_review_authorized": True,
        "strength_claim": False, "confirmation_launch_authorized": False,
        "production_promotion": False, "production_deployment": False,
        "retry_or_extension_authorized": False}
    aggregate["result_sha256"] = digest(aggregate, newline=True)
    aggregate_path = write(tmp_path / ctrl.RESULT_PATH, aggregate)

    class Runtime:
        REPO = tmp_path
        CTRL = ctrl
        SCREEN = T4Screen
        AGGREGATE_SCHEMA = "t4-aggregate"
        self_hash = staticmethod(lambda value, field: digest(
            {k: v for k, v in value.items() if k != field}, newline=True))
        load_json = staticmethod(lambda path: json.loads(path.read_text()))
        _packet = staticmethod(lambda *_args: (packet, None))
        _receipt = staticmethod(lambda *_args, **_kwargs: (
            json.loads((tmp_path / ctrl.RECEIPT_PATH).read_text()),
            json.loads((tmp_path / ctrl.CAPACITY_RESULT_PATH).read_text())))
        _supervisor_final = staticmethod(lambda **_kwargs: final)
        _supervisor_review_claim = staticmethod(
            lambda *_args: supervisor_claim)

        @staticmethod
        def _validate_attempt_slot(**kwargs):
            path = tmp_path / kwargs["logical"]
            if file_sha(path) != kwargs["expected_sha256"] or json.loads(
                    path.read_text()) != admission:
                raise ReviewRefused("T4 aggregate admission binding drift")

        @staticmethod
        def validate_shard(shard, **_kwargs):
            if shard.get("shard_sha256") != digest(
                    {k: v for k, v in shard.items() if k != "shard_sha256"},
                    newline=True):
                raise ReviewRefused("bad shard")

    module = SimpleNamespace(BASE=Runtime)
    monkeypatch.setattr(T4_REVIEW, "exact_source", lambda *_args: None)
    monkeypatch.setattr(
        T4_REVIEW, "import_script", lambda *_args, **_kwargs: module)
    return (packet_review, capacity_review, supervisor_review,
            admission_path, aggregate_path, tmp_path / ctrl.SHARD_PATHS[0])


def test_t4_recursive_review_is_read_only(tmp_path, monkeypatch):
    packet, capacity, supervisor, *_ = t4_fixture(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    claim = T4_REVIEW.review(tmp_path, packet, capacity, supervisor)
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    assert claim["recursive_statistic_reconstruction"] is True


def test_t4_admission_refuses_before_malformed_shard_open(tmp_path, monkeypatch):
    packet, capacity, supervisor, admission, aggregate, shard = t4_fixture(
        tmp_path, monkeypatch)
    write(admission, {"kind": "forged"})
    shard.write_bytes(b"not-json")
    with pytest.raises(ReviewRefused, match="admission"):
        T4_REVIEW.review(tmp_path, packet, capacity, supervisor)


def test_t4_aggregate_preopen_binding_drift_refuses_before_shard_open(
        tmp_path, monkeypatch):
    packet, capacity, supervisor, _, aggregate_path, shard_path = t4_fixture(
        tmp_path, monkeypatch)
    aggregate = json.loads(aggregate_path.read_text())
    aggregate["confirmation_launch_authorized"] = True
    aggregate["result_sha256"] = digest(
        {key: value for key, value in aggregate.items()
         if key != "result_sha256"}, newline=True)
    write(aggregate_path, aggregate)
    shard_path.write_bytes(b"outcome bytes must remain unopened")
    with pytest.raises(ReviewRefused, match="aggregate pre-open binding drift"):
        T4_REVIEW.review(tmp_path, packet, capacity, supervisor)


def test_t4_supervisor_final_changed_during_validation_refuses(
        tmp_path, monkeypatch):
    packet, capacity, supervisor, *_ = t4_fixture(tmp_path, monkeypatch)
    runtime = T4_REVIEW.import_script(None, None, None).BASE
    final_path = tmp_path / runtime.CTRL.SUPERVISOR_FINAL_PATH
    original = copy.deepcopy(runtime._supervisor_final())

    def changed_final(**_kwargs):
        changed = copy.deepcopy(original)
        changed["final_sha256"] = "0" * 64
        write(final_path, changed)
        return changed

    monkeypatch.setattr(runtime, "_supervisor_final", changed_final)
    with pytest.raises(ReviewRefused, match="final changed during validation"):
        T4_REVIEW.review(tmp_path, packet, capacity, supervisor)


@pytest.mark.parametrize("drift", ["external", "internal", "log"])
def test_t4_sealed_shard_drift_refuses(tmp_path, monkeypatch, drift):
    packet, capacity, supervisor, _, aggregate_path, shard_path = t4_fixture(
        tmp_path, monkeypatch)
    runtime = T4_REVIEW.import_script(None, None, None).BASE
    ctrl = runtime.CTRL
    if drift == "log":
        (tmp_path / ctrl.SHARD_LOG_PATHS[0]).write_bytes(b"changed log\n")
    else:
        shard = json.loads(shard_path.read_text())
        shard["records"]["treatment"][0]["value"] += 1
        shard["shard_sha256"] = digest(
            {key: value for key, value in shard.items()
             if key != "shard_sha256"}, newline=True)
        write(shard_path, shard)
        if drift == "internal":
            final = runtime._supervisor_final()
            final["shards"][0]["external_sha256"] = file_sha(shard_path)
            final_path = tmp_path / ctrl.SUPERVISOR_FINAL_PATH
            write(final_path, final)
            final_sha = file_sha(final_path)
            claim = runtime._supervisor_review_claim()
            claim["final"] = final_sha
            marker(supervisor, "SUP ", claim)
            aggregate = json.loads(aggregate_path.read_text())
            aggregate["supervisor_final_sha256"] = final_sha
            aggregate["supervisor_review_record_sha256"] = file_sha(supervisor)
            aggregate["supervisor_review_claim"] = claim
            aggregate["result_sha256"] = digest(
                {key: value for key, value in aggregate.items()
                 if key != "result_sha256"}, newline=True)
            write(aggregate_path, aggregate)
    with pytest.raises(ReviewRefused, match="sealed shard 0 drift"):
        T4_REVIEW.review(tmp_path, packet, capacity, supervisor)


def test_t4_duplicate_key_shard_refuses_after_valid_seals(
        tmp_path, monkeypatch):
    packet, capacity, supervisor, _, aggregate_path, shard_path = t4_fixture(
        tmp_path, monkeypatch)
    runtime = T4_REVIEW.import_script(None, None, None).BASE
    ctrl = runtime.CTRL
    shard = json.loads(shard_path.read_text())
    raw = json.dumps(shard, sort_keys=True, separators=(",", ":"))
    shard_path.write_text(
        raw[:-1] + ",\"records\":" + json.dumps(
            shard["records"], sort_keys=True, separators=(",", ":"))
        + "}\n")

    final = runtime._supervisor_final()
    final["shards"][0]["external_sha256"] = file_sha(shard_path)
    final_path = tmp_path / ctrl.SUPERVISOR_FINAL_PATH
    write(final_path, final)
    final_sha = file_sha(final_path)
    supervisor_claim = runtime._supervisor_review_claim()
    supervisor_claim["final"] = final_sha
    marker(supervisor, "SUP ", supervisor_claim)

    aggregate = json.loads(aggregate_path.read_text())
    aggregate["supervisor_final_sha256"] = final_sha
    aggregate["supervisor_review_record_sha256"] = file_sha(supervisor)
    aggregate["supervisor_review_claim"] = supervisor_claim
    aggregate["shards"][0]["external_sha256"] = file_sha(shard_path)
    aggregate["result_sha256"] = digest(
        {key: value for key, value in aggregate.items()
         if key != "result_sha256"}, newline=True)
    write(aggregate_path, aggregate)

    with pytest.raises(ReviewRefused, match="duplicate JSON key: records"):
        T4_REVIEW.review(tmp_path, packet, capacity, supervisor)


class PairScreen:
    RUN_ID = "pair"
    AGGREGATE_SCHEMA = "pair-aggregate"
    PACKET_REVIEW_PREFIX = "PACKET "
    SUPERVISOR_REVIEW_PREFIX = "SUPERVISOR "
    stable_digest = staticmethod(digest)


def pair_fixture(tmp_path: Path, monkeypatch):
    screen = PairScreen
    screen.REPO = tmp_path
    run, locks = tmp_path / "run", tmp_path / "locks"
    screen.AGGREGATE_PATH = run / "aggregate.json"
    screen.CAPACITY_RESULT_PATH = run / "capacity.json"
    screen.PLANNING_REVIEW_PATH = tmp_path / "planning-review"
    screen.PACKET_PATH = run / "packet.json"
    screen.RECEIPT_PATH = run / "receipt.json"
    screen.SUPERVISOR_FINAL_PATH = run / "final.json"
    screen.AGGREGATE_ADMISSION_PATH = locks / "aggregate.json"
    screen.EXECUTION_ADMISSION_PATH = locks / "execution.json"
    screen.SUPERVISOR_ADMISSION_PATH = locks / "supervisor.json"
    screen.SHARD_PATHS = [run / f"shard-{i}.json" for i in range(2)]
    screen.SHARD_LOG_PATHS = [run / f"shard-{i}.log" for i in range(2)]
    screen.SHARD_ADMISSION_PATHS = [
        locks / f"shard-{i}.json" for i in range(2)]
    packet = {"git": PAIR_REVIEW.GIT, "internal_sha256": "p" * 64}
    write(screen.PACKET_PATH, packet)
    write(screen.CAPACITY_RESULT_PATH, {})
    write(screen.PLANNING_REVIEW_PATH, b"planning\n")
    packet_claim = {"packet": PAIR_REVIEW.PACKET_SHA, "verdict": "PASS"}
    packet_review = marker(tmp_path / "packet-review", "PACKET ", packet_claim)

    def admission(schema, **extra):
        value = {
            "schema": schema, "run_id": screen.RUN_ID,
            "git": PAIR_REVIEW.GIT,
            "packet_sha256": PAIR_REVIEW.PACKET_SHA,
            "nonce": "a" * 64, "created_time_ns": 1,
            "retry_or_extension_authorized": False,
            "production_deployment": False, **extra}
        value["internal_sha256"] = digest(value)
        return value

    execution = admission(
        "pair-aware-rollout-screen-execution-admission-v1",
        packet_review_record_sha256=file_sha(packet_review))
    write(screen.EXECUTION_ADMISSION_PATH, execution)
    receipt = {
        "receipt": True,
        "execution_admission_sha256": file_sha(
            screen.EXECUTION_ADMISSION_PATH)}
    write(screen.RECEIPT_PATH, receipt)
    receipt_sha = file_sha(screen.RECEIPT_PATH)
    shards = []
    for index, path in enumerate(screen.SHARD_PATHS):
        shard_admission = admission(
            "pair-aware-rollout-screen-shard-admission-v1",
            receipt_sha256=receipt_sha, shard_index=index)
        write(screen.SHARD_ADMISSION_PATHS[index], shard_admission)
        shard = {"index": index, "values": [index + 1, index + 2]}
        shard["shard_admission_sha256"] = file_sha(
            screen.SHARD_ADMISSION_PATHS[index])
        shard["internal_sha256"] = digest(shard)
        write(path, shard)
        write(screen.SHARD_LOG_PATHS[index], b"done\n")
        shards.append(shard)
    supervisor_admission = admission(
        "pair-aware-rollout-screen-supervisor-admission-v1",
        receipt_sha256=receipt_sha)
    write(screen.SUPERVISOR_ADMISSION_PATH, supervisor_admission)
    final = {
        "shards": [
            {"index": i, "log_sha256": file_sha(
                screen.SHARD_LOG_PATHS[i])}
            for i in range(2)],
        "supervisor_admission_sha256": file_sha(
            screen.SUPERVISOR_ADMISSION_PATH)}
    write(screen.SUPERVISOR_FINAL_PATH, final)
    final_sha = file_sha(screen.SUPERVISOR_FINAL_PATH)
    supervisor_claim = {"final": final_sha, "verdict": "PASS"}
    supervisor_review = marker(
        tmp_path / "supervisor-review", "SUPERVISOR ", supervisor_claim)
    supervisor_marker = {"sha256": file_sha(supervisor_review),
                         "marker": supervisor_review.read_text().strip()}
    admission = {
        "schema": "pair-aware-rollout-screen-aggregate-admission-v1",
        "run_id": screen.RUN_ID, "git": PAIR_REVIEW.GIT,
        "packet_sha256": PAIR_REVIEW.PACKET_SHA, "nonce": "a" * 64,
        "created_time_ns": 1, "retry_or_extension_authorized": False,
        "production_deployment": False, "receipt_sha256": receipt_sha,
        "supervisor_review_record_sha256": supervisor_marker["sha256"]}
    admission["internal_sha256"] = digest(admission)
    write(screen.AGGREGATE_ADMISSION_PATH, admission)

    def aggregate_payload(**kwargs):
        total = sum(sum(shard["values"]) for shard in kwargs["shard_values"])
        value = {
            "schema": screen.AGGREGATE_SCHEMA,
            "run_id": screen.RUN_ID, "git": PAIR_REVIEW.GIT,
            "packet_sha256": PAIR_REVIEW.PACKET_SHA,
            "receipt_sha256": receipt_sha,
            "supervisor_final_sha256": final_sha,
            "supervisor_review_record_sha256": supervisor_marker["sha256"],
            "supervisor_review_marker": supervisor_marker["marker"],
            "status": "PASS_SCREEN", "primary_level_utility": {"total": total},
            "secondary_game_win_rate": {"total": total / 2},
            "natural_dose": {"total": 1},
            "confirmation_packet_design_authorized": True,
            "confirmation_execution_authorized": False,
            "strength_claim": False, "production_promotion": False,
            "production_deployment": False,
            "retry_or_extension_authorized": False}
        value["internal_sha256"] = digest(value)
        return value

    def parse_marker(path, prefix, claim, **_kwargs):
        expected = prefix + json.dumps(claim, sort_keys=True,
                                       separators=(",", ":"))
        lines = [line for line in path.read_text().splitlines()
                 if line.startswith(prefix)]
        if lines != [expected]:
            raise ReviewRefused("marker drift")
        return {"sha256": file_sha(path), "marker": expected}

    screen.load_packet = staticmethod(lambda *_args, **_kwargs: packet)
    screen.packet_review_claim = staticmethod(lambda *_args: packet_claim)
    screen.parse_marker = staticmethod(parse_marker)
    screen.load_receipt = staticmethod(lambda *_args, **_kwargs: receipt)
    screen.supervisor_review_claim = staticmethod(
        lambda *_args: supervisor_claim)
    screen.validate_supervisor_final = staticmethod(lambda *_args, **_kwargs: None)
    screen.aggregate_payload = staticmethod(aggregate_payload)
    expected = aggregate_payload(
        shard_values=shards, shard_sha256s=[], packet=packet,
        packet_sha256=PAIR_REVIEW.PACKET_SHA, receipt_sha256=receipt_sha,
        supervisor_final_sha256=final_sha,
        supervisor_review=supervisor_marker)
    expected["aggregate_admission_sha256"] = file_sha(
        screen.AGGREGATE_ADMISSION_PATH)
    expected.pop("internal_sha256")
    expected["internal_sha256"] = digest(expected)
    write(screen.AGGREGATE_PATH, expected)
    monkeypatch.setattr(PAIR_REVIEW, "exact_source", lambda *_args: None)
    monkeypatch.setattr(
        PAIR_REVIEW, "import_script", lambda *_args, **_kwargs: screen)
    return (packet_review, supervisor_review, screen.AGGREGATE_ADMISSION_PATH,
            screen.AGGREGATE_PATH, screen.SHARD_PATHS[0])


def test_pair_recursive_review_is_read_only(tmp_path, monkeypatch):
    packet, supervisor, *_ = pair_fixture(tmp_path, monkeypatch)
    admission_schemas = []
    real_admission = PAIR_REVIEW._admission

    def recording_admission(*args, **kwargs):
        admission_schemas.append(kwargs["schema"])
        return real_admission(*args, **kwargs)

    monkeypatch.setattr(PAIR_REVIEW, "_admission", recording_admission)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    claim = PAIR_REVIEW.review(tmp_path, packet, supervisor)
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    assert claim["recursive_statistic_reconstruction"] is True
    assert admission_schemas == [
        "pair-aware-rollout-screen-execution-admission-v1",
        "pair-aware-rollout-screen-supervisor-admission-v1",
        "pair-aware-rollout-screen-aggregate-admission-v1",
        "pair-aware-rollout-screen-shard-admission-v1",
        "pair-aware-rollout-screen-shard-admission-v1",
    ]


def test_pair_admission_refuses_before_malformed_shard_open(tmp_path, monkeypatch):
    packet, supervisor, admission, aggregate, shard = pair_fixture(
        tmp_path, monkeypatch)
    forged = json.loads(admission.read_text())
    forged["nonce"] = "b" * 64
    forged["internal_sha256"] = digest(
        {k: v for k, v in forged.items() if k != "internal_sha256"})
    write(admission, forged)
    shard.write_bytes(b"not-json")
    with pytest.raises(ReviewRefused, match="admission"):
        PAIR_REVIEW.review(tmp_path, packet, supervisor)


def test_common_rejects_hardlink_and_nonfinite_json(tmp_path):
    original = write(tmp_path / "original.json", {})
    linked = tmp_path / "linked.json"
    os.link(original, linked)
    with pytest.raises(ReviewRefused, match="regular unlinked"):
        COMMON.load_json(linked, "hardlink")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}\n')
    with pytest.raises(ReviewRefused, match="strict JSON"):
        COMMON.load_json(nonfinite, "nonfinite")


def test_common_single_fd_reader_refuses_path_replacement(
        tmp_path, monkeypatch):
    target = write(tmp_path / "target.json", {"value": 1})
    replacement = write(tmp_path / "replacement.json", {"value": 2})
    displaced = tmp_path / "displaced.json"
    real_read = COMMON.os.read
    swapped = False

    def replacing_read(descriptor, size):
        nonlocal swapped
        value = real_read(descriptor, size)
        if not swapped:
            swapped = True
            target.rename(displaced)
            replacement.rename(target)
        return value

    monkeypatch.setattr(COMMON.os, "read", replacing_read)
    with pytest.raises(ReviewRefused, match="changed while reading"):
        COMMON.load_json_with_sha256(target, "raced JSON")


def test_common_rejects_dirty_tracked_dependency(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo,
                   check=True)
    module = write(repo / "server/scripts/lane.py", b"VALUE = 1\n")
    dependency = write(repo / "server/scripts/dependency.py", b"VALUE = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          check=True, text=True, capture_output=True).stdout.strip()
    dependency.write_text("VALUE = 2\n")
    with pytest.raises(ReviewRefused, match="tracked-tree"):
        COMMON.exact_source(repo, head, {"server/scripts/lane.py": file_sha(module)})


@pytest.mark.parametrize("claim_expected_path", [False, True])
def test_common_rejects_preloaded_module(
        tmp_path, monkeypatch, claim_expected_path):
    repo = tmp_path / "repo"
    expected = write(repo / "server/scripts/lane.py", b"VALUE = 1\n")
    wrong = write(tmp_path / "wrong/lane.py", b"VALUE = 2\n")
    poisoned = SimpleNamespace(
        __file__=str(expected if claim_expected_path else wrong))
    monkeypatch.setitem(sys.modules, "terminal_review_test_lane", poisoned)
    with pytest.raises(ReviewRefused, match="preloaded source module"):
        COMMON.import_script(
            repo, "terminal_review_test_lane",
            str(expected.relative_to(repo)))


def test_common_rejects_preloaded_dependency(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    lane = write(repo / "server/scripts/lane.py", b"VALUE = 1\n")
    dependency = write(
        repo / "server/scripts/dependency.py", b"VALUE = 1\n")
    monkeypatch.setitem(
        sys.modules, "terminal_review_test_dependency",
        SimpleNamespace(__file__=str(dependency)))
    with pytest.raises(ReviewRefused, match="preloaded source module"):
        COMMON.import_script(
            repo, "terminal_review_test_lane", str(lane.relative_to(repo)),
            {"terminal_review_test_dependency":
             str(dependency.relative_to(repo))})


def test_common_rejects_dependency_import_path_drift(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    lane = write(repo / "server/scripts/lane.py", b"VALUE = 1\n")
    dependency = write(
        repo / "server/scripts/dependency.py", b"VALUE = 1\n")
    wrong = write(tmp_path / "wrong/dependency.py", b"VALUE = 2\n")
    lane_module = SimpleNamespace(__file__=str(lane))
    dependency_module = SimpleNamespace(__file__=str(wrong))

    def forged_import(name):
        assert name == "terminal_review_test_lane"
        monkeypatch.setitem(
            sys.modules, "terminal_review_test_lane", lane_module)
        monkeypatch.setitem(
            sys.modules, "terminal_review_test_dependency",
            dependency_module)
        return lane_module

    monkeypatch.setattr(COMMON.importlib, "import_module", forged_import)
    with pytest.raises(
            ReviewRefused, match="import path drift: terminal_review_test_dependency"):
        COMMON.import_script(
            repo, "terminal_review_test_lane", str(lane.relative_to(repo)),
            {"terminal_review_test_dependency":
             str(dependency.relative_to(repo))})


def test_common_rejects_preloaded_transitive_shengji_module(
        tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    write(repo / "server/scripts/lane.py", b"VALUE = 1\n")
    write(repo / "server/shengji/__init__.py", b"")
    dependency = write(
        repo / "server/shengji/dependency.py", b"VALUE = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo,
                   check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo,
                   check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        text=True, capture_output=True).stdout.strip()
    monkeypatch.setitem(
        sys.modules, "shengji.dependency",
        SimpleNamespace(__file__=str(dependency), VALUE="forged"))
    with pytest.raises(ReviewRefused, match="preloaded source module"):
        COMMON.import_script(
            repo, "lane", "server/scripts/lane.py", git=head)


def test_pair_rejects_rehashed_execution_admission_authority(
        tmp_path, monkeypatch):
    packet, supervisor, *_ = pair_fixture(tmp_path, monkeypatch)
    screen = PAIR_REVIEW.import_script(None, None, None)
    admission = json.loads(screen.EXECUTION_ADMISSION_PATH.read_text())
    admission["production_deployment"] = True
    admission["internal_sha256"] = digest(
        {key: value for key, value in admission.items()
         if key != "internal_sha256"})
    write(screen.EXECUTION_ADMISSION_PATH, admission)
    receipt = json.loads(screen.RECEIPT_PATH.read_text())
    receipt["execution_admission_sha256"] = file_sha(
        screen.EXECUTION_ADMISSION_PATH)
    write(screen.RECEIPT_PATH, receipt)
    screen.load_receipt = staticmethod(lambda *_args, **_kwargs: receipt)
    with pytest.raises(ReviewRefused, match="execution-admission.*binding"):
        PAIR_REVIEW.review(tmp_path, packet, supervisor)


def test_pair_refuses_hash_then_parse_substitution(tmp_path, monkeypatch):
    packet_review, supervisor_review, *_ = pair_fixture(tmp_path, monkeypatch)
    screen = PAIR_REVIEW.import_script(None, None, None)
    forged = json.loads(screen.PACKET_PATH.read_text())
    forged["forged_after_hash"] = True
    screen.load_packet = staticmethod(lambda *_args, **_kwargs: forged)
    with pytest.raises(ReviewRefused, match="packet changed during validation"):
        PAIR_REVIEW.review(tmp_path, packet_review, supervisor_review)


@pytest.mark.parametrize("lane", ["t4", "pair"])
def test_rehashed_terminal_statistic_mutation_refuses(tmp_path, monkeypatch, lane):
    if lane == "t4":
        packet, capacity, supervisor, _, aggregate_path, _ = t4_fixture(
            tmp_path, monkeypatch)
        aggregate = json.loads(aggregate_path.read_text())
        aggregate["screen"]["stats"]["mean"] = 999
        aggregate["result_sha256"] = digest(
            {k: v for k, v in aggregate.items() if k != "result_sha256"},
            newline=True)
        write(aggregate_path, aggregate)
        call = lambda: T4_REVIEW.review(
            tmp_path, packet, capacity, supervisor)
    else:
        packet, supervisor, _, aggregate_path, _ = pair_fixture(
            tmp_path, monkeypatch)
        aggregate = json.loads(aggregate_path.read_text())
        aggregate["primary_level_utility"]["total"] = 999
        aggregate["internal_sha256"] = digest(
            {k: v for k, v in aggregate.items() if k != "internal_sha256"})
        write(aggregate_path, aggregate)
        call = lambda: PAIR_REVIEW.review(tmp_path, packet, supervisor)
    with pytest.raises(ReviewRefused, match="reconstruction drift"):
        call()
