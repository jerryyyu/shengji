"""Root-state factorised policy prior (#419): root tensors, factorised scoring,
the listwise ballot target, and the extract -> train -> eval plumbing."""
import json
import random

import numpy as np
import pytest
import torch

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.rl.encode import CARD_INDEX
from shengji.train import policy_prior as pp
from shengji.train.cwv_data import tensors_at
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401


def _round_in_play(seed, plays=0):
    g = Game(random.Random(seed)); r = g.start_round(); hb = HeuristicBot()
    while r.phase != "play":
        if r.phase == "deal": r.deal_next()
        elif r.phase == "declare": r.finalize_declare()
        elif r.phase == "bury": r.bury(r.banker, hb.decide_bury(r, r.banker))
    for _ in range(plays):
        r.play(r.turn, hb.decide_play(r, r.turn))
    return r


def test_root_tensors_build_for_the_opening_lead_and_match_the_builder_later():
    r = _round_in_play(3)
    t = pp.root_tensors(r, r.turn)                       # empty history: the hand-built path
    assert pp.flat_input(t).shape == (pp.INPUT_DIM,)
    assert t.public.shape[0] == 561 and t.world.sum() == pytest.approx(0.5 * (4 * len(r.hands[0]) + len(r.buried)))
    r2 = _round_in_play(3, plays=5)
    a = pp.flat_input(pp.root_tensors(r2, r2.turn)); b = pp.flat_input(tensors_at(r2, r2.turn, version=2))
    assert np.array_equal(a, b)                          # non-empty history: the frozen builder verbatim


def test_factorised_score_is_the_sum_of_card_log_odds_with_multiplicity_and_order_free():
    lo = np.arange(54, dtype=np.float64) / 10
    h2, h3 = CARD_INDEX["H2"], CARD_INDEX["H3"]
    s = pp.score_candidates(lo, [[h2], [h2, h2], [h3, h2], [h2, h3]])
    assert s[0] == pytest.approx(lo[h2]) and s[1] == pytest.approx(2 * lo[h2])
    assert s[2] == pytest.approx(s[3]) == pytest.approx(lo[h2] + lo[h3])


def test_listwise_loss_prefers_the_played_candidate_and_ignores_rows_outside_the_ballot():
    meta = [{"ballot": [[CARD_INDEX["H2"]], [CARD_INDEX["S9"]], [CARD_INDEX["C5"], CARD_INDEX["C5"]]], "taken": [CARD_INDEX["S9"]]},
            {"ballot": [[CARD_INDEX["H2"]]], "taken": [CARD_INDEX["DK"]]}]          # played action not in the ballot
    ball, mask, tgt = pp.ballot_tensors(meta)
    assert tgt.tolist() == [1, -1] and mask[0].tolist() == [True, True, True, False, False, False]
    good = torch.full((2, 54), -3.0); good[0, CARD_INDEX["S9"]] = 6.0
    bad = torch.full((2, 54), -3.0); bad[0, CARD_INDEX["H2"]] = 6.0
    assert float(pp.listwise_loss(good, ball, mask, tgt)) < 0.01 < float(pp.listwise_loss(bad, ball, mask, tgt))
    only_out = pp.listwise_loss(good, ball[1:], mask[1:], tgt[1:])
    assert float(only_out) == 0.0 and only_out.requires_grad is False or float(only_out) == 0.0


def test_extract_train_eval_round_trip(store_dir, tmp_path):  # noqa: F811
    out = tmp_path / "rows"
    summary = pp.extract(out, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    assert summary["rows"] > 0
    d = np.load(str(out) + ".npz"); assert d["X"].shape[1] == pp.INPUT_DIM and d["Y"].shape[1] == 54
    meta = [json.loads(l) for l in open(str(out) + ".meta.jsonl")]
    assert all(m["taken"] and m["n_legal"] >= 1 for m in meta)
    ck = tmp_path / "prior.pt"
    res = pp.train(out, ck, test=out, epochs=2, listwise_weight=1.0, threads=1, log=None)
    assert len(res["history"]) == 2 and res["eval"]["rows"] == summary["rows"]
    net, payload = pp.load_prior(ck)
    assert payload["schema"] == pp.SCHEMA and payload["listwise_weight"] == 1.0
    small = [b for b in res["eval"]["buckets"] if b["bucket"][1] <= 20]
    assert small and small[0]["taken_recall"]["256"] == 1.0          # every ≤20-legal decision is inside top-256
    with pytest.raises(pp.PolicyPriorError):
        torch.save({"schema": "x"}, tmp_path / "bad.pt"); pp.load_prior(tmp_path / "bad.pt")
