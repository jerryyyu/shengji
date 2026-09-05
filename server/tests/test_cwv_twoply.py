"""Witnesses for the complete-world TWO-PLY bot (``CWVTwoPlyBot``).

Each witness carries its mutation: the assertion that would go RED if the
guarded behaviour were dropped is exercised against an explicit mutant.

1. replies are the net's argmax over production's ballot in EVERY world
   (RED when a reply falls back to the heuristic finisher);
2. the perspective flips at each ply: a reply seat maximises ITS team's
   expected level (RED when replies are scored from the root's perspective);
3. ``plies=1`` finishes exactly the current trick, ``plies=2`` exactly one
   more (RED when one extra play happens);
4. one mixed-seat batch equals per-position scoring within 1e-6 (RED when
   rows are misassigned);
5. a terminal reached mid-ply takes its exact value and never touches the
   net (RED when terminals are routed through the model);
6. the calibration binding carries ``plies`` and refuses a mismatch.
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
    CWVError,
    CWVOnePlyBot,
    CWVTwoPlyBot,
    CompleteWorldEvaluator,
    StratifiedPriorEvaluator,
    child_position,
    control_name,
    cwv_registry_entries,
    env_registry_entries,
    finish_current_trick,
    load_cwv_checkpoint,
    policy_name,
)
from shengji.ai.mcbot import MCBot
from shengji.ai.registry import REGISTRY, make_bot, register_cwv_policies
from shengji.ai.smart import SmartBot
from shengji.engine.ballot import ballot_for_policy
from shengji.engine.game import Game
from shengji.rl.value_afterstate import (
    category_signed_level,
    signed_level_category,
    terminal_distribution,
)
from shengji.rl.value_inference import predict_round


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("cwv2") / "tiny.pt"
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


def _contested(rnd) -> bool:
    return len(MCBot(seed=0)._candidates(rnd, rnd.turn)) >= 2


def _last_play(position):
    """The newest play of a position (the move whose afterstate it is)."""
    if position.trick is not None and position.trick.plays:
        return position.trick.plays[-1]
    return position.history[-1].plays[-1]


def _key(cards) -> float:
    """A strict total order over card multisets (distinct sets, distinct keys)."""
    text = "".join(sorted(cards))
    return float(sum((index + 1) * ord(ch) * 7919 ** (index % 3)
                     for index, ch in enumerate(text)) % 10_000_019) + 0.5 * len(cards)


class _StubNet:
    """A stub evaluator with ``score_many``: a rule on (position, seat)."""

    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, rule):
        self.rule = rule
        self.batches: list[tuple[list, list[int]]] = []
        self.movers: list[list[int]] = []
        self.forward_calls = 0

    def identity(self):
        return {"kind": "stub"}

    def score(self, positions, root_seat):
        return self.score_many(positions, [root_seat] * len(positions))

    def score_many(self, positions, seats):
        # positions are recorded AT SCORING TIME: the bot re-uses a chosen
        # child as the next clone, so the objects move on afterwards
        self.batches.append((list(positions), list(seats)))
        self.movers.append([_last_play(p).seat for p in positions])
        self.forward_calls += 1
        return np.asarray([self.rule(p, s) for p, s in zip(positions, seats)],
                          dtype=np.float64)


def _two_ply(evaluator, *, worlds: int = 3, plies: int = 1, seed: int = 2) -> CWVTwoPlyBot:
    bot = CWVTwoPlyBot(seed=seed, evaluator=evaluator)
    bot.CWV_WORLDS = worlds
    bot.CWV_PLIES = plies
    bot.CWV_TRACE_PLIES = True
    bot.TRACTOR_LOCK = False
    return bot


def _replay(bot: CWVTwoPlyBot, root, seat: int, positions, expect):
    """Walk every final position from its root afterstate and compare each
    contested reply against ``expect(clone, moving_seat, ballot)``.

    Returns ``(contested replies checked, replies that differ)``.  The ballot
    is production's, regenerated independently of the bot's own reply loop.
    """
    worlds = bot.last_worlds
    candidates = bot.last_decision_record["candidates"]
    checked = differing = 0
    for w, (hands, buried) in enumerate(worlds):
        for k, cand in enumerate(candidates):
            final = positions[w * len(candidates) + k]
            clone = cwv_policy.afterstate(root, seat, hands, buried, cand, finish_trick=False)
            plays = [p for trick in final.history[len(root.history):] for p in trick.plays]
            if final.trick is not None:
                plays.extend(final.trick.plays)
            for play in plays[len(root.trick.plays) + 1:]:        # after the root's move
                mover = clone.turn
                assert mover == play.seat
                ballot = bot._reply_candidates(clone, mover)
                if len(ballot) > 1:
                    checked += 1
                    if sorted(play.cards) != sorted(expect(clone, mover, ballot)):
                        differing += 1
                clone.play(mover, list(play.cards))
            assert clone.phase == final.phase
    return checked, differing


# ------------------------------------------ 1. replies are the net's choice

def test_replies_are_the_stubs_argmax_in_every_world_never_the_heuristic(monkeypatch):
    root = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    seat = root.turn
    stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
    bot = _two_ply(stub, worlds=3)
    bot.decide_play(copy.deepcopy(root), seat)
    positions = stub.batches[-1][0]                          # the final root forward
    assert stub.batches[-1][1] == [seat] * len(positions)
    checked, differing = _replay(bot, root, seat, positions,
                                 lambda clone, mover, ballot: max(ballot, key=_key))
    assert checked >= 3 and differing == 0, (checked, differing)
    # every reply step was ONE batch: root forward + one per ply step
    work = bot.last_decision_record["work"]
    assert work["ply_steps"] == 3 and work["forward_passes"] == 4
    assert len(stub.batches) == 4
    assert work["reply_positions"] > 0
    assert work["positions"] == work["root_positions"] + work["reply_positions"]
    assert bot.positions_evaluated == work["positions"]
    # the trace agrees with the replay: chosen == argmax of the recorded values
    for step in bot.last_ply_trace:
        for entry in step:
            if entry["values"] is not None:
                assert entry["chosen"] == int(np.argmax(entry["values"]))
                assert entry["chosen"] == max(range(len(entry["candidates"])),
                                              key=lambda i: _key(entry["candidates"][i]))

    # RED when replies fall back to the heuristic: a mutant whose reply loop
    # is the one-ply bot's trick finisher plays what the heuristic likes, and
    # the replay finds replies that are not the stub's argmax.
    def heuristic_replies(self, clones, target_tricks):
        for clone in clones:
            finish_current_trick(clone, self.rollout_policy)
        return {"reply_positions": 0, "ply_steps": 0, "plies": 1}
    monkeypatch.setattr(CWVTwoPlyBot, "_reply_plies", heuristic_replies)
    stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
    mutant = _two_ply(stub, worlds=3)
    mutant.decide_play(copy.deepcopy(root), seat)
    checked, differing = _replay(mutant, root, seat, stub.batches[-1][0],
                                 lambda clone, mover, ballot: max(ballot, key=_key))
    assert checked >= 3 and differing > 0, "the heuristic mutant went undetected"


# -------------------------------------------------- 2. perspective flips

def test_reply_seats_maximise_their_own_teams_level(monkeypatch):
    root = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    seat = root.turn

    def team_rule(position, moving_seat):
        # the root's team likes LARGE keys, the other team likes SMALL keys
        return _key(_last_play(position).cards) * (1.0 if moving_seat % 2 == seat % 2 else -1.0)

    def expect(clone, mover, ballot):
        return max(ballot, key=_key) if mover % 2 == seat % 2 else min(ballot, key=_key)

    stub = _StubNet(team_rule)
    bot = _two_ply(stub, worlds=3)
    bot.decide_play(copy.deepcopy(root), seat)
    positions = stub.batches[-1][0]
    checked, differing = _replay(bot, root, seat, positions, expect)
    assert checked >= 3 and differing == 0
    # the reply batches were scored from the MOVING seat, and the moving
    # seats include both teams
    reply_seats = [s for batch, seats in stub.batches[:-1] for s in seats]
    assert {s % 2 for s in reply_seats} == {0, 1}
    for movers, (_batch, seats) in zip(stub.movers[:-1], stub.batches[:-1]):
        assert movers == seats, "a reply row was scored from a seat other than its mover"
    # the opponents' replies really are the opposite of the root team's rule
    opponent_replies = [
        entry for step in bot.last_ply_trace for entry in step
        if entry["values"] is not None and entry["seat"] % 2 != seat % 2]
    assert opponent_replies
    for entry in opponent_replies:
        assert entry["chosen"] == min(range(len(entry["candidates"])),
                                      key=lambda i: _key(entry["candidates"][i]))

    # RED when the root's perspective is used for every reply: a mutant that
    # rewrites the seats to the root seat scores every ply as the root team
    # and the opponents now play the root team's favourite.
    stub = _StubNet(team_rule)
    real = stub.score_many
    stub.score_many = lambda positions, seats: real(positions, [seat] * len(positions))
    mutant = _two_ply(stub, worlds=3)
    mutant.decide_play(copy.deepcopy(root), seat)
    checked, differing = _replay(mutant, root, seat, stub.batches[-1][0], expect)
    assert checked >= 3 and differing > 0, "the root-perspective mutant went undetected"


# ------------------------------------------------ 3. exactly N tricks

def _check_depth(positions, root, plies: int):
    for position in positions:
        if position.phase == "round_end":
            continue
        assert len(position.history) == len(root.history) + plies, \
            f"expected exactly {plies} more resolved trick(s)"
        assert position.trick.plays == [], "no play beyond the last resolved trick"


@pytest.mark.parametrize("plies", [1, 2])
def test_plies_finish_exactly_the_current_trick_or_one_more(plies, monkeypatch):
    lead = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    follow = _state_where(13, lambda r: len(r.trick.plays) == 2 and _contested(r), start=4)
    for root in (lead, follow):
        seat = root.turn
        stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
        bot = _two_ply(stub, worlds=3, plies=plies)
        bot.decide_play(copy.deepcopy(root), seat)
        positions = stub.batches[-1][0]
        assert len(positions) == 3 * len(bot.last_decision_record["candidates"])
        _check_depth(positions, root, plies)
        expected_steps = (3 - len(root.trick.plays)) + (4 if plies == 2 else 0)
        assert bot.last_decision_record["work"]["ply_steps"] == expected_steps
        assert bot.last_decision_record["work"]["plies"] == plies
        assert [list(h) for h in root.hands] == [list(h) for h in copy.deepcopy(root).hands]
    # the one-ply bot's finisher reaches the same boundary for plies=1
    if plies == 1:
        one = CWVOnePlyBot(seed=2, evaluator=_StubNet(lambda p, s: 0.0))
        one.CWV_WORLDS = 3
        one.TRACTOR_LOCK = False
        one.decide_play(copy.deepcopy(lead), lead.turn)
        _check_depth(one.evaluator.batches[-1][0], lead, 1)

    # RED when an extra play happens: a mutant that lets the heuristic play
    # once more after the reply plies leaves a play in the next trick.
    original = CWVTwoPlyBot._reply_plies

    def one_play_too_many(self, clones, target_tricks):
        extra = original(self, clones, target_tricks)
        for clone in clones:
            if clone.phase == "play":
                s = clone.turn
                clone.play(s, self.rollout_policy.decide_play(clone, s))
        return extra
    monkeypatch.setattr(CWVTwoPlyBot, "_reply_plies", one_play_too_many)
    stub = _StubNet(lambda p, s: 0.0)
    mutant = _two_ply(stub, worlds=3, plies=plies)
    mutant.decide_play(copy.deepcopy(lead), lead.turn)
    with pytest.raises(AssertionError):
        _check_depth(stub.batches[-1][0], lead, plies)
    # and a target one trick deeper is a different depth, also refused
    monkeypatch.setattr(CWVTwoPlyBot, "_reply_plies",
                        lambda self, clones, target: original(self, clones, target + 1))
    stub = _StubNet(lambda p, s: 0.0)
    deeper = _two_ply(stub, worlds=3, plies=plies)
    deeper.decide_play(copy.deepcopy(lead), lead.turn)
    with pytest.raises(AssertionError):
        _check_depth(stub.batches[-1][0], lead, plies)


# ------------------------------------------- 4. batching == per-position

def test_mixed_seat_batch_equals_per_position_scoring(checkpoint):
    model, _meta, _sha = load_cwv_checkpoint(checkpoint)
    root = _state_where(3, lambda r: not r.trick.plays and _contested(r), start=6)
    seat = root.turn
    # one reply step's worth of positions: every seat of the trick moves
    positions, seats = [], []
    clone = copy.deepcopy(root)
    for _ in range(4):
        mover = clone.turn
        ballot = MCBot(seed=0)._candidates(clone, mover)[:3]
        for cand in ballot:
            positions.append(child_position(clone, mover, cand))
            seats.append(mover)
        clone = child_position(clone, mover, ballot[0])
    positions.append(_state_after(5, 100))                # a terminal row
    seats.append(seat)
    assert len({s for s in seats}) == 4
    for max_batch in (4096, 2):
        evaluator = CompleteWorldEvaluator(checkpoint, max_batch=max_batch)
        batched = evaluator.score_many(positions, seats)
        single = [predict_round(model, p, s).expected_signed_level
                  if p.phase != "round_end"
                  else float(terminal_distribution(p, s) @ evaluator.support)
                  for p, s in zip(positions, seats)]
        assert np.allclose(batched, single, atol=1e-6), (batched, single)
    assert evaluator.terminal_rows == 1
    # ``score`` is the single-seat special case of ``score_many``
    assert np.allclose(evaluator.score(positions, seat),
                       evaluator.score_many(positions, [seat] * len(positions)))
    with pytest.raises(CWVError):
        evaluator.score_many(positions, seats[:-1])

    # RED when rows are misassigned: the same rows with the seats rotated by
    # one are different numbers for every non-terminal row of another team.
    rotated = evaluator.score_many(positions, seats[1:] + seats[:1])
    assert not np.allclose(rotated, batched, atol=1e-6)

    # and the bot's reply argmax is exactly the per-position argmax
    bot = _two_ply(evaluator, worlds=2)
    bot.decide_play(copy.deepcopy(root), seat)
    recorded = [p for step in bot.last_ply_trace for p in step if p["values"] is not None]
    assert recorded

    def expect(clone, mover, ballot):
        values = [predict_round(model, child_position(clone, mover, cand), mover)
                  .expected_signed_level for cand in ballot]
        return ballot[int(np.argmax(values))]
    # a twin on the same seed (same worlds) records the final positions; the
    # replay regenerates every reply ballot and its per-position argmax
    twin = _two_ply(_Recording(evaluator), worlds=2)
    twin.decide_play(copy.deepcopy(root), seat)
    checked, differing = _replay(twin, root, seat, twin.evaluator.last_positions, expect)
    assert checked >= 2 and differing == 0
    assert twin.last_decision_record["means"] == bot.last_decision_record["means"]


class _Recording:
    """Delegate to a real evaluator, keep the last batch's positions."""

    def __init__(self, inner):
        self.inner = inner
        self.last_positions = None
        self.forward_calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def score(self, positions, root_seat):
        return self.score_many(positions, [root_seat] * len(positions))

    def score_many(self, positions, seats):
        self.last_positions = list(positions)
        self.forward_calls += 1
        return self.inner.score_many(positions, seats)


# ------------------------------------------- 5. terminals bypass the net

def test_terminal_reached_mid_ply_is_exact_and_never_touches_the_net():
    import torch

    class Counting(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.rows = 0
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def forward(self, public, history, mask, world, perspective):
            self.rows += int(public.shape[0])
            return torch.zeros(public.shape[0], 204) + self.dummy

    # The PENULTIMATE trick, two cards a hand, a contested lead: ``plies=2``
    # plays the last trick too (every hand's single card is a forced reply,
    # applied without the net) and every final position is ``round_end``.
    # In a last trick with two-card hands every reply is forced and one-card
    # hands never search, so this is where a terminal is reached mid-ply.
    def penultimate(r):
        return (not r.trick.plays and _contested(r)
                and all(len(h) == 2 for h in r.hands))
    root = None
    for seed in range(1, 40):                # plays != cards: scan by hand size
        try:
            root = _state_where(seed, penultimate, start=50, limit=100)
            break
        except AssertionError:
            continue
    assert root is not None, "no contested penultimate-trick lead found"
    seat = root.turn
    model = Counting()
    evaluator = _Recording(CompleteWorldEvaluator(None, model=model))
    bot = _two_ply(evaluator, worlds=2, plies=2)
    bot.decide_play(copy.deepcopy(root), seat)
    finals = evaluator.last_positions
    assert finals and all(p.phase == "round_end" for p in finals)
    assert model.rows > 0, "the penultimate trick's replies did use the net"
    rows_before_final = model.rows
    values = evaluator.inner.score(finals, seat)
    assert model.rows == rows_before_final, "terminal rows reached the model"
    exact = [category_signed_level(signed_level_category(
        p.attacker_points, p.is_attacker(seat))) for p in finals]
    assert np.array_equal(values, exact)
    # the last trick's replies were forced (no net), the terminal came mid-ply
    last_step = bot.last_ply_trace[-1]
    assert last_step and all(e["values"] is None for e in last_step)
    assert bot.last_decision_record["work"]["ply_steps"] == 7
    means = bot.last_decision_record["means"]
    K = len(bot.last_decision_record["candidates"])
    assert means == pytest.approx(np.asarray(exact).reshape(-1, K).mean(axis=0).tolist())
    # the prior control takes the exact terminal too, in its own scale
    prior = StratifiedPriorEvaluator({}, 0.0, source="t", scale="pt0")
    assert prior.score_many(finals, [seat] * len(finals)).tolist() == [
        cwv_policy.pt0_level(v) for v in exact]

    # RED when terminals are routed through the net: a mutant evaluator whose
    # terminal branch is dropped sends the terminal rows to the model, whose
    # zero logits give the uniform expectation instead of the exact value.
    class NoTerminalBranch(CompleteWorldEvaluator):
        def score_many(self, positions, seats):
            from shengji.rl.value_afterstate import tensors_from_round
            rows = [tensors_from_round(p, s) for p, s in zip(positions, seats)]
            return self.probabilities(rows) @ self.support
    mutant_model = Counting()
    mutant = NoTerminalBranch(None, model=mutant_model)
    routed = mutant.score(finals, seat)
    assert mutant_model.rows == len(finals)
    assert not np.array_equal(routed, exact)


# ------------------------------------------ 6. registry + calibration

def test_registry_names_and_calibration_binding_include_plies(checkpoint, tmp_path):
    sha8 = cwv_policy.checkpoint_id(checkpoint)
    assert policy_name(sha8, 7, plies=1) == f"mc-cwv2-{sha8}-w7"
    assert policy_name(sha8, 7, plies=2) == f"mc-cwv2-{sha8}-w7-p2"
    assert control_name(sha8, 7, plies=1) == f"mc-cwv2-prior-{sha8}-w7"
    assert control_name(sha8, 7, plies=2, lcb=1.5) == f"mc-cwv2-prior-{sha8}-w7-p2-lcb1.5"
    assert policy_name(sha8, 7) == f"mc-cwv-{sha8}-w7"          # one-ply unchanged
    assert set(cwv_registry_entries(checkpoint, [7], plies=2)) == {
        f"mc-cwv2-{sha8}-w7-p2", f"mc-cwv2-prior-{sha8}-w7-p2"}
    with pytest.raises(CWVError):
        cwv_registry_entries(checkpoint, [7], plies=3)
    names = register_cwv_policies(checkpoint, [7], plies=1)
    try:
        arm = make_bot(f"mc-cwv2-{sha8}-w7", seed=3)
        assert isinstance(arm, CWVTwoPlyBot) and arm.CWV_WORLDS == 7 and arm.CWV_PLIES == 1
        assert arm.CWV_FINISH_TRICK is False and arm.cwv_ckpt8 == sha8
        control = make_bot(f"mc-cwv2-prior-{sha8}-w7", seed=4)
        assert isinstance(control, CWVTwoPlyBot)
        assert isinstance(control.evaluator, StratifiedPriorEvaluator)
        production = ballot_for_policy("mc-s0-report-lcb")
        for name in names:
            assert ballot_for_policy(name).digest == production.digest, name
    finally:
        for name in names:
            REGISTRY.pop(name, None)
    env = {"SHENGJI_CWV_CKPT": checkpoint, "SHENGJI_CWV_WORLDS": "5", "SHENGJI_CWV_PLIES": "2"}
    assert set(env_registry_entries(env)) == {
        f"mc-cwv2-{sha8}-w5-p2", f"mc-cwv2-prior-{sha8}-w5-p2"}

    duel = _load_script("cwv_duel")
    assert duel.bot_plies(0) is None and duel.bot_plies(2) == 2
    with pytest.raises(ValueError):
        duel.bot_plies(3)
    args = duel.build_parser().parse_args([
        "calibrate", "--checkpoint", checkpoint, "--out", str(tmp_path / "cal2.json"),
        "--base-policy", "mc-lite", "--deals", "1", "--grid", "2,3",
        "--subset-stride", "12", "--max-iterations", "1", "--budgets", "1x,3x",
        "--no-production-ladder", "--plies", "1"])
    try:
        calibration = duel.calibrate(args)
    finally:
        for name in list(REGISTRY):
            if name.startswith("mc-cwv"):
                REGISTRY.pop(name)
    binding = calibration["binding"]
    assert binding["plies"] == 1 and calibration["bot"] == "two-ply"
    assert calibration["arm_policy_at_1x"].startswith(f"mc-cwv2-{sha8}-w")
    assert all(row["forwards_per_decision"] >= 1 for row in calibration["grid"])
    assert calibration["identity_sha256"] == duel.calibration_identity(binding)
    live = dict(checkpoint_sha256=binding["checkpoint_sha256"], finish_trick=True,
                lcb=0.0, base_policy="mc-lite", trump_ranks="canonical", budgets=[1.0, 3.0])
    rungs = duel.check_calibration(calibration, plies=1, **live)
    assert [r["worlds"] for r in rungs] == [r["worlds"] for r in calibration["ladder"]]
    for plies in (0, 2):
        with pytest.raises(duel.CalibrationMismatch, match="plies"):
            duel.check_calibration(calibration, plies=plies, **live)
    # a one-ply calibration (no plies field, the #229 files) is one-ply only
    legacy = {**calibration, "binding": {k: v for k, v in binding.items() if k != "plies"}}
    legacy["identity_sha256"] = duel.calibration_identity(legacy["binding"])
    duel.check_calibration(legacy, plies=0, **live)
    with pytest.raises(duel.CalibrationMismatch, match="plies"):
        duel.check_calibration(legacy, plies=1, **live)
    # RED when the binding forgets plies: the identity no longer separates
    # the two bots, so the same file would be accepted for both.
    forgetful = duel.calibration_binding(
        binding["checkpoint_sha256"], finish_trick=True, lcb=0.0, base_policy="mc-lite",
        trump_ranks="canonical", budgets=calibration["ladder"], plies=1)
    forgetful.pop("plies")
    other = duel.calibration_binding(
        binding["checkpoint_sha256"], finish_trick=True, lcb=0.0, base_policy="mc-lite",
        trump_ranks="canonical", budgets=calibration["ladder"], plies=2)
    other.pop("plies")
    assert duel.calibration_identity(forgetful) == duel.calibration_identity(other)
    assert duel.calibration_identity(binding) != duel.calibration_identity(
        {**binding, "plies": 2})
