"""Synthetic, byte-bound tests for auditing the pre-binding rollout witness.

The fixture below is produced by the real mirror, policy, and benchmark
transport seams.  Its row deliberately has the old source shape: the modern
rollout diagnostics and response bindings are removed after capture.  This is
synthetic evidence for the validator contract, not historical authentication.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random

import pytest

from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.luna.benchmark_games import play_mirror
from shengji.luna.benchmark_transport import BenchmarkTransport
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.transport import InvocationResult
from test_benchmark_rollout_proof import RUNTIME
from test_luna_transport import trace


SOURCE_COMMIT = "c53ec3bc2852ce4eefa22173dc88777fdb914e94"


def _legacy_fixture(tmp_path: Path) -> dict:
    """Produce the interleaved failed mirror and old-shape byte evidence."""
    call_ordinals = {1: 0, 3: 0}

    def run_command(command, prompt, workspace, timeout):
        # BenchmarkTransport's prompt is a fixed instruction line followed by
        # the canonical packet.  Read that actual prompt, rather than
        # reconstructing a packet in the test.
        packet = json.loads(prompt.split(b"\n", 1)[1])
        seat = packet["observation"]["seat"]
        ordinal = call_ordinals[seat]
        call_ordinals[seat] += 1
        candidates = packet["suggested_actions"]
        candidate = next(cards for cards in candidates if cards)
        legal = {"cards": list(candidate), "continuation": "heuristic-all"}

        if seat == 1 and ordinal == 0:
            evaluations = [dict(legal) for _ in range(4)]
        elif seat == 3 and ordinal == 0:
            evaluations = [dict(legal) for _ in range(3)]
        elif seat == 1 and ordinal == 2:
            evaluations = [dict(legal) for _ in range(16)]
        elif seat == 1 and ordinal == 3:
            evaluations = ([dict(legal), dict(legal),
                            {"cards": [], "continuation": "heuristic-all"}]
                           + [dict(legal) for _ in range(4)])
        else:
            # The second call of each completed decision is the final action.
            evaluations = None

        final = ({"cards": None, "evaluations": evaluations, "memory": ""}
                 if evaluations is not None else
                 {"cards": list(candidate), "evaluations": None, "memory": ""})
        final_bytes = json.dumps(final, indent=2).encode() + b"\n"
        (workspace / "final.json").write_bytes(final_bytes)
        return InvocationResult(0, trace(final), b"", 1)

    def planner_factory(seat):
        transport = BenchmarkTransport(
            evidence_root=tmp_path / f"seat-{seat}", codex_binary="/usr/bin/true",
            runtime_attestor=lambda _: dict(RUNTIME), run_command=run_command)
        return transport

    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    row = play_mirror(
        game, flip=1, information="perfect", planner_factory=planner_factory,
        baseline_factory=lambda seat, seed: HeuristicBot(), seed=733)

    # play_mirror flattens each planner's calls by planner, so this is not the
    # chronological stream.  The packet bytes retain the actual chronology.
    assert row["rollout_usage"] == {
        "requested_batches": 4, "attempted_evaluations": 26,
        "completed_evaluations": 25, "completed_world_rollouts": 25}
    assert row["error"].startswith("IllegalPlay:")
    assert len(row["events"]) == 5
    assert len(row["calls"]) == 6

    old_row = copy.deepcopy(row)
    old_row.update(
        schema="w32-llm-benchmark-mirror-v1",
        key="sol-perfect-seed733-flip1",
        arm="sol-perfect", model="sol")
    old_row.pop("rollout_diagnostic", None)
    old_row.pop("rollout_request_binding", None)
    for call in old_row["calls"]:
        call.pop("response_binding", None)

    evidence = {}
    call_pins = {}
    for call in old_row["calls"]:
        path = call["evidence_path"]
        prompt_bytes = (Path(path) / "prompt.txt").read_bytes()
        final_bytes = (Path(path) / "final.json").read_bytes()
        evidence[path] = {"prompt_bytes": prompt_bytes,
                          "final_bytes": final_bytes}
        call_pins[path] = {
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "final_sha256": hashlib.sha256(final_bytes).hexdigest(),
        }

    row_bytes = canonical_json_bytes(old_row)
    pins = {
        "schema": "benchmark-legacy-evidence-pins-v1",
        "source_commit": SOURCE_COMMIT,
        "row_sha256": hashlib.sha256(row_bytes).hexdigest(),
        "calls": call_pins,
    }
    return {"row": old_row, "row_bytes": row_bytes,
            "evidence": evidence, "pins": pins}


def _audit(fixture):
    from shengji.luna.benchmark_legacy_evidence import audit_legacy_rollout_failure

    return audit_legacy_rollout_failure(
        fixture["row_bytes"], evidence=fixture["evidence"], pins=fixture["pins"])


def _repin_row(fixture):
    fixture["row_bytes"] = canonical_json_bytes(fixture["row"])
    fixture["pins"]["row_sha256"] = hashlib.sha256(
        fixture["row_bytes"]).hexdigest()


def _repin_final(fixture, path, final_bytes):
    fixture["evidence"][path]["final_bytes"] = final_bytes
    fixture["pins"]["calls"][path]["final_sha256"] = hashlib.sha256(
        final_bytes).hexdigest()


def _failed_call(fixture):
    # The old row is grouped by planner: seat 1's fourth call is the failed
    # second rollout batch, even though seat 3 ran between seat 1 decisions.
    return next(call for call in fixture["row"]["calls"]
                if call["attempt"] == 1 and
                json.loads(fixture["evidence"][call["evidence_path"]][
                    "prompt_bytes"].split(b"\n", 1)[1])["observation"]["seat"] == 1
                and len(json.loads(fixture["evidence"][call["evidence_path"]][
                    "prompt_bytes"].split(b"\n", 1)[1])["rollout_results"]) == 16)


def test_actual_chain_passes_without_mutating_grouped_legacy_evidence(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    before = copy.deepcopy(fixture)
    audit = _audit(fixture)

    assert audit["schema"] == "benchmark-legacy-rollout-audit-v1"
    assert audit["seat"] == 1
    assert audit["request_index"] == 1
    assert audit["evaluation_index"] == 2
    assert audit["prior_completed_evaluations"] == 23
    assert audit["decision_local_completed_evaluations"] == 16
    assert audit["completed_play_events"] == len(fixture["row"]["events"])
    assert audit["candidate_cards"] == []
    # The validator consumes immutable bytes and does not rewrite source,
    # pins, or captured provider evidence.
    assert fixture == before
    assert [json.loads(fixture["evidence"][call["evidence_path"]][
        "prompt_bytes"].split(b"\n", 1)[1])["observation"]["seat"]
        for call in fixture["row"]["calls"]] == [1, 1, 1, 1, 3, 3]


@pytest.mark.parametrize("mutation", [
    lambda f: f.update(row_bytes=f["row_bytes"] + b" "),
    lambda f: f["pins"]["calls"][next(iter(f["evidence"]))].update(
        prompt_sha256="0" * 64),
    lambda f: f["evidence"].pop(next(iter(f["evidence"]))),
    lambda f: f["evidence"].update(
        extra={"prompt_bytes": b"x", "final_bytes": b"x"}),
])
def test_row_hash_prompt_hash_and_evidence_set_drift_refuse(
        tmp_path, mutation):
    fixture = _legacy_fixture(tmp_path)
    mutation(fixture)
    with pytest.raises(ValueError):
        _audit(fixture)


def test_wrong_source_pin_refuses(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    fixture["pins"]["source_commit"] = "0" * 40
    with pytest.raises(ValueError):
        _audit(fixture)


@pytest.mark.parametrize("counter", [
    "requested_batches", "attempted_evaluations", "completed_evaluations",
])
def test_counter_drift_refuses_after_row_repin(tmp_path, counter):
    fixture = _legacy_fixture(tmp_path)
    fixture["row"]["rollout_usage"][counter] += 1
    _repin_row(fixture)
    with pytest.raises(ValueError):
        _audit(fixture)


def test_duplicate_accepted_call_receipt_refuses(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    fixture["row"]["calls"].append(copy.deepcopy(fixture["row"]["calls"][0]))
    _repin_row(fixture)
    with pytest.raises(ValueError):
        _audit(fixture)


@pytest.mark.parametrize("binding", ["row", "call"])
def test_modern_bindings_in_old_source_shape_refuse(tmp_path, binding):
    fixture = _legacy_fixture(tmp_path)
    if binding == "row":
        fixture["row"]["rollout_diagnostic"] = {"schema": "modern"}
    else:
        fixture["row"]["calls"][0]["response_binding"] = {"schema": "modern"}
    _repin_row(fixture)
    with pytest.raises(ValueError):
        _audit(fixture)


def test_final_action_instead_of_rollout_request_refuses(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    call = _failed_call(fixture)
    path = call["evidence_path"]
    original = json.loads(fixture["evidence"][path]["final_bytes"])
    final_bytes = json.dumps(
        {"cards": original["evaluations"][0]["cards"],
         "evaluations": None, "memory": ""}, indent=2).encode() + b"\n"
    _repin_final(fixture, path, final_bytes)
    with pytest.raises(ValueError):
        _audit(fixture)


def test_rebound_selected_legal_candidate_is_not_a_rejection(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    call = _failed_call(fixture)
    path = call["evidence_path"]
    final = json.loads(fixture["evidence"][path]["final_bytes"])
    legal_cards = final["evaluations"][0]["cards"]
    final["evaluations"][2] = {
        "cards": list(legal_cards), "continuation": "heuristic-all"}
    final_bytes = json.dumps(final, indent=2).encode() + b"\n"
    _repin_final(fixture, path, final_bytes)
    with pytest.raises(ValueError, match="candidate"):
        _audit(fixture)


@pytest.mark.parametrize("terminal", [False, True])
def test_unknown_historical_continuation_refuses_even_with_rebound_pins(tmp_path, terminal):
    fixture = _legacy_fixture(tmp_path)
    path = (_failed_call(fixture) if terminal else fixture["row"]["calls"][0])["evidence_path"]
    final = json.loads(fixture["evidence"][path]["final_bytes"])
    final["evaluations"][2 if terminal else 0]["continuation"] = "unknown-policy"
    _repin_final(fixture, path, canonical_json_bytes(final))
    with pytest.raises(ValueError, match="invalid evaluation"):
        _audit(fixture)


@pytest.mark.parametrize("error", [None, "TimeoutError: observation expired", 1])
def test_terminal_error_must_corroborate_rejection(tmp_path, error):
    fixture = _legacy_fixture(tmp_path)
    if error is None:
        fixture["row"].pop("error")
    else:
        fixture["row"]["error"] = error
    _repin_row(fixture)
    with pytest.raises(ValueError, match="terminal error"):
        _audit(fixture)


def test_receipt_permutation_and_rejected_transport_do_not_change_inference(tmp_path):
    fixture = _legacy_fixture(tmp_path)
    original = _audit(fixture)
    fixture["row"]["calls"].reverse()
    # Rejected transport attempts never reach the evaluator. They remain
    # authenticated by the mirror pin, but need no accepted-reply evidence.
    rejected = copy.deepcopy(fixture["row"]["calls"][0])
    rejected.update(accepted=False, evidence_path="synthetic-rejected-attempt")
    fixture["row"]["calls"].insert(1, rejected)
    _repin_row(fixture)
    actual = _audit(fixture)
    for key in original.keys() - {"row_sha256", "pins_sha256"}:
        assert actual[key] == original[key]


@pytest.mark.parametrize("mutation", ["cards", "continuation", "worlds", "count", "request"])
def test_rebound_packet_local_join_drift_refuses(tmp_path, mutation):
    fixture = _legacy_fixture(tmp_path)
    path = _failed_call(fixture)["evidence_path"]
    prompt = fixture["evidence"][path]["prompt_bytes"]
    prefix, packet_bytes = prompt.split(b"\n", 1)
    packet = json.loads(packet_bytes)
    if mutation == "count":
        packet["rollout_results"].pop()
    elif mutation == "request":
        packet["rollout_calls_remaining"] = 2
    else:
        packet["rollout_results"][0][mutation] = {
            "cards": [], "continuation": "smart-all", "worlds": True}[mutation]
    rebound = prefix + b"\n" + canonical_json_bytes(packet)
    fixture["evidence"][path]["prompt_bytes"] = rebound
    fixture["pins"]["calls"][path]["prompt_sha256"] = hashlib.sha256(rebound).hexdigest()
    with pytest.raises(ValueError):
        _audit(fixture)
