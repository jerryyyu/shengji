"""Falsification tests for the pre-outcome S0c lag-17 repair."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_dependency_audit as AUDIT  # noqa: E402


def stat(mean: float, half: float = 0.1, clusters: int = 4_096) -> dict:
    return {"mean": mean, "half_width_95": half, "clusters": clusters}


def passing_stats() -> dict:
    return {
        "arm-reference": stat(0.3),
        "arm-null": stat(0.3),
        "null-reference": stat(0.0),
    }


def test_registered_lag_graph_is_exact_and_exhaustive():
    assert AUDIT.NULL_OFFSET == 999_983
    assert AUDIT.OPPONENT_OFFSETS == (1_000_000, 1_500_000)
    assert AUDIT.DEPENDENCY_LAG == 17
    seeds = set(range(AUDIT.SEED0, AUDIT.SEED_HI + 1))
    witness = AUDIT.stream_witness(seeds)
    assert witness["cross_seed_collision_count"] == 2 * (8_192 - 17)
    pairs = {
        tuple(values)
        for values in witness["cross_seed_collisions"].values()
    }
    assert pairs == {
        (seed, seed + 17)
        for seed in range(AUDIT.SEED0, AUDIT.SEED_HI - 16)
    }


def test_global_chain_colours_are_exact_disjoint_and_collision_free():
    seeds = set(range(AUDIT.SEED0, AUDIT.SEED_HI + 1))
    parts = [
        {seed for seed in seeds if AUDIT.chain_colour(seed) == colour}
        for colour in (0, 1)
    ]
    assert [len(part) for part in parts] == [4_097, 4_095]
    assert parts[0].isdisjoint(parts[1])
    assert parts[0] | parts[1] == seeds
    assert [AUDIT.stream_witness(part)["cross_seed_collision_count"]
            for part in parts] == [0, 0]


def test_resetting_parity_at_shard_boundaries_is_falsified():
    seeds = set(range(AUDIT.SEED0, AUDIT.SEED_HI + 1))

    def wrong_colour(seed: int) -> int:
        local = (seed - AUDIT.SEED0) % (AUDIT.CLUSTERS // 8)
        return (local // AUDIT.DEPENDENCY_LAG) % 2

    wrong_parts = [
        {seed for seed in seeds if wrong_colour(seed) == colour}
        for colour in (0, 1)
    ]
    assert any(AUDIT.stream_witness(part)["cross_seed_collision_count"]
               for part in wrong_parts)


def test_each_colour_requires_both_strength_lcbs_and_two_sided_null():
    criteria = AUDIT.criteria(passing_stats())
    assert criteria == {
        "arm_reference_lcb_gt_0": True,
        "arm_null_lcb_gt_0": True,
        "null_reference_interval_contains_0": True,
        "all": True,
    }

    weak = passing_stats()
    weak["arm-null"] = stat(0.05)
    assert AUDIT.criteria(weak)["all"] is False

    positive_null = passing_stats()
    positive_null["null-reference"] = stat(0.2)
    assert AUDIT.criteria(positive_null)["all"] is False

    # The old one-sided rule would accept a significantly negative null. The
    # repair deliberately refuses it because it can make arm-null look easy.
    negative_null = passing_stats()
    negative_null["null-reference"] = stat(-0.2)
    assert AUDIT.criteria(negative_null)["all"] is False


def test_both_colours_must_pass_and_select_none_cannot_be_rescued():
    colours = {
        "0": {"criteria": AUDIT.criteria(passing_stats())},
        "1": {"criteria": AUDIT.criteria(passing_stats())},
    }
    assert AUDIT.corrected_decision(True, colours) == (
        True, "S0_COMPLETE_PROMOTE", "PROMOTE mc-s0-adaptive")
    assert AUDIT.corrected_decision(False, colours) == (
        True, "S0_COMPLETE_SELECT_NONE",
        "SELECT NONE; production remains mc-strong")

    failed = copy.deepcopy(colours)
    failed["1"]["criteria"]["arm_null_lcb_gt_0"] = False
    failed["1"]["criteria"]["all"] = False
    assert AUDIT.corrected_decision(True, failed) == (
        False, "S0_COMPLETE_SELECT_NONE",
        "SELECT NONE; production remains mc-strong")


def test_selection_rule_forbids_pooling_extension_and_fallback():
    rule = AUDIT.SELECTION_RULE
    assert "both collision-free colours" in rule
    assert "No retry" in rule
    assert "extension" in rule
    assert "report-policy fallback" in rule
    assert "8,192" not in rule or "full-population" not in rule


def counters(*, searches: int, accepted: int, rollouts: int) -> dict:
    return {
        "rollouts": rollouts,
        "searches": searches,
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "short_searches": 0,
        "zero_world": 0,
        "void_fallbacks": 0,
    }


def test_exact_candidate_rollout_arithmetic_is_enforced():
    # Two searches, candidate counts 2 and 14: 30*(2+14) selection
    # rollouts plus 600 report rollouts per search.
    report = counters(searches=2, accepted=660, rollouts=1_680)
    assert AUDIT.counter_problems("arm", "arm", report) == []

    adaptive_extra_worlds = copy.deepcopy(report)
    adaptive_extra_worlds["accepted_worlds"] = 700
    adaptive_extra_worlds["sample_attempts"] = 700
    assert AUDIT.counter_problems(
        "arm", "arm", adaptive_extra_worlds) == []

    fake = copy.deepcopy(report)
    fake["rollouts"] = 1
    problems = AUDIT.counter_problems("arm", "arm", fake)
    assert any("fewer than two candidates" in problem for problem in problems)
    assert any("rollout arithmetic" in problem for problem in problems)

    extra_report = copy.deepcopy(report)
    extra_report["accepted_worlds"] = 661
    extra_report["sample_attempts"] = 661
    # Adaptive sampling may use more selection worlds, so accepted worlds can
    # exceed 330/search. Rollouts, not accepted draws, prove exact work.
    assert AUDIT.counter_problems("arm", "arm", extra_report) == []

    plain = counters(searches=2, accepted=60, rollouts=480)
    assert AUDIT.counter_problems("null", "arm", plain) == []
    too_many_plain_worlds = copy.deepcopy(plain)
    too_many_plain_worlds["accepted_worlds"] += 1
    too_many_plain_worlds["sample_attempts"] += 1
    assert any("plain accepted dose differs" in problem for problem in
               AUDIT.counter_problems("null", "arm", too_many_plain_worlds))


def test_score_blind_seal_detects_same_size_seed_permutation(
        monkeypatch, tmp_path):
    """A post-seal color-changing seed edit cannot preserve authority."""
    monkeypatch.setattr(AUDIT, "EVIDENCE_SERVER", tmp_path)
    raw = tmp_path / "records.jsonl"
    raw.write_text('{"seed":135000000}\n{"seed":135000017}\n')
    monkeypatch.setattr(AUDIT, "canonical_input_paths", lambda: (raw,))
    inputs = AUDIT.snapshot_inputs([raw])
    seal = {"inputs": inputs}
    assert AUDIT.read_sealed_inputs(seal)["records.jsonl"] == raw.read_bytes()

    # Swap equal-width IDs across opposite chain colors. Coverage and whole-
    # population statistics could remain unchanged, but the sealed bytes may
    # not be reinterpreted under the predeclared color split.
    raw.write_text('{"seed":135000017}\n{"seed":135000000}\n')
    with pytest.raises(AUDIT.AuditRefused, match="digest/size drift"):
        AUDIT.read_sealed_inputs(seal)


def test_single_fd_reader_refuses_symlink_and_path_replacement(
        monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"sealed-original")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(AUDIT.AuditRefused, match="unreadable"):
        AUDIT.read_regular_bytes(link)

    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"changed-content")
    displaced = tmp_path / "displaced"
    real_read = AUDIT.os.read
    swapped = False

    def replacing_read(descriptor, size):
        nonlocal swapped
        value = real_read(descriptor, size)
        if not swapped:
            swapped = True
            target.rename(displaced)
            replacement.rename(target)
        return value

    monkeypatch.setattr(AUDIT.os, "read", replacing_read)
    with pytest.raises(AUDIT.AuditRefused, match="pathname changed"):
        AUDIT.read_regular_bytes(target)


def test_attempt_receipt_is_direct_durable_and_nonretryable(tmp_path):
    path = tmp_path / "attempt.json"
    AUDIT.write_attempt(path, {"schema": "test", "outcomes_parsed": False})
    assert json.loads(path.read_text())["outcomes_parsed"] is False
    assert not Path(str(path) + ".partial").exists()
    with pytest.raises(AUDIT.AuditRefused, match="already exists"):
        AUDIT.write_attempt(path, {"schema": "changed"})


def test_seal_attempt_precedes_all_content_hashing(monkeypatch, tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    raw = evidence / "raw.jsonl"
    raw.write_text('{"seed":1}\n')
    freeze = tmp_path / "freeze.json"
    freeze.write_text("{}\n")
    monkeypatch.setattr(AUDIT, "EVIDENCE_SERVER", evidence)
    monkeypatch.setattr(AUDIT, "FREEZE_PATH", freeze)
    monkeypatch.setattr(AUDIT, "SEAL", evidence / "seal.json")
    monkeypatch.setattr(AUDIT, "SEAL_ATTEMPT", evidence / "seal.attempt.json")
    monkeypatch.setattr(AUDIT, "EVALUATE_ATTEMPT", evidence / "eval.attempt.json")
    monkeypatch.setattr(AUDIT, "OUTPUT", evidence / "decision.json")
    monkeypatch.setattr(AUDIT, "canonical_input_paths", lambda: (raw,))
    monkeypatch.setattr(AUDIT, "require_runtime", lambda: "a" * 40)
    original_snapshot = AUDIT.snapshot_inputs
    calls = []

    def guarded_snapshot(paths):
        assert AUDIT.SEAL_ATTEMPT.is_file()
        calls.append("hash")
        return original_snapshot(paths)

    monkeypatch.setattr(AUDIT, "snapshot_inputs", guarded_snapshot)
    seal = AUDIT.seal_inputs()
    assert calls == ["hash", "hash"]
    assert seal["outcomes_parsed"] is False
    assert AUDIT.SEAL.is_file()
    assert AUDIT.load_and_verify_seal("a" * 40) == seal

    contaminated = json.loads(AUDIT.SEAL.read_text())
    contaminated["observed_mean"] = 1.0
    AUDIT.SEAL.write_text(json.dumps(contaminated) + "\n")
    with pytest.raises(AUDIT.AuditRefused, match="fields drifted"):
        AUDIT.load_and_verify_seal("a" * 40)


def test_evaluation_attempt_precedes_decoding(monkeypatch, tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    seal_path = evidence / "seal.json"
    seal_path.write_text("{}\n")
    seal_attempt = evidence / "seal.attempt.json"
    seal_attempt.write_text("{}\n")
    eval_attempt = evidence / "eval.attempt.json"
    output = evidence / "decision.json"
    freeze = tmp_path / "freeze.json"
    freeze.write_text("{}\n")
    monkeypatch.setattr(AUDIT, "SEAL", seal_path)
    monkeypatch.setattr(AUDIT, "SEAL_ATTEMPT", seal_attempt)
    monkeypatch.setattr(AUDIT, "EVALUATE_ATTEMPT", eval_attempt)
    monkeypatch.setattr(AUDIT, "OUTPUT", output)
    monkeypatch.setattr(AUDIT, "FREEZE_PATH", freeze)
    monkeypatch.setattr(AUDIT, "require_runtime", lambda: "b" * 40)
    monkeypatch.setattr(AUDIT, "canonical_input_paths", lambda: ())

    def load_seal(_head, expected_sha256=None):
        assert expected_sha256 == AUDIT.sha256(seal_path)
        assert eval_attempt.is_file()
        return {"inputs": {}, "input_set_sha256": AUDIT.stable_digest({})}

    def verify(_blobs):
        assert eval_attempt.is_file()
        return ({"state": "S0_COMPLETE_SELECT_NONE",
                 "packet_sha256": "c" * 64}, "packet", "d" * 64)

    monkeypatch.setattr(AUDIT, "load_and_verify_seal", load_seal)
    monkeypatch.setattr(AUDIT, "read_sealed_inputs", lambda _seal: {})
    monkeypatch.setattr(AUDIT, "verify_original_terminal", verify)
    monkeypatch.setattr(
        AUDIT, "run", lambda *_args: {"complete": True, "final": "none"})
    assert AUDIT.evaluate() == {"complete": True, "final": "none"}
    assert output.is_file()


def test_canonical_seal_set_is_exact_and_includes_raw_records():
    paths = AUDIT.canonical_input_paths()
    assert len(paths) == 18
    assert paths[:2] == (AUDIT.PACKET, AUDIT.AGGREGATE)
    assert paths[2:] == tuple(
        path for index in range(8)
        for path in (AUDIT.manifest_path(index), AUDIT.record_path(index)))


def test_counter_totals_reopen_every_registered_field():
    row = {
        side: {field: index + 1
               for index, field in enumerate(AUDIT.COUNTER_FIELDS)}
        for side in ("arm", "opp")
    }
    totals = AUDIT.counter_totals({"arm": [row, copy.deepcopy(row)]})
    assert set(totals["arm"]["arm"]) == set(AUDIT.COUNTER_FIELDS)
    assert totals["arm"]["arm"]["rollouts"] == 2
    assert totals["arm"]["opp"]["void_fallbacks"] == \
        2 * (AUDIT.COUNTER_FIELDS.index("void_fallbacks") + 1)


def _tiny_raw_blobs(monkeypatch, tmp_path):
    monkeypatch.setattr(AUDIT, "EVIDENCE_SERVER", tmp_path)
    monkeypatch.setattr(AUDIT, "LOGS", tmp_path / "runs" / "logs")
    monkeypatch.setattr(AUDIT, "SHARDS", 1)
    monkeypatch.setattr(AUDIT, "CLUSTERS", 2)
    monkeypatch.setattr(AUDIT, "CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(AUDIT, "SEED_HI", AUDIT.SEED0 + 1)
    monkeypatch.setattr(AUDIT, "AGGREGATE", AUDIT.LOGS / "aggregate.json")
    monkeypatch.setattr(AUDIT, "SEAL", tmp_path / "seal.json")
    monkeypatch.setattr(AUDIT, "EVALUATE_ATTEMPT", tmp_path / "eval.json")
    AUDIT.SEAL.write_text("{}\n")
    AUDIT.EVALUATE_ATTEMPT.write_text("{}\n")
    run_id = f"s0-protocol-v2_{AUDIT.PHASE}_shard00_{AUDIT.SHORT_SHA}"
    utility = {"arm": 2, "null": -1, "reference": -2}
    records = {label: [] for label in AUDIT.LABELS}
    rows = []
    for label, policy in AUDIT.LABELS.items():
        for seed in range(AUDIT.SEED0, AUDIT.SEED0 + 2):
            for flip in (0, 1):
                arm = (counters(searches=1, accepted=330, rollouts=660)
                       if label == "arm" else
                       counters(searches=1, accepted=30, rollouts=60))
                row = {
                    "run": run_id, "label": label, "policy": policy,
                    "seed": seed, "flip": flip,
                    "won": int(utility[label] > 0),
                    "level_utility": utility[label],
                    "arm": arm,
                    "opp": counters(searches=1, accepted=30, rollouts=60),
                }
                rows.append(row)
                records[label].append(row)
    paired_stats = {}
    for label in AUDIT.LABELS:
        value = AUDIT.paired(records, label, "reference")
        paired_stats[label] = {
            key: item for key, item in value.items() if key not in {"a", "b"}
        }
    manifest = {
        "schema": "s0-protocol-v2", "phase": AUDIT.PHASE,
        "run_id": run_id, "git_sha": AUDIT.GIT_SHA,
        "host": AUDIT.EXPECTED_RUNTIME["host"],
        "python": AUDIT.EXPECTED_RUNTIME["python"],
        "fast_engine": True, "require_voids": True,
        "digests": AUDIT.EXPECTED_RUNTIME["digests"],
        "complete": True, "promotable": True, "problems": [],
        "tree_dirty": False, "dirty_files": [], "shard_count": 1,
        "total_clusters": 2, "clusters": 2, "shard_index": 0,
        "seed0": AUDIT.SEED0, "seed_hi": AUDIT.SEED0 + 1,
        "opponent": "mc-strong", "labels": AUDIT.LABELS,
        "kind": "confirmation", "report_worlds": 300,
        "paired_vs_reference": paired_stats,
    }
    mpath = AUDIT.manifest_path(0)
    rpath = AUDIT.record_path(0)
    return {
        AUDIT.input_key(mpath): json.dumps(manifest).encode(),
        AUDIT.input_key(rpath): (
            "\n".join(json.dumps(row) for row in rows) + "\n").encode(),
    }, mpath, rpath


def test_raw_reopening_falsifies_local_stats_coverage_and_result_signs(
        monkeypatch, tmp_path):
    blobs, mpath, rpath = _tiny_raw_blobs(monkeypatch, tmp_path)
    manifests, records, _ = AUDIT.load_raw(blobs)
    assert len(manifests) == 1
    assert all(len(rows) == 4 for rows in records.values())

    bad_stats = dict(blobs)
    manifest = json.loads(bad_stats[AUDIT.input_key(mpath)])
    manifest["paired_vs_reference"]["arm"]["mean"] += 1
    bad_stats[AUDIT.input_key(mpath)] = json.dumps(manifest).encode()
    with pytest.raises(AUDIT.AuditRefused, match="manifest statistics"):
        AUDIT.load_raw(bad_stats)

    bad_sign = dict(blobs)
    rows = [json.loads(line) for line in
            bad_sign[AUDIT.input_key(rpath)].decode().splitlines()]
    rows[0]["won"] = 0
    bad_sign[AUDIT.input_key(rpath)] = (
        "\n".join(json.dumps(row) for row in rows) + "\n").encode()
    with pytest.raises(AUDIT.AuditRefused, match="sign disagreement"):
        AUDIT.load_raw(bad_sign)

    zero_utility = dict(blobs)
    rows = [json.loads(line) for line in
            zero_utility[AUDIT.input_key(rpath)].decode().splitlines()]
    rows[0]["level_utility"] = 0
    zero_utility[AUDIT.input_key(rpath)] = (
        "\n".join(json.dumps(row) for row in rows) + "\n").encode()
    with pytest.raises(AUDIT.AuditRefused, match="malformed utility"):
        AUDIT.load_raw(zero_utility)

    noninteger_utility = dict(blobs)
    rows = [json.loads(line) for line in
            noninteger_utility[AUDIT.input_key(rpath)].decode().splitlines()]
    rows[0]["level_utility"] = 1.0
    noninteger_utility[AUDIT.input_key(rpath)] = (
        "\n".join(json.dumps(row) for row in rows) + "\n").encode()
    with pytest.raises(AUDIT.AuditRefused, match="malformed utility"):
        AUDIT.load_raw(noninteger_utility)

    bad_coverage = dict(blobs)
    rows = [json.loads(line) for line in
            bad_coverage[AUDIT.input_key(rpath)].decode().splitlines()]
    rows[0]["seed"] = AUDIT.SEED0 + 1
    bad_coverage[AUDIT.input_key(rpath)] = (
        "\n".join(json.dumps(row) for row in rows) + "\n").encode()
    with pytest.raises(AUDIT.AuditRefused, match="local coverage"):
        AUDIT.load_raw(bad_coverage)


def test_promote_run_rejects_reopened_stats_and_aggregate_counter_mutants(
        monkeypatch, tmp_path):
    blobs, _, _ = _tiny_raw_blobs(monkeypatch, tmp_path)
    _, records, _ = AUDIT.load_raw(blobs)
    aggregate = {
        "schema": "s0-mechanism-aggregate-v1", "phase": AUDIT.PHASE,
        "clusters": AUDIT.CLUSTERS, "seed0": AUDIT.SEED0,
        "seed_hi": AUDIT.SEED_HI, "git_sha": AUDIT.GIT_SHA,
        "record_counts": {
            label: 2 * AUDIT.CLUSTERS for label in AUDIT.LABELS},
        "runtime_identity": AUDIT.EXPECTED_RUNTIME,
        "hosts": [AUDIT.EXPECTED_RUNTIME["host"]],
        "survivor_label": "arm", "survivor_policy": "mc-s0-adaptive",
        "promotion": True, "criteria": {"all": True},
        "stats": AUDIT.all_stats(records),
        "counter_totals": AUDIT.counter_totals(records),
    }
    terminal = {
        "state": "S0_COMPLETE_PROMOTE", "packet_sha256": "a" * 64}
    packet = "Final production decision from registered rule: PROMOTE mc-s0-adaptive\n"
    seal = {"input_set_sha256": "b" * 64}

    bad_stats = copy.deepcopy(aggregate)
    bad_stats["stats"]["arm-reference"]["mean"] += 1
    blobs[AUDIT.input_key(AUDIT.AGGREGATE)] = json.dumps(bad_stats).encode()
    with pytest.raises(AUDIT.AuditRefused, match="stats differ"):
        AUDIT.run("c" * 40, seal, blobs, terminal, packet, "d" * 64)

    bad_counters = copy.deepcopy(aggregate)
    bad_counters["counter_totals"]["arm"]["arm"]["rollouts"] += 30
    blobs[AUDIT.input_key(AUDIT.AGGREGATE)] = json.dumps(bad_counters).encode()
    with pytest.raises(AUDIT.AuditRefused, match="counters differ"):
        AUDIT.run("c" * 40, seal, blobs, terminal, packet, "d" * 64)


def test_terminal_verifier_binds_packet_aggregate_and_all_eight_manifests(
        monkeypatch):
    aggregate = b"sealed aggregate bytes\n"
    manifest_bytes = {
        index: f"sealed manifest {index}\n".encode() for index in range(8)
    }
    aggregate_hash = AUDIT.sha256_bytes(aggregate)
    manifest_line = "; ".join(
        f"{AUDIT.manifest_path(index).relative_to(AUDIT.EVIDENCE_SERVER)} "
        f"sha256={AUDIT.sha256_bytes(manifest_bytes[index])}"
        for index in range(8)
    )
    packet = (
        f"{AUDIT.PHASE} aggregate: runs/logs/aggregate.json "
        f"sha256={aggregate_hash}\n"
        f"{AUDIT.PHASE} manifests (8/8): {manifest_line}\n"
    ).encode()
    blobs = {
        AUDIT.input_key(AUDIT.PACKET): packet,
        AUDIT.input_key(AUDIT.AGGREGATE): aggregate,
        **{
            AUDIT.input_key(AUDIT.manifest_path(index)): manifest_bytes[index]
            for index in range(8)
        },
    }

    def verified(*_args, **_kwargs):
        return {
            "state": "S0_COMPLETE_PROMOTE",
            "packet_sha256": AUDIT.sha256_bytes(packet),
            "phases": ["s0a", "s0b-lcb", AUDIT.PHASE],
        }

    monkeypatch.setattr(
        AUDIT.CLOSEOUT, "verify_terminal_packet", verified)
    terminal, text, observed_hash = AUDIT.verify_original_terminal(blobs)
    assert terminal["state"] == "S0_COMPLETE_PROMOTE"
    assert text == packet.decode()
    assert observed_hash == aggregate_hash

    bad_aggregate = dict(blobs)
    bad_aggregate[AUDIT.input_key(AUDIT.AGGREGATE)] += b"mutant"
    with pytest.raises(AUDIT.AuditRefused, match="aggregate digest"):
        AUDIT.verify_original_terminal(bad_aggregate)

    bad_manifest = dict(blobs)
    bad_manifest[AUDIT.input_key(AUDIT.manifest_path(7))] += b"mutant"
    with pytest.raises(AUDIT.AuditRefused, match="manifest 7"):
        AUDIT.verify_original_terminal(bad_manifest)


def test_original_select_none_emits_minimal_artifact_without_color_analysis(
        monkeypatch, tmp_path):
    seal_path = tmp_path / "seal.json"
    seal_path.write_text("{}\n")
    attempt = tmp_path / "attempt.json"
    attempt.write_text("{}\n")
    monkeypatch.setattr(AUDIT, "SEAL", seal_path)
    monkeypatch.setattr(AUDIT, "EVALUATE_ATTEMPT", attempt)
    monkeypatch.setattr(
        AUDIT, "load_raw",
        lambda _blobs: (_ for _ in ()).throw(AssertionError("raw parsed")),
    )
    result = AUDIT.run(
        "e" * 40,
        {"input_set_sha256": "f" * 64},
        {},
        {"state": "S0_COMPLETE_SELECT_NONE", "packet_sha256": "a" * 64},
        "ignored",
        "b" * 64,
    )
    assert result["final_state"] == "S0_COMPLETE_SELECT_NONE"
    assert result["promotion_admissible"] is False
    assert result["raw_reopened"] is False
    assert result["colours_analyzed"] is False
    assert "colours" not in result


def test_freeze_is_preterminal_outcome_blind_and_matches_script():
    freeze = AUDIT.load_freeze()
    assert freeze["script_sha256"] == AUDIT.sha256(AUDIT.__file__)
    assert freeze["selection_digest"] == \
        AUDIT.stable_digest(AUDIT.SELECTION_RULE)
    assert freeze["python"] == "3.14.6"
    assert freeze["evidence_root"] == str(AUDIT.EVIDENCE_SERVER)
    assert freeze["audit_root"] == str(AUDIT.AUDIT_SERVER)
    assert not any("mean" in key or "effect" in key for key in freeze)
    assert AUDIT.freeze_problems() == []
