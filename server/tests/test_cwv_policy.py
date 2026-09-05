"""Witnesses for the complete-world value evaluator and the one-ply bot.

Every test carries its mutation: the assertion that would go RED if the
guarded behaviour were dropped is exercised against an explicit mutant, so a
GREEN here means the check discriminates rather than merely passes.
"""
from __future__ import annotations

import copy
import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import cwv_policy
from shengji.ai.cwv_policy import (
    CWVCheckpointMismatch,
    CWVOnePlyBot,
    CompleteWorldEvaluator,
    StratifiedPriorEvaluator,
    afterstate_encoder_identity,
    control_name,
    cwv_registry_entries,
    env_registry_entries,
    load_cwv_checkpoint,
    policy_name,
    prior_table_from,
    verify_checkpoint_identity,
)
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.ai.registry import REGISTRY, make_bot, register_cwv_policies
from shengji.ai.smart import SmartBot
from shengji.engine.ballot import ballot_for_policy
from shengji.engine.game import Game
from shengji.rl.value_afterstate import apply_action, category_signed_level
from shengji.rl.value_checkpoint import save_checkpoint
from shengji.rl.value_inference import predict_round
from shengji.rl.value_model import ValueModelConfig, ValueNetwork


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    """A tiny checkpoint trained through value_training on two rounds."""
    out = tmp_path_factory.mktemp("cwv") / "tiny.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(out), rounds=2, max_epochs=2, quiet=True)
    return str(out)


def _state_after(seed: int, plies: int):
    """A complete round (every hand known) after ``plies`` heuristic plays."""
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bots = [SmartBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    for _ in range(plies):
        if rnd.phase != "play":
            break
        seat = rnd.turn
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return rnd


def _state_where(seed: int, predicate, *, start: int = 0, limit: int = 100):
    for plies in range(start, limit):
        rnd = _state_after(seed, plies)
        if rnd.phase == "play" and predicate(rnd):
            return rnd
    raise AssertionError("no state satisfied the predicate")


def _root_play(position, seat: int) -> list[str]:
    """The cards ``seat`` played in the position's newest trick."""
    if position.trick is not None:
        for play in position.trick.plays:
            if play.seat == seat:
                return list(play.cards)
    for play in position.history[-1].plays:
        if play.seat == seat:
            return list(play.cards)
    raise AssertionError("root seat has not played in the newest trick")


class _StubEvaluator:
    """Scores positions by a rule on the root's own play; records batches."""

    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, rule):
        self.rule = rule
        self.batches = []
        self.positions = 0

    def identity(self):
        return {"kind": "stub"}

    def score(self, positions, root_seat):
        self.batches.append((list(positions), root_seat))
        self.positions += len(positions)
        return np.asarray([self.rule(position, root_seat, index)
                           for index, position in enumerate(positions)],
                          dtype=np.float64)


# ------------------------------------------------------------ 1. evaluator

def test_batched_scores_equal_per_position_api_and_terminals_bypass_model(checkpoint):
    model, _meta, _sha = load_cwv_checkpoint(checkpoint)
    rnd = _state_where(3, lambda r: len(MCBot(seed=0)._candidates(r, r.turn)) >= 3,
                       start=6)
    seat = rnd.turn
    candidates = MCBot(seed=0)._candidates(rnd, seat)[:3]
    positions = [apply_action(rnd, seat, cand)[0] for cand in candidates]
    terminal = _state_after(5, 100)
    assert terminal.phase == "round_end"
    positions.append(terminal)

    for max_batch in (4096, 2):          # one forward, and forced chunking
        evaluator = CompleteWorldEvaluator(checkpoint, max_batch=max_batch)
        batched = evaluator.score(positions, seat)
        single = [predict_round(model, p, seat).expected_signed_level
                  for p in positions]
        assert batched.shape == (4,)
        assert np.allclose(batched, single, atol=1e-6), (batched, single)
    assert evaluator.forward_calls == 2 and evaluator.terminal_rows == 1

    # RED when the perspective is taken from the wrong seat: the same
    # positions scored for the opponent's seat are different numbers, and the
    # exact terminal value flips its sign.
    other = (seat + 1) % 4
    flipped = evaluator.score(positions, other)
    assert not np.allclose(flipped[:3], batched[:3])
    assert flipped[3] == pytest.approx(-batched[3])
    assert batched[3] == category_signed_level(
        __import__("shengji.rl.value_afterstate", fromlist=["x"])
        .signed_level_category(terminal.attacker_points, terminal.is_attacker(seat)))

    # Terminal positions bypass the model exactly: a model that refuses to run
    # scores a terminal, and is what RED looks like for any other position.
    class MustNotRun:
        def __call__(self, *args, **kwargs):
            raise AssertionError("terminal evaluation called the model")

    guarded = CompleteWorldEvaluator(None, model=MustNotRun())
    assert guarded.score([terminal], seat)[0] == batched[3]
    with pytest.raises(AssertionError, match="called the model"):
        guarded.score([positions[0]], seat)


def test_mlp_architecture_receives_a_history_free_batch_with_identical_scores():
    """The training build's ``mlp`` ignores history; the evaluator must not
    pay for the padded sequence, and the fixed-size tensors must be intact."""
    import torch
    from types import SimpleNamespace
    from shengji.rl.value_afterstate import (PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
                                             tensors_from_round)
    from shengji.rl.encode import N_CARDS

    class HistoryFree(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(architecture="mlp")
            self.head = torch.nn.Linear(PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM,
                                        204)
            self.history_lengths = []

        def forward(self, public, history, mask, world, perspective):
            self.history_lengths.append(int(history.shape[1]))
            assert mask.dtype == torch.bool and bool(torch.all(mask.any(dim=1)))
            return self.head(torch.cat((public, world.flatten(start_dim=1), perspective), dim=1))

    torch.manual_seed(3)
    model = HistoryFree()
    rnd = _state_after(23, 30)
    seat = rnd.turn
    candidates = MCBot(seed=0)._candidates(rnd, seat)[:3]
    positions = [apply_action(rnd, seat, cand)[0] for cand in candidates]
    evaluator = CompleteWorldEvaluator(None, model=model)
    scores = evaluator.score(positions, seat)
    assert model.history_lengths == [1], "the mlp path sends a one-row history"
    rows = [tensors_from_round(p, seat) for p in positions]
    full = [predict_tensors_reference(model, row) for row in rows]
    assert np.allclose(scores, full, atol=1e-6)
    # RED when the history-free path corrupts the fixed-size tensors: the
    # sequence path (full history) must give the same numbers.
    model.config.architecture = "gru"
    assert np.allclose(evaluator.score(positions, seat), scores, atol=1e-6)
    assert model.history_lengths[-1] > 1


def predict_tensors_reference(model, row):
    """#214's predict_tensors on one row (full padded history)."""
    from shengji.rl.value_inference import predict_tensors
    return predict_tensors(model, [row])[0].expected_signed_level


def test_encoder_identity_is_the_training_builds_recipe():
    import hashlib
    from shengji.rl.value_afterstate import AFTERSTATE_SCHEMA

    identity = afterstate_encoder_identity()
    assert identity["identity_schema"] == "shengji-cwv-encoder-identity-v1"
    assert set(identity["source_sha256s"]) == {
        "value_afterstate", "encode", "douzero_micro", "memory", "cards",
        "combos", "round", "rebuild", "teacher_v1"}
    payload = "|".join(
        ["shengji-cwv-encoder-identity-v1", AFTERSTATE_SCHEMA]
        + [f"{name}:{sha}" for name, sha in sorted(identity["source_sha256s"].items())])
    assert identity["implementation_sha256"] == hashlib.sha256(payload.encode("ascii")).hexdigest()
    for name, path in cwv_policy.AFTERSTATE_SOURCE_PATHS.items():
        assert identity["source_sha256s"][name] == cwv_policy.file_sha256(path)
    assert cwv_policy.local_encoder_identity()["implementation_sha256"] == \
        identity["implementation_sha256"]
    # a declaration carrying drifted sources is refused and the file is named
    drifted = {"encoder": {**identity, "implementation_sha256": "f" * 64,
                           "source_sha256s": {**identity["source_sha256s"], "memory": "0" * 64}}}
    with pytest.raises(CWVCheckpointMismatch, match="drifted sources: memory"):
        verify_checkpoint_identity(drifted)


# ------------------------------------------------------------- 2. decision

def test_one_ply_decision_plays_the_candidate_the_evaluator_prefers(checkpoint):
    rnd = _state_where(7, lambda r: len(MCBot(seed=0)._candidates(r, r.turn)) >= 3,
                       start=4)
    seat = rnd.turn
    candidates = MCBot(seed=0)._candidates(rnd, seat)
    assert len(candidates) >= 3
    for target in (1, 2):
        wanted = sorted(candidates[target])
        stub = _StubEvaluator(
            lambda p, s, i, w=wanted: 5.0 if sorted(_root_play(p, s)) == w else -5.0)
        bot = CWVOnePlyBot(seed=1, evaluator=stub)
        bot.CWV_WORLDS = 4
        bot.CWV_FINISH_TRICK = False
        played = bot.decide_play(copy.deepcopy(rnd), seat)
        assert sorted(played) == wanted
        record = bot.last_decision_record
        assert record["schema"] == "cwv-decision-v1"
        assert record["raw_winner_index"] == record["played_index"] == target
        assert record["worlds"] == 4 and record["work"]["positions"] == 4 * len(candidates)
        assert len(stub.batches) == 1, "all W x |ballot| positions go in ONE batch"
        assert stub.batches[0][1] == seat
        assert bot.positions_evaluated == 4 * len(candidates)

    # RED when the argmax is taken over the wrong axis: a mutant that reduces
    # over CANDIDATES (per-world means, which all tie here) can no longer see
    # the target and falls back to candidate 0.
    wanted = sorted(candidates[1])
    stub = _StubEvaluator(
        lambda p, s, i: 5.0 if sorted(_root_play(p, s)) == wanted else -5.0)
    bot = CWVOnePlyBot(seed=1, evaluator=stub)
    bot.CWV_WORLDS = 4
    bot.CWV_FINISH_TRICK = False

    def wrong_axis(matrix, lcb_k):
        per_world = np.asarray(matrix).mean(axis=1)
        return np.resize(per_world, matrix.shape[1]), np.zeros(matrix.shape[1])
    bot.reduce_scores = wrong_axis
    assert sorted(bot.decide_play(copy.deepcopy(rnd), seat)) != wanted


def test_reduce_scores_mean_and_lcb():
    matrix = np.asarray([[1.0, 4.0, 2.0], [3.0, 0.0, 2.0], [2.0, 2.0, 2.0],
                         [2.0, 2.0, 2.0]])
    score, se = CWVOnePlyBot.reduce_scores(matrix, 0.0)
    assert np.allclose(score, [2.0, 2.0, 2.0]) and se[2] == 0.0
    lcb, _ = CWVOnePlyBot.reduce_scores(matrix, 1.0)
    assert int(np.argmax(lcb)) == 2, "the LCB prefers the certain candidate"
    assert np.argmax(score) == 0, "ties resolve to the FIRST candidate"


# ------------------------------------------------------------- 3. sampler

def test_world_sampling_is_productions_canonicalised_sampler(monkeypatch):
    rnd = _state_after(11, 9)
    seat = rnd.turn
    stub = _StubEvaluator(lambda p, s, i: 0.0)
    prod = MCBot(seed=21)
    bot = CWVOnePlyBot(seed=21, evaluator=stub)
    mem_p = Memory(rnd, seat, own_kitty=True)
    mem_b = Memory(rnd, seat, own_kitty=True)
    expected, raw = [], []
    while len(expected) < 6:
        sampled = prod._sample_hands(rnd, seat, mem_p)
        if sampled is None:
            continue
        hands, buried = sampled
        raw.append(hands)
        expected.append((prod._complete_determinized_hands(
            rnd, seat, hands, buried=buried), sorted(buried)))
    got, attempts = bot.sample_worlds(rnd, seat, 6, mem=mem_b)
    assert got == expected and attempts >= 6
    assert bot.accepted_worlds == prod.accepted_worlds

    # RED when the canonicalisation is skipped: the raw sampler hands are
    # multisets in incidental order, so an uncanonicalised world differs.
    assert any(hand != sorted(hand) for hands in raw for hand in hands.values())

    def uncanonical(self, rnd_, seat_, sampled, *, buried):
        return [list(rnd_.hands[s]) if s == seat_ else list(sampled[s])
                for s in range(4)]
    monkeypatch.setattr(CWVOnePlyBot, "_complete_determinized_hands", uncanonical)
    mutant = CWVOnePlyBot(seed=21, evaluator=stub)
    mutated, _ = mutant.sample_worlds(rnd, seat, 6, mem=Memory(rnd, seat, own_kitty=True))
    assert mutated != expected


# ---------------------------------------------------------- 4. finish trick

def _check_finish_trick(positions, root, seat, finish: bool):
    for position in positions:
        if position.phase == "round_end":
            continue
        if finish:
            assert len(position.history) == len(root.history) + 1, \
                "the root's trick must be resolved -- and only that trick"
            assert position.trick.plays == [], "no play beyond the current trick"
            assert _root_play(position, seat)
        elif len(root.trick.plays) == 3:
            assert len(position.history) == len(root.history) + 1
            assert position.trick.plays == []
        else:
            assert len(position.history) == len(root.history)
            assert len(position.trick.plays) == len(root.trick.plays) + 1
            assert position.trick.plays[-1].seat == seat


@pytest.mark.parametrize("finish", [True, False])
def test_finish_trick_finishes_exactly_the_current_trick(finish, monkeypatch):
    lead_state = _state_where(
        13, lambda r: not r.trick.plays and len(MCBot(seed=0)._candidates(r, r.turn)) >= 2,
        start=4)
    follow_state = _state_where(
        13, lambda r: len(r.trick.plays) == 2
        and len(MCBot(seed=0)._candidates(r, r.turn)) >= 2, start=4)
    for root in (lead_state, follow_state):
        seat = root.turn
        stub = _StubEvaluator(lambda p, s, i: float(i % 3))
        bot = CWVOnePlyBot(seed=2, evaluator=stub)
        bot.CWV_WORLDS = 3
        bot.CWV_FINISH_TRICK = finish
        bot.TRACTOR_LOCK = False
        bot.decide_play(copy.deepcopy(root), seat)
        positions = stub.batches[0][0]
        assert len(positions) == 3 * len(bot.last_decision_record["candidates"])
        _check_finish_trick(positions, root, seat, finish)
        # the stable consumer helper builds the very same world-major batch
        twin = CWVOnePlyBot(seed=2, evaluator=stub)
        twin.TRACTOR_LOCK = False
        candidates = twin._candidates(root, seat)
        worlds, _ = cwv_policy.sample_worlds(twin, root, seat, 3)
        rebuilt = cwv_policy.positions_from_candidates(
            root, seat, candidates, worlds, finish_trick=finish)
        assert len(rebuilt) == len(positions)
        for mine, theirs in zip(positions, rebuilt):
            if mine.phase == "round_end":
                assert theirs.phase == "round_end"
                continue
            from shengji.rl.value_afterstate import tensors_from_round
            assert tensors_from_round(mine, seat).sha256() == \
                tensors_from_round(theirs, seat).sha256()
        assert [list(h) for h in root.hands] == [list(h) for h in copy.deepcopy(root).hands]

    if finish:
        # RED when it plays an extra trick: a mutant that keeps going past the
        # resolved trick leaves plays in the next trick, which the check
        # refuses.
        original = CWVOnePlyBot._finish_trick

        def one_play_too_many(self, clone):
            original(self, clone)
            if clone.phase == "play":
                s = clone.turn
                clone.play(s, self.rollout_policy.decide_play(clone, s))
        monkeypatch.setattr(CWVOnePlyBot, "_finish_trick", one_play_too_many)
        stub = _StubEvaluator(lambda p, s, i: 0.0)
        mutant = CWVOnePlyBot(seed=2, evaluator=stub)
        mutant.CWV_WORLDS = 3
        mutant.TRACTOR_LOCK = False
        mutant.decide_play(copy.deepcopy(lead_state), lead_state.turn)
        with pytest.raises(AssertionError):
            _check_finish_trick(stub.batches[0][0], lead_state, lead_state.turn, True)


# --------------------------------------------------------------- 5. registry

def test_registry_names_embed_checkpoint_and_share_productions_ballot(checkpoint):
    sha8 = cwv_policy.checkpoint_id(checkpoint)
    entries = cwv_registry_entries(checkpoint, [7])
    assert set(entries) == {f"mc-cwv-{sha8}-w7", "mc-cwv-prior-w7"}
    assert policy_name(sha8, 7) == f"mc-cwv-{sha8}-w7"
    assert control_name(7, lcb=1.5) == "mc-cwv-prior-w7-lcb1.5"
    names = register_cwv_policies(checkpoint, [7])
    try:
        arm = make_bot(f"mc-cwv-{sha8}-w7", seed=3)
        assert isinstance(arm, CWVOnePlyBot) and arm.CWV_WORLDS == 7
        assert arm.cwv_ckpt8 == sha8 and arm.policy_name == f"mc-cwv-{sha8}-w7"
        assert arm.seed == 3 and arm.CWV_FINISH_TRICK is True
        control = make_bot("mc-cwv-prior-w7", seed=4)
        assert isinstance(control.evaluator, StratifiedPriorEvaluator)
        assert set(control.evaluator.table) <= set(cwv_policy.PRIOR_STRATA)
        # the arm and its control enumerate exactly production's ballot
        production = ballot_for_policy("mc-s0-report-lcb")
        for name in names:
            assert ballot_for_policy(name).digest == production.digest, name
    finally:
        for name in names:
            REGISTRY.pop(name, None)

    env = {"SHENGJI_CWV_CKPT": checkpoint, "SHENGJI_CWV_WORLDS": "5,9",
           "SHENGJI_CWV_FINISH_TRICK": "0", "SHENGJI_CWV_LCB": "0"}
    assert set(env_registry_entries(env)) == {
        f"mc-cwv-{sha8}-w5", f"mc-cwv-{sha8}-w9", "mc-cwv-prior-w5", "mc-cwv-prior-w9"}
    assert env_registry_entries({}) == {}


def test_foreign_or_mismatched_checkpoint_is_refused(tmp_path, monkeypatch):
    config = ValueModelConfig(architecture="gru", width=8, history_layers=1,
                              attention_heads=2, feedforward_width=16)
    identity = afterstate_encoder_identity()
    foreign = tmp_path / "foreign.pt"
    save_checkpoint(foreign, ValueNetwork(config), metadata={"best_epoch": 1})
    with pytest.raises(CWVCheckpointMismatch, match="no afterstate encoder identity"):
        load_cwv_checkpoint(foreign)
    with pytest.raises(CWVCheckpointMismatch):
        cwv_registry_entries(foreign, [3])[f"mc-cwv-{cwv_policy.checkpoint_id(foreign)}-w3"](seed=1)

    drifted = tmp_path / "drifted.pt"
    save_checkpoint(drifted, ValueNetwork(config), metadata={
        "encoder": {"implementation_sha256": "0" * 64}})
    with pytest.raises(CWVCheckpointMismatch, match="matches neither"):
        load_cwv_checkpoint(drifted)

    # every accepted declaration form
    for meta in ({"encoder": {"implementation_sha256": identity["implementation_sha256"]}},
                 {"encoder_identity": identity["source_sha256s"]["value_afterstate"]},
                 {"afterstate_encoder": identity["implementation_sha256"]}):
        assert verify_checkpoint_identity(meta) in (
            identity["implementation_sha256"],
            identity["source_sha256s"]["value_afterstate"])

    # RED when the check is skipped: with the gate disabled the foreign
    # checkpoint loads, so the gate is the only thing refusing it.
    monkeypatch.setattr(cwv_policy, "verify_checkpoint_identity",
                        lambda metadata, **kw: "skipped")
    skipped = tmp_path / "skipped.pt"
    save_checkpoint(skipped, ValueNetwork(config), metadata={"best_epoch": 1})
    model, metadata, sha = load_cwv_checkpoint(skipped)
    assert metadata == {"best_epoch": 1} and len(sha) == 64


def test_prior_table_forms_and_control_scores_by_stratum():
    uniform = [1.0 / 204] * 204
    table, default = prior_table_from({
        "global_probability": uniform,
        "strata_probability": [["early|attacker", uniform]]})
    assert table["early|attacker"] == pytest.approx(default)
    table, default = prior_table_from({"strata": {"late|defender": 1.5}, "global": -0.5})
    assert table == {"late|defender": 1.5} and default == -0.5
    table, default = prior_table_from({"global_mean": 0.25, "cells": [
        {"stratum": "middle|attacker|0-39", "n": 3, "mean": 1.0},
        {"stratum": "middle|attacker|40-79", "n": 1, "mean": -1.0}]})
    assert table == {"middle|attacker": pytest.approx(0.5)} and default == 0.25
    with pytest.raises(cwv_policy.CWVError):
        prior_table_from({"strata": {"never|attacker": 1.0}})

    rnd = _state_after(17, 3)
    evaluator = StratifiedPriorEvaluator({"early|attacker": 2.0, "early|defender": -2.0},
                                         0.0, source="test")
    seat = rnd.turn
    value = evaluator.score([rnd], seat)[0]
    assert value == (2.0 if rnd.is_attacker(seat) else -2.0)
    terminal = _state_after(17, 100)
    assert evaluator.score([terminal], seat)[0] == category_signed_level(
        __import__("shengji.rl.value_afterstate", fromlist=["x"])
        .signed_level_category(terminal.attacker_points, terminal.is_attacker(seat)))
