"""The belief trainer's banker-side void loss (``belief_seq train --void-weight``).

Off (weight 0, the default) the training loss is exactly the per-copy
cross-entropy.  On, it adds the weighted binary cross-entropy of the void
events ``banker_side_void_items`` selects: the banker's and the banker's
partner's plain suits (never the actor's), with an unknown copy and no public
pin at that receiver.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train.belief_history import N_CARD_FEATURES  # noqa: E402

from tests.test_belief_seq_init import SMALL, synthetic_part  # noqa: E402


def _model():
    torch.manual_seed(0)
    m = bs.build_model(**SMALL)
    with torch.no_grad():
        for p in m.parameters():
            p.add_(0.05 * torch.randn_like(p))
    m.eval()
    return m


def _suited_part(seed: int):
    """A synthetic part whose card features give every card one plain suit or trump."""
    part = synthetic_part(3, 20, 4, seed=seed)
    cf = np.zeros((3, 54, N_CARD_FEATURES), np.float16)
    for c in range(54):
        cf[:, c, 1 + c % 5] = 1.0          # columns 1..4 plain S/H/D/C, column 5 trump
    part["_rounds"]["card_feat"] = cf
    for rel in (1, 2, 3):                  # no public pins (random features would pin most cards)
        at = bs._block_at(f"pinned_rel{rel}")
        part["X"][:, at:at + 54] = 0
    return part


def _batch(part):
    return bs.to_torch(bs.make_batch(part, np.arange(3), np.arange(len(part["X"]))))


def test_void_weight_zero_is_the_cross_entropy_exactly():
    m = _model()
    tb = _batch(_suited_part(1))
    with torch.no_grad():
        base, n = bs.batch_loss(m, tb)
        off, n0 = bs.batch_loss(m, tb, void_weight=0.0)
    assert float(off) == float(base) and float(n0) == float(n)


def test_void_weight_adds_the_weighted_void_loss_and_keeps_the_count():
    m = _model()
    tb = _batch(_suited_part(2))
    with torch.no_grad():
        base, n = bs.batch_loss(m, tb)
        on, n3 = bs.batch_loss(m, tb, void_weight=3.0)
        logp = torch.log_softmax(m(tb).float().masked_fill(~tb["M"], -1e9), -1)
        vl, items = bs.void_loss(logp, tb)
    assert float(items) > 0 and float(vl) > 0
    assert float(on) == pytest.approx(float(base) + 3.0 * float(vl), rel=1e-6)
    assert float(n3) == float(n)


def test_void_probability_is_the_independent_copy_product():
    m = _model()
    part = _suited_part(3)
    tb = _batch(part)
    with torch.no_grad():
        logp = torch.log_softmax(m(tb).float().masked_fill(~tb["M"], -1e9), -1)
    p = logp.exp().numpy().astype(np.float64)
    Y = tb["Y"].numpy()
    plain, truth, valid = bs.banker_side_void_items(
        Y, tb["row_card"].numpy(), tb["card_feat"].numpy()[tb["rr"].numpy()], tb["seat"].numpy(),
        tb["banker"].numpy()[tb["rr"].numpy()])
    want = 0.0
    for i, r, s in zip(*np.nonzero(valid)):
        q = np.prod([(1 - min(p[i, c, r], 1 - 1e-6)) ** Y[i, c].sum() for c in range(54) if plain[i, c, s]])
        q = min(q, np.exp(-1e-6))
        want += -np.log(q) if truth[i, r, s] else -np.log1p(-q)
    with torch.no_grad():
        got, _ = bs.void_loss(logp, tb)
    assert float(got) == pytest.approx(want, rel=1e-4)


def test_void_items_select_the_banker_side_and_skip_pins():
    N = 3
    Y = np.zeros((N, 54, 4), np.float32)
    row_card = np.zeros((N, 54, bs.N_ROW_CARD), np.float32)
    cf = np.zeros((N, 54, N_CARD_FEATURES), np.float32)
    for c in range(54):
        cf[:, c, 1 + c % 5] = 1.0
    seat = np.array([0, 1, 0])
    banker = np.array([1, 3, 0])
    # row 0: actor 0, banker 1 (rel1) and its partner 3 (rel3); suit 0 unknown copy with rel1
    Y[0, 0, 0] = 1
    # row 1: actor 1, banker 3 (rel2) and partner 1 = the actor: only rel2 is banker side
    Y[1, 5, 1] = 1                                    # suit 0 copy with the banker
    Y[1, 1, 0] = 1                                    # suit 1 copy with rel1 (a defender)
    # row 2: the actor is the banker; its partner is rel2; suit 2's copy is pinned with rel2
    Y[2, 2, 3] = 1
    row_card[2, 2, bs._PIN_CH + 1] = 1.0
    plain, truth, valid = bs.banker_side_void_items(Y, row_card, cf, seat, banker)
    assert plain.shape == (N, 54, 4) and truth.shape == valid.shape == (N, 3, 4)
    assert valid[0, :, 0].tolist() == [True, False, True]       # rel1 banker, rel3 its partner
    assert truth[0, 0, 0] == False and truth[0, 2, 0] == True    # noqa: E712
    assert valid[1].sum(1).tolist() == [0, 2, 0]                 # rel2 only, suits 0 and 1
    assert truth[1, 1, 0] == False and truth[1, 1, 1] == True    # noqa: E712
    assert not valid[2, 1, 2] and truth[2, 1, 2] == False        # noqa: E712  (pinned: settled)
    tt = bs.banker_side_void_items(*(torch.from_numpy(a) for a in (Y, row_card, cf, seat, banker)))
    assert (tt[1].numpy() == truth).all() and (tt[2].numpy() == valid).all()


def test_the_cli_carries_void_weight_with_a_zero_default():
    p = bs.build_parser()
    a = p.parse_args(["train", "--data", "d", "--out", "o"])
    assert a.void_weight == 0.0
    a = p.parse_args(["train", "--data", "d", "--out", "o", "--void-weight", "8"])
    assert a.void_weight == 8.0
