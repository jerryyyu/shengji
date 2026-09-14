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
    assert tgt.tolist() == [1, -1] and mask[0].tolist() == [True, True, True] and ball.shape == (2, 3, 2)
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
    assert len(res["history"]) == 2 and res["eval"]["counters"]["rows"] == summary["rows"]
    net, payload = pp.load_prior(ck)
    assert payload["schema"] == pp.SCHEMA and payload["listwise_weight"] == 1.0
    ev = res["eval"]; assert ev["counters"]["rows"] == summary["rows"]
    small = [b for b in ev["strata"]["exhaustive"] + ev["strata"]["partial"] if b["bucket"][1] <= 20]
    assert small and all(b["taken_recall"]["256"] == 1.0 for b in small)   # every ≤20-legal decision is inside top-256
    with pytest.raises(pp.PolicyPriorError):
        torch.save({"schema": "x"}, tmp_path / "bad.pt"); pp.load_prior(tmp_path / "bad.pt")


def test_a_nine_card_candidate_trains_on_its_full_length():
    """Codex HOLD on #423: the listwise target must score a candidate exactly as inference does,
    whatever its length -- a nine-card throw and its eight-card prefix are different candidates."""
    nine = list(range(9)); eight = nine[:8]
    meta = [{"ballot": [nine, eight], "taken": nine}]
    ball, mask, tgt = pp.ballot_tensors(meta)
    assert ball.shape[2] == 9 and mask.tolist() == [[True, True]] and tgt.tolist() == [0]
    logits = torch.full((1, 54), 0.0); logits[0, 8] = 10.0        # only the ninth card carries evidence
    inference = pp.score_candidates(logits[0].numpy(), [nine, eight])
    assert inference[0] - inference[1] == pytest.approx(10.0)
    loss = float(pp.listwise_loss(logits, ball, mask, tgt))
    assert loss < 1e-3                                             # nine-card candidate wins by 10 in training too
    prefix_only = pp.ballot_tensors([{"ballot": [eight, eight], "taken": eight}])
    assert float(pp.listwise_loss(logits, *prefix_only)) == pytest.approx(np.log(2.0), abs=1e-5)   # a true tie is 0.693


def test_eval_strata_missing_targets_and_same_universe_baseline(tmp_path):
    """Codex HOLD on #423: sampled/incomplete rows are reported apart from exhaustive ones, rows whose
    played action is not in the stored list are counted (not silently dropped), and the random
    baseline is computed on the ranked universe with the full-universe number labelled as a reference."""
    rng = np.random.default_rng(0)
    X = rng.standard_normal((4, pp.INPUT_DIM)).astype(np.float32); Y = np.zeros((4, 54), np.float32)
    rows = [
        {"n_legal": 3, "legal": [[0], [1], [2]], "ballot": [[0], [1]], "taken": [1], "complete": True},          # exhaustive
        {"n_legal": 12000, "legal": [[i] for i in range(50)], "ballot": [[3]], "taken": [3], "complete": True},   # sampled: stored 50 of 12,000
        {"n_legal": 30, "legal": [[i] for i in range(10)], "ballot": [[5]], "taken": [5], "complete": False},     # incomplete
        {"n_legal": 3, "legal": [[0], [1], [2]], "ballot": [[0]], "taken": [9], "complete": True},               # played action not stored
    ]
    np.savez_compressed(tmp_path / "t.npz", X=X, Y=Y)
    with open(tmp_path / "t.meta.jsonl", "w") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
    ck = tmp_path / "p.pt"; pp.train(tmp_path / "t", ck, epochs=1, listwise_weight=0.0, threads=1, log=None)
    ev = pp.evaluate(ck, tmp_path / "t", log=None)
    c = ev["counters"]
    assert c["ranked"] == {"exhaustive": 1, "partial": 2} and c["missing_target"] == {"exhaustive": 1, "partial": 0}
    part = {tuple(b["bucket"]): b for b in ev["strata"]["partial"]}
    big = part[(10001, 10 ** 9)]
    assert big["random_same_universe"]["64"] == 1.0                       # 64 of a 50-action stored universe
    assert big["random_full_universe_reference"]["64"] == pytest.approx(64 / 12000)
    assert "missing target exhaustive 1" in ev["text"] and "[partial]" in ev["text"]
