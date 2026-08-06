"""Adversarial contract tests for the conditional S0 deployment choice."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_deployment_choice as S0E  # noqa: E402


def counters(*, searches=1, accepted=30):
    values = {field: 0 for field in S0E.COUNTER_FIELDS}
    values.update({
        "rollouts": accepted,
        "searches": searches,
        "search_secs": 0.01,
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
    })
    return values


def record(label, seed=1, flip=0, utility=1, *, run="run", source=None):
    candidate = label in {"adaptive", "report_lcb"}
    row = {
        "run": run,
        "label": label,
        "policy": S0E.LABELS[label],
        "seed": seed,
        "flip": flip,
        "won": int(utility > 0),
        "level_utility": utility,
        "arm": counters(accepted=330 if candidate else 30),
        "opp": counters(),
    }
    if source is not None:
        row["_source"] = str(source)
    return row


def effect(mean, half=0.1):
    return {"mean": mean, "half_width_95": half, "clusters": 16_384}


def decision_stats(*, adaptive=0.05, adaptive_null=0.05,
                   report=0.05, report_null=0.05,
                   adaptive_report=0.0, null=0.0, null_half=0.1):
    return {
        "adaptive-current": effect(adaptive),
        "adaptive-current_null": effect(adaptive_null),
        "report_lcb-current": effect(report),
        "report_lcb-current_null": effect(report_null),
        "adaptive-report_lcb": effect(adaptive_report),
        "current_null-current": effect(null, null_half),
    }


def test_registered_geometry_and_live_policy_contracts_are_exact():
    assert S0E.SHARD_COUNT == 8
    assert S0E.TOTAL_CLUSTERS == 16_384
    assert S0E.CLUSTERS_PER_SHARD == 2_048
    assert S0E.SEED0 == 147_000_000
    assert S0E.SEED_HI == 147_016_383
    assert S0E.protocol_problems() == []


def test_preoutcome_lock_freezes_full_runner_source_policy_and_runtime():
    lock = S0E.load_parent_lock()
    receipt = S0E.load_freeze_receipt()
    assert lock["authorized"] is False
    assert lock["terminal_state"] is None
    assert lock["decision"] is None
    assert lock["packet_sha256"] is None
    assert lock["closeout_sha256"] is None
    assert lock["s0c_aggregate_sha256"] is None
    assert lock["freeze_receipt_sha256"] == \
        S0E.sha256(S0E.FREEZE_RECEIPT_PATH)
    assert receipt["frozen_protocol_sha256"] == S0E.sha256(S0E.__file__)
    assert receipt["frozen_source_sha256s"] == S0E.current_source_sha256s()
    assert receipt["frozen_policy_contract_sha256s"] == \
        S0E.policy_contract_sha256s()
    assert receipt["selection_digest"] == S0E.selection_digest()
    assert receipt["python"] == "3.14.6"
    assert receipt["execution_host"] == "Jerrys-Mac-mini.local"
    assert receipt["execution_root"] == str(S0E.SERVER.resolve())
    assert S0E.is_sha256(receipt["fast_binary_sha256"])


@pytest.mark.parametrize(
    ("policy", "field", "value", "problem"),
    [
        ("mc-s0-report-lcb", "REPORT_T_CRITICAL", 1.69,
         "report_lcb: report t-critical drifted"),
        ("mc-s0-adaptive", "CONFIDENCE_Z", 1.63,
         "adaptive: allocation confidence z drifted"),
    ],
)
def test_frozen_selection_constants_are_mutation_falsified(
        policy, field, value, problem, monkeypatch):
    cls = type(S0E.make_bot(policy, seed=7))
    monkeypatch.setattr(cls, field, value)
    problems = S0E.protocol_problems()
    assert problem in problems
    assert "full frozen policy-contract digests drifted" in problems


def test_transitive_source_map_mutation_is_falsified(monkeypatch):
    sources = S0E.current_source_sha256s()
    sources["engine_legal"] = "0" * 64
    monkeypatch.setattr(S0E, "current_source_sha256s", lambda: sources)
    assert "pre-outcome transitive source identity drifted" in \
        S0E.protocol_problems()


def test_source_and_receipt_codrift_still_fails_git_anchor(
        tmp_path, monkeypatch):
    original_bytes = S0E.FREEZE_RECEIPT_PATH.read_bytes()
    receipt = S0E.load_freeze_receipt()
    receipt["frozen_protocol_sha256"] = "0" * 64
    receipt["frozen_source_sha256s"] = dict(
        receipt["frozen_source_sha256s"])
    receipt["frozen_source_sha256s"]["runner"] = "0" * 64
    receipt["frozen_source_sha256s"]["ai_heuristic"] = "1" * 64
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    monkeypatch.setattr(S0E, "FREEZE_RECEIPT_PATH", path)
    monkeypatch.setattr(S0E, "git_file_commits", lambda _path: ["intro"])
    monkeypatch.setattr(
        S0E, "git_blob", lambda _commit, _path: original_bytes)
    assert S0E.immutable_freeze_problems() == [
        "immutable freeze receipt bytes differ from Git introduction"]


def test_policy_and_receipt_codrift_still_fails_git_anchor(
        tmp_path, monkeypatch):
    original_bytes = S0E.FREEZE_RECEIPT_PATH.read_bytes()
    receipt = S0E.load_freeze_receipt()
    receipt["frozen_policy_contract_sha256s"] = {
        name: "2" * 64 for name in receipt["frozen_policy_contract_sha256s"]
    }
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    monkeypatch.setattr(S0E, "FREEZE_RECEIPT_PATH", path)
    monkeypatch.setattr(S0E, "git_file_commits", lambda _path: ["intro"])
    monkeypatch.setattr(
        S0E, "git_blob", lambda _commit, _path: original_bytes)
    assert S0E.immutable_freeze_problems() == [
        "immutable freeze receipt bytes differ from Git introduction"]


def test_parent_lock_allows_only_one_committed_terminal_transition(
        tmp_path, monkeypatch):
    initial = {
        "schema": S0E.PARENT_LOCK_SCHEMA,
        "authorized": False,
        "terminal_state": None,
        "decision": None,
        "packet_sha256": None,
        "closeout_sha256": None,
        "s0c_aggregate_sha256": None,
        "freeze_receipt_sha256": "a" * 64,
        "binding_rule": "fixed",
    }
    terminal = dict(initial)
    terminal.update({
        "terminal_state": "S0_COMPLETE_SELECT_NONE",
        "decision": "SELECT NONE; production remains mc-strong",
        "packet_sha256": "b" * 64,
        "closeout_sha256": "c" * 64,
        "s0c_aggregate_sha256": "d" * 64,
    })
    path = tmp_path / "parent.json"
    path.write_text(json.dumps(terminal, sort_keys=True) + "\n")
    monkeypatch.setattr(S0E, "PARENT_LOCK_PATH", path)
    monkeypatch.setattr(
        S0E, "git_blob",
        lambda _commit, _path: (json.dumps(initial, sort_keys=True) + "\n").encode(),
    )

    monkeypatch.setattr(S0E, "git_file_commits", lambda _path: ["intro"])
    assert "uncommitted parent-lock transition is not admissible" in \
        S0E.parent_transition_problems(terminal)

    monkeypatch.setattr(
        S0E, "git_file_commits", lambda _path: ["terminal", "intro"])
    assert S0E.parent_transition_problems(terminal) == []

    monkeypatch.setattr(
        S0E, "git_file_commits",
        lambda _path: ["rewrite", "terminal", "intro"],
    )
    assert any("more than one terminal transition" in problem for problem in
               S0E.parent_transition_problems(terminal))


def test_geometry_mutation_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(S0E, "TOTAL_CLUSTERS", 8_192)
    assert "registered shard geometry/147M seed block drifted" in \
        S0E.protocol_problems()


def test_frozen_clean_commit_may_aggregate_after_origin_advances(monkeypatch):
    head = "a" * 40

    def fake_git(*args):
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return head
        raise AssertionError(args)

    monkeypatch.setattr(S0E, "git", fake_git)
    monkeypatch.setattr(S0E, "git_is_ancestor", lambda a, b: (a, b) == (
        head, "origin/main"))
    assert S0E.require_clean_pushed_head() == head

    monkeypatch.setattr(S0E, "git_is_ancestor", lambda *_: False)
    with pytest.raises(S0E.ProtocolRefused, match="not published"):
        S0E.require_clean_pushed_head()


@pytest.mark.parametrize("flag", S0E.SAMPLER_FLAGS)
def test_even_empty_experimental_flag_is_refused(flag, monkeypatch):
    for name in S0E.SAMPLER_FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv(flag, "")
    with pytest.raises(S0E.ProtocolRefused, match="must be unset"):
        S0E.require_runtime()


def test_deployment_truth_table_is_complete_and_uses_lcbs():
    criteria = S0E.gate_criteria(decision_stats())
    assert criteria["adaptive_eligible"] is False
    assert criteria["report_lcb_eligible"] is False
    assert S0E.deployment_decision(criteria) == ("KEEP_CURRENT", None)

    criteria = S0E.gate_criteria(decision_stats(
        adaptive=0.3, adaptive_null=0.3))
    assert S0E.deployment_decision(criteria) == (
        "ADAPTIVE_FOR_DEPLOYMENT_REVIEW", "mc-s0-adaptive")

    criteria = S0E.gate_criteria(decision_stats(
        report=0.3, report_null=0.3))
    assert S0E.deployment_decision(criteria) == (
        "REPORT_LCB_FOR_DEPLOYMENT_REVIEW", "mc-s0-report-lcb")

    # Both qualify, but a positive adaptive point estimate is not enough.  Its
    # paired lower bound must clear zero or simplicity breaks the tie.
    criteria = S0E.gate_criteria(decision_stats(
        adaptive=0.3, adaptive_null=0.3,
        report=0.3, report_null=0.3, adaptive_report=0.05))
    assert criteria["adaptive_report_lcb_lcb_gt_0"] is False
    assert S0E.deployment_decision(criteria) == (
        "REPORT_LCB_FOR_DEPLOYMENT_REVIEW", "mc-s0-report-lcb")

    criteria = S0E.gate_criteria(decision_stats(
        adaptive=0.3, adaptive_null=0.3,
        report=0.3, report_null=0.3, adaptive_report=0.3))
    assert S0E.deployment_decision(criteria) == (
        "ADAPTIVE_FOR_DEPLOYMENT_REVIEW", "mc-s0-adaptive")


def test_bad_null_refuses_instead_of_selecting_a_favourable_arm():
    criteria = S0E.gate_criteria(decision_stats(
        adaptive=0.5, adaptive_null=0.5,
        report=0.5, report_null=0.5,
        adaptive_report=0.5, null=0.3, null_half=0.1))
    assert criteria["current_null_interval_contains_0"] is False
    assert S0E.deployment_decision(criteria) == (
        "REFUSE_NULL_CALIBRATION", None)


def test_wrong_population_size_refuses_as_invalid_evidence():
    stats = decision_stats(
        adaptive=0.5, adaptive_null=0.5,
        report=0.5, report_null=0.5, adaptive_report=0.5)
    stats["adaptive-current"]["clusters"] -= 1
    criteria = S0E.gate_criteria(stats)
    assert criteria["exact_registered_clusters"] is False
    assert S0E.deployment_decision(criteria) == (
        "REFUSE_INVALID_EVIDENCE", None)


def _write_terminal_parent(tmp_path, monkeypatch, *,
                           decision="PROMOTE mc-s0-adaptive",
                           state="S0_COMPLETE_PROMOTE",
                           packet_names_aggregate=True,
                           aggregate_pass=True,
                           authorize=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        S0E.S0_CLOSEOUT, "packet_phases",
        lambda _text: list(S0E.EXPECTED_S0_PHASES))
    monkeypatch.setattr(S0E.S0_CLOSEOUT, "packet_problems", lambda *_: [])
    aggregate_path = tmp_path / "s0c-adaptive-lcb-v1.aggregate.json"
    aggregate = {
        "schema": "s0-mechanism-aggregate-v1",
        "phase": "s0c-adaptive-lcb",
        "promotion": True,
        "clusters": 8_192,
        "seed0": 135_000_000,
        "seed_hi": 135_008_191,
        "survivor_label": "arm",
        "survivor_policy": "mc-s0-adaptive",
        "criteria": {"all": aggregate_pass},
        "git_sha": S0E.EXPECTED_S0_GIT_SHA,
        "runtime_identity": {"host": "mini"},
        "record_counts": {
            "arm": 16_384, "null": 16_384, "reference": 16_384},
        "stats": {
            name: {"clusters": 8_192}
            for name in ("arm-reference", "arm-null", "null-reference")
        },
        "parent": {
            "phase": "s0b-lcb",
            "survivor_policy": "mc-s0-adaptive",
            "sha256": "e" * 64,
        },
    }
    aggregate_path.write_text(json.dumps(aggregate) + "\n")
    aggregate_sha = S0E.sha256(aggregate_path)
    named_sha = aggregate_sha if packet_names_aggregate else "0" * 64
    packet_path = tmp_path / "s0-terminal.packet.txt"
    packet_path.write_text(
        "s0c-adaptive-lcb aggregate: runs/logs/x "
        f"sha256={named_sha} survivor='mc-s0-adaptive' promotion=True\n"
        f"Final production decision from registered rule: {decision}\n"
    )
    packet_sha = S0E.sha256(packet_path)
    closeout_path = tmp_path / "s0-terminal.closeout.json"
    closeout_path.write_text(json.dumps({
        "schema": "s0-terminal-closeout-v1",
        "state": state,
        "packet_sha256": packet_sha,
        "phases": list(S0E.EXPECTED_S0_PHASES),
    }) + "\n")
    closeout_sha = S0E.sha256(closeout_path)
    freeze_path = tmp_path / "s0_deployment_choice_freeze.v1.json"
    freeze_path.write_text("{\"schema\": \"test-freeze\"}\n")
    monkeypatch.setattr(S0E, "FREEZE_RECEIPT_PATH", freeze_path)
    if not authorize:
        lock_state = None
        lock_decision = None
        lock_hashes = (None, None, None)
        lock_authorized = False
    else:
        lock_state = state
        lock_decision = decision
        lock_hashes = (packet_sha, closeout_sha, aggregate_sha)
        lock_authorized = state == "S0_COMPLETE_PROMOTE"
    lock_path = tmp_path / "s0_deployment_choice_parent.v1.json"
    lock_path.write_text(json.dumps({
        "schema": S0E.PARENT_LOCK_SCHEMA,
        "authorized": lock_authorized,
        "terminal_state": lock_state,
        "decision": lock_decision,
        "packet_sha256": lock_hashes[0],
        "closeout_sha256": lock_hashes[1],
        "s0c_aggregate_sha256": lock_hashes[2],
        "freeze_receipt_sha256": S0E.sha256(freeze_path),
        "binding_rule": (
            "Bind exact terminal hashes regardless of PASS/FAIL; authorize "
            "only exact PROMOTE mc-s0-adaptive; SELECT NONE remains locked"
        ),
    }, sort_keys=True) + "\n")
    monkeypatch.setattr(S0E, "PARENT_LOCK_PATH", lock_path)
    return {
        "packet_path": packet_path,
        "packet_sha": packet_sha,
        "closeout_path": closeout_path,
        "closeout_sha": closeout_sha,
        "aggregate_path": aggregate_path,
        "aggregate_sha": aggregate_sha,
        "lock_path": lock_path,
    }


def _load_parent(paths):
    return S0E.load_s0_parent(
        paths["packet_path"], paths["packet_sha"],
        paths["closeout_path"], paths["closeout_sha"],
        paths["aggregate_path"], paths["aggregate_sha"],
    )


def test_parent_gate_binds_packet_closeout_and_promoted_s0c(
        tmp_path, monkeypatch):
    paths = _write_terminal_parent(tmp_path, monkeypatch)
    parent = _load_parent(paths)
    assert parent["terminal_state"] == "S0_COMPLETE_PROMOTE"
    assert parent["champion_policy"] == "mc-s0-adaptive"
    assert parent["s0c_aggregate_sha256"] == paths["aggregate_sha"]


def test_caller_hashes_are_not_parent_authority(tmp_path, monkeypatch):
    paths = _write_terminal_parent(
        tmp_path, monkeypatch, authorize=False)
    with pytest.raises(S0E.ProtocolRefused, match="hash lock is not authorized"):
        _load_parent(paths)

    paths = _write_terminal_parent(
        tmp_path / "mismatch", monkeypatch)
    lock = json.loads(paths["lock_path"].read_text())
    lock["packet_sha256"] = "f" * 64
    paths["lock_path"].write_text(json.dumps(lock, sort_keys=True) + "\n")
    with pytest.raises(S0E.ProtocolRefused, match="differ from the frozen"):
        _load_parent(paths)


def test_parent_gate_cannot_rescue_select_none(tmp_path, monkeypatch):
    paths = _write_terminal_parent(
        tmp_path, monkeypatch,
        decision="SELECT NONE; production remains mc-strong",
        state="S0_COMPLETE_SELECT_NONE")
    with pytest.raises(S0E.ProtocolRefused, match="not authorized"):
        _load_parent(paths)


def test_parent_gate_rejects_unbound_or_failed_s0c(tmp_path, monkeypatch):
    unbound = _write_terminal_parent(
        tmp_path / "unbound", monkeypatch, packet_names_aggregate=False)
    with pytest.raises(S0E.ProtocolRefused, match="not bound"):
        _load_parent(unbound)

    failed_dir = tmp_path / "failed"
    failed_dir.mkdir()
    failed = _write_terminal_parent(
        failed_dir, monkeypatch, aggregate_pass=False)
    with pytest.raises(S0E.ProtocolRefused, match="aggregate drift"):
        _load_parent(failed)


def test_record_gate_refuses_shortened_or_failed_work():
    rows = {
        label: [record(label)] for label in S0E.LABELS
    }
    assert S0E.record_problems(rows) == []

    short = copy.deepcopy(rows)
    short["current"][0]["arm"]["accepted_worlds"] = 29
    short["current"][0]["arm"]["sample_attempts"] = 29
    assert "current/arm: plain N=30 accepted dose differs" in \
        S0E.record_problems(short)

    failed = copy.deepcopy(rows)
    failed["adaptive"][0]["arm"]["failed_worlds"] = 1
    failed["adaptive"][0]["arm"]["sample_attempts"] = 331
    assert "adaptive/arm: nonzero failed_worlds" in \
        S0E.record_problems(failed)

    valid_large = copy.deepcopy(rows)
    valid_large["report_lcb"][0]["level_utility"] = 4
    assert "report_lcb: malformed outcome record" not in \
        S0E.record_problems(valid_large)

    malformed = copy.deepcopy(rows)
    malformed["report_lcb"][0]["level_utility"] = 0
    assert "report_lcb: malformed outcome record" in \
        S0E.record_problems(malformed)

    missing_report = copy.deepcopy(rows)
    missing_report["report_lcb"][0]["arm"]["accepted_worlds"] = 30
    missing_report["report_lcb"][0]["arm"]["sample_attempts"] = 30
    assert "report_lcb/arm: fixed selection+report accepted dose differs" in \
        S0E.record_problems(missing_report)

    short_adaptive = copy.deepcopy(rows)
    short_adaptive["adaptive"][0]["arm"]["accepted_worlds"] = 329
    short_adaptive["adaptive"][0]["arm"]["sample_attempts"] = 329
    assert "adaptive/arm: adaptive accepted fewer than base+report dose" in \
        S0E.record_problems(short_adaptive)

    expected = {(1, 0), (1, 1)}
    problems = S0E.record_problems(rows, expected)
    assert all(f"{label}: exact seed/flip coverage differs" in problems
               for label in S0E.LABELS)

    missing = dict(rows)
    missing.pop("current_null")
    assert S0E.record_problems(missing) == [
        "record labels differ from frozen labels"]


def _tiny_population(tmp_path, monkeypatch):
    monkeypatch.setattr(S0E, "SHARD_COUNT", 1)
    monkeypatch.setattr(S0E, "TOTAL_CLUSTERS", 2)
    monkeypatch.setattr(S0E, "CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(S0E, "SEED0", 1)
    monkeypatch.setattr(S0E, "SEED_HI", 2)
    monkeypatch.setattr(S0E, "RUN_DIR", tmp_path)
    monkeypatch.setattr(S0E, "AGGREGATE_PATH", tmp_path / "aggregate.json")
    monkeypatch.setattr(S0E, "protocol_problems", lambda: [])
    runtime = {
        "host": "test", "python": "test", "fast_engine": True,
        "require_voids": True, "experimental_sampler_flags": [],
        "digests": {"runner": "a" * 64, "fast_binary": "b" * 64},
    }
    parent = {"packet_sha256": "c" * 64}
    head = "d" * 40
    run_id = f"{S0E.SCHEMA}_shard00_{head[:10]}"
    record_path = (tmp_path / "shard00.jsonl").resolve()
    manifest_path = Path(str(record_path) + ".manifest.json")
    rows = {
        label: [
            record(label, seed, flip, run=run_id, source=record_path)
            for seed in (1, 2) for flip in (0, 1)
        ]
        for label in S0E.LABELS
    }
    with record_path.open("w") as fh:
        for label in S0E.LABELS:
            for row in rows[label]:
                stored = dict(row)
                stored.pop("_source")
                fh.write(json.dumps(stored) + "\n")
    policies = sorted(set(S0E.LABELS.values()))
    manifest = {
        "schema": S0E.SCHEMA,
        "claim": S0E.CLAIM,
        "claim_boundary": S0E.CLAIM_BOUNDARY,
        "complete": True,
        "promotable": True,
        "problems": [],
        "production_promotion": False,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "score_blind_progress": True,
        "shard_statistics_persisted": False,
        "git_sha": head,
        "tree_dirty": False,
        "runtime_identity": runtime,
        "shard_index": 0,
        "shard_count": 1,
        "total_clusters": 2,
        "clusters": 2,
        "seed0": 1,
        "seed_hi": 2,
        "opponent": S0E.OPPONENT,
        "labels": S0E.LABELS,
        "selection_rule": S0E.SELECTION_RULE,
        "selection_digest": S0E.selection_digest(),
        "s0_parent": parent,
        "policy_contracts": {
            name: S0E.policy_contract(name) for name in policies},
        "ballots": S0E.arm_ballots(policies),
        "run_id": run_id,
        "record_counts": {label: len(value) for label, value in rows.items()},
        "counter_totals": S0E.counter_totals(rows),
        "records_sha256": S0E.sha256(record_path),
    }
    manifest_path.write_text(json.dumps(manifest) + "\n")
    return runtime, parent, head, record_path, manifest_path, rows, manifest


def test_population_gate_recomputes_exact_local_and_global_coverage(
        tmp_path, monkeypatch):
    runtime, parent, head, _, manifest_path, rows, manifest = \
        _tiny_population(tmp_path, monkeypatch)
    assert S0E.validate_population(
        [(manifest_path, manifest)], rows, runtime, head, parent) == []
    rows["adaptive"][0]["seed"] = 99
    problems = S0E.validate_population(
        [(manifest_path, manifest)], rows, runtime, head, parent)
    assert any("local shard coverage" in problem for problem in problems)
    assert "adaptive: exact seed/flip coverage differs" in problems


def test_aggregate_reopening_recomputes_raw_and_detects_mutation(
        tmp_path, monkeypatch):
    runtime, parent, head, record_path, manifest_path, rows, manifest = \
        _tiny_population(tmp_path, monkeypatch)
    stats = S0E.all_contrasts(rows)
    criteria = S0E.gate_criteria(stats)
    decision, candidate = S0E.deployment_decision(criteria)
    policies = sorted(set(S0E.LABELS.values()))
    aggregate_path = tmp_path / "aggregate.json"
    payload = {
        "schema": S0E.AGGREGATE_SCHEMA,
        "claim": S0E.CLAIM,
        "complete": True,
        "git_sha": head,
        "runtime_identity": runtime,
        "clusters": 2,
        "seed0": 1,
        "seed_hi": 2,
        "shard_count": 1,
        "labels": S0E.LABELS,
        "opponent": S0E.OPPONENT,
        "selection_rule": S0E.SELECTION_RULE,
        "selection_digest": S0E.selection_digest(),
        "s0_parent": parent,
        "policy_contracts": {
            name: S0E.policy_contract(name) for name in policies},
        "ballots": S0E.arm_ballots(policies),
        "input_shards": [{
            "shard_index": 0,
            "manifest_path": manifest_path.name,
            "manifest_sha256": S0E.sha256(manifest_path),
            "records_path": record_path.name,
            "records_sha256": manifest["records_sha256"],
        }],
        "record_counts": {label: len(value) for label, value in rows.items()},
        "counter_totals": S0E.counter_totals(rows),
        "stats": stats,
        "criteria": criteria,
        "decision": decision,
        "deployment_review_candidate": candidate,
        "production_promotion": False,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "claim_boundary": S0E.CLAIM_BOUNDARY,
    }
    aggregate_path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    aggregate_sha = S0E.sha256(aggregate_path)
    reopened = S0E.reopen_aggregate(
        aggregate_path, aggregate_sha, runtime, head, parent)
    assert reopened["decision"] == "KEEP_CURRENT"

    with record_path.open("a") as fh:
        fh.write("\n")
    with pytest.raises(S0E.ProtocolRefused, match="input digest mismatch"):
        S0E.reopen_aggregate(
            aggregate_path, aggregate_sha, runtime, head, parent)


def test_shard_stdout_is_score_blind(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(S0E, "CLUSTERS_PER_SHARD", 2)
    monkeypatch.setattr(S0E, "require_runtime", lambda: (None, {"test": True}))
    monkeypatch.setattr(S0E, "require_clean_pushed_head", lambda: "f" * 40)
    monkeypatch.setattr(S0E, "protocol_problems", lambda: [])
    monkeypatch.setattr(S0E, "_parent_from_args", lambda _args: {"parent": True})
    monkeypatch.setattr(S0E, "RUN_DIR", tmp_path)
    monkeypatch.setattr(S0E, "AGGREGATE_PATH", tmp_path / "aggregate.json")

    progress_score_args = []

    def fake_run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
                     progress_scores=True):
        progress_score_args.append(progress_scores)
        result = []
        for seed in range(seed0, seed0 + clusters):
            for flip in (0, 1):
                row = record(label, seed, flip, run=run_id)
                result.append(row)
                fh.write(json.dumps(row) + "\n")
        return result

    monkeypatch.setattr(S0E, "run_arm", fake_run_arm)
    out = S0E.canonical_record_path(0)
    S0E.run_shard(SimpleNamespace(shard_index=0))
    stdout = capsys.readouterr().out
    assert progress_score_args == [False] * len(S0E.LABELS)
    assert "+/-" not in stdout
    assert "rounds," not in stdout
    assert " vs " not in stdout
    assert json.loads(Path(str(out) + ".manifest.json").read_text())["complete"]


def test_canonical_namespace_refuses_alternate_outputs_and_retries(
        tmp_path, monkeypatch):
    monkeypatch.setattr(S0E, "SHARD_COUNT", 2)
    monkeypatch.setattr(S0E, "RUN_DIR", tmp_path)
    monkeypatch.setattr(S0E, "AGGREGATE_PATH", tmp_path / "aggregate.json")
    assert S0E.canonical_namespace_problems("run", 0) == []

    alternate = tmp_path / "chosen-after-looking.jsonl.manifest.json"
    alternate.write_text("{}\n")
    problems = S0E.canonical_namespace_problems("run", 0)
    assert any("contains unknown" in problem for problem in problems)
    alternate.unlink()

    partial = Path(str(S0E.canonical_record_path(0)) + ".partial")
    partial.write_text("started\n")
    problems = S0E.canonical_namespace_problems("run", 0)
    assert any("already attempted" in problem for problem in problems)
    partial.unlink()

    failed = Path(str(S0E.canonical_record_path(1)) + ".FAILED")
    failed.write_text("failed\n")
    problems = S0E.canonical_namespace_problems("run", 0)
    assert any("contains failed shard" in problem for problem in problems)


def test_aggregate_requires_exact_canonical_finals_and_zero_residue(
        tmp_path, monkeypatch):
    monkeypatch.setattr(S0E, "SHARD_COUNT", 2)
    monkeypatch.setattr(S0E, "RUN_DIR", tmp_path)
    monkeypatch.setattr(S0E, "AGGREGATE_PATH", tmp_path / "aggregate.json")
    for index in range(2):
        S0E.canonical_record_path(index).write_text("records\n")
        S0E.canonical_manifest_path(index).write_text("{}\n")
    assert S0E.canonical_namespace_problems("aggregate") == []

    residue = Path(str(S0E.canonical_manifest_path(1)) + ".partial")
    residue.write_text("partial\n")
    assert any("partial residue" in problem for problem in
               S0E.canonical_namespace_problems("aggregate"))


def test_stable_selection_rule_digest_is_nonempty():
    # A lightweight receipt used by launch documentation after the code-freeze
    # commit; changing any branch or prose changes this value.
    digest = S0E.selection_digest()
    assert digest == \
        "02f07f1c190368c109f7f02cdcf62e45b1367e7e92383a9ff8f4ca4ec2dfa81a"
