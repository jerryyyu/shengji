"""Tests for the evidence-only benchmark rollout rejection proof."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from shengji.engine.cards import Ordering
from shengji.engine.legal import IllegalPlay
from shengji.engine.round import Trick, TrickPlay
from shengji.luna.benchmark_policy import SeatPlannerPolicy
from shengji.luna.benchmark_transport import BenchmarkTransport
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.transport import InvocationResult
from test_llm_benchmark_observation import state
from test_luna_transport import trace


RUNTIME = {"schema": "pt-luna-codex-tool-catalog-v1"}


def _round(*, lead=True):
    rnd = state()
    rnd.turn = 1
    rnd.trump_rank = "8"
    rnd.trump_suit = "S"
    rnd.trump_is_nt = False
    rnd.ordering = Ordering("S", "8")
    rnd.hands[1] = ["H8", "H9"]
    rnd.history = []
    if lead:
        rnd.trick = Trick(leader=1)
    else:
        rnd.trick = Trick(leader=0, plays=[TrickPlay(0, ["HA"])])
    return rnd


def _evidence(tmp_path, *, cards=None, continuation="heuristic-all", lead=False,
              invalid_action_feedback=False):
    """Produce one retained row through the real policy and transport seams."""
    cards = [] if cards is None and lead else ["H8"] if cards is None else list(cards)
    final = {"cards": None,
             "evaluations": [{"cards": cards, "continuation": continuation}],
             "memory": ""}
    final_bytes = json.dumps(final, indent=2).encode() + b"\n"
    packet_bytes = []

    def run_command(command, prompt, workspace, timeout):
        (workspace / "final.json").write_bytes(final_bytes)
        return InvocationResult(0, trace(final), b"", 1)

    transport = BenchmarkTransport(
        evidence_root=tmp_path, codex_binary="/usr/bin/true",
        runtime_attestor=lambda _: dict(RUNTIME), run_command=run_command)

    def planner(packet):
        # This is the exact canonical request consumed by BenchmarkTransport;
        # the transport also records the same digest in response_binding.
        packet_bytes.append(canonical_json_bytes(packet))
        return transport(packet)

    rnd = _round(lead=lead)
    seat = 1
    bot = SeatPlannerPolicy(
        seat=seat, information="perfect", planner=planner, setup_policy=None,
        worlds=1, invalid_action_feedback=invalid_action_feedback)
    with pytest.raises(IllegalPlay) as raised:
        bot.decide_play(rnd, seat)

    events = ([{"seat": 0, "attempted_cards": ["HA"], "wall_seconds": 0.0}]
              if not lead else [])
    diagnostic = dict(bot.rollout_diagnostic, completed_play_events=len(events))
    binding = dict(bot.rollout_request_binding, completed_play_events=len(events))
    row = {
        "complete": False,
        "flip": seat % 2,
        "information": "perfect",
        "invalid_action_feedback": invalid_action_feedback,
        "events": events,
        "error": f"IllegalPlay: {raised.value}",
        "calls": copy.deepcopy(transport.calls),
        "rollout_diagnostic": diagnostic,
        "rollout_request_binding": binding,
    }
    return {
        "row": row,
        "packet_bytes": packet_bytes[0],
        "final_bytes": final_bytes,
        "transport": transport,
        "round": rnd,
        "diagnostic": diagnostic,
        "binding": binding,
    }


def _verify(evidence):
    from shengji.luna.benchmark_rollout_proof import verify_rollout_rejection

    return verify_rollout_rejection(
        evidence["row"], packet_bytes=evidence["packet_bytes"],
        final_bytes=evidence["final_bytes"])


def _rebound(evidence, *, cards):
    """Return a copy whose provider bytes and all receipt hashes agree."""
    out = copy.deepcopy(evidence)
    final = {"cards": None,
             "evaluations": [{"cards": list(cards), "continuation": "heuristic-all"}],
             "memory": ""}
    final_bytes = json.dumps(final, indent=2).encode() + b"\n"
    answer = {"evaluations": final["evaluations"], "memory": ""}
    packet_sha = hashlib.sha256(out["packet_bytes"]).hexdigest()
    final_sha = hashlib.sha256(final_bytes).hexdigest()
    reply_sha = hashlib.sha256(canonical_json_bytes(answer)).hexdigest()
    for call in out["row"]["calls"]:
        call["response_binding"].update(
            packet_sha256=packet_sha, final_sha256=final_sha,
            reply_sha256=reply_sha)
    out["row"]["rollout_request_binding"]["reply_sha256"] = reply_sha
    out["row"]["rollout_diagnostic"]["cards"] = list(cards)
    out["final_bytes"] = final_bytes
    return out


def _packet_mutate(evidence, mutate):
    packet = json.loads(evidence["packet_bytes"])
    mutate(packet)
    evidence["packet_bytes"] = canonical_json_bytes(packet)


def test_actual_policy_transport_chain_proves_follow_rejection_without_mutation(tmp_path):
    evidence = _evidence(tmp_path, lead=False)
    before = copy.deepcopy(evidence["row"])
    proof = _verify(evidence)

    assert proof == {
        "schema": "benchmark-rollout-rejection-proof-v1",
        "seat": 1,
        "request_index": 0,
        "evaluation_index": 0,
        "completed_play_events": 1,
        "cards": ["H8"],
        "continuation": "heuristic-all",
        "packet_sha256": evidence["binding"]["packet_sha256"],
        "final_sha256": evidence["transport"].calls[0]["response_binding"]["final_sha256"],
        "reply_sha256": evidence["binding"]["reply_sha256"],
        "observation_sha256": evidence["binding"]["observation_sha256"],
        "validation": "follow",
    }
    assert evidence["row"] == before


def test_actual_policy_transport_chain_proves_empty_lead_rejection(tmp_path):
    evidence = _evidence(tmp_path, lead=True)
    assert _verify(evidence)["validation"] == "lead"
    assert _verify(evidence)["completed_play_events"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e["row"]["rollout_diagnostic"].update(stage="rollout_continuation"),
        lambda e: e["row"]["rollout_diagnostic"].update(error_type="RuntimeError"),
        lambda e: e["row"]["rollout_diagnostic"].update(request_index=1),
        lambda e: e["row"]["rollout_diagnostic"].update(seat=3),
        lambda e: e["row"].update(flip=0),
        lambda e: e["row"]["rollout_diagnostic"].update(completed_play_events=0),
        lambda e: e["row"]["rollout_diagnostic"].update(cards=["H9"]),
        lambda e: e["row"].update(invalid_action_feedback=True),
        lambda e: e["row"]["calls"][0].update(accepted=False),
        lambda e: e["row"]["calls"].append(copy.deepcopy(e["row"]["calls"][0])),
    ],
)
def test_malformed_or_non_rejection_evidence_refuses(tmp_path, mutation):
    evidence = _evidence(tmp_path, lead=False)
    mutation(evidence)
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


@pytest.mark.parametrize("which", ["packet_bytes", "final_bytes"])
def test_altered_provider_bytes_refuse_even_when_row_is_unchanged(tmp_path, which):
    evidence = _evidence(tmp_path, lead=False)
    evidence[which] = evidence[which] + b" "
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


def test_non_evaluation_final_output_refuses(tmp_path):
    evidence = _evidence(tmp_path, lead=False)
    final = {"cards": ["H9"], "evaluations": None, "memory": ""}
    final_bytes = json.dumps(final, indent=2).encode() + b"\n"
    evidence["final_bytes"] = final_bytes
    evidence["row"]["calls"][0]["response_binding"]["final_sha256"] = \
        hashlib.sha256(final_bytes).hexdigest()
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


def test_packet_observation_and_digest_mismatch_refuse(tmp_path):
    evidence = _evidence(tmp_path, lead=False)
    packet = json.loads(evidence["packet_bytes"])
    packet["observation"]["trump_suit"] = "H"
    evidence["packet_bytes"] = canonical_json_bytes(packet)
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


def test_rebound_packet_hash_cannot_hide_observation_hash_mismatch(tmp_path):
    evidence = _evidence(tmp_path, lead=False)
    packet = json.loads(evidence["packet_bytes"])
    packet["observation"]["trump_suit"] = "H"
    evidence["packet_bytes"] = canonical_json_bytes(packet)
    packet_sha = hashlib.sha256(evidence["packet_bytes"]).hexdigest()
    evidence["row"]["rollout_request_binding"]["packet_sha256"] = packet_sha
    evidence["row"]["calls"][0]["response_binding"]["packet_sha256"] = packet_sha
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


def test_engine_legal_candidate_is_not_inferred_illegal_from_rebound_diagnostic(tmp_path):
    evidence = _rebound(_evidence(tmp_path, lead=False), cards=["H9"])
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda e: e["row"]["rollout_diagnostic"].update(cards=["ZZ"]),
        lambda e: e["row"]["rollout_diagnostic"].update(cards=["H8", "H9"]),
        lambda e: e["row"]["rollout_diagnostic"].update(continuation="not-a-continuation"),
        lambda e: _packet_mutate(
            e, lambda packet: packet["observation"]["current_trick"]["plays"][0]
            .update(cards=["ZZ"])),
        lambda e: _packet_mutate(
            e, lambda packet: packet["observation"]["current_trick"]["plays"][0]
            .update(seat=2)),
    ],
)
def test_invalid_card_or_context_codes_refuse(tmp_path, mutator):
    evidence = _evidence(tmp_path, lead=False)
    mutator(evidence)
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


def test_invalid_ordering_context_refuses(tmp_path):
    evidence = _evidence(tmp_path, lead=False)
    packet = json.loads(evidence["packet_bytes"])
    packet["observation"]["trump_rank"] = "not-a-rank"
    evidence["packet_bytes"] = canonical_json_bytes(packet)
    with pytest.raises((ValueError, TypeError)):
        _verify(evidence)


@pytest.mark.parametrize("field,value,match", [
    ("trump_rank", "bad", "ordering"),
    ("trump_is_nt", True, "no-trump"),
    ("own_hand", ["ZZ"], "hand cards"),
    ("own_hand", ["H9", "H9", "H9"], "multiplicities"),
    ("current_trick", {"leader": 2, "plays": []}, "trick order"),
])
def test_invalid_context_refuses_even_with_all_hashes_rebound(tmp_path, field, value, match):
    evidence = _evidence(tmp_path)
    packet = json.loads(evidence["packet_bytes"])
    observation = packet["observation"]
    observation[field] = value
    del observation["observation_sha256"]
    observation["observation_sha256"] = hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    raw = canonical_json_bytes(packet)
    packet_sha = hashlib.sha256(raw).hexdigest()
    evidence["packet_bytes"] = raw
    evidence["row"]["rollout_request_binding"].update(
        packet_sha256=packet_sha, observation_sha256=observation["observation_sha256"])
    evidence["row"]["calls"][0]["response_binding"]["packet_sha256"] = packet_sha
    with pytest.raises(ValueError, match=match):
        _verify(evidence)


def test_third_evaluation_is_bound_by_index_not_first_matching_reply(tmp_path):
    evidence = _evidence(tmp_path)
    final = json.loads(evidence["final_bytes"])
    final["evaluations"] = [
        {"cards": ["H9"], "continuation": "heuristic-all"},
        {"cards": ["H9"], "continuation": "heuristic-all"},
        {"cards": ["H8"], "continuation": "heuristic-all"},
    ]
    raw = canonical_json_bytes(final)
    reply_sha = hashlib.sha256(canonical_json_bytes(
        {"evaluations": final["evaluations"], "memory": final["memory"]})).hexdigest()
    evidence["final_bytes"] = raw
    evidence["row"]["calls"][0]["response_binding"].update(
        final_sha256=hashlib.sha256(raw).hexdigest(), reply_sha256=reply_sha)
    evidence["row"]["rollout_request_binding"].update(evaluation_index=2, reply_sha256=reply_sha)
    evidence["row"]["rollout_diagnostic"]["evaluation_index"] = 2
    assert _verify(evidence)["evaluation_index"] == 2
    evidence["row"]["rollout_request_binding"]["evaluation_index"] = 1
    evidence["row"]["rollout_diagnostic"]["evaluation_index"] = 1
    with pytest.raises(ValueError, match="selected evaluation"):
        _verify(evidence)


@pytest.mark.parametrize("events", [
    [None], [{"seat": 0}],
    [{"seat": 3, "attempted_cards": ["HA"], "wall_seconds": 0.0}],
])
def test_same_length_malformed_or_wrong_actor_events_refuse(tmp_path, events):
    evidence = _evidence(tmp_path)
    evidence["row"]["events"] = events
    with pytest.raises(ValueError, match="event"):
        _verify(evidence)


@pytest.mark.parametrize("mutation", ["valid", "leader", "seat", "cards", "empty"])
def test_history_actor_join_with_all_hashes_rebound(tmp_path, mutation):
    evidence = _evidence(tmp_path)
    packet = json.loads(evidence["packet_bytes"])
    past = {"leader": 0, "plays": [
        {"seat": seat, "cards": ["C3"]} for seat in range(4)]}
    if mutation == "leader":
        past["leader"] = False
    elif mutation == "seat":
        past["plays"][1]["seat"] = 3
    elif mutation == "cards":
        past["plays"][0]["cards"] = ["ZZ"]
    elif mutation == "empty":
        past["plays"][0]["cards"] = []
    observation = packet["observation"]
    observation["history"] = [past]
    del observation["observation_sha256"]
    observation["observation_sha256"] = hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    raw = canonical_json_bytes(packet)
    packet_sha = hashlib.sha256(raw).hexdigest()
    evidence["packet_bytes"] = raw
    evidence["row"]["events"] = [
        {"seat": seat, "attempted_cards": ["C3"], "wall_seconds": 0.0}
        for seat in range(4)] + evidence["row"]["events"]
    evidence["row"]["rollout_request_binding"].update(
        packet_sha256=packet_sha, observation_sha256=observation["observation_sha256"],
        completed_play_events=5)
    evidence["row"]["rollout_diagnostic"]["completed_play_events"] = 5
    evidence["row"]["calls"][0]["response_binding"]["packet_sha256"] = packet_sha
    if mutation == "valid":
        assert _verify(evidence)["completed_play_events"] == 5
    else:
        with pytest.raises(ValueError):
            _verify(evidence)


def test_attempted_throw_cards_need_not_equal_committed_cards(tmp_path):
    evidence = _evidence(tmp_path)
    evidence["row"]["events"][0]["attempted_cards"] = ["HA", "H3"]
    assert _verify(evidence)["completed_play_events"] == 1
