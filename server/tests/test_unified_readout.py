"""The per-world readout on the unified trunk (`train.unified_readout`, `ai.unified_readout_numpy`) and its
serving wiring (`train.unified_slots`): the training leaves read from tokens equal the leaves read from
round states, the NumPy runtime equals the torch model, and the value and reply slots change only the bot
they are installed on."""
from __future__ import annotations

import copy

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai import belief_numpy as bn  # noqa: E402
from shengji.ai import unified_readout_numpy as rn  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.rl.encode import CARD_INDEX  # noqa: E402
from shengji.train import pv_search_policy as pv  # noqa: E402
from shengji.train import pv_tree_search as pts  # noqa: E402
from shengji.train import unified_readout as ur  # noqa: E402
from shengji.train import unified_slots as us  # noqa: E402
from shengji.train.belief_eval import known_counts  # noqa: E402
from tests.test_pv_search_serving import SMALL as PV_SMALL  # noqa: E402
from tests.test_pv_search_serving import _play_state, package  # noqa: E402,F401

ARCH = dict(d=32, heads=4, enc_layers=1, xattn_layers=1, x_hidden=32, card_self_attn=True)
READOUT = {"dp": 8, "dc": 12, "width": 24, "hidden": 40, "blocks": 2}
WHL = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True)


def _counts(cards):
    out = np.zeros(54, np.float32)
    for c in cards:
        out[CARD_INDEX[c]] += 1
    return out


def _game():
    """Every play state of one heuristic game, and the finished round."""
    rnd = _play_state()
    h = HeuristicBot()
    states = []
    while rnd.phase == "play":
        states.append(copy.deepcopy(rnd))
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    return states, rnd


def _batch(states, final):
    """The rows of one round as `unified_seq.make_unified_batch` lays them out, labels from the true hands."""
    tok = bn.history_tokens(final)
    X, Y, seats = [], [], []
    for rnd in states:
        seat = rnd.turn
        x = bn.decision_inputs(rnd, seat, ())["X"]
        K = known_counts(x[None])[0]
        y = np.zeros((54, 4), np.float32)
        for rel in (1, 2, 3):
            y[:, rel - 1] = _counts(rnd.hands[(seat + rel) % 4]) - K[:, rel - 1]
        if seat != rnd.banker:
            y[:, 3] = _counts(rnd.buried)
        X.append(x)
        Y.append(y)
        seats.append(seat)
    n = len(states)
    return {"tok_int": tok["tok_int"][None], "tok_f": tok["tok_f"][None], "tok_cards": tok["tok_cards"][None],
            "X": np.stack(X), "Y": np.stack(Y), "rr": np.zeros(n, np.int64), "ply": np.arange(n, dtype=np.int64),
            "seat": np.asarray(seats, np.int64)}


def test_training_leaves_from_tokens_equal_the_leaves_of_the_round_states():
    states, final = _game()
    b = _batch(states, final)
    L = ur.leaf_batch(b)
    after = states[1:] + [final]
    assert len(L["row"]) > len(states) and set(L["k"]) == {0, 1, 2, 3}
    compared = 0
    for row, k, planes, scalars, reply, hand, has in zip(L["row"], L["k"], L["planes"], L["scalars"], L["reply"],
                                                         L["reply_hand"], L["has_reply"]):
        leaf = after[row + k]
        frame = us.LeafFrame(None, states[row], states[row].turn)
        got = us.leaf_features(frame, leaf)
        if leaf.phase != "play":
            assert got is None and not has
            continue
        assert np.array_equal(got[0], planes) and np.array_equal(got[1], scalars)
        assert bool(has) == bool(leaf.trick.plays)
        if has:
            played = states[row + k + 1].turn
            assert np.array_equal(reply, _counts(leaf.hands[played]) - _counts(after[row + k + 1].hands[played]))
            assert np.array_equal(hand, _counts(leaf.hands[played]) > 0)
        compared += 1
    assert compared > 80
    # a state outside the decision's trick is not a leaf of it
    assert us.leaf_features(us.LeafFrame(None, states[0], states[0].turn), states[9]) is None
    assert us.leaf_features(us.LeafFrame(None, states[4], states[4].turn), states[4]) is None


def _model(tmp_path, seed=0):
    torch.manual_seed(seed)
    m = ur.build(ARCH, READOUT)
    sd = {k: v.detach().float().numpy() for k, v in m.state_dict().items()}
    path = tmp_path / f"r{seed}.npz"
    sha = rn.save_package(path, m.config, {k[6:]: v for k, v in sd.items() if k.startswith("trunk.")},
                          {k: v for k, v in sd.items() if k.startswith(("q_head.", "p_head."))},
                          {k[8:]: v for k, v in sd.items() if k.startswith("readout.")}, {"temperature": 1.2})
    return m, rn.load_unified_readout_numpy(path, sha)


def test_numpy_readout_equals_the_torch_readout_and_exports_its_belief_package(tmp_path):
    m, model = _model(tmp_path)
    states, final = _game()
    b = _batch(states[:12], final)
    L = ur.leaf_batch(b)
    rnd = states[5]
    inp = bn.decision_inputs(rnd, rnd.turn, ())
    q, g = model.card_states(inp, model.trunk.encode_history(inp))
    pick = np.nonzero(L["row"] == 5)[0]
    with torch.no_grad():
        tv, tr = m.readout(torch.from_numpy(q)[None], torch.from_numpy(g)[None], torch.zeros(len(pick), dtype=torch.long),
                           torch.from_numpy(L["planes"][pick]), torch.from_numpy(L["scalars"][pick]))
    cache = model.decision_cache(q, g)
    assert np.allclose(model.leaf_value_logits(cache, L["planes"][pick], L["scalars"][pick]), tv.numpy(), atol=1e-4)
    assert np.allclose(model.leaf_reply_logits(cache, L["planes"][pick], L["scalars"][pick]), tr.numpy(), atol=1e-4)
    p = model.leaf_value_probs(cache, L["planes"][pick], L["scalars"][pick])
    assert p.shape == (len(pick), 204) and np.allclose(p.sum(-1), 1.0)
    sha = rn.belief_package(model, tmp_path / "belief.npz")
    belief = bn.load_belief_numpy(tmp_path / "belief.npz", sha)
    assert belief.temperature == 1.2 and all(np.array_equal(belief.w[k], model.trunk.w[k]) for k in belief.w)


def test_losses_run_on_a_batch_and_reach_the_trunk(tmp_path):
    m, _ = _model(tmp_path)
    states, final = _game()
    b = _batch(states[:20], final)
    T = b["tok_int"].shape[1]
    b.update(tok_att=np.zeros((1, T, 54), np.float32), banker=np.asarray([final.banker]),
             card_feat=bn.decision_inputs(states[0], states[0].turn, ())["card_feat"][None],
             row_card=np.stack([bn.decision_inputs(s, s.turn, ())["row_card"] for s in states[:20]]),
             M=np.stack([bn.decision_inputs(s, s.turn, ())["M"] for s in states[:20]]),
             q_target=np.full(20, 7, np.int64), pol_target=np.stack([_counts(final.history[0].plays[0].cards)] * 20))
    b["tok_int"] = b["tok_int"].astype(np.int64)
    b["pol_target"] = b["tok_cards"][0, :20].astype(np.float32)
    for k, v in ur.leaf_batch(b).items():
        b["leaf_" + k] = v
    L = ur.losses(m, {k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in b.items()})
    means = ur.means([float(L[k].detach()) for k in ur.SUM_KEYS])
    assert all(np.isfinite(v) for v in means.values()) and L["replies"] > 0
    (L["v_sum"] + L["r_sum"]).backward()
    assert m.trunk.card_id.grad is not None and float(m.trunk.card_id.grad.abs().sum()) > 0


# ---- serving

def _bot(package, belief=None, seed=3, **kw):
    extra = dict(WHL, belief_checkpoint=belief[0], belief_sha256=belief[1]) if belief else {}
    return pv.make_pv_search_bot(package[0], sha256=package[1], seed=seed, **PV_SMALL, serving_budget_seconds=30.0,
                                 **extra, **kw)


def _record(bot):
    return {k: v for k, v in bot.last_decision_record.items() if "seconds" not in k and not k.endswith("_ms") and k != "policy"}


def test_value_readout_scores_the_decisions_own_trick_and_leaves_other_bots_alone(package, tmp_path):
    _, model = _model(tmp_path)
    rnd = _play_state()
    seat = rnd.turn
    before = _bot(package)
    played = before.decide_play(copy.deepcopy(rnd), seat)
    record = _record(before)
    bot = us.install_value_readout(_bot(package), model)
    assert bot.policy_name.endswith(f"-{us.VALUE_TOKEN}{model.package_sha256[:8]}")
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA
    assert bot.unified_value_rows > 0 and bot.unified_trunk_forwards == 1 and bot.unified_frame is None
    assert bot.unified_value_other == 0
    after = _bot(package)
    assert type(after.evaluator) is type(before.evaluator) and "_search" not in vars(after)
    assert after.decide_play(copy.deepcopy(rnd), seat) == played and _record(after) == record
    # outside a framed decision every position is the served evaluator's
    leaf = copy.deepcopy(rnd)
    leaf.play(seat, played)
    n = bot.unified_value_rows
    assert bot.evaluator.score([leaf], seat)[0] == before.evaluator.score([leaf], seat)[0] and bot.unified_value_rows == n
    # inside one: the readout's expected level, negated for the other team
    bot.unified_frame = us.LeafFrame(bot, rnd, seat)
    feats = us.leaf_features(bot.unified_frame, leaf)
    want = float(model.leaf_value_probs(bot.unified_frame.cache(model), feats[0][None], feats[1][None])[0] @ bot.evaluator.support)
    got = bot.evaluator.score_many([leaf, leaf], [seat, (seat + 1) % 4])
    assert got[0] == pytest.approx(want) and got[1] == pytest.approx(-want)
    with pytest.raises(us.UnifiedSlotError):
        us.install_value_readout(bot, model)


def test_value_readout_takes_the_shared_forwards_states(package, tmp_path):
    _, model = _model(tmp_path)
    belief = (str(tmp_path / "b.npz"), rn.belief_package(model, tmp_path / "b.npz"))
    rnd = _play_state()
    bot = us.install_value_readout(us.install_shared_forward(_bot(package, belief), model), model)
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA
    assert (bot.unified_shared_hits, bot.unified_trunk_shared, bot.unified_trunk_forwards) == (1, 1, 0)
    assert bot.unified_value_rows > 0


def test_reply_readout_ranks_follows_only_for_the_marked_bot(package, tmp_path, monkeypatch):
    _, model = _model(tmp_path)
    rnd = _play_state()
    seat = rnd.turn
    rules = dict(leaf_greedy_finish=True)
    before = _bot(package, **rules)
    played = before.decide_play(copy.deepcopy(rnd), seat)
    record = _record(before)
    monkeypatch.setattr(pts, "greedy_reply_ply", us.readout_reply_ply(pts.greedy_reply_ply))
    same = _bot(package, **rules)
    assert same.decide_play(copy.deepcopy(rnd), seat) == played and _record(same) == record
    assert record["schema"] == pv.RECORD_SCHEMA and record.get("tree_policy_rows", 1) > 0
    bot = us.install_reply_readout(_bot(package, **rules), model)
    assert bot.policy_name.endswith(f"-{us.REPLY_TOKEN}{model.package_sha256[:8]}")
    served_predict = bot.predict
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA
    assert bot.unified_reply_rows > 0 and bot.predict is served_predict


def test_value_readout_under_the_prefix_encoder_takes_the_leaves_as_states(package, tmp_path, monkeypatch):
    from shengji.train import pv_encode_prefix as pep
    _, model = _model(tmp_path)
    rnd = _play_state()
    seat = rnd.turn
    before = _bot(package)
    before.encode_prefix_cache = True
    played = before.decide_play(copy.deepcopy(rnd), seat)
    record = _record(before)
    monkeypatch.setattr(pep, "score_leaves", us.readout_score_leaves(pep.score_leaves))
    same = _bot(package)
    same.encode_prefix_cache = True
    assert same.decide_play(copy.deepcopy(rnd), seat) == played and _record(same) == record
    off = us.install_value_readout(_bot(package), model)
    bot = _bot(package)
    bot.encode_prefix_cache = True
    us.install_value_readout(bot, model, keep_prefix=True)
    assert bot.encode_prefix_cache and bot.decide_play(copy.deepcopy(rnd), seat) == off.decide_play(copy.deepcopy(rnd), seat)
    assert _record(bot) == {**_record(off), **{k: v for k, v in _record(bot).items() if k not in _record(off) or "prefix" in k}}
    assert bot.unified_value_rows == off.unified_value_rows > 0 and bot.unified_value_other == 0


def test_polish_trains_only_the_per_leaf_body_and_equals_the_joint_forward(tmp_path):
    m, _ = _model(tmp_path)
    states, final = _game()
    b = _batch(states[:20], final)
    T = b["tok_int"].shape[1]
    b.update(tok_att=np.zeros((1, T, 54), np.float32), banker=np.asarray([final.banker]),
             card_feat=bn.decision_inputs(states[0], states[0].turn, ())["card_feat"][None],
             row_card=np.stack([bn.decision_inputs(s, s.turn, ())["row_card"] for s in states[:20]]),
             M=np.stack([bn.decision_inputs(s, s.turn, ())["M"] for s in states[:20]]))
    b["tok_int"] = b["tok_int"].astype(np.int64)
    L = ur.leaf_batch(b)
    tb = {k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in b.items()}
    with torch.no_grad():
        _, _, q, g = ur.us.trunk_forward(m.trunk, tb)
        S, c = m.readout.project(q, g)
        row = torch.from_numpy(L["row"])
        joint = m.readout(q, g, row, torch.from_numpy(L["planes"]), torch.from_numpy(L["scalars"]))
    z = {"S": S.numpy().astype(np.float16), "c": c.numpy().astype(np.float16), "leaf_row": L["row"].astype(np.int32),
         "leaf_planes": L["planes"].astype(np.uint8), "leaf_scalars": L["scalars"], "leaf_target": np.full(len(L["row"]), 7, np.int16),
         "leaf_reply": L["reply"].astype(np.uint8), "leaf_reply_hand": L["reply_hand"], "leaf_has_reply": L["has_reply"]}
    t = ur._polish_tensors(z)
    with torch.no_grad():
        v, r = m.readout.body(*t[:4])
    assert torch.allclose(v, joint[0], atol=2e-2) and torch.allclose(r, joint[1], atol=2e-2)     # float16 cache
    v_ce, r_ce, end, has = ur.polish_losses(m.readout, t)
    assert v_ce.shape == r_ce.shape == end.shape and int(end.sum()) > 0 and bool((r_ce[~has] == 0).all())
    body = {n for n, _ in m.readout.named_parameters() if n.startswith(ur.BODY_PREFIXES)}
    assert {n for n, _ in m.readout.named_parameters()} - body == {"card_ln.weight", "card_ln.bias", "card_proj.weight",
                                                                    "card_proj.bias", "ctx.weight", "ctx.bias"}
    ev = ur.polish_eval(m.readout, z)
    assert set(ev) == {"leaf_value", "leaf_value_end", "reply"} and all(np.isfinite(x) for x in ev.values())


def test_mixture_nll_is_the_nll_of_the_mean_distribution_and_reaches_the_body(tmp_path):
    m, _ = _model(tmp_path)
    rng = np.random.default_rng(3)
    n, K = 5, 4
    logits = torch.from_numpy(rng.standard_normal((n, K, 204)).astype(np.float32))
    target = torch.from_numpy(rng.integers(0, 204, n))
    want = -torch.log(torch.softmax(logits, -1).mean(1)[torch.arange(n), target])
    assert torch.allclose(ur.mixture_nll(logits, target), want, atol=1e-5)
    same = logits[:, :1].expand(-1, K, -1)
    assert torch.allclose(ur.mixture_nll(same, target), torch.nn.functional.cross_entropy(logits[:, 0], target, reduction="none"), atol=1e-5)
    dp, dc = READOUT["dp"], READOUT["dc"]
    z = {"S": rng.standard_normal((n, 54, dp)).astype(np.float16), "c": rng.random((n, dc)).astype(np.float16),
         "planes": (rng.random((n, K, 9, 54)) < 0.2).astype(np.uint8), "scalars": rng.random((n, K, 12)).astype(np.float32),
         "tplanes": (rng.random((n, 9, 54)) < 0.2).astype(np.uint8), "tscalars": rng.random((n, 12)).astype(np.float32),
         "target": rng.integers(0, 204, n).astype(np.int16)}
    v, tv, t = ur.mix_forward(m.readout, z, np.arange(n))
    assert v.shape == (n, K, 204) and tv.shape == (n, 204)
    with torch.no_grad():                         # each world's row is the body on that world's own leaf
        one, _ = m.readout.body(torch.from_numpy(z["S"][2:3].astype(np.float32)), torch.from_numpy(z["c"][2:3].astype(np.float32)),
                                torch.from_numpy(z["planes"][2, 3:4].astype(np.float32)), torch.from_numpy(z["scalars"][2, 3:4]))
    assert torch.allclose(v[2, 3], one[0], atol=1e-5)
    ur.mixture_nll(v, t).mean().backward()
    assert float(m.readout.stem.weight.grad.abs().sum()) > 0


def _action_weights(dh=24, de=32, k=8):
    shapes = {"ln.weight": (dh,), "ln.bias": (dh,), "e_mu": (de,), "e_sd": (de,),
              "A.weight": (k, dh), "A.bias": (k,), "B.weight": (k, de), "B.bias": (k,),
              "W1.weight": (k, 3*k), "W1.bias": (k,), "W2.weight": (64, k),
              "W2.bias": (64,), "w.weight": (1, 64), "w.bias": (1,)}
    rng = np.random.default_rng(871)
    weights = {key: rng.normal(0, .2, size=shape).astype(np.float32) for key, shape in shapes.items()}
    weights["ln.weight"] += 1
    weights["e_sd"] = np.abs(weights["e_sd"]) + .01
    return weights


def test_action_scorer_matches_torch_residual_and_authenticates_package(tmp_path):
    import hashlib
    from shengji.train import unified_reply_action as ra
    weights = _action_weights()
    scorer = ra.ReplyActionScorer(weights, "a" * 64, "b" * 64)
    rng = np.random.default_rng(3)
    h, e = rng.normal(size=24).astype(np.float32), rng.normal(size=(17, 32)).astype(np.float32)
    w = {key: torch.from_numpy(value) for key, value in weights.items()}
    F = torch.nn.functional
    u = F.relu(F.linear(F.layer_norm(torch.from_numpy(h), (24,), w["ln.weight"], w["ln.bias"]),
                        w["A.weight"], w["A.bias"]))
    v = F.relu(F.linear((torch.from_numpy(e) - w["e_mu"]) / w["e_sd"], w["B.weight"], w["B.bias"]))
    x = F.relu(F.linear(torch.cat([u.expand_as(v), v, u*v], -1), w["W1.weight"], w["W1.bias"]))
    want = F.linear(F.relu(F.linear(x, w["W2.weight"], w["W2.bias"])), w["w.weight"], w["w.bias"]).numpy().ravel()
    assert np.allclose(scorer.residual(h, e), want, atol=2e-6, rtol=2e-5)
    path = tmp_path / "actions.npz"
    np.savez(path, schema=ra.SCHEMA, base_model_sha256="a" * 64, **weights)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = ra.load_reply_action(path, sha256=sha)
    assert np.array_equal(loaded.residual(h, e), scorer.residual(h, e))
    with pytest.raises(ValueError, match="hash mismatch"):
        ra.load_reply_action(path, sha256="c" * 64)
    weights["e_sd"][0] = 0
    with pytest.raises(ValueError, match="positive"):
        ra.ReplyActionScorer(weights, "a" * 64, "b" * 64)


@pytest.mark.parametrize(("trump", "lead", "follow"), [
    ("H", ["H3", "H3"], ["H4", "H4"]),
    (None, ["S7", "S7"], ["D7", "D7"]),
    ("D", ["C3", "C3", "C4", "C4"], ["C8", "C8", "C9", "CJ"]),
])
def test_compact_action_features_match_listed_card_features(trump, lead, follow):
    from shengji.train import unified_reply_action as ra
    from tests.test_endgame_compact import _play_round

    width = len(lead)
    cards = ["HK", "D7", "C5", "C6", "DJ", "LJ", "S7"]
    actions = [[a, a, b, b][:width] for a in cards for b in cards if a != b]
    actions += [[a, b, a, b][:width] for a in cards for b in cards if a != b]
    root = _play_round(trump, "7", 0, [lead, follow, [], []], [], leader=0, attacker_points=0)
    root.play(0, lead)
    root.play(1, follow)
    legal = pts.CompactReplies(actions, leads=False)
    counts = legal.multiplicity().astype(np.float32)
    actual = ra._compact_feats(legal, root, counts, counts.sum(1))
    np.testing.assert_array_equal(actual, ra.action_feats(actions, root, root.turn))


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("multi", [False, True])
def test_action_scorer_flows_through_readout_to_real_reply_play(package, tmp_path, monkeypatch, fast, multi):
    from shengji.train import unified_reply_action as ra
    from shengji.harvest.legal import enumerate_legal
    _, model = _model(tmp_path)
    from tests.test_pv_small_joker_lead import _fresh_round
    root = _fresh_round(707_001)
    source = None
    while source is None and root.phase == "play":
        if not root.trick.plays:
            for action in enumerate_legal(root, root.turn, cap=30).actions:
                if (len(action) > 1) != multi:
                    continue
                candidate = pts.child_position(root, root.turn, list(action))
                if len(enumerate_legal(candidate, candidate.turn, cap=30).actions) >= (16 if multi else 2):
                    source = candidate
                    break
        if source is None:
            root.play(root.turn, HeuristicBot().decide_play(root, root.turn))
    assert source is not None
    seat = source.turn
    bot = us.install_reply_readout(_bot(package), model)
    bot.unified_fast = fast
    weights = _action_weights()
    path = tmp_path / "action-head.npz"
    sha = ra.save_reply_action(path, weights, base_model_sha256=model.package_sha256)
    scorer = ra.load_reply_action(path, sha256=sha)
    ra.install_reply_action(bot, scorer)
    with pytest.raises(ValueError, match="already installed"):
        ra.install_reply_action(bot, scorer)
    with pytest.raises(ValueError, match="disagree"):
        ra.install_reply_action(us.install_reply_readout(_bot(package), model),
            ra.ReplyActionScorer(weights, "a" * 64, "b" * 64))
    active = [copy.deepcopy(source) for _ in range(3)]
    legal = [list(a) for a in enumerate_legal(source, seat, cap=30).actions]
    bot.unified_frame = us.LeafFrame(bot, root, root.turn)
    frame = bot.unified_frame
    planes, scalars = us.leaf_features(frame, source)
    cache = frame.cache(model)
    h = model.leaf_hidden_fused(frame.fused(model), planes.reshape(1, -1), scalars[None])[0] if fast else \
        model.leaf_hidden(cache, planes[None], scalars[None])[0]
    z = h @ model._t["reply.weight"] + model.r["reply.bias"]
    expected_scores = scorer.scores(source, legal, z, h, cache[0], planes) if multi else \
        np.array([sum(z[CARD_INDEX[c]] for c in action) for action in legal])
    expected = legal[int(np.argmax(expected_scores))]
    original_predict = bot.predict
    calls = []
    original_scores = scorer.scores
    def scores(*args):
        calls.append(args[0])
        return original_scores(*args)
    monkeypatch.setattr(scorer, "scores", scores)
    def listing(clone, seat, cache):
        actions = legal[:1] if clone is active[0] else legal
        counts = np.stack([_counts(a) for a in actions])
        return (pts.CompactReplies(actions, leads=False) if fast else actions), counts
    stats = pts.greedy_stats()
    us.readout_reply_ply(pts.greedy_reply_ply)(bot, active, None, {}, stats, 1, 1, listing,
        lambda leaves, seat, gate: (np.zeros(len(leaves)), 1))
    want = copy.deepcopy(source)
    want.play(seat, expected)
    assert all(list(clone.trick.plays[-1].cards) == expected for clone in active[1:])
    assert all(clone.hands == want.hands and clone.turn == want.turn for clone in active[1:])
    assert len(calls) == (2 if multi else 0)
    assert bot.predict is original_predict
    assert stats["tree_forced_plays"] == 1


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("multi_first", [False, True])
def test_action_scorer_gates_each_clone_in_a_mixed_lead_ply(package, tmp_path, monkeypatch, fast, multi_first):
    from shengji.train import unified_reply_action as ra
    from shengji.harvest.legal import enumerate_legal
    from tests.test_pv_small_joker_lead import _fresh_round

    _, model = _model(tmp_path)
    root = _fresh_round(707_001)
    sources = {}
    while root.phase == "play":
        if not root.trick.plays:
            sources = {}
            for action in enumerate_legal(root, root.turn, cap=30).actions:
                child = pts.child_position(root, root.turn, list(action))
                if len(enumerate_legal(child, child.turn, cap=6).actions) >= 2:
                    sources.setdefault(len(action) > 1, child)
            if len(sources) == 2:
                break
        root.play(root.turn, HeuristicBot().decide_play(root, root.turn))
    assert len(sources) == 2
    originals = [sources[multi_first], sources[not multi_first], sources[True]]
    baseline, active = [[copy.deepcopy(c) for c in originals] for _ in range(2)]
    bot = us.install_reply_readout(_bot(package), model)
    bot.unified_fast = fast
    bot.batch_size = 1
    bot.unified_frame = us.LeafFrame(bot, root, root.turn)
    ply = us.readout_reply_ply(pts.greedy_reply_ply)

    def run(clones):
        def listing(clone, seat, cache):
            actions = [list(a) for a in enumerate_legal(clone, seat, cap=6).actions]
            if clone is clones[-1]:
                actions = actions[:1]
            return actions, np.stack([_counts(a) for a in actions])
        stats = pts.greedy_stats()
        ply(bot, clones, None, {}, stats, 1, 1, listing,
            lambda leaves, seat, gate: (np.zeros(len(leaves)), 1))
        assert stats["tree_forced_plays"] == 1

    run(baseline)
    scorer = ra.ReplyActionScorer(_action_weights(), model.package_sha256, "b" * 64)
    ra.install_reply_action(bot, scorer)
    seen, targets = [], {}

    def scores(clone, legal, *unused):
        seen.append(len(clone.trick.plays[0].cards))
        target = legal[-1]
        targets[id(clone)] = target
        return np.arange(len(legal), dtype=np.float64)

    monkeypatch.setattr(scorer, "scores", scores)
    original_predict = bot.predict
    run(active)
    assert seen == [len(sources[True].trick.plays[0].cards)]
    for before, actual, default in zip(originals, active, baseline):
        if id(actual) in targets:
            expected = copy.deepcopy(before)
            expected.play(expected.turn, targets[id(actual)])
        else:
            expected = default
        assert actual.hands == expected.hands
        assert actual.turn == expected.turn
        assert actual.trick.plays == expected.trick.plays
    assert bot.predict is original_predict
