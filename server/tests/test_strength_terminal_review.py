from __future__ import annotations

import copy
import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import strength_terminal_review as REVIEW


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"))
                    + "\n")
    return path


def _write_marker(path: Path, prefix: str, claim: dict) -> Path:
    path.write_text(prefix + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def _self_newline(value: dict, field: str) -> str:
    return REVIEW.stable_digest(
        {key: item for key, item in value.items() if key != field},
        newline=True)


class FakeT4Controller:
    SCHEMA = "packet"
    REVIEW_MARKER = "PACKET_REVIEW "
    CAPACITY_RESULT_SCHEMA = "capacity"
    CAPACITY_REVIEW_MARKER = "CAPACITY_REVIEW "
    RUNTIME_RECEIPT_SCHEMA = "receipt"
    RUNTIME_SUPERVISOR_FINAL_SCHEMA = "supervisor"
    SUPERVISOR_REVIEW_MARKER = "SUPERVISOR_REVIEW "
    SCREEN_SEED0 = 100
    CLUSTERS_PER_SHARD = 2
    SCREEN_CLUSTERS = 4
    SHARD_PATHS = ("shard-0", "shard-1")
    SHARD_LOG_PATHS = ("log-0", "log-1")
    SHARD_ADMISSION_PATHS = ("attempt-0", "attempt-1")
    SUPERVISOR_ADMISSION_PATH = "supervisor-slot"
    AGGREGATE_ADMISSION_PATH = "aggregate-slot"

    self_hash = staticmethod(_self_newline)

    @staticmethod
    def manifest_hash(value):
        return REVIEW.stable_digest(value, newline=True)

    @staticmethod
    def is_sha256(value):
        return isinstance(value, str) and len(value) == 64

    @staticmethod
    def expected_review_claim(packet, packet_sha):
        return {"schema": "packet-review", "packet": packet_sha,
                "git": packet["producer"]["git"], "verdict": "PASS"}

    @staticmethod
    def expected_capacity_review_claim(packet, packet_sha, capacity,
                                       capacity_sha):
        return {"schema": "capacity-review", "packet": packet_sha,
                "capacity": capacity_sha,
                "internal": capacity["result_sha256"], "verdict": "PASS"}

    @staticmethod
    def expected_supervisor_review_claim(packet, packet_sha, final,
                                         final_sha):
        return {"schema": "supervisor-review", "packet": packet_sha,
                "final": final_sha, "manifest": final["shard_manifest_sha256"],
                "verdict": "PASS"}


class FakeT4Screen:
    LABELS = ("treatment", "matched_null", "champion")

    @classmethod
    def aggregate_screen(cls, records, *, expected_seed0,
                         expected_clusters, expected_surface):
        assert set(records) == set(cls.LABELS)
        assert expected_surface == "play"
        assert all(len(records[label]) == expected_clusters
                   for label in cls.LABELS)
        for label in cls.LABELS:
            assert [row["seed"] for row in records[label]] == list(
                range(expected_seed0, expected_seed0 + expected_clusters))
        treatment = sum(row["value"] for row in records["treatment"])
        champion = sum(row["value"] for row in records["champion"])
        mean = (treatment - champion) / expected_clusters
        return {
            "stats": {"treatment_champion": {"mean": mean}},
            "criteria": {"all": mean > 0},
            "status": ("AUTHORIZE_CONFIRM_PACKET_REVIEW"
                       if mean > 0 else "SELECT_NONE"),
        }


class FakeT4Runtime:
    SHARD_SCHEMA = "shard"
    AGGREGATE_SCHEMA = "aggregate"

    @staticmethod
    def _attempt_slot_payload(*, packet, packet_sha256, receipt_sha256,
                              review_record, kind):
        value = {
            "schema": "attempt", "run_id": packet["run_id"],
            "git": packet["producer"]["git"], "packet": packet_sha256,
            "receipt": receipt_sha256,
            "review": REVIEW.sha256(review_record), "kind": kind,
        }
        value["slot_sha256"] = _self_newline(value, "slot_sha256")
        return value

    @staticmethod
    def _child_command(*, index, **_kwargs):
        return ["child", str(index)]


def _t4_fixture(tmp_path: Path):
    controller = FakeT4Controller
    runtime = FakeT4Runtime
    api = SimpleNamespace(
        controller=controller, runtime=runtime, screen=FakeT4Screen)
    sources = {"source": "a" * 64}
    packet = {
        "schema": controller.SCHEMA,
        "run_id": "t4-test",
        "producer": {"git": "1" * 40, "sources": sources},
        "selected_capability": {"surface": "play"},
        "model_exports_sha256": "b" * 64,
    }
    packet["packet_sha256"] = controller.self_hash(packet, "packet_sha256")
    packet_path = _write_json(tmp_path / "packet.json", packet)
    profile = REVIEW.Profile(
        "test-t4", "1" * 40, REVIEW.sha256(packet_path), "t4-test", 2,
        "T4_RESULT ", "t4-result-review", sources)
    packet_claim = controller.expected_review_claim(
        packet, profile.packet_sha256)
    packet_review = _write_marker(
        tmp_path / "packet-review", controller.REVIEW_MARKER, packet_claim)
    capacity = {
        "schema": controller.CAPACITY_RESULT_SCHEMA,
        "run_id": profile.run_id,
        "git": profile.git,
        "controller_packet_sha256": profile.packet_sha256,
        "capacity_pass": True,
        "score_free": True,
        "outcomes_published": False,
        "screen_max_shard_seconds": 100.0,
    }
    capacity["result_sha256"] = controller.self_hash(
        capacity, "result_sha256")
    capacity_path = _write_json(tmp_path / "capacity.json", capacity)
    capacity_claim = controller.expected_capacity_review_claim(
        packet, profile.packet_sha256, capacity, REVIEW.sha256(capacity_path))
    capacity_review = _write_marker(
        tmp_path / "capacity-review", controller.CAPACITY_REVIEW_MARKER,
        capacity_claim)
    receipt = {
        "schema": controller.RUNTIME_RECEIPT_SCHEMA,
        "run_id": profile.run_id,
        "git": profile.git,
        "controller_packet_sha256": profile.packet_sha256,
        "controller_review_record_sha256": REVIEW.sha256(packet_review),
        "controller_review_claim": packet_claim,
        "capacity_result_sha256": REVIEW.sha256(capacity_path),
        "capacity_review_record_sha256": REVIEW.sha256(capacity_review),
        "capacity_review_claim": capacity_claim,
        "screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    receipt["receipt_sha256"] = controller.self_hash(
        receipt, "receipt_sha256")
    receipt_path = _write_json(tmp_path / "receipt.json", receipt)
    receipt_sha = REVIEW.sha256(receipt_path)

    shard_paths, log_paths, refs = [], [], []
    merged = {label: [] for label in FakeT4Screen.LABELS}
    for index in range(2):
        seed0 = controller.SCREEN_SEED0 + index * controller.CLUSTERS_PER_SHARD
        records = {
            label: [{"seed": seed, "value": 2 if label == "treatment" else 1}
                    for seed in range(seed0, seed0 + 2)]
            for label in FakeT4Screen.LABELS
        }
        shard = {
            "schema": runtime.SHARD_SCHEMA, "run_id": profile.run_id,
            "git": profile.git,
            "controller_packet_sha256": profile.packet_sha256,
            "screen_receipt_sha256": receipt_sha,
            "supervisor_admission_slot": controller.SUPERVISOR_ADMISSION_PATH,
            "supervisor_admission_slot_sha256": "9" * 64,
            "attempt_admission_slot": controller.SHARD_ADMISSION_PATHS[index],
            "attempt_admission_slot_sha256": "8" * 64,
            "shard_index": index, "seed0": seed0, "clusters": 2,
            "records": records,
            "record_counts": {label: 4 for label in FakeT4Screen.LABELS},
            "complete": True,
            "strength_claim": False,
            "confirmation_launch_authorized": False,
            "production_promotion": False, "production_deployment": False,
            "retry_or_extension_authorized": False,
        }
        shard["shard_sha256"] = controller.self_hash(shard, "shard_sha256")
        shard_path = _write_json(tmp_path / f"shard-{index}.json", shard)
        log_path = tmp_path / f"shard-{index}.log"
        log_path.write_text("score-free log\n")
        shard_paths.append(shard_path)
        log_paths.append(log_path)
        refs.append({"index": index,
                     "logical_path": controller.SHARD_PATHS[index],
                     "external_sha256": REVIEW.sha256(shard_path),
                     "internal_sha256": shard["shard_sha256"],
                     "log_logical_path": controller.SHARD_LOG_PATHS[index],
                     "log_sha256": REVIEW.sha256(log_path),
                     "exit_code": 0})
        for label in FakeT4Screen.LABELS:
            merged[label].extend(records[label])
    final = {
        "schema": controller.RUNTIME_SUPERVISOR_FINAL_SCHEMA,
        "run_id": profile.run_id, "git": profile.git,
        "controller_packet_sha256": profile.packet_sha256,
        "controller_review_record_sha256": REVIEW.sha256(packet_review),
        "screen_receipt_sha256": receipt_sha,
        "capacity_result_sha256": REVIEW.sha256(capacity_path),
        "capacity_review_record_sha256": REVIEW.sha256(capacity_review),
        "supervisor_admission_slot": controller.SUPERVISOR_ADMISSION_PATH,
        "supervisor_admission_slot_sha256": "9" * 64,
        "commands": [["child", str(index)] for index in range(2)],
        "shards": refs,
        "shard_manifest_sha256": controller.manifest_hash(refs),
        "elapsed_seconds": 2.0,
        "all_children_exit_zero": True, "outcomes_published": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "confirmation_launch_authorized": False, "strength_claim": False,
        "production_promotion": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    final["final_sha256"] = controller.self_hash(final, "final_sha256")
    final_path = _write_json(tmp_path / "supervisor-final.json", final)
    supervisor_claim = controller.expected_supervisor_review_claim(
        packet, profile.packet_sha256, final, REVIEW.sha256(final_path))
    supervisor_review = _write_marker(
        tmp_path / "supervisor-review", controller.SUPERVISOR_REVIEW_MARKER,
        supervisor_claim)
    admission = runtime._attempt_slot_payload(
        packet=packet, packet_sha256=profile.packet_sha256,
        receipt_sha256=receipt_sha, review_record=packet_review,
        kind="aggregate")
    admission_path = _write_json(tmp_path / "aggregate-admission.json", admission)
    rebuilt = FakeT4Screen.aggregate_screen(
        merged, expected_seed0=controller.SCREEN_SEED0,
        expected_clusters=controller.SCREEN_CLUSTERS,
        expected_surface="play")
    manifest = [{"index": i, "logical_path": controller.SHARD_PATHS[i],
                 "external_sha256": REVIEW.sha256(shard_paths[i]),
                 "internal_sha256": load_json(shard_paths[i])["shard_sha256"]}
                for i in range(2)]
    aggregate = {
        "schema": runtime.AGGREGATE_SCHEMA, "run_id": profile.run_id,
        "git": profile.git,
        "controller_packet_sha256": profile.packet_sha256,
        "screen_receipt_sha256": receipt_sha,
        "supervisor_final_sha256": REVIEW.sha256(final_path),
        "supervisor_final_internal_sha256": final["final_sha256"],
        "supervisor_review_record_sha256": REVIEW.sha256(supervisor_review),
        "supervisor_review_claim": supervisor_claim,
        "aggregate_admission_slot": controller.AGGREGATE_ADMISSION_PATH,
        "aggregate_admission_slot_sha256": REVIEW.sha256(admission_path),
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "shards": manifest, "screen": rebuilt, "decision": rebuilt["status"],
        "confirmation_packet_review_authorized": True,
        "strength_claim": False, "confirmation_launch_authorized": False,
        "production_promotion": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    aggregate["result_sha256"] = controller.self_hash(
        aggregate, "result_sha256")
    aggregate_path = _write_json(tmp_path / "aggregate.json", aggregate)
    args = Namespace(
        packet=packet_path, receipt=receipt_path,
        capacity_result=capacity_path, packet_review_record=packet_review,
        capacity_review_record=capacity_review, supervisor_final=final_path,
        supervisor_review_record=supervisor_review,
        aggregate_admission=admission_path, aggregate=aggregate_path,
        shards=shard_paths, logs=log_paths)
    return args, api, profile


def load_json(path: Path):
    return json.loads(path.read_text())


def test_t4_review_is_read_only_and_reconstructs_statistics(tmp_path):
    args, api, profile = _t4_fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    claim = REVIEW._t4_review(args, api, profile)
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert before == after
    assert claim["decision"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert claim["recursive_statistic_reconstruction"] is True


def test_t4_rehashed_statistic_mutation_refuses(tmp_path):
    args, api, profile = _t4_fixture(tmp_path)
    aggregate = load_json(args.aggregate)
    aggregate["screen"]["stats"]["treatment_champion"]["mean"] = 99
    aggregate["result_sha256"] = api.controller.self_hash(
        aggregate, "result_sha256")
    _write_json(args.aggregate, aggregate)
    with pytest.raises(REVIEW.ReviewRefused, match="reconstruction drift"):
        REVIEW._t4_review(args, api, profile)


class FakePairScreen:
    PACKET_SCHEMA = "pair-packet"
    PACKET_REVIEW_PREFIX = "PAIR_PACKET_REVIEW "
    RECEIPT_SCHEMA = "pair-receipt"
    SUPERVISOR_SCHEMA = "pair-supervisor"
    SUPERVISOR_REVIEW_PREFIX = "PAIR_SUPERVISOR_REVIEW "
    SCREEN_CLUSTERS = 4
    CLUSTERS_PER_SHARD = 2
    REPO = Path("/repo")
    EXECUTION_ADMISSION_PATH = REPO / "execution-slot"
    SHARD_PATHS = (REPO / "shard-0", REPO / "shard-1")
    SHARD_LOG_PATHS = (REPO / "log-0", REPO / "log-1")

    stable_digest = staticmethod(lambda value: REVIEW.stable_digest(value))

    @staticmethod
    def packet_review_claim(packet, packet_sha):
        return {"schema": "pair-packet-review", "packet": packet_sha,
                "verdict": "PASS"}

    @staticmethod
    def supervisor_review_claim(packet, packet_sha, receipt_sha, final,
                                final_sha):
        return {"schema": "pair-supervisor-review", "packet": packet_sha,
                "receipt": receipt_sha, "final": final_sha,
                "verdict": "PASS"}

    @classmethod
    def validate_shard(cls, shard, *, packet, packet_sha256,
                       receipt_sha256, shard_index):
        unsigned = dict(shard)
        observed = unsigned.pop("internal_sha256")
        if (observed != cls.stable_digest(unsigned)
                or shard["index"] != shard_index
                or shard["packet"] != packet_sha256
                or shard["receipt"] != receipt_sha256):
            raise RuntimeError("pair shard drift")

    @classmethod
    def aggregate_payload(cls, *, packet, packet_sha256, receipt_sha256,
                          shard_values, shard_sha256s,
                          supervisor_final_sha256, supervisor_review):
        values = [value for shard in shard_values for value in shard["values"]]
        mean = sum(values) / len(values)
        result = {
            "schema": "pair-aggregate", "run_id": packet["run_id"],
            "git": packet["git"], "packet_sha256": packet_sha256,
            "receipt_sha256": receipt_sha256,
            "supervisor_final_sha256": supervisor_final_sha256,
            "supervisor_review_record_sha256": supervisor_review["sha256"],
            "supervisor_review_marker": supervisor_review["marker"],
            "clusters": cls.SCREEN_CLUSTERS, "shards": len(shard_values),
            "shard_sha256s": shard_sha256s,
            "primary_level_utility": {"treatment_minus_champion": {
                "mean": mean}},
            "secondary_game_win_rate": {"treatment_minus_champion": {
                "mean": mean / 2}},
            "natural_dose": {"changes": len(values)},
            "integrity": {"all_shards_exact_work": True},
            "status": "PASS_SCREEN", "screen_passed": True,
            "confirmation_packet_design_authorized": True,
            "confirmation_execution_authorized": False,
            "strength_claim": False, "production_promotion": False,
            "production_deployment": False,
            "retry_or_extension_authorized": False,
        }
        result["internal_sha256"] = cls.stable_digest(result)
        return result


def _pair_fixture(tmp_path: Path):
    screen = FakePairScreen
    sources = {"source": "d" * 64}
    packet = {"schema": screen.PACKET_SCHEMA, "run_id": "pair-test",
              "git": "2" * 40, "source_sha256s": sources}
    packet["internal_sha256"] = screen.stable_digest(packet)
    packet_path = _write_json(tmp_path / "packet.json", packet)
    profile = REVIEW.Profile(
        "test-pair", packet["git"], REVIEW.sha256(packet_path),
        packet["run_id"], 2, "PAIR_RESULT ", "pair-result-review", sources)
    packet_claim = screen.packet_review_claim(packet, profile.packet_sha256)
    packet_review = _write_marker(
        tmp_path / "packet-review", screen.PACKET_REVIEW_PREFIX, packet_claim)
    receipt = {
        "schema": screen.RECEIPT_SCHEMA, "run_id": profile.run_id,
        "git": profile.git, "packet_sha256": profile.packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_record_sha256": REVIEW.sha256(packet_review),
        "packet_review_marker": packet_review.read_text().strip(),
        "execution_admission_path": "execution-slot",
        "execution_admission_sha256": "a" * 64,
        "nonce": "b" * 64, "created_time_ns": 1,
        "one_screen_execution_authorized": True,
        "aggregate_execution_authorized": False, "strength_claim": False,
        "production_deployment": False, "retry_or_extension_authorized": False,
    }
    receipt["internal_sha256"] = screen.stable_digest(receipt)
    receipt_path = _write_json(tmp_path / "receipt.json", receipt)
    receipt_sha = REVIEW.sha256(receipt_path)
    shards, logs, refs = [], [], []
    for index in range(2):
        shard = {"index": index, "packet": profile.packet_sha256,
                 "receipt": receipt_sha, "values": [index + 1, index + 2]}
        shard["internal_sha256"] = screen.stable_digest(shard)
        path = _write_json(tmp_path / f"shard-{index}.json", shard)
        log = tmp_path / f"log-{index}"
        log.write_text("score-free\n")
        shards.append(path)
        logs.append(log)
        refs.append({"index": index,
                     "path": str(screen.SHARD_PATHS[index].relative_to(
                         screen.REPO)), "sha256": REVIEW.sha256(path),
                     "clusters": 2,
                     "log_path": str(screen.SHARD_LOG_PATHS[index].relative_to(
                         screen.REPO)), "log_sha256": REVIEW.sha256(log)})
    final = {
        "schema": screen.SUPERVISOR_SCHEMA, "run_id": profile.run_id,
        "git": profile.git, "packet_sha256": profile.packet_sha256,
        "receipt_sha256": receipt_sha,
        "supervisor_admission_sha256": "c" * 64,
        "elapsed_seconds": 2.0, "shards": refs,
        "all_shards_complete": True, "outcomes_published": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False, "strength_claim": False,
        "production_deployment": False, "retry_or_extension_authorized": False,
    }
    final["internal_sha256"] = screen.stable_digest(final)
    final_path = _write_json(tmp_path / "final.json", final)
    supervisor_claim = screen.supervisor_review_claim(
        packet, profile.packet_sha256, receipt_sha, final,
        REVIEW.sha256(final_path))
    supervisor_review = _write_marker(
        tmp_path / "supervisor-review", screen.SUPERVISOR_REVIEW_PREFIX,
        supervisor_claim)
    supervisor_evidence = {
        "sha256": REVIEW.sha256(supervisor_review),
        "marker": supervisor_review.read_text().strip(),
        "claim": supervisor_claim,
    }
    admission = {
        "schema": "pair-aware-rollout-screen-aggregate-admission-v1",
        "run_id": profile.run_id, "git": profile.git,
        "packet_sha256": profile.packet_sha256, "nonce": "f" * 64,
        "created_time_ns": 2, "retry_or_extension_authorized": False,
        "production_deployment": False, "receipt_sha256": receipt_sha,
        "supervisor_review_record_sha256": REVIEW.sha256(supervisor_review),
    }
    admission["internal_sha256"] = screen.stable_digest(admission)
    admission_path = _write_json(tmp_path / "aggregate-admission.json", admission)
    aggregate = screen.aggregate_payload(
        packet=packet, packet_sha256=profile.packet_sha256,
        receipt_sha256=receipt_sha,
        shard_values=[load_json(path) for path in shards],
        shard_sha256s=[REVIEW.sha256(path) for path in shards],
        supervisor_final_sha256=REVIEW.sha256(final_path),
        supervisor_review=supervisor_evidence)
    aggregate["aggregate_admission_sha256"] = REVIEW.sha256(admission_path)
    aggregate.pop("internal_sha256")
    aggregate["internal_sha256"] = screen.stable_digest(aggregate)
    aggregate_path = _write_json(tmp_path / "aggregate.json", aggregate)
    args = Namespace(
        packet=packet_path, packet_review_record=packet_review,
        receipt=receipt_path, supervisor_final=final_path,
        supervisor_review_record=supervisor_review,
        aggregate_admission=admission_path, aggregate=aggregate_path,
        shards=shards, logs=logs)
    return args, SimpleNamespace(screen=screen), profile


def test_pair_review_is_read_only_and_reconstructs_statistics(tmp_path):
    args, api, profile = _pair_fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    claim = REVIEW._pair_review(args, api, profile)
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert before == after
    assert claim["decision"] == "PASS_SCREEN"
    assert claim["recursive_statistic_reconstruction"] is True


def test_pair_rehashed_statistic_mutation_refuses(tmp_path):
    args, api, profile = _pair_fixture(tmp_path)
    aggregate = load_json(args.aggregate)
    aggregate["primary_level_utility"]["treatment_minus_champion"][
        "mean"] = 99
    aggregate["internal_sha256"] = api.screen.stable_digest({
        key: value for key, value in aggregate.items()
        if key != "internal_sha256"})
    _write_json(args.aggregate, aggregate)
    with pytest.raises(REVIEW.ReviewRefused, match="reconstruction drift"):
        REVIEW._pair_review(args, api, profile)


def test_duplicate_review_marker_refuses(tmp_path):
    args, api, profile = _pair_fixture(tmp_path)
    args.supervisor_review_record.write_text(
        args.supervisor_review_record.read_text() * 2)
    with pytest.raises(REVIEW.ReviewRefused, match="exactly one"):
        REVIEW._pair_review(args, api, profile)


def test_aggregate_binding_refuses_before_any_shard_payload_open(tmp_path):
    args, api, profile = _pair_fixture(tmp_path)
    aggregate = load_json(args.aggregate)
    aggregate["supervisor_final_sha256"] = "0" * 64
    aggregate["internal_sha256"] = api.screen.stable_digest({
        key: value for key, value in aggregate.items()
        if key != "internal_sha256"})
    _write_json(args.aggregate, aggregate)
    # If the ordering regresses, this malformed shard would fail first.
    args.shards[0].write_text("not JSON\n")
    with pytest.raises(REVIEW.ReviewRefused,
                       match="aggregate pre-open binding drift"):
        REVIEW._pair_review(args, api, profile)


def test_aggregate_admission_payload_is_not_shape_only(tmp_path):
    args, api, profile = _pair_fixture(tmp_path)
    admission = load_json(args.aggregate_admission)
    admission["supervisor_review_record_sha256"] = "0" * 64
    admission["internal_sha256"] = api.screen.stable_digest({
        key: value for key, value in admission.items()
        if key != "internal_sha256"})
    _write_json(args.aggregate_admission, admission)
    aggregate = load_json(args.aggregate)
    aggregate["aggregate_admission_sha256"] = REVIEW.sha256(
        args.aggregate_admission)
    aggregate["internal_sha256"] = api.screen.stable_digest({
        key: value for key, value in aggregate.items()
        if key != "internal_sha256"})
    _write_json(args.aggregate, aggregate)
    with pytest.raises(REVIEW.ReviewRefused,
                       match="aggregate admission binding drift"):
        REVIEW._pair_review(args, api, profile)
