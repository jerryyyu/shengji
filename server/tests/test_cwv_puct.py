"""Witnesses for the PUCT-over-sampled-worlds bot (cwv_puct).

Every test carries its mutation: the assertion that would go RED if the
guarded behaviour were dropped is exercised against an explicit mutant, so
a GREEN here means the check discriminates rather than merely passes.
"""
from __future__ import annotations

import copy
import importlib.util
import math
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import cwv_puct
from shengji.ai.cwv_puct import (
    CWVPuctBot,
    Node,
    action_key,
    backup,
    cwv_puct_registry_entries,
    puct_control_name,
    puct_policy_name,
    puct_scores,
    select_move,
)
from shengji.ai.cwv_policy import CWVError
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _contested_state(seed: int = 5, start: int = 4):
    """A play state where production's ballot has at least three actions."""
    probe = SmartBot()
    del probe
    from shengji.ai.mcbot import MCBot
    bot = MCBot(seed=0)
    for plies in range(start, 80):
        rnd = _state_after(seed, plies)
        if rnd.phase != "play":
            break
        if len(bot._candidates(rnd, rnd.turn)) >= 3:
            return rnd
    raise AssertionError("no contested state found")


def _plays_of(position) -> tuple:
    """The public action sequence of a position (all plays so far)."""
    out = []
    for trick in position.history:
        for play in trick.plays:
            out.append(action_key(play.cards))
    if position.trick is not None:
        for play in position.trick.plays:
            out.append(action_key(play.cards))
    return tuple(out)


class _StubEvaluator:
    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, rule):
        self.rule = rule
        self.batches = []
        self.forward_calls = 0

    def identity(self):
        return {"kind": "stub"}

    def score(self, positions, root_seat):
        self.batches.append((list(positions), root_seat))
        self.forward_calls += 1
        return np.asarray([self.rule(p, root_seat) for p in positions], dtype=np.float64)


def _bot(evaluator, **attrs) -> CWVPuctBot:
    cls = type("Probe", (CWVPuctBot,), {"CWV_WORLD_POOL": 4, "CWV_BATCH": 4,
                                        "CWV_SIMULATIONS": 48, **attrs})
    return cls(seed=7, evaluator=evaluator)


# ------------------------------------------------- 1. the selection formula

def test_puct_selection_reproduces_a_hand_computed_case():
    # parent N = 16 (sqrt = 4); three children (N, W, pending) and priors
    children = [(9, 4.5, 0), (4, 3.2, 0), (0, 0.0, 0)]
    priors = [0.2, 0.5, 0.3]
    c, fpu = 1.5, 0.4
    got = puct_scores(16, children, priors, c_puct=c, sign=1.0, fpu_q=fpu,
                      virtual_loss=1.0)
    want = [0.5 + c * 0.2 * 4 / 10,       # Q .5, explore 1.5*.2*sqrt(16)/(1+9)
            0.8 + c * 0.5 * 4 / 5,        # Q .8
            fpu + c * 0.3 * 4 / 1]        # unvisited: parent's Q, n = 0
    assert got == pytest.approx(want, abs=1e-12)
    # opponent node: the same children, the objective negated
    opp = puct_scores(16, children, priors, c_puct=c, sign=-1.0, fpu_q=fpu,
                      virtual_loss=1.0)
    assert opp == pytest.approx([-0.5 + c * 0.2 * 4 / 10, -0.8 + c * 0.5 * 4 / 5,
                                 -fpu + c * 0.3 * 4 / 1], abs=1e-12)
    # a pending path prices as vloss worse to the selecting seat
    pend = puct_scores(17, [(9, 4.5, 1)], [0.2], c_puct=c, sign=1.0, fpu_q=fpu,
                       virtual_loss=1.0)
    assert pend == pytest.approx([(4.5 - 1.0) / 10 + c * 0.2 * math.sqrt(17) / 11])

    # MUTANT: the sqrt dropped (parent N used linearly).  Parent N = 100:
    # A (N 50, Q 1.5, P .2) beats B (N 10, Q .55, P .5) under sqrt(100) = 10
    # but loses under a linear 100.
    ab = [(50, 75.0, 0), (10, 5.5, 0)]
    with_sqrt = puct_scores(100, ab, [0.2, 0.5], c_puct=c, sign=1.0, fpu_q=0.0,
                            virtual_loss=1.0)
    assert with_sqrt == pytest.approx([1.5 + c * 0.2 * 10 / 51, 0.55 + c * 0.5 * 10 / 11])
    assert with_sqrt[0] > with_sqrt[1]
    linear = [1.5 + c * 0.2 * 100 / 51, 0.55 + c * 0.5 * 100 / 11]
    assert linear[1] > linear[0]                     # the mutant is RED


# ------------------------------------------------------------- 2. back-up

def test_backup_propagates_the_root_team_value_unchanged_along_the_path():
    root = Node((), 0)
    a = root.child(("SA",))
    b = a.child(("HK",))
    c = b.child(("D3",))
    path = [root, a, b, c]
    for node in path:
        node.pending += 1
    backup(path, -1.5)
    backup(path, 0.5)
    for node in path:
        assert node.N == 2 and node.W == pytest.approx(-1.0) and node.pending == 0
        assert node.Q == pytest.approx(-0.5)
    # perspective: the leaf value reaches every node with the SAME sign,
    # opponent nodes included (a and c are opponent-to-act in a real tree)

    # MUTANT: a backup that only touches the leaf leaves the interior stale
    def mutant(path, value):
        path[-1].N += 1
        path[-1].W += value
    root2 = Node((), 0)
    x = root2.child(("SA",))
    y = x.child(("HK",))
    mutant([root2, x, y], 1.0)
    assert y.N == 1
    assert root2.N == 0 and x.N == 0          # the mutant is RED here
    assert not all(n.N == 1 for n in (root2, x, y))


def test_search_backs_up_every_node_on_every_path():
    rnd = _contested_state()
    seat = rnd.turn
    stub = _StubEvaluator(lambda p, s: 0.25)
    bot = _bot(stub, CWV_TRACE=True, CWV_SIMULATIONS=24)
    bot.decide_play(rnd, seat)
    root = bot.last_root
    assert root.N == 24
    # every node's visits equal the sum of its children's visits plus the
    # number of simulations that ended AT it (leaf creations + terminals)
    ended_at = {}
    for tr in bot.last_trace:
        ended_at[tr["path"][-1]] = ended_at.get(tr["path"][-1], 0) + 1

    def walk(node):
        total = sum(walk(child) for child in node.children.values())
        assert node.N == total + ended_at.get(node.key, 0), node.key
        assert node.pending == 0
        assert node.Q == pytest.approx(0.25)
        return node.N
    walk(root)


# ------------------------------------------------ 3. legality masking

def _violations(bot, rnd, seat):
    """Selections of an action the current world's ballot does not offer."""
    bad = []
    for tr in bot.last_trace:
        for key, s, action, world_ballot in tr["moves"]:
            if action not in world_ballot:
                bad.append((key, s, action))
    return bad


def test_actions_illegal_in_the_current_world_are_never_selected(monkeypatch):
    rnd = _contested_state()
    seat = rnd.turn
    stub = _StubEvaluator(lambda p, s: float(len(_plays_of(p)) % 3) - 1.0)
    bot = _bot(stub, CWV_TRACE=True, CWV_SIMULATIONS=96)
    bot.decide_play(rnd, seat)
    # the union below the root is wider than any one world's ballot: the
    # mask has something to mask
    below = [n for n in bot.last_root.children.values() if n.actions]
    assert any(len(n.actions) > len(set(w_b)) for n in below
               for tr in bot.last_trace for key, s, a, w_b in tr["moves"]
               if key == n.key), "no node saw differing ballots across worlds"
    assert _violations(bot, rnd, seat) == []

    # MUTANT: masking removed -- the union is selected from directly
    monkeypatch.setattr(CWVPuctBot, "_legal_children",
                        lambda self, node, world_ballot: list(node.actions))
    mutant = _bot(stub, CWV_TRACE=True, CWV_SIMULATIONS=96)
    try:
        mutant.decide_play(rnd, seat)
        violated = bool(_violations(mutant, rnd, seat))
    except Exception:                  # the engine refuses a card not in hand
        violated = True
    assert violated


# --------------------------------------- 4. batched == per-leaf scoring

def test_batched_leaf_values_are_assigned_to_their_own_leaves():
    rnd = _contested_state()
    seat = rnd.turn

    def rule(position, root_seat):
        return float(hash(_plays_of(position)) % 1000) / 1000.0
    stub = _StubEvaluator(rule)
    bot = _bot(stub, CWV_TRACE=True, CWV_SIMULATIONS=32, CWV_BATCH=8)
    bot.decide_play(rnd, seat)
    assert len(stub.batches) == 4 and all(len(b[0]) == 8 for b in stub.batches)
    for tr in bot.last_trace:
        assert tr["value"] == pytest.approx(rule(tr["leaf"], seat))

    # MUTANT: rows misassigned (the batch's values reversed)
    class Reversed(_StubEvaluator):
        def score(self, positions, root_seat):
            return super().score(positions, root_seat)[::-1].copy()
    mutant = _bot(Reversed(rule), CWV_TRACE=True, CWV_SIMULATIONS=32, CWV_BATCH=8)
    mutant.decide_play(rnd, seat)
    assert any(tr["value"] != pytest.approx(rule(tr["leaf"], seat))
               for tr in mutant.last_trace)


# --------------------------------------------- 5. virtual loss restored

def _all_nodes(node):
    yield node
    for child in node.children.values():
        yield from _all_nodes(child)


def test_virtual_loss_is_removed_after_backup():
    rnd = _contested_state()
    seat = rnd.turn
    constant = 0.375
    stub = _StubEvaluator(lambda p, s: constant)
    sequential = _bot(stub, CWV_SIMULATIONS=64, CWV_BATCH=1)
    batched = _bot(stub, CWV_SIMULATIONS=64, CWV_BATCH=4)
    sequential.decide_play(copy.deepcopy(rnd), seat)
    batched.decide_play(copy.deepcopy(rnd), seat)
    for bot in (sequential, batched):
        nodes = list(_all_nodes(bot.last_root))
        assert bot.last_root.N == 64
        assert all(n.pending == 0 for n in nodes)
        # with a constant leaf every node's value equals the constant
        # exactly, K=1 and K=4 alike, iff the virtual loss was restored
        assert all(abs(n.Q - constant) < 1e-9 for n in nodes if n.N)
        assert sum(n.N for n in bot.last_root.children.values()) == 64

    # MUTANT: pending visits are not released at backup -- Q is polluted
    def leaky(path, value):
        for node in path:
            node.N += 1
            node.W += value
    original = cwv_puct.backup
    cwv_puct.backup = leaky
    try:
        mutant = _bot(stub, CWV_SIMULATIONS=64, CWV_BATCH=4)
        mutant.decide_play(copy.deepcopy(rnd), seat)
    finally:
        cwv_puct.backup = original
    nodes = list(_all_nodes(mutant.last_root))
    assert any(n.pending > 0 for n in nodes)


# ------------------------------------------------- 6. argmax visits

def test_move_is_the_argmax_of_root_visits_not_values():
    root = Node((), 0)
    candidates = [["SA"], ["HK"], ["D3"]]
    for cand, n, w in zip(candidates, (10, 2, 5), (1.0, 1.8, 0.0)):
        child = root.child(action_key(cand))
        child.N, child.W = n, w
    assert select_move(root, candidates) == 0            # 10 visits, Q 0.1
    # MUTANT: argmax over Q picks the rarely visited high-Q child
    by_value = max(range(3), key=lambda i: root.children[action_key(candidates[i])].Q)
    assert by_value == 1 and by_value != select_move(root, candidates)

    # end to end: a stub that rewards one root action makes it dominate
    rnd = _contested_state()
    seat = rnd.turn
    from shengji.ai.mcbot import MCBot
    ballot = MCBot(seed=0)._candidates(rnd, seat)
    target = action_key(ballot[-1])

    def rule(position, root_seat):
        return 1.0 if _plays_of(position)[len(_plays_of(rnd))] == target else -1.0
    stub = _StubEvaluator(rule)
    bot = _bot(stub, CWV_SIMULATIONS=96)
    move = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert action_key(move) == target
    assert rec["visits"][len(ballot) - 1] == max(rec["visits"])
    assert rec["reason"] == "puct_argmax_visits"
    assert rec["work"]["simulations"] == 96 and rec["work"]["positions"] == 96
    assert rec["work"]["max_depth"] >= 1 and rec["work"]["forward_passes"] == 96 // 4


# ------------------------------------- 7. identity / calibration binding

def test_search_identity_and_calibration_binding_refuse_a_mismatch(tmp_path):
    stub = _StubEvaluator(lambda p, s: 0.0)
    bot = _bot(stub, CWV_SIMULATIONS=64, CWV_WORLD_POOL=8, CWV_BATCH=16,
               CWV_C_PUCT=2.0, CWV_PRIOR="uniform")
    identity = bot.search_identity()
    assert identity["simulations"] == 64 and identity["world_pool"] == 8
    assert identity["batch"] == 16 and identity["c_puct"] == 2.0
    assert identity["prior"] == "uniform"
    rnd = _contested_state()
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_decision_record["search"] == identity

    duel = _load_script("cwv_duel")
    search = duel.search_binding(world_pool=8, batch=16, c_puct=2.0, prior="uniform",
                                 prior_checkpoint_sha256=None)
    rungs = [{"budget": "1x", "multiplier": 1.0, "worlds": 64}]
    binding = duel.calibration_binding(
        "a" * 64, finish_trick=True, lcb=0.0, base_policy="mc-s0-report-lcb",
        trump_ranks="2", budgets=rungs, search=search)
    calibration = {"schema": duel.CALIBRATION_SCHEMA, "binding": binding,
                   "identity_sha256": duel.calibration_identity(binding)}
    common = dict(checkpoint_sha256="a" * 64, finish_trick=True, lcb=0.0,
                  base_policy="mc-s0-report-lcb", trump_ranks="2", budgets=[1.0])
    assert duel.check_calibration(calibration, search=search, **common)[0]["worlds"] == 64
    for mutation in ({"world_pool": 32}, {"batch": 8}, {"c_puct": 1.5},
                     {"prior": "head", "prior_checkpoint_sha256": "b" * 64},
                     {"prior_checkpoint_sha256": "c" * 64}):
        drifted = duel.search_binding(**{**dict(world_pool=8, batch=16, c_puct=2.0,
                                                prior="uniform",
                                                prior_checkpoint_sha256=None),
                                         **mutation})
        with pytest.raises(duel.CalibrationMismatch):
            duel.check_calibration(calibration, search=drifted, **common)
    # the one-ply calibration (no search block) is refused for a tree run
    with pytest.raises(duel.CalibrationMismatch):
        duel.check_calibration(calibration, search=None, **common)
    # and S itself is a budget: a rung not in the calibration is refused
    with pytest.raises(duel.CalibrationMismatch):
        duel.check_calibration(calibration, search=search,
                               **{**common, "budgets": [1.0, 3.0]})


def test_registry_names_bind_checkpoint_and_simulations(tmp_path):
    ckpt = tmp_path / "x.pt"
    ckpt.write_bytes(b"not a checkpoint")
    entries = cwv_puct_registry_entries(str(ckpt), [64, 256], prior="uniform")
    ckpt8 = cwv_puct.checkpoint_id(ckpt)
    assert set(entries) == {puct_policy_name(ckpt8, 64), puct_policy_name(ckpt8, 256),
                            puct_control_name(ckpt8, 64), puct_control_name(ckpt8, 256)}
    assert all(name.startswith("mc-cwvpuct-") for name in entries)
    with pytest.raises(CWVError):
        cwv_puct.make_cwv_puct_bot(str(ckpt), simulations=4, prior="head")


# --------------------------------------------- 8. zero-signal baseline

def test_constant_leaf_spreads_visits_uniformly_and_keeps_the_heuristic_pick():
    """With no signal the tree cannot prefer anything: a constant leaf and
    a uniform prior reduce PUCT to round-robin, root visits differ by at most
    one across the ballot, and the move is ballot[0] -- production's own
    heuristic pick, the same move the one-ply bot makes on a constant
    evaluator (reason ``candidate0_best``)."""
    from shengji.ai.mcbot import MCBot
    from shengji.ai.cwv_policy import CWVOnePlyBot

    stub = _StubEvaluator(lambda p, s: 0.0)
    for seed in (5, 6):
        rnd = _contested_state(seed)
        seat = rnd.turn
        ballot = MCBot(seed=0)._candidates(rnd, seat)
        bot = _bot(stub, CWV_SIMULATIONS=40)
        move = bot.decide_play(copy.deepcopy(rnd), seat)
        rec = bot.last_decision_record
        assert max(rec["visits"]) - min(rec["visits"]) <= 1
        assert move == ballot[0] and rec["reason"] == "candidate0_best"
        one_ply = type("OnePly", (CWVOnePlyBot,), {"CWV_WORLDS": 4})(
            seed=7, evaluator=_StubEvaluator(lambda p, s: 0.0))
        assert one_ply.decide_play(copy.deepcopy(rnd), seat) == move

    # MUTANT: a leaf with signal breaks the uniform spread
    rnd = _contested_state(5)
    seat = rnd.turn
    ballot = MCBot(seed=0)._candidates(rnd, seat)
    target = action_key(ballot[1])
    signal = _StubEvaluator(
        lambda p, s: 1.0 if _plays_of(p)[len(_plays_of(rnd))] == target else -1.0)
    mutant = _bot(signal, CWV_SIMULATIONS=40)
    mutant.decide_play(copy.deepcopy(rnd), seat)
    rec = mutant.last_decision_record
    assert max(rec["visits"]) - min(rec["visits"]) > 1
