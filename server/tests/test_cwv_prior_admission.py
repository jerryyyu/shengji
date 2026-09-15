"""Witness the learned-prior admission (#425 step 4) on real game states."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math

import numpy as np
import pytest

from shengji.ai.registry import REGISTRY
from shengji.harvest.legal import enumerate_legal
from shengji.rl.encode import CARD_INDEX
from shengji.train import cwv_shortlist_screen as S
from shengji.train import policy_prior as pp
from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot, CWVPriorAdmissionConfig, SCHEMA
from shengji.train.cwv_shortlist import CWVShortlistConfig
from shengji.train.screen_deadline import _phases
from tests.test_cwv_shortlist import Values
from tests.test_world_shortlist import play_state, round_signature


@pytest.fixture(scope="module")
def prior_ckpt(tmp_path_factory):
    """A real (tiny, one-epoch) prior checkpoint plus its SHA256."""
    d = tmp_path_factory.mktemp("prior")
    rng = np.random.default_rng(0)
    X = rng.standard_normal((16, pp.INPUT_DIM)).astype(np.float32); Y = np.zeros((16, 54), np.float32)
    rows = [{"n_legal": 3, "legal": [[0], [1], [2]], "ballot": [[0]], "taken": [0], "complete": True,
             "deal": "d" * 16} for _ in range(16)]
    np.savez_compressed(d / "t.npz", X=X, Y=Y)
    with open(d / "t.meta.jsonl", "w") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
    ck = d / "prior.pt"; pp.train(d / "t", ck, epochs=1, listwise_weight=0.0, threads=1, log=None)
    with open(ck, "rb") as fh:
        sha = hashlib.file_digest(fh, "sha256").hexdigest()
    return str(ck), sha


def recipe(prior_ckpt, **over):
    path, sha = prior_ckpt
    return CWVPriorAdmissionConfig(checkpoint=path, checkpoint_sha256=sha, **over)


def test_recipe_is_strict_and_checkpoint_is_verified(prior_ckpt, tmp_path):
    path, sha = prior_ckpt
    assert asdict(recipe(prior_ckpt)) == {"checkpoint": path, "checkpoint_sha256": sha,
                                          "threshold": 10_000, "top": 256, "schema": SCHEMA}
    with pytest.raises(ValueError):
        CWVPriorAdmissionConfig(checkpoint=path, checkpoint_sha256="short")
    with pytest.raises(ValueError):
        recipe(prior_ckpt, top=0)
    with pytest.raises(ValueError, match="incumbent plus alternatives"):
        CWVPriorAdmissionBot(Values(), prior=recipe(prior_ckpt, top=4))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        CWVPriorAdmissionBot(Values(), prior=CWVPriorAdmissionConfig(checkpoint=path, checkpoint_sha256="0" * 64))
    with pytest.raises(ValueError, match="capture"):
        CWVPriorAdmissionBot(Values(), prior=recipe(prior_ckpt), capture_full_legal_scores=True)
    with pytest.raises(ValueError, match="learned"):
        CWVPriorAdmissionBot(None, prior=recipe(prior_ckpt), config=CWVShortlistConfig(uniform=True))


def test_below_threshold_is_the_unchanged_one_stage_path(prior_ckpt):
    rnd = play_state()
    calls = []

    class Traced(CWVPriorAdmissionBot):
        def _means(self, rnd, seat, actions, worlds):
            calls.append((len(actions), len(worlds)))
            return super()._means(rnd, seat, actions, worlds)

        def _prior_scores(self, *args):
            raise AssertionError("the prior must not run below the threshold")

    bot = Traced(Values(), seed=13, prior=recipe(prior_ckpt, threshold=10 ** 9),
                 config=CWVShortlistConfig(worlds=2))
    selected = bot._candidates(rnd, rnd.turn)
    assert len(selected) == 5 and calls == [(bot.last_shortlist["legal_count"], 2)]
    assert "prior_admission" not in bot.last_shortlist
    assert bot.shortlist_counts["prior_decisions"] == 0


def test_wide_decision_pool_is_the_union_of_per_world_top_lists_plus_anchors(prior_ckpt):
    rnd = play_state()
    before = round_signature(rnd)
    seat = rnd.turn
    legal = enumerate_legal(rnd, seat, cap=None).actions
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, seat)
    production_keys = {tuple(sorted(a)) for a in production}
    singles = [a for a in legal if len(a) == 1 and tuple(a) not in production_keys]
    favourite_a, favourite_b = singles[0], singles[1]
    calls = []

    recorded = []

    class Controlled(CWVPriorAdmissionBot):
        def _means(self, rnd, seat, actions, worlds):
            calls.append((len(actions), len(worlds), [tuple(sorted(a)) for a in actions]))
            return super()._means(rnd, seat, actions, worlds)

        def _prior_scores(self, rnd, seat, actions, worlds):
            scores = super()._prior_scores(rnd, seat, actions, worlds)
            recorded.append(scores)
            return scores

        def _prior_log_odds(self, X):
            # World 0 wants favourite_a's card, world 1 wants favourite_b's card.
            assert X.shape == (2, pp.INPUT_DIM)
            rows = np.zeros((2, 54)); rows[0, CARD_INDEX[favourite_a[0]]] = 10.0; rows[1, CARD_INDEX[favourite_b[0]]] = 10.0
            return rows

    bot = Controlled(Values(), seed=13, prior=recipe(prior_ckpt, threshold=1, top=8),
                     config=CWVShortlistConfig(worlds=2))
    rng = bot.rng.getstate()
    selected = bot._candidates(rnd, seat)
    detail = bot.last_shortlist
    diag = detail["prior_admission"]
    assert len(selected) == 5 and len(calls) == 1                     # one value-ranking pass, over the pool only
    pool_keys = set(calls[0][2])
    assert calls[0][1] == 2 and calls[0][0] == diag["pool_action_count"] == len(pool_keys)
    assert diag["legal_count"] == len(legal) > diag["pool_action_count"]
    assert diag["union_size"] <= 2 * 8 and diag["top"] == 8 and diag["worlds"] == 2
    assert tuple(favourite_a) in pool_keys and tuple(favourite_b) in pool_keys   # each world's favourite survives
    assert production_keys <= pool_keys                                    # every production anchor is protected
    # Expected union from the recorded per-world scores, computed independently of the bot.
    scores = recorded[0]
    expected_union = set()
    for row in scores:
        order = sorted(range(len(legal)), key=lambda i: (-row[i], i))[:8]
        expected_union.update(tuple(sorted(legal[i])) for i in order)
    anchors = set(production_keys)
    assert pool_keys == expected_union | anchors
    assert diag["union_size"] == len(expected_union)
    assert diag["anchors_added"] == len(anchors - expected_union)
    assert {tuple(sorted(a)) for a in selected} <= pool_keys              # the shortlist is drawn from the pool
    assert all(math.isfinite(v) for v in detail["shortlist_means"])
    assert detail["ranking_basis"] == "prior-union-then-world-mean"
    assert detail["full_legal_world_means_complete"] is False
    assert diag["prior_seconds"] >= 0 and diag["prior_checkpoint_sha256"] == prior_ckpt[1]
    assert bot.shortlist_counts["prior_decisions"] == 1 and bot.shortlist_counts["prior_forwards"] == 2
    assert bot.shortlist_counts["prior_pool_actions"] == diag["pool_action_count"]
    assert bot.rng.getstate() == rng                                       # ranking never consumes search RNG
    assert round_signature(rnd) == before


def test_prior_inputs_are_the_sampled_worlds_and_ignore_the_true_hidden_hands(prior_ckpt):
    """Codex HOLD on #427: witness the privacy claim on the tensors the network receives.
    Two controlled worlds redistribute the non-actor hands and the kitty; X must equal the
    mover-relative root tensors of each world clone, and must not change when only the TRUE
    round's hidden hands and kitty change with the worlds held fixed."""
    from shengji.train.cwv_prior_admission import root_clone
    from shengji.train.policy_prior import flat_input, root_tensors
    rnd = play_state()
    seat = rnd.turn
    others = [s for s in range(4) if s != seat]
    actions = enumerate_legal(rnd, seat, cap=None).actions[:6]
    # World A: the truth.  World B: two non-actor hands swapped and the kitty exchanged with
    # the first len(buried) cards of the third non-actor's hand (deck conserved).
    a_hands, a_buried = [list(h) for h in rnd.hands], list(rnd.buried)
    b_hands = [list(h) for h in rnd.hands]
    b_hands[others[0]], b_hands[others[1]] = list(rnd.hands[others[1]]), list(rnd.hands[others[0]])
    k = len(rnd.buried)
    b_buried = sorted(b_hands[others[2]][:k]); b_hands[others[2]] = b_hands[others[2]][k:] + list(rnd.buried)
    worlds = [(a_hands, a_buried), (b_hands, b_buried)]
    seen = []

    class Watch(CWVPriorAdmissionBot):
        def _prior_log_odds(self, X):
            seen.append(np.array(X, copy=True))
            return super()._prior_log_odds(X)

    bot = Watch(Values(), seed=13, prior=recipe(prior_ckpt, threshold=1, top=8), config=CWVShortlistConfig(worlds=2))
    scores = bot._prior_scores(rnd, seat, actions, worlds)
    assert scores.shape == (2, 6) and np.isfinite(scores).all() and len(seen) == 1
    X = seen[0]
    expected = np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat)) for hands, buried in worlds])
    assert X.shape == (2, pp.INPUT_DIM) and np.array_equal(X, expected)
    assert not np.array_equal(X[0], X[1])                                  # hand ownership and kitty are encoded
    assert not np.array_equal(X[1], flat_input(root_tensors(rnd, seat)))    # world B is not the truth

    # Mutate ONLY the true round's hidden information (actor's hand untouched), worlds fixed.
    rnd.hands[others[0]], rnd.hands[others[2]] = rnd.hands[others[2]], rnd.hands[others[0]]
    swapped = rnd.hands[others[1]][:k]
    rnd.hands[others[1]] = rnd.hands[others[1]][k:] + list(rnd.buried); rnd.buried = sorted(swapped)
    assert not np.array_equal(flat_input(root_tensors(rnd, seat)), flat_input(root_tensors(root_clone(rnd, a_hands, a_buried), seat)))
    scores_after = bot._prior_scores(rnd, seat, actions, worlds)
    assert len(seen) == 2 and np.array_equal(seen[1], X)                    # a bypass of root_clone would change this
    assert np.array_equal(scores_after, scores)


def test_deadline_instrumentation_marks_the_prior_phase_with_the_full_population():
    marks = []

    class Bot:
        def _prior_scores(self, rnd, seat, actions, worlds):
            return None

        def _means(self, rnd, seat, actions, worlds):
            return None

    bot = Bot()
    with _phases(bot, lambda name, n: marks.append((name, n))):
        bot._prior_scores(None, 0, list(range(12_000)), [1, 2])
        bot._means(None, 0, list(range(300)), [1, 2])
    assert ("prior", 12_000) in marks
    assert marks[-1] == ("ranking", 12_000)      # the pool call keeps the largest population for attribution


def test_screen_wiring_binds_the_prior_recipe_on_the_arm_only(prior_ckpt, monkeypatch):
    from tests.test_cwv_shortlist_screen import cfg
    path, sha = prior_ckpt

    class Evaluator:
        checkpoint_sha256 = "value-sha"
        def score(self, states, seat):
            return np.zeros(len(states))

    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: Evaluator())
    prior = asdict(CWVPriorAdmissionConfig(checkpoint=path, checkpoint_sha256=sha))
    config = cfg("learned", checkpoint="v.pt", checkpoint_sha256="value-sha", prior=prior,
                 shortlist={"worlds": 32, "selection_worlds": 30, "alternatives": 4, "batch_size": 128, "uniform": False})
    arm = S.make_side(config, "arm", 1)
    assert isinstance(arm, CWVPriorAdmissionBot) and arm.prior_config.checkpoint_sha256 == sha
    baseline = S.make_side(config, "baseline", 1)
    assert not isinstance(baseline, CWVPriorAdmissionBot)
    assert S._recipe(config)["prior"] == prior
    with pytest.raises(ValueError, match="plain learned"):
        S.make_side(dict(config, wide_tail={"threshold": 10_000, "coarse_worlds": 2, "pool": 256}), "arm", 1)


def test_a_value_checkpoint_with_a_policy_head_serves_as_the_prior(prior_ckpt, tmp_path):
    """#425 in play: the admission accepts a train_cwv checkpoint carrying a policy head (the joint
    net) and reads its head over the trunk features; a headless value checkpoint is refused; the
    trace records the prior kind.  Real checkpoints from one-epoch trainer runs on the tiny store."""
    import hashlib
    from shengji.train import policy_prior as pp, train_cwv
    from shengji.train.cwv_prior_admission import load_prior_checked
    from tests.test_cwv_train import THIRDS
    from shengji.harvest import trajectory
    store = tmp_path / "store"
    trajectory.generate(rounds=6, seed0=4_100_000, out_dir=store, workers=1, merge=False,
                        select_worlds=2, report_worlds=30, explore_rate=0.5, explore_k=2)
    rows = tmp_path / "rows"
    pp.extract(rows, [str(store)], lo=0.0, hi=1.01, thin=1.0, max_rows=200, workers=1)
    kw = dict(data=[str(store)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
              log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2, **THIRDS)
    train_cwv.train(out=tmp_path / "headless", **kw)
    train_cwv.train(out=tmp_path / "joint", policy_head=True, policy_rows=str(rows), **kw)
    sha = lambda p: hashlib.file_digest(open(p, "rb"), "sha256").hexdigest()
    joint, headless = str(tmp_path / "joint" / "best.pt"), str(tmp_path / "headless" / "best.pt")
    kind, model, payload = load_prior_checked(joint, sha(joint))
    assert kind == "joint" and payload is None and model.config.policy_head
    with pytest.raises(ValueError, match="neither"):
        load_prior_checked(headless, sha(headless))
    assert load_prior_checked(prior_ckpt[0], prior_ckpt[1])[0] == "separate"
    rnd = play_state(); seat = rnd.turn
    bot = CWVPriorAdmissionBot(Values(), seed=13, config=CWVShortlistConfig(worlds=2),
                               prior=CWVPriorAdmissionConfig(checkpoint=joint, checkpoint_sha256=sha(joint), threshold=1, top=8))
    selected = bot._candidates(rnd, seat)
    assert len(selected) == 5 and bot.last_shortlist["prior_admission"]["prior_kind"] == "joint"
    scores = bot._prior_scores(rnd, seat, enumerate_legal(rnd, seat, cap=None).actions[:5], [(rnd.hands, rnd.buried)])
    assert scores.shape == (1, 5) and np.isfinite(scores).all()
