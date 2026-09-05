"""Value-at-leaf arms: the rollout leaf is the ONLY change, in production's
units, from the clone's seat to act.  Every property carries a mutation
witness: the same check under a one-line mutant, which must go RED."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import (REGISTRY, VLEAF_LEAF_TRICKS, make_bot, register_vleaf_arms,
                                 vleaf_policy_name)
from shengji.engine.game import Game
from shengji.rl.encode import ACT_DIM, OBS_DIM
from shengji.train import data
from shengji.train import leaf_policy as L
from shengji.train.baselines import N_STRATA, stratum_index
from shengji.train.model import DEFAULT_ARCH, MODEL_SCHEMA, ValuePriorNet
from shengji.train.search_inference import CHECKPOINT_SCHEMA, LEGACY_CHECKPOINT_SCHEMA
from shengji.train.search_screen import _publish

BASE = "mc-s0-report-lcb"
VOLATILE = ("search_secs", "policy", "policy_class")
NO_TRUNCATION = 100          # beyond any round's trick count: the identity horizon


# ------------------------------------------------------------------ fixtures

def deal(seed: int):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policy = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policy.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policy.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, policy.decide_bury(rnd, rnd.banker))
    return rnd


def advance(rnd, stop):
    """Play the heuristic until ``stop(rnd)``; returns the seat to act."""
    policy = HeuristicBot()
    while rnd.phase == "play" and not stop(rnd):
        rnd.play(rnd.turn, policy.decide_play(rnd, rnd.turn))
    assert rnd.phase == "play"
    return rnd.turn


def pair_lead_state(seed: int):
    """A lead with exactly two identical cards in hand: the ballot is [pair,
    single]; the pair ends the round in one trick, the single does not."""
    rnd = deal(seed)
    seat = advance(rnd, lambda r: not r.trick.plays and len(r.hands[r.turn]) == 2
                   and r.hands[r.turn][0] == r.hands[r.turn][1])
    return rnd, seat


def last_trick_state(seed: int):
    rnd = deal(seed)
    seat = advance(rnd, lambda r: not r.trick.plays and sum(map(len, r.hands)) == 4)
    return rnd, seat


def mid_trick_state(seed: int):
    rnd = deal(seed)
    seat = advance(rnd, lambda r: len(r.trick.plays) == 1 and len(r.history) >= 2)
    return rnd, seat


def true_world(rnd, seat):
    return {s: list(h) for s, h in enumerate(rnd.hands) if s != seat}, list(rnd.buried)


def _tiny(bot):
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 30
    return bot


def _strip(record):
    return {k: v for k, v in record.items() if k not in VOLATILE}


def _play_seat0(bot, seed, twin=None):
    """One round with ``bot`` at seat 0 (heuristics elsewhere); with ``twin``
    the twin decides every seat-0 play on the SAME state first and the two
    must agree on cards, decision record and RNG advance (test_oracle_screen)."""
    game = Game(random.Random(seed))
    rnd = game.start_round()
    pol = [bot, HeuristicBot(), HeuristicBot(), HeuristicBot()]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = pol[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = pol[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    bury = pol[rnd.banker].decide_bury(rnd, rnd.banker)
    if twin is not None and rnd.banker == 0:
        assert twin.decide_bury(rnd, 0) == bury
    rnd.bury(rnd.banker, bury)
    decisions = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if seat == 0 and twin is not None:
            assert twin.rng.getstate() == bot.rng.getstate()
            expected = twin.decide_play(rnd, 0)
            expected_record = twin.last_decision_record
        cards = pol[seat].decide_play(rnd, seat)
        if seat == 0:
            decisions += 1
            if twin is not None:
                assert cards == expected
                assert twin.rng.getstate() == bot.rng.getstate(), \
                    "the leaf advanced the production stream differently"
                actual = bot.last_decision_record
                assert (actual is None) == (expected_record is None)
                if actual is not None:
                    assert _strip(actual) == _strip(expected_record)
        rnd.play(seat, cards)
    game.finish_round()
    return decisions


class Const:
    """A stub leaf: constant final attacker points."""

    kind = "stub"

    def __init__(self, value):
        self.value = float(value)
        self.calls = 0

    def final_attacker_points(self, clone, seat):
        self.calls += 1
        return self.value

    def describe(self):
        return {"kind": self.kind, "value": self.value}


def small_arch(aux: bool = True) -> dict:
    return {"obs_dim": OBS_DIM, "act_dim": ACT_DIM, "trunk": [16, 8], "value_hidden": 4,
            "prior_hidden": 5, "dropout": 0.0, "aux_points": aux, "aux_search_mean": False}


def payload(model, *, schema=CHECKPOINT_SCHEMA, encoder=None) -> dict:
    return {"schema": schema, "model_schema": MODEL_SCHEMA, "arch": model.arch,
            "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "encoder": encoder or data.encoder_identity(), "epoch": 3,
            "population": {"schema": "population-test", "counts": {"train": 1}}}


def save(path, model, **kw):
    torch.save(payload(model, **kw), path)
    return str(path)


@pytest.fixture()
def aux_model():
    torch.manual_seed(11)
    return ValuePriorNet(small_arch(True)).eval()


@pytest.fixture()
def aux_checkpoint(tmp_path, aux_model):
    return save(tmp_path / "aux.pt", aux_model)


@pytest.fixture()
def headless_checkpoint(tmp_path):
    torch.manual_seed(12)
    return save(tmp_path / "headless.pt", ValuePriorNet(small_arch(False)).eval())


def prior_table(sums=None, counts=None, **prov):
    sums = np.arange(N_STRATA, dtype=float) * 10.0 if sums is None else np.asarray(sums, float)
    counts = np.ones(N_STRATA, dtype=np.int64) if counts is None else np.asarray(counts, np.int64)
    return L.StratifiedPointsPrior(sums, counts, provenance={"fitted_on": "test", **prov})


# --------------------------------------------- 1. exact when nothing is truncated

@pytest.mark.parametrize("seed", [4_242, 4_243, 4_244])
def test_leaf_substitution_is_exact_when_nothing_is_truncated(seed):
    """Horizon beyond the round: the arm is production, byte for byte (cards,
    record, RNG), and the head is never consulted."""
    prod = _tiny(make_bot(BASE, seed=seed))
    leaf = Const(999.0)
    arm = _tiny(L.MCValueLeafSearch(leaf, seed=seed, leaf_tricks=NO_TRUNCATION))
    assert isinstance(arm, type(prod))
    decisions = _play_seat0(arm, seed, twin=prod)
    assert decisions > 5
    assert arm.search_calls == prod.search_calls > 0
    assert arm.rollouts == prod.rollouts > 0
    assert leaf.calls == 0 and arm.leaf_secs == 0.0
    assert arm.leaf_counts["predicted_leaves"] == 0
    assert arm.leaf_counts["terminal_leaves"] == arm.leaf_counts["leaf_calls"] == arm.rollouts


def test_witness_truncation_before_round_end_at_large_t_is_caught(monkeypatch):
    """Mutant: the horizon silently caps T at three tricks."""
    monkeypatch.setattr(L.MCValueLeafSearch, "_leaf_horizon",
                        lambda self, rnd: len(rnd.history) + min(self.LEAF_TRICKS, 3))
    seed = 4_242
    prod = _tiny(make_bot(BASE, seed=seed))
    arm = _tiny(L.MCValueLeafSearch(Const(999.0), seed=seed, leaf_tricks=NO_TRUNCATION))
    with pytest.raises(AssertionError):
        _play_seat0(arm, seed, twin=prod)
    assert arm.leaf_counts["predicted_leaves"] > 0


# ---------------------------------------------------------- 2. terminal units

def test_terminal_leaf_returns_production_points_never_the_head():
    rnd, seat = last_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    prod = make_bot(BASE, seed=1)
    leaf = Const(999.0)
    arm = L.MCValueLeafSearch(leaf, seed=1, leaf_tricks=1)
    candidate = prod._candidates(rnd, seat)[0]
    expected = prod._rollout(rnd, seat, sampled, buried, list(candidate))
    got = arm._rollout(rnd, seat, sampled, buried, list(candidate))
    truth = copy.deepcopy(rnd)
    truth.play(seat, list(candidate))
    policy = HeuristicBot()
    while truth.phase == "play":
        truth.play(truth.turn, policy.decide_play(truth, truth.turn))
    assert got == expected == float(truth.attacker_points)
    assert isinstance(got, float) and got != 999.0
    assert leaf.calls == 0
    assert arm.leaf_counts == {"leaf_calls": 1, "terminal_leaves": 1, "exact_leaves": 0,
                               "predicted_leaves": 0, "leaf_plies": 3}


def test_witness_head_returned_for_a_terminal_leaf_is_caught(monkeypatch):
    """Mutant: the terminal leaf asks the head."""
    monkeypatch.setattr(L.MCValueLeafSearch, "_terminal_value",
                        lambda self, clone: self.leaf.final_attacker_points(clone, 0))
    rnd, seat = last_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    prod = make_bot(BASE, seed=1)
    arm = L.MCValueLeafSearch(Const(999.0), seed=1, leaf_tricks=1)
    candidate = prod._candidates(rnd, seat)[0]
    expected = prod._rollout(rnd, seat, sampled, buried, list(candidate))
    got = arm._rollout(rnd, seat, sampled, buried, list(candidate))
    assert got == 999.0 != expected


# ------------------------------------------------------ 3. the leaf is used

@pytest.mark.parametrize("seed", [15, 28])
def test_learned_leaf_is_used_constant_heads_change_the_decision(seed):
    """At a two-card pair lead with T=1 the pair's continuation ends the round
    (production's value) while the single's is a predicted leaf; a head that
    says 200 and one that says 0 must rank them differently."""
    rnd, seat = pair_lead_state(seed)
    decisions = {}
    for value in (200.0, 0.0):
        bot = _tiny(L.MCValueLeafSearch(Const(value), seed=7, leaf_tricks=1))
        decisions[value] = bot.decide_play(copy.deepcopy(rnd), seat)
        assert bot.leaf_counts["terminal_leaves"] > 0
        assert bot.leaf_counts["predicted_leaves"] > 0
        assert bot.last_decision_record["work"]["complete"]
    assert decisions[200.0] != decisions[0.0]
    assert {tuple(d) for d in decisions.values()} == {tuple(c) for c in
                                                       make_bot(BASE)._candidates(rnd, seat)}


def test_witness_bypassed_head_makes_constant_heads_indistinguishable(monkeypatch):
    """Mutant: the continuation ignores T and always plays to round end."""
    monkeypatch.setattr(L.MCValueLeafSearch, "_leaf_horizon",
                        lambda self, rnd: len(rnd.history) + NO_TRUNCATION)
    rnd, seat = pair_lead_state(15)
    decisions = {}
    for value in (200.0, 0.0):
        bot = _tiny(L.MCValueLeafSearch(Const(value), seed=7, leaf_tricks=1))
        decisions[value] = bot.decide_play(copy.deepcopy(rnd), seat)
    assert decisions[200.0] == decisions[0.0]


# --------------------------------------------------------- 4. numpy == torch

def test_numpy_points_head_matches_torch_on_256_random_rows():
    torch.manual_seed(5)
    model = ValuePriorNet({**DEFAULT_ARCH, "aux_points": True}).eval()
    head = L.PointsHead.from_model(model)
    rows = torch.rand(256, OBS_DIM, generator=torch.Generator().manual_seed(6))
    with torch.inference_mode():
        expected = model.value_head(model.trunk(rows)).numpy()
    got = head.forward(rows.numpy())
    assert got.shape == (256, 2)
    assert np.abs(got - expected).max() < 1e-5
    assert head.final_attacker_points(rows[0].numpy()) == pytest.approx(
        float(expected[0, 1]) * L.POINTS_SCALE, abs=1e-3)
    assert head.calls == 1


def test_witness_dropped_bias_breaks_numpy_torch_parity(monkeypatch):
    """Mutant: the exporter forgets the first hidden bias."""
    original = L.PointsHead.__init__

    def dropped(self, hidden, output, **kw):
        w, _ = hidden[0]
        original(self, [(w, np.zeros(w.shape[0]))] + list(hidden[1:]), output, **kw)

    monkeypatch.setattr(L.PointsHead, "__init__", dropped)
    torch.manual_seed(5)
    model = ValuePriorNet({**DEFAULT_ARCH, "aux_points": True}).eval()
    head = L.PointsHead.from_model(model)
    rows = torch.rand(256, OBS_DIM, generator=torch.Generator().manual_seed(6))
    with torch.inference_mode():
        expected = model.value_head(model.trunk(rows)).numpy()
    assert np.abs(head.forward(rows.numpy()) - expected).max() > 1e-5


def test_erf_table_matches_math_erf():
    xs = np.random.default_rng(0).uniform(-9, 9, 200_000)
    exact = np.fromiter(map(math.erf, xs), dtype=float, count=xs.size)
    assert np.abs(L.erf(xs) - exact).max() < 1e-8
    assert L.erf(np.array([-12.0, 0.0, 12.0])) == pytest.approx([-1.0, 0.0, 1.0], abs=1e-12)
    x = torch.linspace(-6, 6, 1001, dtype=torch.float64)
    assert np.abs(L.gelu(x.numpy()) - torch.nn.functional.gelu(x).numpy()).max() < 1e-8


# ------------------------------------------------------------- 5. refusals

def test_refusals_without_points_head_and_encoder_mismatch(tmp_path, headless_checkpoint,
                                                           aux_model):
    with pytest.raises(L.LeafError, match="no points head"):
        L.PointsHead.from_checkpoint(headless_checkpoint)
    with pytest.raises(L.LeafError, match="no points head"):
        L.PointsHead.from_model(ValuePriorNet(small_arch(False)))
    forged = save(tmp_path / "forged.pt", aux_model,
                  encoder={**data.encoder_identity(), "implementation_sha256": "forged"})
    with pytest.raises(ValueError, match="encoder differs"):
        L.PointsHead.from_checkpoint(forged)
    legacy = save(tmp_path / "legacy.pt", aux_model, schema=LEGACY_CHECKPOINT_SCHEMA)
    with pytest.raises(ValueError, match="allow_legacy"):
        L.PointsHead.from_checkpoint(legacy)
    assert L.PointsHead.from_checkpoint(legacy, allow_legacy=True).metadata["legacy"] is True
    # The registry factory refuses too: a named arm cannot load a headless net.
    names = register_vleaf_arms(checkpoint=headless_checkpoint, leaf_tricks=(1,), registry={})
    with pytest.raises(L.LeafError, match="no points head"):
        L.make_vleaf_bot(checkpoint=headless_checkpoint, leaf_tricks=1)
    assert list(names) == [vleaf_policy_name(
        leaf_tricks=1, checkpoint_id=hashlib.sha256(
            open(headless_checkpoint, "rb").read()).hexdigest()[:8])]


def test_witness_skipped_points_head_check_accepts_a_headless_checkpoint(monkeypatch,
                                                                         headless_checkpoint):
    """Mutant: the points-head requirement is a no-op."""
    monkeypatch.setattr(L, "require_points_head", lambda **kw: None)
    head = L.PointsHead.from_checkpoint(headless_checkpoint)
    assert isinstance(head, L.PointsHead)       # the refusal test would be RED


def test_witness_loader_bypassing_search_heads_accepts_a_forged_encoder(monkeypatch, tmp_path,
                                                                       aux_model):
    """Mutant: a loader that skips SearchHeads.from_checkpoint's identity checks."""
    def raw_loader(path, *, allow_legacy=False):
        loaded = torch.load(path, map_location="cpu", weights_only=True)
        model = ValuePriorNet(dict(loaded["arch"]))
        model.load_state_dict(loaded["model_state"])
        return L.PointsHead.from_model(model.eval())

    monkeypatch.setattr(L.PointsHead, "from_checkpoint", staticmethod(raw_loader))
    forged = save(tmp_path / "forged.pt", aux_model,
                  encoder={**data.encoder_identity(), "implementation_sha256": "forged"})
    assert isinstance(L.PointsHead.from_checkpoint(forged), L.PointsHead)


# ---------------------------------------------------------- 7. perspective

@pytest.mark.parametrize("tricks", [0, 1])
def test_leaf_encodes_from_the_clones_seat_to_act(monkeypatch, aux_model, tricks):
    seen = []
    real = L.encode_obs

    def recording(clone, seat):
        seen.append((clone.turn, seat, len(clone.history), len(clone.trick.plays)))
        return real(clone, seat)

    monkeypatch.setattr(L, "encode_obs", recording)
    rnd, seat = mid_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    arm = L.MCValueLeafSearch(L.LearnedPointsLeaf(L.PointsHead.from_model(aux_model)),
                              seed=1, leaf_tricks=tricks)
    for candidate in make_bot(BASE)._candidates(rnd, seat):
        value = arm._rollout(rnd, seat, sampled, buried, list(candidate))
        assert math.isfinite(value)
    assert seen and all(turn == used for turn, used, _, _ in seen)
    assert any(used != seat for _, used, _, _ in seen)
    horizon = len(rnd.history) + tricks
    assert all(history == horizon and plays == (0 if tricks else len(rnd.trick.plays) + 1)
               for _, _, history, plays in seen)


def test_witness_root_seat_perspective_is_caught(monkeypatch, aux_model):
    """Mutant: the leaf is encoded from the root seat."""
    rnd, seat = mid_trick_state(4_242)
    monkeypatch.setattr(L.MCValueLeafSearch, "_leaf_value",
                        lambda self, clone: self.leaf.final_attacker_points(clone, seat))
    seen = []
    real = L.encode_obs
    monkeypatch.setattr(L, "encode_obs",
                        lambda clone, s: seen.append((clone.turn, s)) or real(clone, s))
    sampled, buried = true_world(rnd, seat)
    arm = L.MCValueLeafSearch(L.LearnedPointsLeaf(L.PointsHead.from_model(aux_model)),
                              seed=1, leaf_tricks=0)
    arm._rollout(rnd, seat, sampled, buried, make_bot(BASE)._candidates(rnd, seat)[0])
    assert seen and not all(turn == used for turn, used in seen)


# --------------------------------------------------- prior control and refit

def test_prior_leaf_uses_the_trainers_strata_on_final_points():
    rng = np.random.default_rng(3)
    ply = rng.integers(0, 100, 500)
    role = rng.integers(0, 2, 500).astype(bool)
    points = rng.uniform(0, 160, 500)
    expected = stratum_index(ply, role, points)
    assert [L.leaf_stratum(int(p), bool(r), float(x)) for p, r, x in zip(ply, role, points)] \
        == expected.tolist()
    counts = np.ones(N_STRATA, dtype=np.int64)
    counts[5] = 0                                   # an empty cell: global mean
    sums = np.arange(N_STRATA, dtype=float) * 10.0
    sums[5] = 0.0
    table = L.StratifiedPointsPrior(sums, counts)
    means = table.means
    assert means[5] == pytest.approx(sums.sum() / counts.sum())
    rnd, seat = mid_trick_state(4_242)
    sampled, buried = true_world(rnd, seat)
    leaf = L.PriorPointsLeaf(table)
    arm = L.MCValueLeafSearch(leaf, seed=1, leaf_tricks=1)
    candidate = make_bot(BASE)._candidates(rnd, seat)[0]
    got = arm._rollout(rnd, seat, sampled, buried, list(candidate))
    clone = copy.deepcopy(rnd)
    clone.play(seat, list(candidate))
    policy = HeuristicBot()
    while len(clone.history) < len(rnd.history) + 1:
        clone.play(clone.turn, policy.decide_play(clone, clone.turn))
    cell = L.leaf_stratum(L.leaf_ply(clone), clone.is_attacker(clone.turn), clone.attacker_points)
    assert got == float(means[cell])
    assert L.leaf_ply(clone) == 4 * len(clone.history) + len(clone.trick.plays)
    assert arm.leaf_counts["predicted_leaves"] == 1


def _synthetic_cache(cache_dir, i, rows, *, rng):
    """A cache file in the production layout; five deals per file."""
    deals = [f"deck:{i:04d}{r % 5:060d}" for r in range(rows)]
    ply = rng.integers(0, 100, size=rows).astype(np.int32)
    role = rng.integers(0, 2, size=rows).astype(bool)
    so_far = rng.uniform(0, 150, size=rows).astype(np.float32)
    final = rng.uniform(0, 200, size=rows).astype(np.float32)
    widths = np.ones(rows, dtype=np.int64)
    offsets = np.zeros(rows + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(widths)
    arrays = {
        "obs": np.zeros((rows, OBS_DIM), dtype=np.float32),
        "cand_offsets": offsets, "cand_feats": np.zeros((rows, ACT_DIM), dtype=np.float32),
        "cand_softmax": np.ones(rows, dtype=np.float32), "has_softmax": np.ones(rows, dtype=bool),
        "played": np.zeros(rows, dtype=np.int32), "utility": np.zeros(rows, dtype=np.float32),
        "attacker_points": final, "points_so_far": so_far, "ply": ply, "role_attacker": role,
        "seat": np.zeros(rows, dtype=np.int8), "cluster": np.asarray([f"syn:{i}"] * rows, dtype=str),
        "record_sha256": np.asarray([b"0" * 64] * rows, dtype="S64"),
        "source_ref": np.asarray([f"syn:{i}:{r}" for r in range(rows)], dtype=str),
        "search_mean": np.zeros(rows, dtype=np.float32),
        "has_search_mean": np.zeros(rows, dtype=bool),
        "deal_key": np.asarray(deals, dtype=str),
    }
    sha = hashlib.sha256(f"synthetic-{i}".encode()).hexdigest()
    meta = {"schema": data.CACHE_SCHEMA, "encoder": data.encoder_identity(),
            "shard": {"label": f"synthetic-{i}", "sha256": sha, "records": rows, "cluster": i,
                      "store": "synthetic"},
            "counts": {}, "witness_seed": 0, "witness_every": 1, "witness_sampled": False,
            "deal_key_schema": data.DEAL_KEY_SCHEMA, "deals": 5,
            "nbytes": int(sum(a.nbytes for a in arrays.values()))}
    path = data.cache_path(cache_dir, sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        np.savez(fh, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    return str(path), sha, arrays


def test_fit_points_prior_reproduces_the_trainers_train_split(tmp_path):
    rng = np.random.default_rng(9)
    files = [_synthetic_cache(tmp_path / "cache", i, 40, rng=rng) for i in range(6)]
    table = L.fit_points_prior([p for p, _, _ in files], split_seed=1, val_fraction=0.1,
                               test_fraction=0.1, expected_shards={p: sha for p, sha, _ in files})
    keys = sorted({k for _, _, a in files for k in a["deal_key"].tolist()})
    assignment = data.split_deals(keys, seed=1, val_fraction=0.1, test_fraction=0.1)
    train = {k for k, v in assignment.items() if v == "train"}
    assert 0 < len(train) < len(keys)
    sums = np.zeros(N_STRATA)
    counts = np.zeros(N_STRATA, dtype=np.int64)
    for _, _, a in files:
        keep = np.isin(a["deal_key"], sorted(train))
        idx = stratum_index(a["ply"][keep], a["role_attacker"][keep], a["points_so_far"][keep])
        sums += np.bincount(idx, weights=a["attacker_points"][keep].astype(float), minlength=N_STRATA)
        counts += np.bincount(idx, minlength=N_STRATA)
    assert table.prior.counts.tolist() == counts.tolist()
    assert table.prior.sums == pytest.approx(sums, rel=1e-6)
    assert table.provenance["deals"]["train"] == len(train)
    assert table.provenance["rows"]["train"] == int(counts.sum())
    # Round trip through the JSON the control arm loads.
    path = tmp_path / "prior_points.json"
    _publish(path, table.to_dict())
    loaded = L.StratifiedPointsPrior.from_json(path)
    assert loaded.means.tolist() == table.means.tolist()
    assert loaded.provenance["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    # A cache file bound to another shard refuses.
    with pytest.raises(data.TrainDataError, match="another shard"):
        L.fit_points_prior([files[0][0]], split_seed=1, val_fraction=0.1, test_fraction=0.1,
                           expected_shards={files[0][0]: files[1][1]})


# ------------------------------------------------------------- registry names

def test_registry_names_embed_the_checkpoint_id_and_build_seeded_bots(tmp_path, aux_checkpoint):
    table_path = tmp_path / "prior_points.json"
    _publish(table_path, prior_table().to_dict())
    registry = {BASE: REGISTRY[BASE]}
    names = register_vleaf_arms(checkpoint=aux_checkpoint, prior=table_path, registry=registry)
    sha = hashlib.sha256(open(aux_checkpoint, "rb").read()).hexdigest()
    assert names == {**{f"mc-vleaf-{sha[:8]}-t{t}": "learned" for t in VLEAF_LEAF_TRICKS},
                     **{f"mc-vleaf-prior-t{t}": "prior" for t in VLEAF_LEAF_TRICKS}}
    assert register_vleaf_arms(checkpoint=aux_checkpoint, prior=table_path, registry=registry) == names
    for name, kind in names.items():
        bot = registry[name](seed=5)
        assert isinstance(bot, L.MCValueLeafSearch) and isinstance(bot, REGISTRY[BASE])
        assert bot.leaf.kind == kind
        assert bot.LEAF_TRICKS == int(name.rsplit("-t", 1)[1])
        assert bot.rng.getstate() == random.Random(5).getstate()
        assert bot.N_DETERMINIZATIONS == 30 and bot.REPORT_FOLD_WORLDS == 300
    other = tmp_path / "other_prior.json"
    _publish(other, prior_table(counts=np.full(N_STRATA, 2)).to_dict())
    with pytest.raises(RuntimeError, match="refusing to rebind"):
        register_vleaf_arms(prior=other, registry=registry)
    with pytest.raises(RuntimeError, match="already a registered policy"):
        register_vleaf_arms(prior=table_path, registry={"mc-vleaf-prior-t1": object()})
    with pytest.raises(ValueError):
        vleaf_policy_name(leaf_tricks=3)
    with pytest.raises(L.LeafError):
        L.MCValueLeafSearch(Const(0), leaf_tricks=-1)


def test_make_bot_by_name_binds_the_policy_name_and_counters_reconcile(monkeypatch, aux_checkpoint):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    names = register_vleaf_arms(checkpoint=aux_checkpoint, leaf_tricks=(1,))
    name = next(iter(names))
    bot = _tiny(make_bot(name, seed=3))
    assert bot.policy_name == name
    rnd = deal(4_242)
    seat = rnd.turn
    action = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert action == rec["played"] and rec["policy"] == name
    counts = bot.leaf_counts
    assert counts["leaf_calls"] == bot.rollouts == rec["work"]["total_rollouts"] > 0
    assert counts["terminal_leaves"] + counts["exact_leaves"] + counts["predicted_leaves"] \
        == counts["leaf_calls"]
    assert counts["predicted_leaves"] == bot.leaf.head.calls > 0
    assert bot.leaf_secs > 0
    assert L.leaf_record(bot)["leaf"]["checkpoint_id"] == name.split("-")[2]
    assert L.leaf_record(make_bot(BASE))["leaf"] is None
