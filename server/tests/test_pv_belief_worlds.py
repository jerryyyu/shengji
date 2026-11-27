"""The OPTIONAL S17 belief proposal of the pv-search bot (``belief_worlds``,
`ai.belief_numpy.BeliefProposal` inside `ai.history_legality`).

Witnesses: off, the production and release-45 names and the history-legal
digest are unchanged; on, the name gains ``-bw`` after ``-whl`` and the digest
the package sha; the flag needs ``world_history_legal`` and the package pair;
the served draw returns W worlds that keep sizes, voids and pins and pass the
history test, records the rule's fields, and falls back to the history-legal
production draw on any error; the model is shared across a bot snapshot.
"""
import copy
import json

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, W, fixture, served
from test_encoder_round_compat import pinned_production_package  # noqa: F401

BELIEF_KEYS = {"belief_fallback", "belief_proposed", "belief_ms"}


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from shengji.train import belief_seq as bs
    from shengji.train.belief_sampler import export
    torch.manual_seed(5)
    model = bs.build_model(d=16, heads=2, enc_layers=1, xattn_layers=1, x_hidden=16).eval()
    root = tmp_path_factory.mktemp("bw")
    torch.save({"model": model.state_dict(), "config": model.config,
                "args": {"no_history": False}, "epoch": 1, "calib_ll": 1.0}, root / "best.pt")
    info = export(str(root / "best.pt"), str(root / "s17.npz"), temperature=1.0)
    return {"path": str(root / "s17.npz"), "sha256": info["sha256"]}


@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: _SHAS.get(str(path), PRODUCTION_SHA))


_SHAS: dict = {}


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_names_unchanged_off_and_distinct_on(production_package, package):
    _SHAS[package["path"]] = package["sha256"]
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    off = {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
           "SHENGJI_PV_WORLD_HISTORY_DRAW": "1"}
    whl, = names(off)
    assert names({**off, "SHENGJI_PV_BELIEF_WORLDS": "0"}) == [whl]
    on = {**off, "SHENGJI_PV_BELIEF_WORLDS": "1", "SHENGJI_PV_BELIEF_CKPT": package["path"],
          "SHENGJI_PV_BELIEF_SHA256": package["sha256"]}
    bw, = names(on)
    assert "-rc-whl-whd-bw-tb-" in bw and bw != whl
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             world_history_legal=True, world_history_draw=True)
    assert "belief_worlds" not in pv.recipe_payload(base)
    assert "belief_sha256" not in pv.recipe_payload(base)
    a = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                          world_history_legal=True, world_history_draw=True, belief_worlds=True,
                          belief_sha256="a" * 64)
    b = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                          world_history_legal=True, world_history_draw=True, belief_worlds=True,
                          belief_sha256="b" * 64)
    pa = pv.recipe_payload(a)
    assert pa["belief_worlds"] is True and pa["belief_worlds_package"]["sha256"] == "a" * 64
    assert len({pv.recipe_digest(base), pv.recipe_digest(a), pv.recipe_digest(b)}) == 3


def test_flag_contract(production_package, package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal and"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal and"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            world_history_legal=True, belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="full sha256"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, belief_worlds=True,
                                            world_history_legal=True, world_history_draw=True))
    with pytest.raises(pv.PVSearchPolicyError, match="needs belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            belief_sha256="a" * 64))
    with pytest.raises(pv.PVSearchPolicyError, match="go together"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_BELIEF_CKPT": package["path"]})
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_BELIEF_WORLDS": "yes"})
    with pytest.raises(pv.PVSearchPolicyError, match="BELIEF_(CKPT|SHA256)"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
               "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1"})
    _SHAS[package["path"]] = "c" * 64
    with pytest.raises(pv.PVSearchPolicyError, match="does not match"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
               "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1", "SHENGJI_PV_BELIEF_CKPT": package["path"],
               "SHENGJI_PV_BELIEF_SHA256": package["sha256"]})
    _SHAS.pop(package["path"])


def belief_bot(package, seed=7):
    bot = served(seed=seed, world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256=package["sha256"])
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def test_served_draw_is_belief_proposed_and_history_legal(package):
    _, now, seat = fixture()
    bot = belief_bot(package)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["belief_fallback"] == 0 and stats["belief_proposed"] >= W
    constraints = HL.draw_constraints(now, seat)
    assert stats["history_draw_constraints"] == len(constraints) >= 1
    mem = Memory(now, seat, own_kitty=True)
    hidden = sum((__import__("collections").Counter(h) for s, h in enumerate(worlds[0][0])
                  if s != seat), __import__("collections").Counter())
    for hands, buried in worlds:
        assert hands[seat] == sorted(now.hands[seat])
        for s in range(4):
            assert len(hands[s]) == len(now.hands[s])
            if s != seat:
                assert not any(now.ordering.eff_suit(c) in mem.voids[s] for c in hands[s])
        assert HL.history_legal(now, seat, hands)
    assert sum(hidden.values()) == sum(len(now.hands[s]) for s in range(4) if s != seat)
    # the same seed draws the same worlds
    again, _ = belief_bot(package)._worlds(copy.deepcopy(now), seat)
    assert again == worlds


def test_any_error_falls_back_to_the_history_legal_draw(package, monkeypatch):
    _, now, seat = fixture()
    bot = belief_bot(package)
    monkeypatch.setattr(bn.BeliefNumpy, "marginals",
                        lambda self, inp: (_ for _ in ()).throw(RuntimeError("boom")))
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W
    assert bot._last_sampling["belief_fallback"] == 1
    assert bot._last_sampling["belief_error"] == "RuntimeError"
    assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)
    unbound = served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                     belief_sha256=package["sha256"])
    worlds, _ = unbound._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W and unbound._last_sampling["belief_fallback"] == 1


def test_budget_expiry_is_not_swallowed(package):
    _, now, seat = fixture()
    bot = belief_bot(package)

    def expired():
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot._worlds(copy.deepcopy(now), seat, check_budget=expired)


@pytest.mark.parametrize('stage', ['entry', 'features', 'model'])
@pytest.mark.parametrize('error', [pv.PVSearchBudgetExceeded, pv._AdaptiveWorldsExpired])
def test_expired_belief_preparation_stops_before_next_stage(package, monkeypatch, stage, error):
    _, now, seat = fixture()
    bot = belief_bot(package)
    expired = stage == 'entry'
    calls = []
    rng_before = bot.sampler.rng.getstate()
    original_inputs, original_model = bn.decision_inputs, bn.BeliefNumpy.marginals

    def check():
        if expired:
            raise error('expired')

    def inputs(*args, **kwargs):
        nonlocal expired
        calls.append('features')
        result = original_inputs(*args, **kwargs)
        expired = stage == 'features'
        return result

    def model(self, inp):
        nonlocal expired
        calls.append('model')
        result = original_model(self, inp)
        expired = stage == 'model'
        return result

    def forbidden(*args, **kwargs):
        pytest.fail('expired preparation must not project or start either sampler')

    from shengji.train import belief_seq
    monkeypatch.setattr(bn, 'decision_inputs', inputs)
    monkeypatch.setattr(bn.BeliefNumpy, 'marginals', model)
    monkeypatch.setattr(belief_seq, 'project_sizes', forbidden)
    monkeypatch.setattr(pv, 'sample_worlds_history_legal', forbidden)
    with pytest.raises(error):
        bot._worlds(copy.deepcopy(now), seat, check_budget=check)
    assert calls == {'entry': [], 'features': ['features'], 'model': ['features', 'model']}[stage]
    if stage == 'entry':
        assert bot.sampler.rng.getstate() == rng_before


def test_record_and_snapshot(package):
    _, now, seat = fixture()
    bot = belief_bot(package)
    bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert BELIEF_KEYS <= set(record) and record["belief_fallback"] == 0
    json.dumps(record)
    snap = copy.deepcopy(bot)
    assert snap.belief_model is bot.belief_model
    off = served(world_history_legal=True, world_history_draw=True)
    off.decide_play(copy.deepcopy(now), seat)
    assert not BELIEF_KEYS & set(off.last_decision_record)


def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, package, tmp_path):
    """No stub model or sampler: the enabled env recipe reaches the live
    consumer through the server's snapshot and commit path."""
    import asyncio
    import random
    import tomllib
    from pathlib import Path
    from shengji.api import server as srv
    from shengji.engine.game import Game
    env = _r49_env()
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package),
               SHENGJI_PV_WORLD_HISTORY_LEGAL="1", SHENGJI_PV_WORLD_HISTORY_DRAW="1",
               SHENGJI_PV_BELIEF_WORLDS="1",
               SHENGJI_PV_BELIEF_CKPT=package["path"], SHENGJI_PV_BELIEF_SHA256=package["sha256"])
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=7)
    assert bot.belief_worlds and "-whl-whd-bw-" in name
    assert bot.belief_model.package_sha256 == package["sha256"]
    _, rnd, seat = fixture()

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="BW", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["worlds"] == 64 and BELIEF_KEYS <= record.keys()
        assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)

    asyncio.run(scenario())


def test_the_proposal_never_deals_a_forbidden_twin(package):
    """Every proposed hand (not only the accepted ones) honours the draw-time
    constraints, on states with follow history; the truth always does."""
    from test_world_history_draw import breaks_constraints, states
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    checked = constrained = 0
    for rnd, seat in states(n_games=4):
        constraints = HL.draw_constraints(rnd, seat)
        assert not breaks_constraints(constraints, rnd.hands, rnd.ordering)
        propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints)
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(16):
            hands, _ = propose(rnd, seat, mem)
            full = [hands.get(s, rnd.hands[s]) for s in range(4)]
            assert not breaks_constraints(constraints, full, rnd.ordering)
            checked += 1
        constrained += bool(constraints)
    assert checked > 100 and constrained > 3


def _r49_env():
    """Release 49's ``fly.toml`` env: the repo's, with release 50 rolled back (the
    release-49 recipe the identities in this module are derived from)."""
    from test_release49_fly_config import fly_env
    return fly_env()


@pytest.mark.parametrize("offset", [0, 1])
def test_joint_lengths_reach_returned_hands_and_kitty(offset):
    from shengji.rl.encode import CARD_INDEX
    from shengji.train.belief_history import EFF
    from shengji.train.belief_seq import sample_worlds
    from test_world_history_legal import started

    rnd, _ = started(7)
    seat = (rnd.banker + offset) % 4
    expected = []

    class Uniform:
        def marginals(self, inp):
            return np.ones_like(inp["M"], dtype=float)

    def length_draw(inp, mask, batch, rng):
        # Generate feasible test quotas using only information available to the actor.
        seed_worlds = sample_worlds(Uniform().marginals(inp), inp["n_c"], mask,
                                    inp["sizes"], batch, rng)
        suit = inp["card_feat"][:, 1:6].argmax(axis=1)
        quotas = np.stack([seed_worlds[:, suit == s].sum(1) for s in range(5)], axis=1)
        expected.extend(quotas)
        return quotas

    proposal = bn.SuitLengthProposal(Uniform(), rnd, seat, draw_lengths=length_draw,
                                     seed=33, batch=4)
    for row in range(5):
        hands, kitty = proposal(rnd, seat, None)
        counts = np.zeros_like(proposal.inp["K"])
        for rel in (1, 2, 3):
            for code in hands[(seat + rel) % 4]:
                counts[CARD_INDEX[code], rel - 1] += 1
        if offset:
            for code in kitty:
                counts[CARD_INDEX[code], 3] += 1
        else:
            assert kitty == rnd.buried
        residual = counts - proposal.inp["K"]
        assert (residual >= 0).all()
        assert not residual[~proposal.M].any()
        np.testing.assert_array_equal(residual.sum(1), proposal.inp["n_c"])
        groups = np.array([EFF.index(rnd.ordering.eff_suit(c)) for c in bn._codes()])
        actual = np.stack([residual[groups == s].sum(0) for s in range(5)])
        np.testing.assert_array_equal(actual, expected[row])
    assert not np.array_equal(expected[0], expected[1])

    proposal.queue.clear()
    proposal.draw_lengths = lambda *args: np.zeros((4, 5, 4), dtype=int)
    with pytest.raises(bn.BeliefNumpyError, match="available slots or cards"):
        proposal(rnd, seat, None)
    assert not proposal.queue

    # Balanced quotas can still require a receiver that the draw mask forbids.
    from shengji.train.belief_seq import BeliefSeqError
    group, receiver = np.argwhere(expected[0] > 0)[0]
    proposal.M[groups == group, receiver] = False
    proposal.draw_lengths = lambda *args: np.stack(expected[:4])
    with pytest.raises(BeliefSeqError, match="infeasible state"):
        proposal(rnd, seat, None)
    assert not proposal.queue


def test_learned_length_scores_change_hands_at_the_proposal_boundary():
    torch = pytest.importorskip("torch")
    from collections import Counter
    from shengji.train.belief_lengths import build_length_head
    from test_world_history_legal import started

    class Uniform:
        def marginals(self, inp):
            return np.ones_like(inp["M"], dtype=float)

    rnd, _ = started(7)
    seat = (rnd.banker + 1) % 4
    head = build_length_head(width=8)
    totals = []
    for sign in (-1, 1):
        with torch.no_grad():
            head.output[-1].weight.zero_()
            head.output[-1].bias.copy_(sign * 100 * torch.arange(26))
        proposal = bn.SuitLengthProposal(Uniform(), rnd, seat, seed=13, batch=3,
                                         draw_lengths=head.draw_lengths)
        hands, kitty = proposal(rnd, seat, None)
        assert len(kitty) == len(rnd.buried)
        assert all(len(cards) == len(rnd.hands[s]) for s, cards in hands.items())
        totals.append([Counter(map(rnd.ordering.eff_suit, hand)) for hand in hands.values()])
    assert totals[0] != totals[1]


def test_suit_length_bounds_match_all_feasible_completions():
    from itertools import product
    from shengji.train.belief_lengths import _allocation_steps

    rng = np.random.default_rng(20)
    for _ in range(30):
        suits = rng.integers(0, 5, size=5)
        card_feat = np.pad(np.eye(5)[suits], ((0, 0), (1, 0)))
        masks = rng.random((5, 4)) < .65
        holders = rng.integers(0, 4, size=5)
        masks[np.arange(5), holders] = True
        copies = np.array([2, 1, 1, 1, 1])
        owners = np.repeat(np.arange(5), copies)
        sizes = np.bincount(holders[owners], minlength=4)
        assignments = np.array([r for r in product(*(np.flatnonzero(masks[c]) for c in owners))
                                if np.array_equal(np.bincount(r, minlength=4), sizes)])
        steps = _allocation_steps(card_feat, masks, copies, sizes)
        step = next(steps)
        while True:
            totals = (assignments[:, step.cards[owners]] == step.receiver).sum(1)
            np.testing.assert_array_equal(step.choices, np.unique(totals))
            k = rng.choice(step.choices)
            assignments = assignments[totals == k]
            try:
                step = steps.send(k)
            except StopIteration:
                break

    with pytest.raises(ValueError, match="no feasible suit length"):
        next(_allocation_steps(np.eye(1, 6, 1), [[True, False, False, False]],
                               [2], [1, 1, 0, 0]))


def test_paired_void_cli_reads_only_held_out_decisions(package, tmp_path, capsys):
    import hashlib
    from shengji.train import belief_history as bh
    from shengji.train import belief_labels as bl
    from shengji.train import belief_length_eval as evaluator
    from shengji.train import belief_lengths as fitter
    from test_belief_labels import synthetic_cluster

    hist = tmp_path / "hist"
    hist.mkdir()
    files, histories, keys = {}, {}, {}
    for split, seed in [("train", 1003), ("test", 1017), ("other", 1018)]:
        shard = tmp_path / (split + ".jsonl")
        shard.write_text("".join(json.dumps(r) + "\n" for r in synthetic_cluster(seed)))
        rows = bl.extract_cluster(shard, store_index=0, cluster_index=0, calib=0, test=0,
                                  windows=[], sampler_worlds=0, sampler_splits=())
        keys[seed] = rows["deal_key"]
        name = split + ".npz"
        path = tmp_path / name
        np.savez(path, **{k: rows[k][:3] for k in bl.ARRAY_KEYS})
        history = bh.chunk_history(str(path), [str(shard)])
        np.savez(hist / name, **history)
        files[split] = {"file": name, "rows": 3, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        histories[name] = hashlib.sha256((hist / name).read_bytes()).hexdigest()

    def manifests(extra=False):
        chunks = [{"files": files}]
        if extra:
            chunks.append({"files": {"test": files["other"]}})
        data = json.dumps({"chunks": chunks}).encode()
        (tmp_path / "manifest.json").write_bytes(data)
        (hist / "manifest.json").write_text(json.dumps({
            "schema": bh.SCHEMA, "files": histories,
            "source_extract_manifest_sha256": hashlib.sha256(data).hexdigest()}))

    manifests()
    ckpt = str(tmp_path / "head.pt")
    assert fitter.main(["--extract", str(tmp_path), "--out", ckpt, "--steps", "1",
                        "--seed", "15", "--width", "8"]) == 0
    capsys.readouterr()
    args = ["--extract", str(tmp_path), "--length-checkpoint", ckpt, "--seed", "3",
            "--belief-package", package["path"], "--belief-sha256", package["sha256"]]
    assert evaluator.main(args) is None
    result = json.loads(capsys.readouterr().out)
    assert (result["worlds"], result["decisions"], result["deals"]) == (64, 3, 1)
    for role in ("banker", "other_seats", "kitty"):
        joint, plain = (result["arms"][a][role] for a in ("joint", "plain"))
        assert joint["candidate_pairs"] == plain["candidate_pairs"] > 0
        assert joint["true_voids"] == plain["true_voids"]
        assert 0 <= joint["sampled_void_ece"] <= 1
    evaluator.main([*args, "--ll-max-draws", "1", "--ll-replicates", "2"])
    scored = json.loads(capsys.readouterr().out)
    assert scored["arms"] == result["arms"]
    loss = scored["nonbanker_marginal_log_loss"]
    assert loss["hidden_copies"] > 0 and loss["projected_baseline_nats_per_copy"] > 0
    assert loss["unresolved_copy_observations"] > 0
    assert loss["joint_minus_baseline_nats_per_copy"] is None
    assert 0 < loss["worlds_drawn"] <= loss["maximum_worlds"] == 2 * loss["scored_decisions"]
    manifests(extra=True)
    cohort = tmp_path / "cohort.json"
    member = {"seed": 1017, "deal_key": keys[1017], "rows": 3}
    def select(*members):
        cohort.write_text(json.dumps({
            "deals": members, "belief_sha256": package["sha256"],
            "source": {"extract_manifest_sha256": hashlib.sha256(
                (tmp_path / "manifest.json").read_bytes()).hexdigest()},
        }))
        evaluator.main([*args, "--cohort", str(cohort), "--ll-max-draws", "1", "--ll-replicates", "2"])
        return json.loads(capsys.readouterr().out)
    assert select(member) == scored
    from scripts.time_belief_length_fit_eval import main as time_pilot
    out = tmp_path / "timed"
    pilot_args = ["--train-extract", str(tmp_path), "--test-extract", str(tmp_path),
                  "--cohort", str(cohort), "--cohort-sha256", hashlib.sha256(cohort.read_bytes()).hexdigest(),
                  "--belief-package", package["path"], "--belief-sha256", package["sha256"],
                  "--output-dir", str(out)]
    time_pilot(pilot_args)
    timed = json.loads((out / "timing.json").read_text())
    assert 0 < timed["fit_process_seconds"] < timed["fit_eval_process_seconds"]
    assert timed["timing"]["decisions"] == 3 and timed["timing"]["worlds_drawn"] > 0
    assert (out / "length.pt").is_file()
    with pytest.raises(FileExistsError):
        time_pilot(pilot_args)
    with pytest.raises(ValueError, match="wrong timing cohort"):
        time_pilot([*pilot_args, "--cohort-sha256", "bad"])

    evaluator.main([*args, "--cohort", str(cohort), "--ll-max-draws", "1", "--ll-replicates", "2",
                    "--timing-only"])
    timing = json.loads(capsys.readouterr().out)
    assert 0 < timing.pop("log_loss_seconds") <= timing.pop("evaluation_seconds")
    counters = ("scored_decisions", "worlds_drawn", "maximum_worlds", "unresolved_copy_observations",
                "draw_limit_per_row_per_replicate", "replicates")
    assert timing == {"decisions": scored["decisions"], "deals": scored["deals"],
                      "worlds_per_void_arm": scored["worlds"], **{k: loss[k] for k in counters}}
    with pytest.raises(SystemExit):
        evaluator.main([*args, "--timing-only", "--ll-max-draws", "1"])
    with pytest.raises(SystemExit):
        evaluator.main([*args, "--cohort", str(cohort), "--timing-only"])
    with pytest.raises(ValueError, match="seed and extracted deal disagree"):
        select(dict(member, deal_key=keys[1018]))
    with pytest.raises(ValueError, match="missing rows"):
        select(dict(member, rows=4))
    with pytest.raises(ValueError, match="extra rows"):
        select(dict(member, rows=2))
    with pytest.raises(ValueError, match="duplicate seed or deal"):
        select(member, member)
    cohort.write_text(json.dumps({"deals": [member], "source": {"extract_manifest_sha256": "bad"}}))
    with pytest.raises(ValueError, match="different extract manifest"):
        evaluator.main([*args, "--cohort", str(cohort)])
    cohort.write_text(json.dumps({"deals": [member], "belief_sha256": "bad"}))
    with pytest.raises(ValueError, match="different belief package"):
        evaluator.main([*args, "--cohort", str(cohort)])
    # Two individually valid chunks replace the third decision with a repeat of the second.
    with np.load(tmp_path / "test.npz") as original:
        for split, indices in (("test", [0, 1]), ("other", [1])):
            path = tmp_path / f"overlap-{split}.npz"
            np.savez(path, **{key: original[key][indices] for key in bl.ARRAY_KEYS})
            np.savez(hist / path.name, **bh.chunk_history(str(path), [str(tmp_path / "test.jsonl")]))
            histories[path.name] = hashlib.sha256((hist / path.name).read_bytes()).hexdigest()
            files[split] = dict(file=path.name, rows=len(indices),
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifests(extra=True)
    with pytest.raises(ValueError, match="duplicate held-out decision"):
        select(member)
    files["test"] = files["train"]
    manifests()
    with pytest.raises(ValueError, match="training exposure"):
        evaluator.main(args)
