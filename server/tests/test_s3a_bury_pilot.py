"""S3a's offline evidence runner is parent-bound, paired and fail-closed."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3a_bury_pilot as S3A  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


class _FastReplayBot(MCBot):
    """Cheap deterministic registered-bot seam for evidence reopening tests."""

    def _sample_hands(self, rnd, seat, _mem):
        self.sample_attempts += 1
        others = [other for other in range(4) if other != seat]
        sizes = {other: len(rnd.hands[other]) for other in others}
        pool = [card for other in others for card in rnd.hands[other]]
        self.rng.shuffle(pool)
        hands = {}
        offset = 0
        for other in others:
            hands[other] = pool[offset:offset + sizes[other]]
            offset += sizes[other]
        self.accepted_worlds += 1
        return hands, []

    def _rollout_from_bury(self, rnd, seat, sampled, bury_cards):
        hands = self._complete_determinized_hands(
            rnd, seat, sampled, buried=[])
        payload = {
            "hands": {str(other): sorted(cards)
                      for other, cards in enumerate(hands)},
            "bury": sorted(bury_cards),
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode()).digest()
        return float(int.from_bytes(digest[:4], "big") % 161)


def _fast_bot_factory(_name, seed=None):
    return _FastReplayBot(seed=seed)


def _state_problems(record):
    return S3A.state_record_problems(
        record, bot_factory=_fast_bot_factory)


def _artifact_problems(artifact):
    return S3A.artifact_problems(
        artifact, bot_factory=_fast_bot_factory)


def _validate_artifacts(artifacts, **kwargs):
    return S3A.validate_artifacts(
        artifacts, bot_factory=_fast_bot_factory, **kwargs)


def _aggregate_result(artifacts, **kwargs):
    return S3A.aggregate_result(
        artifacts, bot_factory=_fast_bot_factory, **kwargs)


def _bury_round(seed=0):
    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    assert rnd.phase == "bury" and rnd.banker is not None
    return rnd, rnd.banker


def _packet_text(state="S0_COMPLETE_SELECT_NONE",
                 champion="mc-s0-report-lcb"):
    decision = (f"PROMOTE {champion}" if state == "S0_COMPLETE_PROMOTE"
                else "SELECT NONE; production remains mc-strong")
    lines = [
        f"STATE: {state}",
        "HEAD / origin / dirty: HEAD=frozen; origin/main=main; dirty=''",
    ]
    for phase in ("s0a", "s0b-lcb", "s0c-report-lcb"):
        manifests = "; ".join(
            f"path{i} sha256=digest{i}" for i in range(8))
        lines.extend((
            f"{phase} manifests (8/8): {manifests}",
            f"{phase} aggregate: path sha256=digest survivor='policy' promotion=False",
            f"{phase} coverage: records={{}}; seeds=1..2; flips=[0,1]; exact=true",
            (f"{phase} provenance: host=mini; python=3.14.6; "
             "compiled_binary_sha256=digest; within_phase=true; "
             "cross_phase=true; frozen_identity=true"),
            f"{phase} sampler counters: {{}}",
        ))
    lines.extend((
        "S0a effects:",
        "S0b allocation contrasts:",
        "  adaptive-report_uniform: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  adaptive-random: +0.1 +/- 0.1 95%=[0, 0.2]",
        "S0c confirmation contrasts:",
        "  arm-reference: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  arm-null: +0.1 +/- 0.1 95%=[0, 0.2]",
        "  null-reference: +0.0 +/- 0.1 95%=[-0.1, 0.1]",
        "S0c criteria: {}",
        f"Final production decision from registered rule: {decision}",
        "CALIB / REPORT: sealed and unscored; never consumed",
    ))
    return "\n".join(lines) + "\n"


def _write_receipt(tmp_path, *, state="S0_COMPLETE_SELECT_NONE",
                   champion="mc-s0-report-lcb"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    packet = tmp_path / "s0-final-packet.txt"
    packet.write_text(_packet_text(state, champion))
    receipt = tmp_path / "s0-closeout.json"
    receipt.write_text(json.dumps({
        "schema": "s0-terminal-closeout-v1",
        "state": state,
        "packet": str(packet),
        "packet_sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
        "phases": ["s0a", "s0b-lcb", "s0c-report-lcb"],
    }))
    return receipt, packet


def _fold_record(stream, count):
    return {
        "schema": "s3a-world-fold-v1",
        "fold": stream["fold"],
        "stream": stream,
        "requested_worlds": count,
        "accepted_worlds": count,
        "draw_ids": [
            f"{stream['identity_sha256']}:{stream['fold']}:{i:04d}"
            for i in range(count)
        ],
        "world_sha256": [f"{i:064x}" for i in range(count)],
        "sampler_counters": {
            "sample_attempts": count,
            "accepted_worlds": count,
            "failed_worlds": 0,
            "rejected_worlds": 0,
            "impossible_worlds": 0,
        },
    }


_STATE_CACHE = {}


def _valid_state(seed=0):
    if seed not in _STATE_CACHE:
        _STATE_CACHE[seed] = S3A.run_state(
            seed, "mc-strong", bot_factory=_fast_bot_factory)
    return copy.deepcopy(_STATE_CACHE[seed])


def _artifact(shard, *, parent, runtime, head="frozen", gains=None):
    seed0 = S3A.SEED0 + shard * S3A.STATES_PER_SHARD
    records = []
    for seed in range(seed0, seed0 + S3A.STATES_PER_SHARD):
        row = _valid_state(seed)
        if gains:
            for arm, gain in gains.items():
                arm_record = row["arms"][arm]
                selection = arm_record["selection"]
                candidate_count = arm_record["candidate_count"]
                assert not gain or candidate_count > 1
                winner = 1 if gain else 0
                matrix = []
                for _ in range(selection["worlds"]):
                    values = [0.0] + [-1.0] * (candidate_count - 1)
                    if gain:
                        values[1] = 10.0
                    matrix.append(values)
                selection["values_by_world"] = matrix
                selection["means"] = [
                    sum(values[index] for values in matrix) / len(matrix)
                    for index in range(candidate_count)]
                selection["paired_mean_vs_incumbent"] = [
                    sum(values[index] - values[0] for values in matrix) /
                    len(matrix) for index in range(candidate_count)]
                selection["raw_winner_index"] = winner
                selection["chosen_index"] = winner
                selection["raw_gap_vs_incumbent"] = \
                    selection["paired_mean_vs_incumbent"][winner]
                selection["reason"] = (
                    "selection_override" if gain else "incumbent_best")

                report = arm_record["report"]
                report["chosen_index"] = winner
                report["selected_values"] = [gain] * report["worlds"]
                report["incumbent_values"] = [0.0] * report["worlds"]
                report["deltas_vs_incumbent"] = [gain] * report["worlds"]
                report["mean_gain_vs_incumbent"] = gain
                report["paired_se"] = 0.0
        records.append(row)
    manifest = {
        "schema": S3A.SCHEMA,
        "run_id": f"shard-{shard}",
        "evidence_eligible": True,
        "production_promotion": False,
        "git_sha": head,
        "tree_dirty": False,
        "host": runtime["host"],
        "python": runtime["python"],
        "fast_engine": True,
        "require_voids": True,
        "digests": runtime["digests"],
        "runtime_identity": runtime,
        "parent": parent,
        "champion": parent["champion"],
        "policy_contract": S3A.policy_contract(parent["champion"]),
        "selection_rule": S3A.SELECTION_RULE,
        "arms": list(S3A.ARMS),
        "structured_max_candidates": 32,
        "minimum_structured_selection_worlds": 8,
        "report_worlds": 120,
        "shard_index": shard,
        "shard_count": 8,
        "total_states": 512,
        "states": 64,
        "seed0": seed0,
        "seed_hi": seed0 + 63,
        "record_count": 64,
        "records_sha256": S3A.records_digest(records),
        "summary": S3A.summarize_records(records),
        "complete": True,
        "problems": [],
    }
    return {"schema": S3A.SCHEMA, "manifest": manifest, "records": records}


def _runtime():
    return {
        "host": "mini", "python": "3.14.6", "fast_engine": True,
        "require_voids": True,
        "digests": {"fast_binary": "d" * 64},
    }


def _parent():
    return {
        "schema": "s3a-terminal-s0-parent-v1",
        "receipt": "/frozen/s0-closeout.json",
        "receipt_sha256": "a" * 64,
        "state": "S0_COMPLETE_SELECT_NONE",
        "packet": "/frozen/s0-final-packet.txt",
        "packet_sha256": "b" * 64,
        "phases": ["s0a", "s0b-lcb", "s0c-report-lcb"],
        "decision": "SELECT NONE; production remains mc-strong",
        "champion": "mc-strong",
    }


def test_protocol_keeps_all_s3_features_off_and_registers_real_controls():
    bot = MCBot(seed=1)
    assert S3A.feature_off_problems(bot) == []
    assert S3A.ARMS == ("structured", "legacy_four", "random_widening")
    assert S3A.REPORT_WORLDS >= 30
    assert S3A.protocol_problems("mc-strong") == []
    assert "AUTHORIZE_DUEL_DESIGN" in S3A.SELECTION_RULE
    assert "never promotes" in S3A.SELECTION_RULE


def test_terminal_parent_is_required_hash_bound_and_names_champion(tmp_path):
    receipt, packet = _write_receipt(tmp_path)
    parent = S3A.terminal_parent(receipt)
    assert parent["state"] == "S0_COMPLETE_SELECT_NONE"
    assert parent["champion"] == "mc-strong"
    assert parent["packet_sha256"] == hashlib.sha256(packet.read_bytes()).hexdigest()

    promoted, _ = _write_receipt(
        tmp_path / "promoted", state="S0_COMPLETE_PROMOTE",
        champion="mc-s0-report-lcb")
    assert S3A.terminal_parent(promoted)["champion"] == "mc-s0-report-lcb"

    packet.write_text(packet.read_text() + "drift\n")
    with pytest.raises(S3A.ProtocolRefused, match="SHA-256"):
        S3A.terminal_parent(receipt)
    with pytest.raises(S3A.ProtocolRefused, match="missing terminal"):
        S3A.terminal_parent(tmp_path / "missing.json")


def test_terminal_parent_rejects_nonterminal_or_schema_only_receipts(tmp_path):
    packet = tmp_path / "packet.txt"
    packet.write_text(_packet_text())
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "schema": "s0-terminal-closeout-v1", "state": "S0B_RUNNING",
        "packet": str(packet),
        "packet_sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
    }))
    with pytest.raises(S3A.ProtocolRefused, match="not terminal"):
        S3A.terminal_parent(receipt)
    receipt.write_text(json.dumps({"schema": "lookalike"}))
    with pytest.raises(S3A.ProtocolRefused, match="schema"):
        S3A.terminal_parent(receipt)


def test_every_source_is_banker_visible_and_controls_match_trigger_and_k():
    rnd, seat = _bury_round(8)
    incumbent = S3A.literal_incumbent(
        MCBot(seed=9), rnd.hands[seat], rnd.ordering, seat)
    stream = S3A.named_stream(
        deal_seed=8, state_id="bury:8", purpose="candidate_source",
        fold="random", seat=seat, policy="mc-strong")
    first = S3A.build_ballots(
        rnd.hands[seat], rnd.ordering, incumbent, seat, stream)

    altered = copy.deepcopy(rnd)
    for other in range(4):
        if other != seat:
            altered.hands[other] = ["BJ"] * len(altered.hands[other])
    altered.deck = list(reversed(altered.deck))
    altered.kitty = ["LJ"] * len(altered.kitty)
    second = S3A.build_ballots(
        altered.hands[seat], altered.ordering, incumbent, seat, stream)
    assert {arm: ballot.record() for arm, ballot in first.items()} == \
        {arm: ballot.record() for arm, ballot in second.items()}
    for ballot in first.values():
        assert ballot.candidates[0].cards == incumbent
    assert len(first["random_widening"].candidates) == \
        len(first["structured"].candidates)
    assert first["random_widening"].triggered == first["structured"].triggered
    assert len(first["legacy_four"].candidates) <= 4


def test_capability_view_raises_if_a_source_reaches_for_an_opponent():
    rnd, seat = _bury_round(1)
    view = S3A._BankerVisibleBuryState(seat, rnd.hands[seat], rnd.ordering)
    assert view.hands[seat] == rnd.hands[seat]
    with pytest.raises(S3A.HiddenInformationAccess, match="hidden seat"):
        _ = view.hands[(seat + 1) % 4]
    with pytest.raises(S3A.HiddenInformationAccess, match="enumerate"):
        list(view.hands)


def test_work_plan_uses_exact_lcm_and_equal_total_candidate_worlds():
    plan = S3A.exact_work_plan({
        "structured": 31, "legacy_four": 4, "random_widening": 31,
    })
    assert plan["selection"]["divisibility_quantum"] == 124
    assert plan["selection"]["candidate_worlds_per_arm"] == 248
    assert plan["selection"]["common_worlds_by_arm"] == {
        "structured": 8, "legacy_four": 62, "random_widening": 8,
    }
    assert plan["report"]["candidate_worlds_per_arm"] == 240
    assert plan["total_candidate_worlds_per_arm"] == 488
    with pytest.raises(S3A.ProtocolRefused, match="random widening K"):
        S3A.exact_work_plan({
            "structured": 31, "legacy_four": 4, "random_widening": 30,
        })


def test_selection_and_report_streams_are_named_deterministic_and_disjoint():
    kwargs = dict(deal_seed=5, state_id="state:5", purpose="determinizations",
                  seat=2, policy="mc-strong")
    selection = S3A.named_stream(**kwargs, fold="selection")
    report = S3A.named_stream(**kwargs, fold="report")
    assert selection == S3A.named_stream(**kwargs, fold="selection")
    assert selection["seed"] != report["seed"]
    assert selection["identity_sha256"] != report["identity_sha256"]
    srec = _fold_record(selection, 8)
    rrec = _fold_record(report, 30)
    assert not set(srec["draw_ids"]) & set(rrec["draw_ids"])


def test_evaluator_consumes_exact_work_even_when_incumbent_is_selected():
    plan = S3A.exact_work_plan({
        "structured": 3, "legacy_four": 2, "random_widening": 3,
    }, report_worlds=30)
    ballot = S3A.ArmBallot(
        "structured",
        tuple(S3A.Candidate((name,), (name,)) for name in ("a", "b", "c")),
        True, {},
    )
    selection = [{"a": 10, "b": 1, "c": 0}] * 8
    report = [{"a": 10, "b": 1, "c": 0}] * 30
    calls = []

    def value(world, cards):
        calls.append(cards)
        return world[cards[0]]

    result = S3A.evaluate_arm(
        ballot, selection, report, plan, 5.0, value,
        selection_ids=[f"s{i}" for i in range(8)],
        report_ids=[f"r{i}" for i in range(30)],
    )
    assert result["selection"]["chosen_index"] == 0
    assert result["work"] == {
        "selection_candidate_worlds": 24,
        "report_candidate_worlds": 60,
        "total_candidate_worlds": 84,
        "expected_selection_candidate_worlds": 24,
        "expected_report_candidate_worlds": 60,
        "expected_total_candidate_worlds": 84,
        "complete": True,
    }
    assert len(calls) == 84
    assert calls[-60:] == [("a",)] * 60, \
        "candidate zero must still be scored twice per report world"


class _ExactWorldBot(MCBot):
    def __init__(self, rnd, seat, *, mode="ok", seed=None):
        super().__init__(seed)
        self._test_round = rnd
        self._test_seat = seat
        self._mode = mode

    def _sample_hands(self, _rnd, _seat, _mem):
        self.sample_attempts += 1
        if self._mode == "fail":
            self.failed_worlds += 1
            return None
        hands = {
            other: list(self._test_round.hands[other])
            for other in range(4) if other != self._test_seat
        }
        if self._mode == "invalid":
            hands.pop(next(iter(hands)))
        self.accepted_worlds += 1
        if self._mode == "rejected":
            self.rejected_worlds += 1
        return hands, []


def test_fold_draws_exact_valid_worlds_and_fails_closed_on_bad_sampler():
    rnd, seat = _bury_round(2)
    stream = S3A.named_stream(
        deal_seed=2, state_id="state:2", purpose="determinizations",
        fold="selection", seat=seat, policy="mc-strong")

    def factory(_name, seed=None, mode="ok"):
        return _ExactWorldBot(rnd, seat, mode=mode, seed=seed)

    worlds, record = S3A.draw_world_fold(
        rnd, seat, "mc-strong", 3, stream, bot_factory=factory)
    assert len(worlds) == 3
    assert record["sampler_counters"] == {
        "sample_attempts": 3, "accepted_worlds": 3, "failed_worlds": 0,
        "rejected_worlds": 0, "impossible_worlds": 0,
    }
    assert S3A.fold_problems(record, 3) == []

    for mode, message in (("fail", "rejected/failed"),
                          ("invalid", "invalid world"),
                          ("rejected", "nonzero or missing rejected_worlds")):
        with pytest.raises(S3A.ProtocolRefused, match=message):
            S3A.draw_world_fold(
                rnd, seat, "mc-strong", 1, stream,
                bot_factory=lambda name, seed=None, mode=mode:
                    factory(name, seed, mode),
            )


def test_state_validator_catches_work_c0_fold_and_control_drift():
    record = _valid_state(4)
    assert _state_problems(record) == []

    broken = copy.deepcopy(record)
    broken["arms"]["structured"]["work"]["total_candidate_worlds"] -= 1
    assert any("structured: total work differs" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    broken["arms"]["random_widening"]["candidates"][0]["cards"] = ["BJ"] * 8
    problems = _state_problems(broken)
    assert any("candidate zero" in problem for problem in problems)
    assert any("illegal candidate" in problem for problem in problems)

    broken = copy.deepcopy(record)
    broken["folds"]["report"]["draw_ids"][0] = \
        broken["folds"]["selection"]["draw_ids"][0]
    assert any("overlap" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    broken["arms"]["random_widening"]["triggered"] = \
        not broken["arms"]["structured"]["triggered"]
    assert any("trigger differs" in problem
               for problem in _state_problems(broken))


@pytest.mark.parametrize("stream_path", [
    ("ballots", "random_widening", "source", "stream"),
    ("folds", "selection", "stream"),
    ("folds", "report", "stream"),
    ("scoring", "stream"),
])
def test_state_validator_rederives_every_named_stream(stream_path):
    record = _valid_state(10)
    stream = record
    for key in stream_path:
        stream = stream[key]
    stream["seed"] += 1
    assert any("stream seed does not derive" in problem
               for problem in _state_problems(record))


def test_state_validator_rederives_source_plan_selection_and_report_math():
    record = _valid_state(11)

    broken = copy.deepcopy(record)
    broken["source_input_sha256"] = "0" * 64
    assert any("source-input SHA" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    broken["work_plan"]["selection"]["divisibility_quantum"] += 1
    assert any("registered formula" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    broken["ballots"]["structured"]["candidates"][1]["sources"] = ["invented"]
    assert any("do not replay exactly" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    selection = broken["arms"]["structured"]["selection"]
    selection["raw_winner_index"] = (
        (selection["raw_winner_index"] + 1) %
        broken["arms"]["structured"]["candidate_count"])
    assert any("raw winner does not match" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    report = broken["arms"]["structured"]["report"]
    report["mean_gain_vs_incumbent"] += 1.0
    report["paired_se"] = 999.0
    problems = _state_problems(broken)
    assert any("report mean does not reconcile" in problem for problem in problems)
    assert any("report SE does not reconcile" in problem for problem in problems)

    broken = copy.deepcopy(record)
    selection = broken["arms"]["structured"]["selection"]
    selection["means"] = [999.0] * len(selection["means"])
    selection["paired_mean_vs_incumbent"] = [0.0] * len(
        selection["paired_mean_vs_incumbent"])
    assert any("do not derive from raw values" in problem
               for problem in _state_problems(broken))

    broken = copy.deepcopy(record)
    report = broken["arms"]["structured"]["report"]
    report["deltas_vs_incumbent"] = [999.0] * report["worlds"]
    report["mean_gain_vs_incumbent"] = 999.0
    report["paired_se"] = 0.0
    assert any("report deltas do not derive from raw values" in problem
               for problem in _state_problems(broken))


def test_state_reopener_redraws_named_fold_and_rejects_valid_digest_rewrite():
    record = _valid_state(12)
    digest = record["folds"]["selection"]["world_sha256"][0]
    record["folds"]["selection"]["world_sha256"][0] = (
        "0" * 64 if digest != "0" * 64 else "1" * 64)

    # Syntax/self-consistency alone cannot see this valid-format substitution.
    assert S3A.state_record_problems(
        record, bot_factory=_fast_bot_factory, replay_evidence=False) == []
    problems = _state_problems(record)
    assert any("ordered world SHA-256 differs from named-stream replay" in problem
               for problem in problems)


def test_state_reopener_rejects_self_consistent_wholesale_raw_value_rewrite():
    record = _valid_state(13)
    for arm in S3A.ARMS:
        arm_record = record["arms"][arm]
        selection = arm_record["selection"]
        candidate_count = arm_record["candidate_count"]
        selection["values_by_world"] = [
            [100.0] + [0.0] * (candidate_count - 1)
            for _ in range(selection["worlds"])
        ]
        selection["means"] = [100.0] + [0.0] * (candidate_count - 1)
        selection["paired_mean_vs_incumbent"] = (
            [0.0] + [-100.0] * (candidate_count - 1))
        selection["raw_winner_index"] = 0
        selection["chosen_index"] = 0
        selection["reason"] = "incumbent_best"
        selection["raw_gap_vs_incumbent"] = 0.0

        report = arm_record["report"]
        report["chosen_index"] = 0
        report["selected_values"] = [50.0] * report["worlds"]
        report["incumbent_values"] = [50.0] * report["worlds"]
        report["deltas_vs_incumbent"] = [0.0] * report["worlds"]
        report["mean_gain_vs_incumbent"] = 0.0
        report["paired_se"] = 0.0

    # All persisted summaries, choices, paired deltas, and work still derive.
    assert S3A.state_record_problems(
        record, bot_factory=_fast_bot_factory, replay_evidence=False) == []
    problems = _state_problems(record)
    for arm in S3A.ARMS:
        assert any(f"{arm}: raw selection values differ" in problem
                   for problem in problems)
        assert any(f"{arm}: raw report selected_values differ" in problem
                   for problem in problems)
        assert any(f"{arm}: raw report incumbent_values differ" in problem
                   for problem in problems)


def test_atomic_output_is_exclusive_and_cleans_failed_partial(tmp_path,
                                                              monkeypatch):
    path = tmp_path / "artifact.json"
    S3A.atomic_json_exclusive(path, {"ok": True})
    assert json.loads(path.read_text()) == {"ok": True}
    with pytest.raises(S3A.ProtocolRefused, match="overwrite"):
        S3A.atomic_json_exclusive(path, {"ok": False})

    failed = tmp_path / "failed.json"
    monkeypatch.setattr(S3A.os, "link", lambda *_args: (_ for _ in ()).throw(
        OSError("injected publish failure")))
    with pytest.raises(OSError, match="injected"):
        S3A.atomic_json_exclusive(failed, {"ok": False})
    assert not failed.exists()
    assert not Path(str(failed) + ".partial").exists()


def test_shard_validator_requires_exact_512_parent_runtime_and_coverage():
    runtime = _runtime()
    parent = _parent()
    artifacts = [
        (Path(f"shard-{i}.json"), _artifact(
            i, parent=parent, runtime=runtime))
        for i in range(8)
    ]
    assert _validate_artifacts(
        artifacts, current_runtime=runtime, current_head="frozen",
        parent=parent) == []

    assert any("found 7 shards" in problem for problem in
               _validate_artifacts(artifacts[:-1]))
    broken = copy.deepcopy(artifacts)
    broken[7][1]["manifest"]["parent"] = {**parent, "receipt_sha256": "drift"}
    assert any("parent" in problem for problem in _validate_artifacts(
        broken, current_runtime=runtime, current_head="frozen", parent=parent))


@pytest.mark.parametrize("mutation, needle", [
    (lambda manifest: manifest.__setitem__("report_worlds", 119),
     "frozen field drift: report_worlds"),
    (lambda manifest: manifest.__setitem__("production_promotion", True),
     "claims production promotion"),
    (lambda manifest: manifest["policy_contract"].__setitem__("margin", 99),
     "policy contract differs"),
    (lambda manifest: manifest["parent"].__setitem__("phases", ["s0c-only"]),
     "parent phases"),
])
def test_manifest_reopener_binds_constants_bits_contract_and_parent(
        mutation, needle):
    artifact = _artifact(0, parent=_parent(), runtime=_runtime())
    mutation(artifact["manifest"])
    assert any(needle in problem for problem in _artifact_problems(artifact))


def test_aggregate_compares_structured_to_incumbent_legacy_and_random(
        tmp_path, monkeypatch):
    runtime = _runtime()
    parent = _parent()
    gains = {"structured": 1.0, "legacy_four": 0.0,
             "random_widening": 0.0}
    artifacts = []
    for shard in range(8):
        artifact = _artifact(
            shard, parent=parent, runtime=runtime, gains=gains)
        path = tmp_path / f"shard-{shard}.json"
        path.write_text(json.dumps(artifact))
        artifacts.append((path, artifact))
    # This test isolates the terminal aggregation formula. Evidence reopening
    # and self-consistent raw-value tampering are exercised separately below.
    monkeypatch.setattr(S3A, "validate_artifacts", lambda *_args, **_kwargs: [])
    result = _aggregate_result(
        artifacts, runtime=runtime, head="frozen", parent=parent)
    assert set(result["stats"]) == {
        "structured-incumbent", "structured-legacy_four",
        "structured-random_widening",
    }
    assert all(stat["mean"] == 1.0 for stat in result["stats"].values())
    assert result["duel_design_authorized"] is True
    assert result["production_promotion"] is False
    assert result["duel_reference_frozen"] is False


def test_aggregate_reopens_named_stream_after_local_summary_digest_rewrite(
        tmp_path):
    runtime = _runtime()
    parent = _parent()
    artifacts = [
        (tmp_path / f"shard-{shard}.json",
         _artifact(shard, parent=parent, runtime=runtime))
        for shard in range(8)
    ]
    row = artifacts[0][1]["records"][0]
    old_fold = row["folds"]["selection"]
    altered = S3A.named_stream(
        deal_seed=row["deal_seed"], state_id=row["state_id"],
        purpose="locally_rewritten_selection", fold="selection",
        seat=row["source_input"]["banker"], policy=row["champion"],
    )
    old_fold["stream"] = altered
    old_fold["draw_ids"] = [
        f"{altered['identity_sha256']}:selection:{index:04d}"
        for index in range(old_fold["requested_worlds"])
    ]
    for arm in S3A.ARMS:
        count = row["arms"][arm]["selection"]["worlds"]
        row["arms"][arm]["selection"]["draw_ids"] = \
            old_fold["draw_ids"][:count]

    # Simulate a producer rewriting every self-reported shard digest/summary.
    # The independent aggregate must derive the frozen purpose from the state,
    # not trust those now-self-consistent local claims.
    manifest = artifacts[0][1]["manifest"]
    manifest["records_sha256"] = S3A.records_digest(
        artifacts[0][1]["records"])
    manifest["summary"] = S3A.summarize_records(
        artifacts[0][1]["records"])
    local = _artifact_problems(artifacts[0][1])
    assert not any("records SHA" in problem or "local summary" in problem
                   for problem in local)
    assert any("stream purpose drift" in problem for problem in local)

    for path, artifact in artifacts:
        path.write_text(json.dumps(artifact))
    aggregate = _aggregate_result(
        artifacts, runtime=runtime, head="frozen", parent=parent)
    assert aggregate["status"] == "HOLD"
    assert aggregate["duel_design_authorized"] is False
    assert aggregate["criteria"] == {"all": False}
    assert any("stream purpose drift" in problem
               for problem in aggregate["problems"])


def test_aggregate_replays_deal_and_holds_a_copied_state_renamed_to_fresh_seed(
        tmp_path):
    runtime = _runtime()
    parent = _parent()
    artifacts = [
        (tmp_path / f"copy-shard-{shard}.json",
         _artifact(shard, parent=parent, runtime=runtime))
        for shard in range(8)
    ]
    records = artifacts[0][1]["records"]
    copied = copy.deepcopy(records[0])
    target_seed = records[1]["deal_seed"]
    banker = copied["source_input"]["banker"]
    copied["deal_seed"] = target_seed
    copied["state_id"] = \
        f"{S3A.SCHEMA}:deal:{target_seed}:banker:{banker}"
    copied["replay"]["deal_seed"] = target_seed
    # The producer can recompute this self-hash perfectly; it still does not
    # establish that the hand came from target_seed.
    copied["source_input_sha256"] = S3A.sha256_bytes(
        S3A._json_bytes(copied["source_input"]))
    records[1] = copied
    manifest = artifacts[0][1]["manifest"]
    manifest["records_sha256"] = S3A.records_digest(records)
    manifest["summary"] = S3A.summarize_records(records)

    local = _artifact_problems(artifacts[0][1])
    assert not any("source-input SHA-256" in problem for problem in local)
    assert any("source input differs from named deal/champion replay" in problem
               for problem in local)
    assert any("replay transcript differs from named deal/champion" in problem
               for problem in local)

    for path, artifact in artifacts:
        path.write_text(json.dumps(artifact))
    aggregate = _aggregate_result(
        artifacts, runtime=runtime, head="frozen", parent=parent)
    assert aggregate["status"] == "HOLD"
    assert aggregate["duel_design_authorized"] is False
    assert any("source input differs from named deal/champion replay" in problem
               for problem in aggregate["problems"])


def test_real_context_requires_compiled_strict_environment(monkeypatch,
                                                            tmp_path):
    receipt, _ = _write_receipt(tmp_path)
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    with pytest.raises(S3A.ProtocolRefused, match="SHENGJI_FAST=1"):
        S3A.require_real_context(receipt)
