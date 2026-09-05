"""Witnesses for the PUCT bot's heuristic-playout leaf (``leaf="playout"``).

Every test carries its mutation: the sign or the scale of the leaf value,
the exact-endgame switch, the leaf keys of the binding.
"""
from __future__ import annotations

import copy
import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import cwv_puct
from shengji.ai.cwv_policy import CWVError
from shengji.ai.cwv_puct import (
    CWVPuctBot,
    action_key,
    cwv_puct_registry_entries,
    leaf_identity,
    playout_level,
    puct_control_name,
    puct_policy_name,
    world_clone,
)
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate import (
    OUTCOME_CLASSES,
    category_signed_level,
    terminal_distribution,
)

SUPPORT = np.asarray([category_signed_level(i) for i in range(OUTCOME_CLASSES)])


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


def _contested_state(seed: int = 5, start: int = 4, *, min_candidates: int = 3,
                     max_cards: int | None = None):
    bot = MCBot(seed=0)
    for plies in range(start, 110):
        rnd = _state_after(seed, plies)
        if rnd.phase != "play":
            break
        if max_cards is not None and max(len(h) for h in rnd.hands) > max_cards:
            continue
        if len(bot._candidates(rnd, rnd.turn)) >= min_candidates:
            return rnd
    raise AssertionError("no suitable state found")


class _StubEvaluator:
    """A net whose value is unmistakable (99): a leaf priced by it is RED."""
    backend = "stub"
    checkpoint_sha256 = None
    ckpt8 = None

    def __init__(self, value: float = 99.0):
        self.value = value
        self.batches = []
        self.forward_calls = 0

    def identity(self):
        return {"kind": "stub"}

    def score(self, positions, root_seat):
        self.batches.append((list(positions), root_seat))
        self.forward_calls += 1
        return np.full(len(positions), self.value, dtype=np.float64)


def _bot(evaluator, **attrs) -> CWVPuctBot:
    cls = type("Probe", (CWVPuctBot,), {"CWV_WORLD_POOL": 4, "CWV_BATCH": 4,
                                        "CWV_SIMULATIONS": 32, "CWV_TRACE": True,
                                        **attrs})
    return cls(seed=7, evaluator=evaluator)


def _capture_worlds(bot):
    """Record the world pool the decision sampled (the trace indexes it)."""
    captured = {}
    original = bot.sample_worlds

    def sample(rnd, seat, n, *, mem=None):
        worlds, attempts = original(rnd, seat, n, mem=mem)
        captured["worlds"] = [([list(h) for h in hands], list(buried))
                              for hands, buried in worlds]
        return worlds, attempts
    bot.sample_worlds = sample
    return captured


def _replay_leaf(rnd, world, trace_entry):
    """The leaf position of one simulation, rebuilt from its world and moves."""
    hands, buried = world
    clone = world_clone(rnd, hands, buried)
    for _key, seat, action, _ballot, _accepted in trace_entry["moves"]:
        clone.play(seat, list(action))
    return clone


def _independent_playout(leaf, root_seat) -> tuple[float, int]:
    """A fresh HeuristicBot plays the world to round end; the value is the
    evaluator's own terminal rule (``terminal_distribution @ support``)."""
    clone = copy.deepcopy(leaf)
    policy = HeuristicBot()
    while clone.phase == "play":
        s = clone.turn
        clone.play(s, policy.decide_play(clone, s))
    return float(terminal_distribution(clone, root_seat) @ SUPPORT), int(clone.attacker_points)


# ------------------------------------------------ 1. the leaf IS a playout

@pytest.mark.parametrize("seed", [5, 6])
def test_playout_leaf_values_equal_an_independent_playout(seed):
    rnd = _contested_state(seed)
    seat = rnd.turn
    stub = _StubEvaluator(99.0)
    bot = _bot(stub, CWV_LEAF="playout")
    captured = _capture_worlds(bot)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    trace = bot.last_trace
    assert len(trace) == rec["work"]["simulations"] == 32
    assert rec["work"]["playouts"] == 32 and stub.batches == []   # the net never priced a leaf
    root = bot.last_root
    assert root.N == 32 and root.W == pytest.approx(sum(t["value"] for t in trace))
    sign_flips = scale_flips = 0
    for entry in trace:
        leaf = _replay_leaf(rnd, captured["worlds"][entry["world"]], entry)
        want, points = _independent_playout(leaf, seat)
        assert entry["value"] == want, (entry["path"], entry["value"], want)
        # MUTANT sign: the value from the other team's view is a different number
        assert entry["value"] == -float(terminal_distribution(
            _terminal_of(leaf), (seat + 1) % 4) @ SUPPORT)
        sign_flips += entry["value"] != -want
        # MUTANT scale: production's raw attacker points are never the tree's level
        scale_flips += entry["value"] != float(points)
    assert sign_flips == len(trace) and scale_flips == len(trace)


def _terminal_of(leaf):
    clone = copy.deepcopy(leaf)
    policy = HeuristicBot()
    while clone.phase == "play":
        s = clone.turn
        clone.play(s, policy.decide_play(clone, s))
    return clone


def test_playout_level_is_the_terminal_leaf_scale():
    """``playout_level`` is exactly what a terminal leaf gets under the net
    leaf (``terminal_distribution @ support``): points -> half-integer signed
    level, signed from the root seat's team."""
    rnd = _contested_state(5)
    terminal = _terminal_of(world_clone(rnd, [list(h) for h in rnd.hands], list(rnd.buried)))
    points = terminal.attacker_points
    for seat in range(4):
        want = float(terminal_distribution(terminal, seat) @ SUPPORT)
        assert playout_level(points, terminal.is_attacker(seat)) == want
        assert playout_level(float(points), terminal.is_attacker(seat)) == want
        assert playout_level(points, not terminal.is_attacker(seat)) == -want   # sign
        assert want != float(points) and abs(want) % 1 == 0.5               # scale
    with pytest.raises(CWVError):
        playout_level(80.5, True)


def test_leaf_playouts_average_and_are_counted():
    rnd = _contested_state(5)
    seat = rnd.turn
    one = _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_LEAF_PLAYOUTS=1)
    three = _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_LEAF_PLAYOUTS=3)
    one.decide_play(copy.deepcopy(rnd), seat)
    three.decide_play(copy.deepcopy(rnd), seat)
    assert one.last_decision_record["work"]["playouts"] == 32
    assert three.last_decision_record["work"]["playouts"] == 96
    assert three.leaf_playouts == 96
    # production's HeuristicBot is deterministic: the average of three equal
    # playouts is the playout, so the two searches agree simulation by simulation
    assert [t["value"] for t in one.last_trace] == [t["value"] for t in three.last_trace]
    assert three.search_identity()["leaf_playouts"] == 3
    with pytest.raises(CWVError):
        _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_LEAF_PLAYOUTS=0)
    with pytest.raises(CWVError):
        _bot(_StubEvaluator(), CWV_LEAF="rollout")


# ------------------------------------------------ 2. the net leaf is untouched

def test_net_leaf_is_the_default_and_prices_every_leaf_by_the_net():
    rnd = _contested_state(5)
    seat = rnd.turn
    stub = _StubEvaluator(99.0)
    bot = _bot(stub)
    assert bot.CWV_LEAF == "net"
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert sum(len(b[0]) for b in stub.batches) == 32
    assert all(t["value"] == 99.0 for t in bot.last_trace)
    # the v1 identity: no leaf keys under the net leaf, no playout counters
    assert "leaf" not in rec["search"] and "leaf_playouts" not in rec["search"]
    assert "playouts" not in rec["work"] and bot.leaf_playouts == 0
    assert leaf_identity("net", 1) == {}
    assert leaf_identity("playout", 1) == {"leaf": "playout", "leaf_playouts": 1}
    assert leaf_identity("playout", 4) == {"leaf": "playout", "leaf_playouts": 4}


# --------------------------------------- 3. the exact-endgame hook at leaves

def test_exact_endgame_hook_settles_short_leaves():
    from shengji.ai.endgame import ExactWorldSession

    rnd = _contested_state(5, start=60, min_candidates=2, max_cards=4)
    assert max(len(h) for h in rnd.hands) <= 4
    seat = rnd.turn
    exact = _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_SIMULATIONS=16,
                 EXACT_ENDGAME=True, EXACT_ENDGAME_MAX_CARDS=4,
                 EXACT_ENDGAME_MAX_NODES=250_000)
    captured = _capture_worlds(exact)
    exact.decide_play(copy.deepcopy(rnd), seat)
    rec = exact.last_decision_record
    assert rec["work"]["simulations"] == 16
    assert rec["work"]["exact_leaves"] == 16 and exact.exact_endgame_calls >= 1
    assert exact.exact_endgame_sessions == len(captured["worlds"])
    for entry in exact.last_trace:
        world = captured["worlds"][entry["world"]]
        leaf = _replay_leaf(rnd, world, entry)
        if leaf.phase != "play":
            want = float(terminal_distribution(leaf, seat) @ SUPPORT)
        else:
            context = copy.copy(rnd)
            context.buried = sorted(world[1])
            solved = ExactWorldSession(context, max_hand_cards=4, max_nodes=250_000).solve(leaf)
            want = playout_level(solved.attacker_points, leaf.is_attacker(seat))
        assert entry["value"] == want
    # MUTANT: the hook off -> every leaf is a heuristic playout, none exact
    plain = _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_SIMULATIONS=16)
    plain.decide_play(copy.deepcopy(rnd), seat)
    assert plain.last_decision_record["work"]["exact_leaves"] == 0
    assert plain.exact_endgame_calls == 0 and plain.exact_leaves == 0


# ---------------------------------------------- 4. identity and the binding

def test_names_bind_the_leaf_mode_and_playouts(tmp_path):
    assert puct_policy_name("abcd1234", 64) == "mc-cwvpuct-abcd1234-s64"
    assert puct_policy_name("abcd1234", 64, leaf="playout") == "mc-cwvpuct-abcd1234-s64-pleaf"
    assert puct_policy_name("abcd1234", 64, leaf="playout", leaf_playouts=3) \
        == "mc-cwvpuct-abcd1234-s64-pleaf3"
    assert puct_control_name("abcd1234", 64, leaf="playout") \
        == "mc-cwvpuct-prior-abcd1234-s64-pleaf"
    ckpt = tmp_path / "x.pt"
    ckpt.write_bytes(b"not a checkpoint")
    ckpt8 = cwv_puct.checkpoint_id(ckpt)
    entries = cwv_puct_registry_entries(str(ckpt), [64], leaf="playout", leaf_playouts=2)
    assert set(entries) == {f"mc-cwvpuct-{ckpt8}-s64-pleaf2",
                            f"mc-cwvpuct-prior-{ckpt8}-s64-pleaf2"}
    assert set(cwv_puct_registry_entries(str(ckpt), [64])) == {
        f"mc-cwvpuct-{ckpt8}-s64", f"mc-cwvpuct-prior-{ckpt8}-s64"}
    with pytest.raises(CWVError):
        cwv_puct_registry_entries(str(ckpt), [64], leaf="rollout")
    with pytest.raises(CWVError):
        puct_policy_name("abcd1234", 64, leaf="playout", leaf_playouts=0)


def test_calibration_binding_refuses_a_net_leaf_calibration_for_a_playout_arm():
    duel = _load_script("cwv_duel")
    base = dict(world_pool=8, batch=16, c_puct=2.0, prior="uniform",
                prior_checkpoint_sha256=None)
    common = dict(checkpoint_sha256="a" * 64, finish_trick=True, lcb=0.0,
                  base_policy="mc-s0-report-lcb", trump_ranks="2", budgets=[1.0])
    rungs = [{"budget": "1x", "multiplier": 1.0, "worlds": 64}]

    def calibration_for(search):
        binding = duel.calibration_binding(
            "a" * 64, finish_trick=True, lcb=0.0, base_policy="mc-s0-report-lcb",
            trump_ranks="2", budgets=rungs, search=search)
        return {"schema": duel.CALIBRATION_SCHEMA, "binding": binding,
                "identity_sha256": duel.calibration_identity(binding)}

    net = duel.search_binding(**base)
    playout = duel.search_binding(**base, leaf="playout")
    playout3 = duel.search_binding(**base, leaf="playout", leaf_playouts=3)
    assert "leaf" not in net and playout["leaf"] == "playout" \
        and playout["leaf_playouts"] == 1 and playout3["leaf_playouts"] == 3
    assert net == duel.search_binding(**base, leaf="net")     # the v1 binding, unchanged
    # a playout arm accepts its own calibration
    assert duel.check_calibration(calibration_for(playout), search=playout, **common)[0]["worlds"] == 64
    # ... and refuses the net-leaf one, another playout count, and vice versa
    for calibration, live in ((calibration_for(net), playout),
                              (calibration_for(playout3), playout),
                              (calibration_for(playout), playout3),
                              (calibration_for(playout), net)):
        with pytest.raises(duel.CalibrationMismatch, match="leaf"):
            duel.check_calibration(calibration, search=live, **common)
    # the search identity the bot records carries the same keys as the binding
    bot = _bot(_StubEvaluator(), CWV_LEAF="playout", CWV_LEAF_PLAYOUTS=3)
    identity = bot.search_identity()
    assert {k: identity[k] for k in ("leaf", "leaf_playouts")} == \
        {k: playout3[k] for k in ("leaf", "leaf_playouts")}
    # and the CLI parses it
    args = duel.build_parser().parse_args(
        ["calibrate", "--checkpoint", "x.pt", "--out", "c.json", "--tree",
         "--leaf", "playout", "--leaf-playouts", "2"])
    assert duel.search_from_args(args)["leaf"] == "playout"
    assert duel.search_from_args(args)["leaf_playouts"] == 2
    assert duel.arm_name(args, "abcd1234", 64) == "mc-cwvpuct-abcd1234-s64-pleaf2"
    assert duel.control_arm_name(args, "abcd1234", 64) == "mc-cwvpuct-prior-abcd1234-s64-pleaf2"
    plain = duel.build_parser().parse_args(
        ["calibrate", "--checkpoint", "x.pt", "--out", "c.json", "--tree"])
    assert "leaf" not in duel.search_from_args(plain)
    assert duel.arm_name(plain, "abcd1234", 64) == "mc-cwvpuct-abcd1234-s64"
