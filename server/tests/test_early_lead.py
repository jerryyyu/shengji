"""`eval.early_lead.EarlyLeadBot`: with ``tricks=0`` it is its base bot decision
for decision; with ``tricks>0`` only leads of the first ``tricks`` tricks reach
the early bot, and every other decision equals the base bot's on a fixed
decision set.  Stub bots pin the routing; a real joint package pins the
identity on full rounds of PV search bots.
"""
import copy
import random

import pytest

from shengji.ai.env import observe_committed_play
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.eval.early_lead import EarlyLeadBot, is_early_lead
from shengji.train.policy_value_search import leading


class _Stub(HeuristicBot):
    def __init__(self, tag):
        super().__init__()
        self.tag = tag
        self.calls = []
        self.observed = 0
        self.policy_name = f"stub-{tag}"
        self.last_decision_record = None

    def decide_play(self, rnd, seat):
        self.calls.append((len(rnd.history), leading(rnd)))
        self.last_decision_record = {"tag": self.tag, "trick": len(rnd.history)}
        return super().decide_play(rnd, seat)

    def observe_public(self, rnd):
        self.observed += 1


def _round_to_play(seed, bots):
    rnd = Game(random.Random(seed)).start_round()
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
    return rnd


def _play_out(rnd, bots, snapshots=None):
    trace = []
    while rnd.phase == "play":
        seat = rnd.turn
        if snapshots is not None:
            snapshots.append((copy.deepcopy(rnd), seat))
        cards = bots[seat].decide_play(rnd, seat)
        trace.append((seat, sorted(cards)))
        rnd.play(seat, cards)
        observe_committed_play(rnd, bots)
    return trace


def test_constructor_refuses_bad_arguments():
    a, b = _Stub("a"), _Stub("b")
    with pytest.raises(ValueError):
        EarlyLeadBot(a, b, -1)
    with pytest.raises(ValueError):
        EarlyLeadBot(a, b, True)
    with pytest.raises(ValueError):
        EarlyLeadBot(a, a, 5)


def test_routes_only_early_leads_and_forwards_observations():
    seed = 625091990
    hybrids = [EarlyLeadBot(_Stub(f"base{s}"), _Stub(f"early{s}"), 5) for s in range(4)]
    rnd = _round_to_play(seed, hybrids)
    plays = 0
    while rnd.phase == "play":
        seat = rnd.turn
        want_early = leading(rnd) and len(rnd.history) < 5
        assert is_early_lead(rnd, 5) == want_early
        hybrids[seat].decide_play(rnd, seat)
        bot = hybrids[seat]
        assert bot.last_routed_early == want_early
        assert bot.last_decision_record["tag"] == (bot.early.tag if want_early else bot.base.tag)
        assert (bot.early if want_early else bot.base).calls[-1] == (len(rnd.history), leading(rnd))
        rnd.play(seat, HeuristicBot().decide_play(rnd, seat))
        observe_committed_play(rnd, hybrids)
        plays += 1
    for h in hybrids:
        assert all(lead and trick < 5 for trick, lead in h.early.calls)
        assert not any(lead and trick < 5 for trick, lead in h.base.calls)
        assert h.early_decisions == len(h.early.calls)
        assert h.base.observed == h.early.observed == plays
    assert sum(len(h.early.calls) for h in hybrids) == 5


def test_tricks_zero_never_consults_early():
    hybrids = [EarlyLeadBot(_Stub("b"), _Stub("e"), 0) for _ in range(4)]
    rnd = _round_to_play(625091990, hybrids)
    _play_out(rnd, hybrids)
    assert all(not h.early.calls and h.base.calls and h.early_decisions == 0 for h in hybrids)


def test_declare_and_bury_come_from_base():
    base, early = _Stub("b"), _Stub("e")
    h = EarlyLeadBot(base, early, 5)
    assert h.decide_bury.__self__ is base
    assert h.decide_declare.__self__ is base
    assert h.policy_name == "stub-b"
    assert EarlyLeadBot(_Stub("x"), _Stub("y"), 5, policy_name="named").policy_name == "named"


# A real joint package and full PV search bots.

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
WIDE = dict(worlds=6, candidates=6, cap=400, batch_size=16)


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("early-lead")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=561, enc_version=2, attention_heads=1,
                                        trunk_block="residual", trunk_layers=2,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2),
                                         "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


def _bots(package, seed, size):
    from shengji.train import pv_search_policy as pv
    path, sha = package
    return pv.make_pv_search_bot(path, sha256=sha, seed=seed, bury_arm="hybrid", **size)


def _strip(rec):
    if not isinstance(rec, dict):
        return rec
    return {k: v for k, v in rec.items() if "second" not in k and not k.endswith("_ms") and k != "elapsed_seconds"}


def _full_round(seed, bots):
    rnd = _round_to_play(seed, bots)
    records = []
    while rnd.phase == "play":
        seat = rnd.turn
        cards = bots[seat].decide_play(rnd, seat)
        records.append((seat, sorted(cards), _strip(bots[seat].last_decision_record)))
        rnd.play(seat, cards)
        observe_committed_play(rnd, bots)
    return records, [b.sampler.rng.getstate() for b in (getattr(x, "base", x) for x in bots)]


def test_pv_tricks_zero_is_base_on_a_full_round(package):
    deal = 625091990
    served = [_bots(package, 100 + s, SMALL) for s in range(4)]
    hybrid = [EarlyLeadBot(_bots(package, 100 + s, SMALL), _bots(package, 900 + s, WIDE), 0) for s in range(4)]
    early_states = [h.early.sampler.rng.getstate() for h in hybrid]
    a, a_rng = _full_round(deal, served)
    b, b_rng = _full_round(deal, hybrid)
    assert a == b
    assert a_rng == b_rng
    assert [h.early.sampler.rng.getstate() for h in hybrid] == early_states
    assert all(h.early_decisions == 0 for h in hybrid)


def test_pv_fixed_decisions_outside_the_window_equal_base(package):
    snaps = []
    heur = [HeuristicBot() for _ in range(4)]
    rnd = _round_to_play(625091990, heur)
    _play_out(rnd, heur, snapshots=snaps)
    assert len(snaps) > 40
    early_seen = late_seen = 0
    for i, (state, seat) in enumerate(snaps[:60]):
        base = _bots(package, 300 + i, SMALL)
        early = _bots(package, 700 + i, WIDE)
        hybrid = EarlyLeadBot(_bots(package, 300 + i, SMALL), _bots(package, 700 + i, WIDE), 5)
        got = hybrid.decide_play(copy.deepcopy(state), seat)
        if is_early_lead(state, 5):
            early_seen += 1
            want = early.decide_play(copy.deepcopy(state), seat)
            assert _strip(hybrid.last_decision_record) == _strip(early.last_decision_record)
        else:
            late_seen += 1
            want = base.decide_play(copy.deepcopy(state), seat)
            assert _strip(hybrid.last_decision_record) == _strip(base.last_decision_record)
        assert sorted(got) == sorted(want), (i, len(state.history))
    assert early_seen == 5 and late_seen > 30
