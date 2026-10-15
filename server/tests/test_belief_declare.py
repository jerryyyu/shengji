"""S23 declaration / bury-rule belief inputs (``train.belief_declare``) and the
widened S17 model (``train.belief_seq``)."""
from __future__ import annotations

import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import card_rank, is_joker
from shengji.engine.game import Game
from shengji.rl.encode import CARD_INDEX
from shengji.train import belief_declare as bd


def _round(seed: int):
    """A heuristic first round with its declaration sequence, at play start."""
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    log = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = h.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            log.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = h.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            log.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd, log


def test_kb_prior_places_the_banker_bury_hand_and_honours_pins():
    rnd, log = _round(11)
    for seat in range(4):
        row, card = bd.declare_features(rnd.ordering, rnd.trump_rank, rnd.banker, seat, log,
                                        list(rnd.hands[seat]), draws=8)
        assert row.shape == (bd.DECL_ROW,) and card.shape == (54, bd.DECL_CARD)
        if seat == rnd.banker:
            assert row[16] == 0 and not card[:, 3:].any()      # the banker knows its kitty
            continue
        kitty, kept = 2 * card[:, 3], 2 * card[:, 4]
        assert kitty.sum() == pytest.approx(8.0) and kept.sum() == pytest.approx(25.0)
        own = Counter(rnd.hands[seat])
        for code, n in own.items():          # no copy the actor holds is placed twice
            assert kitty[CARD_INDEX[code]] + kept[CARD_INDEX[code]] <= 2 - n + 1e-6
        final = log[-1] if log else None
        if final and final["seat"] == rnd.banker:
            for code in final["cards"]:      # the declarer's shown cards are kept, never buried
                if code not in own:
                    assert kept[CARD_INDEX[code]] >= 1 - 1e-6


def test_superseded_declarations_are_shown_planes():
    rnd, _ = _round(3)
    b = rnd.banker
    other = (b + 1) % 4
    trump_rank_card = next(c for c in rnd.deck if not is_joker(c) and card_rank(c) == rnd.trump_rank)
    log = [{"seat": other, "cards": [trump_rank_card]},
           {"seat": b, "cards": ["BJ", "BJ"]}]
    for seat in range(4):
        row, card = bd.declare_features(rnd.ordering, rnd.trump_rank, b, seat, log,
                                        list(rnd.hands[seat]), draws=4)
        rel = (other - seat) % 4
        assert row[4 + rel] == 1.0                            # first declarer
        assert row[8 + 3] == 1.0                              # big-joker pair
        assert row[13] == 1.0                                 # the banker overcalled another seat
        if rel:
            assert card[CARD_INDEX[trump_rank_card], rel - 1] == 0.5
        assert card[:, :3].sum() == (0.5 if rel else 0.0)     # only the superseded call


def test_live_inputs_equal_the_play_start_frame_mid_round():
    rnd, log = _round(29)
    start = bd.round_declare_features(rnd, log, draws=6)
    h = HeuristicBot()
    for _ in range(9):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    for seat in range(4):
        row, card = bd.decision_declare_inputs(rnd, seat, log, draws=6)
        assert np.array_equal(row, start[0][seat].astype(np.float16).astype(np.float32))
        assert np.array_equal(card, start[1][seat].astype(np.float16).astype(np.float32))


def test_widened_model_starts_as_the_s17_model():
    torch = pytest.importorskip("torch")
    from shengji.train import belief_history as bh
    from shengji.train import belief_seq as bs
    from shengji.train.belief_labels import FEATURE_DIM
    torch.manual_seed(0)
    base = bs.build_model(d=16, heads=2, x_hidden=16).eval()
    wide = bs.build_model(d=16, heads=2, x_hidden=16, decl_row=bd.DECL_ROW,
                          decl_card=bd.DECL_CARD).eval()
    wide.load_state_dict(bs.expand_state_dict(base.state_dict(), wide))
    rng = np.random.default_rng(2)
    R, T, B = 2, 6, 3
    b = {"tok_int": np.stack([rng.integers(0, 4, (R, T)), rng.integers(0, 4, (R, T)),
                              rng.integers(0, 25, (R, T)), rng.integers(0, 5, (R, T))], -1),
         "tok_f": rng.random((R, T, bh.N_TOKEN_FLOAT)).astype(np.float32),
         "tok_cards": (rng.random((R, T, 54)) < 0.05).astype(np.float32),
         "tok_att": np.zeros((R, T, 54), np.float32),
         "card_feat": rng.random((R, 54, bh.N_CARD_FEATURES)).astype(np.float32),
         "banker": np.array([0, 2]),
         "X": rng.random((B, FEATURE_DIM + 4)).astype(np.float32),
         "row_card": rng.random((B, 54, bs.N_ROW_CARD)).astype(np.float32),
         "M": np.ones((B, 54, 4), bool), "rr": np.array([0, 1, 1]),
         "seat": np.array([1, 2, 0]), "ply": np.array([3, 0, 5]),
         "decl_row": rng.random((B, bd.DECL_ROW)).astype(np.float32),
         "decl_card": rng.random((B, 54, bd.DECL_CARD)).astype(np.float32)}
    with torch.no_grad():
        assert np.allclose(base(bs.to_torch(b)).numpy(), wide(bs.to_torch(b)).numpy(), atol=1e-6)
    assert wide.config["decl_row"] == bd.DECL_ROW and "decl_row" not in base.config
    with pytest.raises(bs.BeliefSeqError):
        bs.expand_state_dict(wide.state_dict(), base)


def test_capacity_aware_draw_is_legal_and_keeps_a_starved_receiver_on_its_marginals():
    from shengji.train import belief_seq as bs
    rng = np.random.default_rng(4)
    # 20 "trump" copies the kitty almost never holds, 30 others; kitty 8 slots
    n_c = np.zeros(54, np.int64)
    n_c[:20] = 1
    n_c[20:50] = 1
    M = np.zeros((54, 4), bool)
    M[:50] = True
    sizes = np.array([14, 14, 14, 8])
    P = np.zeros((54, 4))
    P[:20] = [1 / 3, 1 / 3, 1 / 3, 1e-4]
    P[20:50] = [0.25, 0.25, 0.25, 0.25]
    P = bs.project_sizes(P, n_c, sizes, M)
    for fn in (bs.sample_worlds, bs.sample_worlds_capacity):
        W = fn(P, n_c, M, sizes, 400, rng)
        assert (W.sum(-1) == n_c[None]).all() and (W.sum(1) == sizes[None]).all()
        assert not (W[:, ~M] > 0).any()
    plain = bs.sample_worlds(P, n_c, M, sizes, 400, rng)[:, :20, 3].sum(1).mean()
    capacity = bs.sample_worlds_capacity(P, n_c, M, sizes, 400, rng)[:, :20, 3].sum(1).mean()
    expected = (P[:20, 3] * n_c[:20]).sum()
    assert expected < 0.05
    assert capacity < 0.1 < plain
