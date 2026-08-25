"""Focused PT1 contract witnesses (no gameplay or promotion authority)."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from shengji.rl.privileged_teacher_pt0 import (
    WorldActionValues, canonical_json_bytes, exact_world_action_values)
from shengji.rl import privileged_teacher_pt1 as pt1
from shengji.engine.round import Round
from shengji.engine.cards import Ordering, make_deck
from shengji.engine.round import Trick, TrickPlay

_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "pt1_runner", Path(__file__).parents[1] / "scripts" / "run_privileged_teacher_pt1.py")
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
pt1_runner = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(pt1_runner)


def _sha(ch: str) -> str:
    return ch * 64


def _arm(name: str, action=("C4",), *, ballot=(("C4",), ("D4",))):
    return pt1.ArmDecision(name, action, ballot, _sha("a"), _sha("b"),
                           pt1.PRODUCTION_POLICY if name != "C" else "ExactWorldSession", 7,
                           pt1.WorkReceipt(30, 300, 1, 30, 1, 300, 1,
                                           900, 900, 0, 0, 1),
                           _sha("e"))


def _record():
    arms = (_arm("A"), _arm("B"), _arm("C"))
    utilities = ((('C4',), 1), (('D4',), 1))
    points = ((('C4',), 80), (('D4',), 80))
    evaluator = pt1._evaluator_identity(_sha("a"), _sha("b"), utilities,
                                         points, 0, 0)
    arms = tuple(pt1.ArmDecision(a.arm, a.selected_action, a.ballot,
                                 a.public_state_sha256, a.true_world_sha256,
                                 a.policy, a.seed, a.work, evaluator)
                 for a in arms)
    return pt1.PT1Record(_sha("c"), _sha("a"), _sha("b"),
                         (("C4",), ("D4",)), arms,
                         (("A", 1), ("B", 1), ("C", 1)),
                         (("A", 80), ("B", 80), ("C", 80)),
                         utilities, points, evaluator, 0,
                         pt1.AUTHORITY)


def _reseal(payload):
    body = {k: payload[k] for k in payload if k != "record_sha256"}
    payload["record_sha256"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return payload


def _real_late_round(*, hidden_swap=False, burial_swap=False):
    """A genuine 23-trick Round with two cards per hand and eight kitty cards."""
    import random
    deck = make_deck()
    indices = [[92, 94], [93, 96], [95, 97], [98, 99]]
    if hidden_swap:
        indices[0][0], indices[2][0] = indices[2][0], indices[0][0]
    hands = [[deck[i] for i in row] for row in indices]
    buried_indices = list(range(100, 108))
    if burial_swap:
        indices[0][0], buried_indices[0] = buried_indices[0], indices[0][0]
    buried = [deck[i] for i in buried_indices]
    held = set(sum(indices, []) + buried_indices)
    played = [card for i, card in enumerate(deck) if i not in held]
    history = [Trick(
        leader=i % 4,
        plays=[TrickPlay((i + j) % 4, [played[4 * i + j]]) for j in range(4)],
        winner=(i + 3) % 4, points=0) for i in range(23)]
    rnd = Round("7", banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = hands
    rnd.buried = buried
    rnd.attacker_points = 0
    rnd.history = history
    rnd.trick = Trick(leader=1)
    rnd.turn = 1
    rnd.deck = deck
    return rnd


def _decision_hidden_round(*, hidden_swap=False):
    """Legal follow witness: a hidden banker C3 versus C7 changes the value."""
    import random
    deck = make_deck()
    indices = [[92], [93, 96], [94, 97], [95, 98]]
    if hidden_swap:
        indices[2][0], indices[3][1] = indices[3][1], indices[2][0]
    buried_indices = [99, 100, 102, 103, 104, 105, 106, 107]
    held = set(sum(indices, []) + buried_indices + [101])
    played = [card for i, card in enumerate(deck) if i not in held]
    history = [Trick(
        leader=i % 4,
        plays=[TrickPlay((i + j) % 4, [played[4 * i + j]]) for j in range(4)],
        winner=(i + 3) % 4, points=0) for i in range(23)]
    rnd = Round("7", banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = [[deck[i] for i in row] for row in indices]
    rnd.buried = [deck[i] for i in buried_indices]
    rnd.attacker_points = 55
    rnd.history = history
    rnd.trick = Trick(leader=0, plays=[TrickPlay(0, [deck[101]])])
    rnd.turn = 1
    rnd.deck = deck
    return rnd


def test_public_hidden_twin_hash_is_invariant_but_world_hash_changes():
    public = type("R", (), {"hands": [["C3"], ["C4"], ["C5"], ["C6"]],
                             "buried": ["H5"], "banker": 0, "trump_rank": "7", "turn": 1})()
    twin = copy.copy(public)
    twin.hands = [list(h) for h in public.hands]
    twin.hands[0] = ["DK"]
    assert pt1._world_hash(public) != pt1._world_hash(twin)


def test_real_selector_public_arm_is_hidden_twin_invariant_and_b_c_are_not():
    first = _real_late_round()
    second = _real_late_round(hidden_swap=True)
    assert pt1.pt0_public_state_sha256(first, perspective_seat=1) == \
        pt1.pt0_public_state_sha256(second, perspective_seat=1)
    a_first = pt1._select_production(first, seed=11, arm="A")
    a_second = pt1._select_production(second, seed=11, arm="A")
    assert (a_first.ballot, a_first.selected_action,
            a_first.public_state_sha256) == \
        (a_second.ballot, a_second.selected_action, a_second.public_state_sha256)
    burial_twin = _real_late_round(burial_swap=True)
    a_burial = pt1._select_production(burial_twin, seed=11, arm="A")
    assert (a_first.ballot, a_first.selected_action,
            a_first.public_state_sha256) == \
        (a_burial.ballot, a_burial.selected_action, a_burial.public_state_sha256)
    b_first = pt1._select_production(
        first, seed=11, arm="B", true_world=first,
        world_identity=pt1._world_hash(first))
    b_second = pt1._select_production(
        second, seed=11, arm="B", true_world=second,
        world_identity=pt1._world_hash(second))
    assert b_first.true_world_sha256 != b_second.true_world_sha256
    assert pt1._world_hash(first) != pt1._world_hash(second)
    c_first = exact_world_action_values(
        first, world_sha256=pt1._world_hash(first), perspective_seat=1,
        max_hand_cards=2)
    c_second = exact_world_action_values(
        second, world_sha256=pt1._world_hash(second), perspective_seat=1,
        max_hand_cards=2)
    assert c_first.values.world_sha256 != c_second.values.world_sha256


def test_hidden_twin_changes_b_decision_and_c_exact_value_bytes():
    first = _decision_hidden_round()
    second = _decision_hidden_round(hidden_swap=True)
    b_first = pt1._select_production(
        first, seed=11, arm="B", true_world=first,
        world_identity=pt1._world_hash(first))
    b_second = pt1._select_production(
        second, seed=11, arm="B", true_world=second,
        world_identity=pt1._world_hash(second))
    assert b_first.selected_action != b_second.selected_action
    c_first = exact_world_action_values(
        first, world_sha256=pt1._world_hash(first), perspective_seat=1,
        max_hand_cards=2)
    c_second = exact_world_action_values(
        second, world_sha256=pt1._world_hash(second), perspective_seat=1,
        max_hand_cards=2)
    assert (c_first.values.action_utilities,
            c_first.final_attacker_points) != \
        (c_second.values.action_utilities, c_second.final_attacker_points)


def test_batch_reuses_one_exact_evaluation_and_matches_serial_bytes(monkeypatch):
    state = _real_late_round()
    sealed = pt1.seal_true_world(state)
    calls = {"exact": 0, "production": 0}
    original_exact = pt1.exact_world_action_values
    original_production = pt1._select_production

    def counted_exact(*args, **kwargs):
        calls["exact"] += 1
        return original_exact(*args, **kwargs)

    def counted_production(*args, **kwargs):
        calls["production"] += 1
        return original_production(*args, **kwargs)

    monkeypatch.setattr(pt1, "exact_world_action_values", counted_exact)
    monkeypatch.setattr(pt1, "_select_production", counted_production)
    monkeypatch.setattr(pt1.time, "perf_counter_ns", lambda: 123456)
    batched = pt1.evaluate_state_batch(
        state, sealed, seeds=(0, 1, 2, 3), max_hand_cards=2)
    assert calls["exact"] == 1
    assert calls["production"] == 8
    calls["exact"] = 0
    calls["production"] = 0
    serial = tuple(pt1.evaluate_state(
        state, sealed, seed=seed, max_hand_cards=2)
    for seed in (0, 1, 2, 3))
    assert calls["exact"] == 4
    assert calls["production"] == 8
    assert [record.canonical_bytes() for record in batched] == \
        [record.canonical_bytes() for record in serial]


def test_deadline_and_checkpoint_sink_are_whole_state_batches(monkeypatch):
    first = _real_late_round()
    second = _real_late_round()
    second.attacker_points = 1

    def fake_batch(public_round, true_world, *, seeds, **kwargs):
        public = pt1.pt0_public_state_sha256(public_round, perspective_seat=1)
        world = pt1._world_hash(true_world.verify())
        base = _record()
        evaluator = pt1._evaluator_identity(
            public, world, base.evaluation_action_utilities,
            base.evaluation_final_points, 0, 0)
        return tuple(replace(
            base, public_state_sha256=public, true_world_sha256=world,
            arms=tuple(replace(arm, public_state_sha256=public,
                               true_world_sha256=world, seed=seed,
                               evaluator_schema=evaluator)
                        for arm in base.arms), evaluator_identity=evaluator,
            capture_id_sha256=hashlib.sha256(
                f"{public}:{seed}".encode()).hexdigest())
                     for seed in seeds)

    monkeypatch.setattr(pt1, "evaluate_state_batch", fake_batch)
    checkpoints = []
    ticks = iter((0.0, 2.0))
    run = pt1.run_pt1(
        [(first, pt1.seal_true_world(first)),
         (second, pt1.seal_true_world(second))], seeds=(0, 1), deadline=1.0,
        monotonic=lambda: next(ticks), checkpoint_sink=checkpoints.append)
    assert run.status == "TRUNCATED"
    assert run.progress["completed_units"] == 2
    assert [json.loads(item.decode())["completed_units"] for item in checkpoints] == [2]
    assert all(len(record.arms) == 3 for record in run.records)


def test_record_is_immutable_and_semantic_tamper_refused():
    record = _record()
    assert pt1.verify_record(record) is record
    payload = record.payload()
    payload["selected_utilities"][0][1] = 99
    with pytest.raises(pt1.PrivilegedTeacherPT1Error, match="record hash drift"):
        pt1.verify_record(canonical_json_bytes(payload))


def test_arm_swap_and_sign_or_authority_tamper_refused():
    payload = _record().payload()
    payload["arms"][0]["arm"], payload["arms"][2]["arm"] = "C", "A"
    with pytest.raises(pt1.PrivilegedTeacherPT1Error, match="arm policy identity drift"):
        pt1.verify_record(_reseal(payload))
    payload = _record().payload()
    payload["arms"][0]["evaluator_schema"] = _sha("f")
    with pytest.raises(pt1.PrivilegedTeacherPT1Error, match="shared evaluator identity drift"):
        pt1.verify_record(_reseal(payload))
    payload = _record().payload()
    payload["arms"][1]["work"]["attempted_rollouts"] += 1
    with pytest.raises(pt1.PrivilegedTeacherPT1Error, match="A/B work parity drift"):
        pt1.verify_record(_reseal(payload))
    payload = _record().payload()
    payload["selected_utilities"][0], payload["selected_utilities"][1] = \
        payload["selected_utilities"][1], payload["selected_utilities"][0]
    with pytest.raises(pt1.PrivilegedTeacherPT1Error, match="arm/sign identity drift"):
        # Changing a signed utility must not be accepted as a new valid record.
        pt1.verify_record(_reseal(payload))
    payload = _record().payload()
    payload["authority"]["promotion_authorized"] = True
    with pytest.raises(pt1.PrivilegedTeacherPT1Error):
        pt1.verify_record(payload)


def test_a_b_ballot_must_equal_exact_legal_ballot():
    payload = _record().payload()
    # Keep A/B equal and re-seal: only the exact-legal-ballot invariant should
    # reject this semantically coherent but incomplete ballot.
    payload["arms"][0]["ballot"] = [["C4"]]
    payload["arms"][1]["ballot"] = [["C4"]]
    with pytest.raises(pt1.PrivilegedTeacherPT1Error,
                       match="A/B ballot is not exact legal ballot"):
        pt1.verify_record(_reseal(payload))


def test_a_b_production_ballot_must_match_each_other():
    payload = _record().payload()
    payload["arms"][0]["production_ballot"] = [["C4"]]
    payload["arms"][1]["production_ballot"] = [["C4"], ["D4"]]
    with pytest.raises(pt1.PrivilegedTeacherPT1Error,
                       match="A/B production ballot drift"):
        pt1.verify_record(_reseal(payload))


def test_true_world_capability_and_non_true_world_refusal():
    real = Round("7", banker=0)
    real.hands = [[], [], [], []]
    real.buried = []
    real.turn = 0
    sealed = pt1.TrueWorld.seal(real)
    assert sealed.verify() is real
    forged = pt1.TrueWorld(real, "0" * 64)
    with pytest.raises(pt1.PrivilegedTeacherPT1Error):
        forged.verify()


def test_canonical_record_includes_shared_evaluator_and_all_false_authority():
    payload = _record().payload()
    assert all(a["evaluator_schema"] == payload["evaluator_identity"]
               for a in payload["arms"])
    assert all(value is False for value in payload["authority"].values())


def test_run_prefix_is_explicitly_truncated_and_checkpoint_canonical():
    # A nonempty population with an expired deadline seals a zero-unit prefix;
    # it cannot be a complete result or silently pass a gate.
    state = _real_late_round()
    run = pt1.run_pt1(
        [(state, pt1.seal_true_world(state))], seeds=(0,), deadline=0.0,
        monotonic=lambda: 1.0)
    assert run.status == "TRUNCATED"
    assert run.truncated_by_deadline is True
    assert run.progress["completed_units"] == 0
    assert run.progress["total_units"] == 1
    assert canonical_json_bytes(json.loads(run.checkpoint.decode())) == run.checkpoint


def test_checkpoint_resume_reopens_prefix_and_is_byte_identical(monkeypatch):
    state = _real_late_round()
    second_state = _real_late_round()
    second_state.attacker_points = 1

    def fake_evaluate(public_round, true_world, *, seed, **kwargs):
        public = pt1.pt0_public_state_sha256(public_round, perspective_seat=1)
        world = pt1._world_hash(true_world.verify())
        base = _record()
        evaluator = pt1._evaluator_identity(
            public, world, base.evaluation_action_utilities,
            base.evaluation_final_points, 0, 0)
        arms = tuple(replace(a, public_state_sha256=public,
                             true_world_sha256=world,
                             seed=seed, evaluator_schema=evaluator)
                     for a in base.arms)
        return replace(base, public_state_sha256=public,
                       true_world_sha256=world, arms=arms,
                       evaluator_identity=evaluator,
                               capture_id_sha256=hashlib.sha256(
                               f"{public}:{seed}".encode()).hexdigest())

    monkeypatch.setattr(pt1, "evaluate_state_batch",
                        lambda public, true, *, seeds, **kwargs:
                        tuple(fake_evaluate(public, true, seed=seed)
                              for seed in seeds))
    ticks = iter((0.0, 2.0))
    states = [(state, pt1.seal_true_world(state)),
              (second_state, pt1.seal_true_world(second_state))]
    partial = pt1.run_pt1(states,
                           seeds=(0, 1), deadline=1.0,
                           monotonic=lambda: next(ticks))
    assert partial.status == "TRUNCATED"
    resumed = pt1.run_pt1(states,
                           seeds=(0, 1), checkpoint=partial.checkpoint,
                           monotonic=lambda: 0.0)
    full = pt1.run_pt1(states,
                        seeds=(0, 1), monotonic=lambda: 0.0)
    assert resumed.status == "COMPLETE"
    assert resumed.payload() == full.payload()


def test_frozen_work_contract_is_30_and_300():
    payload = _record().payload()
    for arm in payload["arms"][:2]:
        assert arm["work"]["n_determinizations"] == 30
        assert arm["work"]["report_worlds"] == 300


def test_first_run_underfill_refuses_before_checkpoint_emission(monkeypatch):
    state = _real_late_round()

    class UnderfilledProduction:
        search_calls = 1
        last_decision_record = None

        def decide_play(self, rnd, seat):
            self.last_decision_record = {
                "candidates": [["C2"], ["C5"]],
                "n_determinizations": 30,
                "report_worlds_requested": 300,
                "alloc": {"attempts": 29, "worlds": 29, "rollouts": 58,
                          "budget": 60, "short": True,
                          "n_by_candidate": [29, 29]},
                "report_fold": {"attempts": 300, "worlds": 300,
                                "complete": True},
                "work": {"selection_budget": 60, "selection_rollouts": 58,
                         "report_budget": 600, "report_rollouts": 600,
                         "total_budget": 660, "total_rollouts": 658},
            }
            return ["C2"]

    monkeypatch.setattr(
        pt1, "_production_bot",
        lambda seed, true_world=None: UnderfilledProduction())
    emitted = []
    with pytest.raises(pt1.PrivilegedTeacherPT1Error,
                       match="production selection work incomplete"):
        pt1.run_pt1(
            [(state, pt1.seal_true_world(state))], seeds=(0,),
            checkpoint_sink=emitted.append)
    assert emitted == []


def test_runner_fsyncs_directory_for_final_and_progress_publication(
        monkeypatch, tmp_path):
    calls = []
    original = pt1_runner._fsync_directory

    def spy(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(pt1_runner, "_fsync_directory", spy)
    pt1_runner._write_once(tmp_path / "packet.json", b"packet\n")
    pt1_runner._write_progress(tmp_path / "progress.json", {
        "completed_units": 1, "total_units": 1,
        "status": "COMPLETE", "truncated_by_deadline": False})
    assert len(calls) >= 3  # final link + temp cleanup, progress replace
    assert all(path == tmp_path for path in calls)


def test_cli_advances_two_truncations_and_refuses_divergent_checkpoint(
        monkeypatch, tmp_path):
    state = _real_late_round()
    second_state = _real_late_round()
    second_state.attacker_points = 1

    def fake_evaluate(public_round, true_world, *, seed, **kwargs):
        public = pt1.pt0_public_state_sha256(public_round, perspective_seat=1)
        world = pt1._world_hash(true_world.verify())
        base = _record()
        evaluator = pt1._evaluator_identity(
            public, world, base.evaluation_action_utilities,
            base.evaluation_final_points, 0, 0)
        arms = tuple(replace(a, public_state_sha256=public,
                             true_world_sha256=world, seed=seed,
                             evaluator_schema=evaluator)
                     for a in base.arms)
        return replace(base, public_state_sha256=public,
                       true_world_sha256=world, arms=arms,
                       evaluator_identity=evaluator,
                       capture_id_sha256=hashlib.sha256(
                           f"{public}:{seed}".encode()).hexdigest())

    monkeypatch.setattr(pt1, "evaluate_state_batch",
                        lambda public, true, *, seeds, **kwargs:
                        tuple(fake_evaluate(public, true, seed=seed)
                              for seed in seeds))
    monkeypatch.setattr(pt1_runner, "_load_states",
                        lambda path: [(state, pt1.seal_true_world(state)),
                                      (second_state, pt1.seal_true_world(second_state))])
    invocation = {"count": 0}

    def wrapped_run(states, *, seeds, deadline, checkpoint, checkpoint_sink):
        invocation["count"] += 1
        if invocation["count"] < 3:
            ticks = iter((0.0, 2.0))
            return pt1.run_pt1(
                states, seeds=seeds, deadline=1.0, checkpoint=checkpoint,
                monotonic=lambda: next(ticks), checkpoint_sink=checkpoint_sink)
        return pt1.run_pt1(
            states, seeds=seeds, deadline=None, checkpoint=checkpoint,
            monotonic=lambda: 0.0, checkpoint_sink=checkpoint_sink)

    monkeypatch.setattr(pt1_runner, "run_pt1", wrapped_run)
    provider = tmp_path / "states.py"
    provider.write_text("def load_states():\n    return []\n")
    output = tmp_path / "out"
    args = ["--states", str(provider), "--output-dir", str(output),
            "--seeds", "0,1,2", "--deadline-seconds", "1"]
    assert pt1_runner.main(args) == 0
    first_checkpoint = (output / "checkpoint.json").read_bytes()
    assert json.loads(first_checkpoint)["completed_units"] == 3
    assert pt1_runner.main(args + ["--resume"]) == 0
    second_checkpoint = (output / "checkpoint.json").read_bytes()
    assert json.loads(second_checkpoint)["completed_units"] == 6
    assert first_checkpoint != second_checkpoint
    divergent = json.loads(second_checkpoint)
    divergent["records"][0]["capture_id_sha256"] = "f" * 64
    (output / "checkpoint.json").write_bytes(canonical_json_bytes(divergent))
    with pytest.raises(SystemExit):
        pt1_runner.main(args + ["--resume"])
    (output / "checkpoint.json").write_bytes(second_checkpoint)
    semantic = json.loads(second_checkpoint)
    mutated = semantic["records"][0]
    mutated["arms"][1]["selected_action"] = ["D4"]
    mutated["record_sha256"] = hashlib.sha256(canonical_json_bytes(
        {k: mutated[k] for k in mutated if k != "record_sha256"})).hexdigest()
    semantic_bytes = canonical_json_bytes(semantic)
    (output / "checkpoint.json").write_bytes(semantic_bytes)
    with pytest.raises(pt1.PrivilegedTeacherPT1Error,
                       match="checkpoint replay semantic drift"):
        pt1.run_pt1([(state, pt1.seal_true_world(state)),
                     (second_state, pt1.seal_true_world(second_state))],
                    seeds=(0, 1, 2),
                    checkpoint=semantic_bytes, monotonic=lambda: 0.0)
    with pytest.raises(SystemExit):
        pt1_runner.main(args + ["--resume"])
    (output / "checkpoint.json").write_bytes(second_checkpoint)
    (output / "packet.json").unlink()
    (output / "manifest.json").unlink()

    original_write_once = pt1_runner._write_once
    def crash_once(path, data):
        raise RuntimeError("injected final-artifact crash")
    monkeypatch.setattr(pt1_runner, "_write_once", crash_once)
    with pytest.raises(RuntimeError, match="injected final-artifact crash"):
        pt1_runner.main(args + ["--resume"])
    assert json.loads((output / "checkpoint.json").read_bytes())["truncated_by_deadline"] is False
    assert not (output / "packet.json").exists()
    monkeypatch.setattr(pt1_runner, "_write_once", original_write_once)
    assert pt1_runner.main(args + ["--resume"]) == 0
    assert json.loads((output / "progress.json").read_bytes())["status"] == "COMPLETE"
    assert (output / "packet.json").is_file()
    assert (output / "manifest.json").is_file()
