"""Witnesses for net-driven rollouts inside production's search
(``train.net_rollout.MCNetRolloutSearch``).  Each carries its mutation.

1. ``K = 0`` report fold == production byte for byte on three states (gap,
   se, statistic, worlds, the decision record); RED when the lockstep draws
   worlds at another position of the seeded stream;
2. with ``K >= 1`` and a stub net that prefers a known play, every clone's
   first-trick plays for the mover are the stub's argmax; RED when the
   heuristic plays instead;
3. the mover's perspective flips per ply (each mover maximises ITS team's
   value); RED when the root perspective is used;
4. exactly ``K`` tricks are net-driven, the rest heuristic; RED when K+1;
5. batching == per-position scoring within 1e-6; RED when rows are
   misassigned;
6. the LCB rule is unchanged: the recorded decision is production's rule
   applied to the produced deltas; RED when the SE is bypassed;
7. the calibration identity binds K / net_stage / checkpoint and refuses a
   mismatch; RED when a binding forgets net_stage.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.cwv_policy import CompleteWorldEvaluator, StratifiedPriorEvaluator, child_position
from shengji.ai.mcbot import MCBot
from shengji.ai.registry import REGISTRY, make_bot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate import terminal_distribution
from shengji.rl.value_inference import predict_round
from shengji.train import net_rollout as NR
from shengji.train import netroll_screen as NS
from shengji.train.net_rollout import (
    MCNetRolloutSearch,
    NetRolloutError,
    env_registry_entries,
    make_netroll_bot,
    netroll_policy_name,
    netroll_registry_entries,
    register_netroll_from_env,
    register_netroll_policies,
)

SMALL_N = 3         # selection worlds (production: 30)
SMALL_R = 30        # report worlds: the LCB rule's minimum (production: 300)


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("netroll") / "tiny-mlp.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(out), rounds=2, max_epochs=2, architecture="mlp", quiet=True)
    return str(out)


def _state_after(seed: int, plies: int):
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


def _contested(rnd) -> bool:
    return len(MCBot(seed=0)._candidates(rnd, rnd.turn)) >= 2


def _state_where(seed: int, predicate, *, start: int = 0, limit: int = 100):
    for plies in range(start, limit):
        rnd = _state_after(seed, plies)
        if rnd.phase == "play" and predicate(rnd):
            return rnd
    raise AssertionError("no state satisfied the predicate")


def _last_play(position):
    if position.trick is not None and position.trick.plays:
        return position.trick.plays[-1]
    return position.history[-1].plays[-1]


def _key(cards) -> float:
    """A strict total order over card multisets."""
    text = "".join(sorted(cards))
    return float(sum((index + 1) * ord(ch) * 7919 ** (index % 3)
                     for index, ch in enumerate(text)) % 10_000_019) + 0.5 * len(cards)


class _StubNet:
    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, rule):
        self.rule = rule
        self.forward_calls = 0
        self.batches = []

    def identity(self):
        return {"kind": "stub"}

    def score_many(self, positions, seats):
        self.forward_calls += 1
        self.batches.append((len(positions), list(seats)))
        return np.asarray([self.rule(p, s) for p, s in zip(positions, seats)], dtype=np.float64)


def _small(bot):
    bot.N_DETERMINIZATIONS = SMALL_N
    bot.REPORT_FOLD_WORLDS = SMALL_R
    return bot


def _netroll(evaluator, *, tricks: int, stage: str = "report", seed: int = 5, trace=True):
    bot = _small(MCNetRolloutSearch(evaluator, seed=seed, net_tricks=tricks, net_stage=stage))
    bot.NET_TRACE = trace
    return bot


def _strip(record):
    record = copy.deepcopy(record)
    for key in ("policy", "policy_class", "search_secs", "net_rollout", "code"):
        record.pop(key, None)
    return record


def _replay(bot, root, seat, expect):
    """Walk every final clone of the last lockstep from its root afterstate
    through the net phase; compare each contested play with ``expect(clone,
    mover, ballot)``.  Returns (contested plays checked, plays differing)."""
    lock = bot.last_lockstep
    horizon = bot._net_horizon(root)
    checked = differing = 0
    for index, final in enumerate(lock["finals"]):
        hands, buried = lock["worlds"][index // len(lock["candidates"])]
        cand = lock["candidates"][index % len(lock["candidates"])]
        from shengji.ai.cwv_policy import afterstate
        clone = afterstate(root, seat, hands, buried, cand, finish_trick=False)
        plays = [p for trick in final.history[len(root.history):] for p in trick.plays]
        if final.trick is not None:
            plays.extend(final.trick.plays)
        for play in plays[len(root.trick.plays) + 1:]:
            if len(clone.history) >= horizon or clone.phase != "play":
                break
            mover = clone.turn
            assert mover == play.seat
            ballot = bot._net_ballot(clone, mover)
            if len(ballot) > 1:
                checked += 1
                if sorted(play.cards) != sorted(expect(clone, mover, ballot)):
                    differing += 1
            clone.play(mover, list(play.cards))
    return checked, differing


# ------------------------------------------- 1. K = 0 is production, exactly

_STATES = [(13, 5), (21, 9), (7, 30)]


@pytest.mark.parametrize("stage", ["report", "all"])
def test_k0_report_fold_is_production_byte_for_byte(stage, monkeypatch):
    stub = _StubNet(lambda p, s: 0.0)
    compared = 0
    for seed, plies in _STATES:
        root = _state_after(seed, plies)
        seat = root.turn
        assert root.phase == "play" and _contested(root)
        prod = _small(make_bot("mc-s0-report-lcb", seed=5))
        net = _netroll(stub, tricks=0, stage=stage, trace=False)
        assert prod.decide_play(copy.deepcopy(root), seat) == net.decide_play(copy.deepcopy(root), seat)
        a, b = _strip(prod.last_decision_record), _strip(net.last_decision_record)
        assert a["report_fold"] == b["report_fold"]          # gap, se, statistic, worlds, ...
        assert prod.last_override_stats == net.last_override_stats
        assert a["means"] == b["means"] and a["paired_se"] == b["paired_se"]
        assert a["reason"] == b["reason"] and a["played"] == b["played"]
        assert a["report_seed"] == b["report_seed"] and a["rng_state"] == b["rng_state"]
        assert a["alloc"]["worlds"] == b["alloc"]["worlds"]
        if stage == "report":
            assert {k: v for k, v in a.items() if k != "alloc"} == \
                {k: v for k, v in b.items() if k not in ("alloc",)}
            assert a["alloc"] == b["alloc"]
        assert stub.forward_calls == 0          # K = 0 never touches the net
        assert net.netroll_counts["net_plays"] == 0 and net.netroll_counts["rollouts"] > 0
        compared += 1
    assert compared == 3

    # RED when the lockstep draws worlds at another position of the seeded
    # stream: a child RNG advanced by one draw before the first world.
    def shifted(seed):
        rng = random.Random(seed)
        rng.random()
        return rng
    monkeypatch.setattr(MCNetRolloutSearch, "_report_rng", staticmethod(shifted))
    differing = 0
    for seed, plies in _STATES:
        root = _state_after(seed, plies)
        seat = root.turn
        prod = _small(make_bot("mc-s0-report-lcb", seed=5))
        mutant = _netroll(stub, tricks=0, stage="report", trace=False)
        prod.decide_play(copy.deepcopy(root), seat)
        mutant.decide_play(copy.deepcopy(root), seat)
        if prod.last_decision_record["report_fold"] != mutant.last_decision_record["report_fold"]:
            differing += 1
    assert differing > 0, "the shifted-stream mutant went undetected"


# ------------------------------------------ 2. the net's argmax is played

def test_first_trick_plays_are_the_stubs_argmax_never_the_heuristic(monkeypatch):
    root = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    seat = root.turn
    stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
    bot = _netroll(stub, tricks=1)
    bot.decide_play(copy.deepcopy(root), seat)
    assert bot.last_lockstep["stage"] == "report" and len(bot.last_lockstep["finals"]) == 2 * SMALL_R
    checked, differing = _replay(bot, root, seat, lambda clone, mover, ballot: max(ballot, key=_key))
    assert checked >= 10 and differing == 0, (checked, differing)
    work = bot.last_decision_record["net_rollout"]["counts"]
    assert work["net_plays"] == checked and work["report_net_plays"] == checked
    assert work["batches"] == stub.forward_calls == work["forwards"] <= 3    # one batch per ply
    assert work["heuristic_plays"] > 0 and work["rollouts"] == 2 * SMALL_R
    for entry in bot.last_net_trace:
        if entry["values"] is not None:
            assert entry["chosen"] == int(np.argmax(entry["values"]))

    # RED when the heuristic plays instead: a mutant whose reply ballot is the
    # heuristic's own move.
    def heuristic_ballot(self, clone, seat):
        return [self.rollout_policy.decide_play(clone, seat)]
    monkeypatch.setattr(MCNetRolloutSearch, "_net_ballot", heuristic_ballot)
    stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
    mutant = _netroll(stub, tricks=1)
    mutant.decide_play(copy.deepcopy(root), seat)
    monkeypatch.undo()
    checked, differing = _replay(mutant, root, seat, lambda clone, mover, ballot: max(ballot, key=_key))
    assert checked >= 10 and differing > 0, "the heuristic mutant went undetected"


# ---------------------------------------------- 3. the perspective flips

def test_each_mover_maximises_its_own_teams_value(monkeypatch):
    root = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    seat = root.turn
    # team 0 likes high keys, team 1 likes low keys: a stub whose sign is the
    # perspective seat's team
    rule = lambda p, s: _key(_last_play(p).cards) * (1.0 if s % 2 == 0 else -1.0)
    expect = lambda clone, mover, ballot: (max if mover % 2 == 0 else min)(ballot, key=_key)
    bot = _netroll(_StubNet(rule), tricks=1)
    bot.decide_play(copy.deepcopy(root), seat)
    movers = {e["seat"] for e in bot.last_net_trace if e["values"] is not None}
    assert any(m % 2 != seat % 2 for m in movers), "no contested opponent mover"
    checked, differing = _replay(bot, root, seat, expect)
    assert checked >= 10 and differing == 0, (checked, differing)

    # RED when the root perspective is used for every mover
    monkeypatch.setattr(MCNetRolloutSearch, "_net_perspective",
                        staticmethod(lambda mover, root_seat: root_seat))
    mutant = _netroll(_StubNet(rule), tricks=1)
    mutant.decide_play(copy.deepcopy(root), seat)
    monkeypatch.undo()
    checked, differing = _replay(mutant, root, seat, expect)
    assert checked >= 10 and differing > 0, "the root-perspective mutant went undetected"


# ---------------------------------------- 4. exactly K tricks net-driven

def _net_phase_plays(bot, root):
    lock = bot.last_lockstep
    expected = []
    for final, n_net in zip(lock["finals"], lock["net_phase_plays"]):
        plays = sum(len(t.plays) for t in final.history[len(root.history):])
        if final.trick is not None:
            plays += len(final.trick.plays)
        after_root = plays - len(root.trick.plays) - 1
        want = min(after_root, 4 * bot.NET_TRICKS - len(root.trick.plays) - 1)
        expected.append((n_net, want))
    return expected


@pytest.mark.parametrize("tricks", [1, 2])
def test_exactly_k_tricks_are_net_driven_then_the_heuristic(tricks, monkeypatch):
    root = _state_where(21, lambda r: not r.trick.plays and _contested(r), start=8)
    seat = root.turn
    bot = _netroll(_StubNet(lambda p, s: _key(_last_play(p).cards)), tricks=tricks)
    bot.decide_play(copy.deepcopy(root), seat)
    pairs = _net_phase_plays(bot, root)
    assert pairs and all(got == want for got, want in pairs), pairs
    assert all(want == 4 * tricks - 1 for _, want in pairs)      # a lead root: 4K-1 plies
    counts = bot.last_decision_record["net_rollout"]["counts"]
    assert counts["net_plays"] + counts["forced_plays"] == sum(g for g, _ in pairs)
    assert counts["heuristic_plays"] > 0
    assert all(root.history.__len__() <= e["trick"] < len(root.history) + tricks
               for e in bot.last_net_trace)

    # RED when K + 1 tricks are net-driven
    monkeypatch.setattr(MCNetRolloutSearch, "_net_horizon",
                        lambda self, rnd: len(rnd.history) + self.NET_TRICKS + 1)
    mutant = _netroll(_StubNet(lambda p, s: _key(_last_play(p).cards)), tricks=tricks)
    mutant.decide_play(copy.deepcopy(root), seat)
    monkeypatch.undo()
    pairs = _net_phase_plays(mutant, root)
    assert any(got != want for got, want in pairs), "the K+1 mutant went undetected"


# ------------------------------------ 5. batching == per-position scoring

def test_lockstep_batch_equals_per_position_scoring(checkpoint, monkeypatch):
    root = _state_where(3, lambda r: not r.trick.plays and _contested(r), start=6)
    seat = root.turn
    evaluator = CompleteWorldEvaluator(checkpoint, max_batch=64)
    model = evaluator.model
    bot = _netroll(evaluator, tricks=1)
    bot.decide_play(copy.deepcopy(root), seat)
    entries = [e for e in bot.last_net_trace if e["values"] is not None]
    assert len(entries) >= 10 and evaluator.forward_calls > 1
    rows = 0
    for entry in entries:
        parent, mover = entry["parent"], entry["seat"]
        single = []
        for cand in entry["candidates"]:
            child = child_position(parent, mover, cand)
            if child.phase == "round_end":
                single.append(float(terminal_distribution(child, mover) @ evaluator.support))
            else:
                single.append(predict_round(model, child, mover).expected_signed_level)
        assert np.allclose(entry["values"], single, atol=1e-6), (entry["values"], single)
        assert entry["chosen"] == int(np.argmax(single))
        rows += len(single)
    assert rows == bot.last_decision_record["net_rollout"]["counts"]["net_positions"]

    # RED when rows are misassigned: values rolled by one row
    original = CompleteWorldEvaluator.score_many
    monkeypatch.setattr(CompleteWorldEvaluator, "score_many",
                        lambda self, positions, seats: np.roll(original(self, positions, seats), 1))
    mutant = _netroll(evaluator, tricks=1)
    mutant.decide_play(copy.deepcopy(root), seat)
    monkeypatch.undo()
    mismatched = 0
    for entry in [e for e in mutant.last_net_trace if e["values"] is not None]:
        single = [predict_round(model, child_position(entry["parent"], entry["seat"], cand),
                                entry["seat"]).expected_signed_level
                  if child_position(entry["parent"], entry["seat"], cand).phase != "round_end"
                  else 0.0 for cand in entry["candidates"]]
        if not np.allclose(entry["values"], single, atol=1e-6):
            mismatched += 1
    assert mismatched > 0, "the misassigned-rows mutant went undetected"


# ------------------------------------------------ 6. the LCB rule holds

def _check_production_rule(bot, root, seat):
    from shengji.ai.memory import Memory
    rec = bot.last_decision_record
    fold = rec["report_fold"]
    cands = rec["candidates"]
    challenger = rec["report_candidate_index"]
    mem = Memory(root, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    out = bot._report_fold_gap(copy.deepcopy(root), seat, mem, root.is_attacker(seat),
                               cands[challenger], cands[0], bot.REPORT_FOLD_WORLDS,
                               seed=rec["report_seed"], keep_deltas=True)
    deltas = out["deltas"]
    assert len(deltas) == fold["worlds"] == bot.REPORT_FOLD_WORLDS
    d_sum = sum(deltas)
    d_sq = sum(d * d for d in deltas)
    assert fold["gap"] == d_sum / len(deltas)
    assert fold["se"] == MCBot._paired_se(d_sum, d_sq, len(deltas))
    critical = MCBot._report_critical(bot, len(deltas))
    assert fold["critical"] == critical == 1.70
    assert fold["statistic"] == fold["gap"] - critical * fold["se"]
    want = ("report_lcb_override" if fold["statistic"] >= bot.REPORT_MIN_GAIN
            else "report_lcb_below_min_gain")
    assert rec["reason"] == want
    assert rec["played"] == (cands[challenger] if want == "report_lcb_override" else cands[0])
    return deltas


def test_lcb_decision_is_productions_rule_on_the_produced_deltas(monkeypatch):
    root = _state_where(13, lambda r: not r.trick.plays and _contested(r), start=4)
    seat = root.turn
    stub = _StubNet(lambda p, s: _key(_last_play(p).cards))
    bot = _netroll(stub, tricks=1, trace=False)
    bot.decide_play(copy.deepcopy(root), seat)
    deltas = _check_production_rule(bot, root, seat)
    assert len(set(deltas)) > 1, "the report deltas must carry variance for the SE to matter"

    # RED when the rule is bypassed: a mutant whose paired SE is always zero
    monkeypatch.setattr(MCNetRolloutSearch, "_paired_se", staticmethod(lambda s, q, n: 0.0))
    mutant = _netroll(stub, tricks=1, trace=False)
    mutant.decide_play(copy.deepcopy(root), seat)
    with pytest.raises(AssertionError):
        _check_production_rule(mutant, root, seat)
    monkeypatch.undo()


# ------------------------------------- 7. identity, names, registry, refusals

def test_calibration_identity_binds_k_stage_and_checkpoint(checkpoint):
    sha = NS.file_sha256(checkpoint)
    binding = NS.calibration_binding(checkpoint_sha256=sha, net_stage="report", tricks=(1, 2),
                                     baseline_select_worlds=30, report_worlds=300,
                                     trump_ranks=("2",))
    calibration = {"schema": NS.CALIBRATION_SCHEMA, "outcomes_read": False, "binding": binding,
                   "identity_sha256": NS.calibration_identity(binding)}
    ok = dict(checkpoint_sha256=sha, net_stage="report", net_tricks=1, baseline_select_worlds=30,
              report_worlds=300, trump_ranks=("2",))
    NS.require_matching_calibration(calibration, **ok)
    for field, bad in (("net_tricks", 4), ("net_stage", "all"),
                       ("checkpoint_sha256", "0" * 64), ("report_worlds", 30),
                       ("trump_ranks", ("3",))):
        with pytest.raises(NS.ScreenError, match=field.split("_")[0]):
            NS.require_matching_calibration(calibration, **{**ok, field: bad})
    tampered = dict(calibration, identity_sha256="f" * 64)
    with pytest.raises(NS.ScreenError, match="identity"):
        NS.require_matching_calibration(tampered, **ok)
    # the identity separates the stages ...
    other = NS.calibration_binding(checkpoint_sha256=sha, net_stage="all", tricks=(1, 2),
                                   baseline_select_worlds=30, report_worlds=300,
                                   trump_ranks=("2",))
    assert NS.calibration_identity(other) != NS.calibration_identity(binding)
    # ... RED when a binding forgets net_stage: both stages hash the same
    forgetful = {k: v for k, v in binding.items() if k != "net_stage"}
    forgetful_other = {k: v for k, v in other.items() if k != "net_stage"}
    assert NS.calibration_identity(forgetful) == NS.calibration_identity(forgetful_other)


def test_registry_names_controls_and_refusals(checkpoint):
    ckpt8 = NR.checkpoint_id(checkpoint)
    assert netroll_policy_name(ckpt8, 1) == f"mc-netroll-{ckpt8}-k1"
    assert netroll_policy_name(ckpt8, 2, net_stage="all") == f"mc-netroll-{ckpt8}-k2-all"
    assert netroll_policy_name(ckpt8, 1, prior=True) == f"mc-netroll-prior-{ckpt8}-k1"
    assert set(netroll_registry_entries(checkpoint, (1, 2), ("report",))) == {
        f"mc-netroll-{ckpt8}-k1", f"mc-netroll-prior-{ckpt8}-k1",
        f"mc-netroll-{ckpt8}-k2", f"mc-netroll-prior-{ckpt8}-k2"}
    assert set(env_registry_entries({"SHENGJI_NETROLL_CKPT": checkpoint,
                                     "SHENGJI_NETROLL_TRICKS": "4",
                                     "SHENGJI_NETROLL_STAGES": "all"})) == {
        f"mc-netroll-{ckpt8}-k4-all", f"mc-netroll-prior-{ckpt8}-k4-all"}
    assert env_registry_entries({}) == {}
    names = register_netroll_policies(checkpoint, (1,), ("report", "all"))
    try:
        arm = make_bot(f"mc-netroll-{ckpt8}-k1", seed=3)
        assert isinstance(arm, MCNetRolloutSearch) and arm.NET_TRICKS == 1
        assert arm.NET_STAGE == "report" and arm.ADAPTIVE_ALLOCATION is False
        assert arm.policy_name == f"mc-netroll-{ckpt8}-k1" and arm.netroll_ckpt8 == ckpt8
        assert isinstance(arm.evaluator, CompleteWorldEvaluator)
        assert arm.N_DETERMINIZATIONS == 30 and arm.REPORT_FOLD_WORLDS == 300   # production's
        control = make_bot(f"mc-netroll-prior-{ckpt8}-k1", seed=4)
        assert isinstance(control.evaluator, StratifiedPriorEvaluator)
        assert control.evaluator.scale in ("level", "pt0") and control.netroll_prior is True
        every = make_bot(f"mc-netroll-{ckpt8}-k1-all", seed=5)
        assert every.NET_STAGE == "all" and every.ADAPTIVE_ALLOCATION is True
        from shengji.engine.ballot import ballot_for_policy
        production = ballot_for_policy("mc-s0-report-lcb")
        for name in names:
            assert ballot_for_policy(name).digest == production.digest, name
        # the same bytes at another path are another artifact: refused
        import shutil
        other = Path(checkpoint).with_name("other.pt")
        shutil.copy(checkpoint, other)
        with pytest.raises(NetRolloutError, match="already bound"):
            register_netroll_policies(str(other), (1,))
    finally:
        for name in names:
            REGISTRY.pop(name, None)
    with pytest.raises(NetRolloutError):
        MCNetRolloutSearch(_StubNet(lambda p, s: 0.0), net_tricks=-1)
    with pytest.raises(NetRolloutError):
        MCNetRolloutSearch(_StubNet(lambda p, s: 0.0), net_tricks=1, net_stage="selection")
    with pytest.raises(NetRolloutError):
        MCNetRolloutSearch(object(), net_tricks=1)
    with pytest.raises(NetRolloutError, match="refused"):
        make_netroll_bot(str(Path(checkpoint).with_name("missing.pt")), net_tricks=1)
    with pytest.raises(NetRolloutError, match="changed"):
        make_netroll_bot(checkpoint, net_tricks=1, expected_sha256="0" * 64)


def test_non_mlp_and_foreign_checkpoints_are_refused(tmp_path):
    gru = tmp_path / "tiny-gru.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(gru), rounds=2, max_epochs=1, architecture="gru", quiet=True)
    with pytest.raises(NetRolloutError, match="mlp"):
        make_netroll_bot(str(gru), net_tricks=1)
    import torch
    payload = torch.load(str(gru), map_location="cpu", weights_only=False)
    payload["metadata"] = {k: v for k, v in payload.get("metadata", {}).items()
                           if "encoder" not in k}
    foreign = tmp_path / "foreign.pt"
    torch.save(payload, str(foreign))
    with pytest.raises(NetRolloutError, match="refused"):
        make_netroll_bot(str(foreign), net_tricks=1)


# ------------------------------- 8. same-path replacement after registration

def test_registered_name_refuses_a_checkpoint_replaced_at_the_same_path(tmp_path, monkeypatch):
    path = tmp_path / "live.pt"
    build = _load_script("cwv_dev_checkpoint").build_dev_checkpoint
    build(str(path), rounds=2, max_epochs=1, architecture="mlp", width=16, quiet=True)
    registered_sha = NS.file_sha256(path)
    names = register_netroll_from_env({"SHENGJI_NETROLL_CKPT": str(path),
                                       "SHENGJI_NETROLL_TRICKS": "1"})
    try:
        name = f"mc-netroll-{registered_sha[:8]}-k1"
        assert name in names and REGISTRY[name].netroll_artifact[1] == registered_sha
        bot = make_bot(name, seed=1)
        assert bot.netroll_checkpoint_sha256 == registered_sha
        # replace the file at the SAME path with different weights (another
        # width and seed: different bytes, different size)
        build(str(path), rounds=2, max_epochs=1, architecture="mlp", width=8, seed=7, quiet=True)
        replaced_sha = NS.file_sha256(path)
        assert replaced_sha != registered_sha
        with pytest.raises(NetRolloutError, match="sha256 mismatch") as excinfo:
            make_bot(name, seed=2)
        assert registered_sha in str(excinfo.value) and replaced_sha in str(excinfo.value)
        with pytest.raises(NetRolloutError, match="sha256 mismatch"):
            make_bot(f"mc-netroll-prior-{registered_sha[:8]}-k1", seed=2)
        # the env hook goes through the rebinding refusal: re-registering the
        # replaced file under the name it now hashes to is a new artifact, and
        # the OLD name is not silently rebound
        again = register_netroll_from_env({"SHENGJI_NETROLL_CKPT": str(path),
                                           "SHENGJI_NETROLL_TRICKS": "1"})
        assert f"mc-netroll-{replaced_sha[:8]}-k1" in again
        assert REGISTRY[name].netroll_artifact[1] == registered_sha
        with pytest.raises(NetRolloutError, match="sha256 mismatch"):
            make_bot(name, seed=3)

        # RED when the check is bypassed: a factory that drops the registered
        # sha loads the NEW weights under the OLD checkpoint-named policy.
        original = NR.make_netroll_bot
        monkeypatch.setattr(NR, "make_netroll_bot",
                            lambda checkpoint, **kw: original(
                                checkpoint, **{k: v for k, v in kw.items() if k != "expected_sha256"}))
        mutant = make_bot(name, seed=4)
        monkeypatch.undo()
        assert mutant.netroll_checkpoint_sha256 == replaced_sha != registered_sha
        with pytest.raises(NetRolloutError, match="sha256 mismatch"):
            make_bot(name, seed=5)                       # restored: refuses again
    finally:
        for n in list(REGISTRY):
            if n.startswith("mc-netroll-"):
                REGISTRY.pop(n, None)
