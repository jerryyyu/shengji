"""The ``pv-search`` production wrapper (`train.pv_search_policy`) on a real joint NumPy
package, through the server's snapshot/commit path.

Witnesses: the registry name and type guard; the env recipe refuses an unpinned package;
the wrapper's decision is IDENTICAL to the screened harness (`PolicyValueBot`) on the same
state, seed and package; the bot survives ``copy.deepcopy`` inside `_paced_bot_step` and
commits through `_commit_bot_turn` with the live RNG untouched and the numpy model-serving
branch taken; an expired serving budget returns the heuristic anchor with a fallback record
and restores the sampler stream; the encoder version comes from the package.
"""
import asyncio
import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv


@pytest.fixture(scope="module", params=["residual", "grid"], ids=["residual", "grid44"])
def package(tmp_path_factory, request):
    """Joint value/policy export through the real served consumer for both trunks.

    Grid uses C14's 44 channels, but a small synthetic model and weights: this
    tests serving compatibility, not the trained checkpoint or its budget.
    """
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("pv")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=561, enc_version=2, attention_heads=1,
                                        trunk_block=request.param, trunk_layers=2,
                                        grid_channels=44 if request.param == "grid" else 0,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2),
                                         "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


def _play_state(seed: int = 625091990):
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play"
    return rnd


SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)


def test_singleton_candidate_loads_package_and_keeps_bury_consumer(package):
    from shengji.eval.singleton_challenger import load_singleton_challenger
    path, sha = package
    recipe = dict(checkpoint=path, sha256=sha, **SMALL, bury_arm='hybrid',
                  leaf_greedy_finish=True, serving_budget_seconds=3.0)
    bot = load_singleton_challenger(name='test-baseline', **recipe)
    control = pv.make_pv_search_bot(**recipe)
    assert isinstance(bot, pv.PVSearchBuryBot)
    assert bot.policy_name == 'test-baseline-sc8'
    assert bot.config == control.config
    rnd = _play_state()
    bury_root = copy.deepcopy(rnd)
    bury_root.hands[bury_root.banker].extend(bury_root.buried)
    bury_root.buried = []
    bury_root.phase = 'bury'
    assert bot.decide_bury(copy.deepcopy(bury_root), bury_root.banker) == control.decide_bury(
        copy.deepcopy(bury_root), bury_root.banker)
    action = bot.decide_play(rnd, rnd.turn)
    record = bot.last_decision_record
    assert record['schema'] == pv.RECORD_SCHEMA and record['work_complete']
    assert record['worlds'] == SMALL['worlds']
    assert len(record['admitted']) == SMALL['candidates']
    rnd.play(rnd.turn, action)


def test_singleton_current_recipe_binding_ignores_ambient_switches(package, tmp_path, monkeypatch):
    import hashlib
    import pathlib
    import tomllib
    from shengji.eval.singleton_challenger import candidate_from_env
    path, sha = package
    env = tomllib.loads((pathlib.Path(__file__).resolve().parents[2] / 'fly.toml').read_text())['env']
    belief = tmp_path / 'belief.npz'
    belief.write_bytes(b'synthetic belief binding')
    env.update(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha,
               SHENGJI_PV_BELIEF_CKPT=str(belief),
               SHENGJI_PV_BELIEF_SHA256=hashlib.sha256(belief.read_bytes()).hexdigest())
    sentinel = object()
    monkeypatch.setattr(pv, '_load_belief', lambda *args: sentinel)
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    baseline_name, = entries
    env['SHENGJI_BOT'] = baseline_name
    expected_switches = pv.latency_switches(env)
    for attr, key in pv.LATENCY_SWITCH_ENV.items():
        monkeypatch.setenv(key, str(int(not expected_switches[attr])))
    candidate = candidate_from_env(env, seed=19)
    control = entries[baseline_name](seed=19)
    assert candidate.config == control.config
    assert candidate.policy_name == baseline_name + '-sc8'
    assert candidate.belief_model is sentinel
    assert candidate.worlds == 64 and candidate.candidates == 8
    assert candidate.serving_budget_seconds == 3.0
    assert candidate.leaf_greedy_finish and candidate.leaf_greedy_finish_exact_skip
    assert candidate.bury_wide_value
    for attr, enabled in expected_switches.items():
        assert getattr(candidate, attr) is enabled
    env['SHENGJI_BOT'] = 'wrong-baseline'
    with pytest.raises(ValueError, match='does not match'):
        candidate_from_env(env)


def test_singleton_qualifier_runs_actual_server_path(package):
    from scripts.qualify_singleton_challenger import fixture, qualify_one
    from shengji.eval.singleton_challenger import load_singleton_challenger
    path, sha = package
    bot = load_singleton_challenger(name='pv-search-test', checkpoint=path, sha256=sha,
                                   **SMALL, leaf_greedy_finish=True, serving_budget_seconds=3)
    root = fixture('4', 2, 625091990)
    before = copy.deepcopy(root.hands)
    row = asyncio.run(qualify_one(root, bot))
    assert row['healthy'] and row['worlds'] == SMALL['worlds']
    assert row['attempted'] and row['accepted']
    assert row['seconds'] >= 0 and root.hands == before


@pytest.mark.parametrize('fault', ['belief', 'worlds', 'incomplete', 'schema'])
def test_singleton_qualifier_refuses_unhealthy_producer(package, monkeypatch, fault):
    from scripts.qualify_singleton_challenger import fixture, qualify_one
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, **SMALL, name='pv-search-test')
    prepare = srv._paced_bot_step
    async def inject(*args, **kwargs):
        prepared = await prepare(*args, **kwargs)
        rec = prepared.decision.snapshot.bot_copy.last_decision_record
        if fault == 'belief':
            bot.belief_worlds = True
            rec['belief_fallback'] = 1
        elif fault == 'worlds':
            rec['worlds'] = 1
        elif fault == 'incomplete':
            rec['work_complete'] = False
        else:
            rec['schema'] = pv.FALLBACK_SCHEMA
        return prepared
    monkeypatch.setattr(srv, '_paced_bot_step', inject)
    row = asyncio.run(qualify_one(fixture('4', 2, 625091990), bot))
    assert not row['healthy']


@pytest.mark.parametrize('bad_arm', [None, 'baseline', 'candidate'])
def test_singleton_qualifier_stops_on_either_arm_and_preserves_rows(tmp_path, monkeypatch, bad_arm):
    import json
    from types import SimpleNamespace
    from scripts import qualify_singleton_challenger as q
    def bot(arm):
        return SimpleNamespace(arm=arm, worlds=64, candidates=8, serving_budget_seconds=3)
    monkeypatch.setattr(q.pv, 'pv_env_recipe', lambda env: {})
    monkeypatch.setattr(q.pv, 'pv_registry_entries', lambda **kwargs: {'baseline': lambda **kw: bot('baseline')})
    monkeypatch.setattr(q, 'candidate_from_env', lambda *args, **kwargs: bot('candidate'))
    monkeypatch.setattr(q, 'fixture', lambda *args: object())
    async def decision(root, actor):
        return dict(healthy=actor.arm != bad_arm, seconds=1.0)
    monkeypatch.setattr(q, 'qualify_one', decision)
    out = tmp_path / 'rows.jsonl'
    with out.open('x') as dest:
        rc = asyncio.run(q.qualify({'SHENGJI_BOT': 'baseline'}, dest))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    if bad_arm is None:
        assert rc == 0 and len(rows) == 105
        assert rows[-1]['passed'] and rows[-1]['calls'] == {'baseline': 52, 'candidate': 52}
        assert [r['arm'] for r in rows[:4]] == ['baseline', 'candidate', 'candidate', 'baseline']
    else:
        assert rc == 1 and len(rows) == (1 if bad_arm == 'baseline' else 2)
        assert rows[-1]['arm'] == bad_arm and not rows[-1]['healthy']
        assert all(row['kind'] == 'decision' for row in rows)


@pytest.fixture
def registered(package):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, **SMALL)
    try:
        yield names
    finally:
        for name in names:
            REGISTRY.pop(name, None)


# --------------------------------------------------------------- registry

def test_registered_name_pins_the_recipe_and_builds_the_wrapper(package, registered):
    path, sha = package
    name, = registered
    config = pv.PVSearchConfig(checkpoint_sha256=sha, **SMALL)
    assert name == f"pv-search-{sha[:8]}-w3-k4-r{pv.recipe_digest(config)}"
    bot = make_bot(name, seed=5)
    assert isinstance(bot, pv.PVSearchBot) and bot.policy_name == name
    assert bot.worlds == 3 and bot.candidates == 4 and bot.cap == 400 and bot.batch_size == 16
    assert bot.checkpoint_sha256 == sha and bot.version == 2
    assert bot.evaluator.backend == "numpy"
    assert isinstance(bot.predict, pv.NumpyPriorPredict)
    # the seed is a run parameter: a different seed keeps the name
    assert make_bot(name, seed=6).policy_name == name
    # the recipe digest excludes the seed and moves with any recipe field
    other = pv.PVSearchConfig(checkpoint_sha256=sha, **{**SMALL, "worlds": 4})
    assert pv.recipe_digest(other) != pv.recipe_digest(config)


def test_wrapper_refuses_an_unpinned_or_mismatched_package(package, tmp_path):
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="SHA256 mismatch"):
        pv.make_pv_search_bot(path, sha256="0" * 64, **SMALL)
    with pytest.raises(pv.PVSearchPolicyError, match="NumPy package"):
        pv.make_pv_search_bot(str(tmp_path / "x.pt"), sha256=sha, **SMALL)
    with pytest.raises(pv.PVSearchPolicyError, match="on disk"):
        pv.pv_registry_entries(path, sha256="1" * 64, **SMALL)


def test_env_recipe_requires_the_full_sha_and_parses_the_knobs(package):
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="SHENGJI_PV_CKPT"):
        pv.pv_env_recipe({})
    with pytest.raises(pv.PVSearchPolicyError, match="full sha256"):
        pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha[:8]})
    recipe = pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha,
                               "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8",
                               "SHENGJI_PV_SERVING_BUDGET_SECONDS": "2.5"})
    assert recipe == dict(checkpoint=path, sha256=sha, worlds=64, candidates=8,
                          serving_budget_seconds=2.5)
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    assert name.startswith(f"pv-search-{sha[:8]}-w64-k8-r")
    bad = pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha,
                            "SHENGJI_PV_SERVING_BUDGET_SECONDS": "0"})
    with pytest.raises(ValueError, match="finite and positive"):
        pv.pv_registry_entries(**bad)


# ------------------------------------------------- parity with the harness

def test_wrapper_decision_equals_the_screened_harness(package):
    """Same package, seed and state: the production wrapper plays exactly what
    `PolicyValueBot` (the screened design) plays, with the same record shape."""
    from shengji.train.policy_value_search import PolicyValueBot
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=17, **SMALL)
    harness = PolicyValueBot.from_checkpoint(path, sha, evaluator=bot.evaluator, seed=17,
                                             worlds=3, candidates=4, cap=400, batch_size=16)
    rnd = _play_state()
    seat = rnd.turn
    ours = bot.decide_play(copy.deepcopy(rnd), seat)
    theirs = harness.decide_play(copy.deepcopy(rnd), seat)
    assert ours == theirs
    a, b = bot.last_decision_record, harness.last_decision_record
    assert a["schema"] == pv.RECORD_SCHEMA and a["work_complete"] is True
    assert a["admitted_indices"] == b["admitted_indices"]
    assert a["selected_index"] == b["selected_index"]
    np.testing.assert_allclose(a["value_means"], b["value_means"])
    assert a["encoder_version"] == 2


# ------------------------------------------------ the server snapshot path

@pytest.mark.parametrize('challenger', [False, True])
def test_wrapper_survives_server_snapshot_and_commit(package, tmp_path, challenger):
    """Release-25 lesson: the server deep-copies the whole bot before any search.
    The wrapper's predictor is a module-level object, so the copy holds a working
    model, the live RNG is untouched, the numpy model-serving branch is taken,
    and the decision commits."""
    path, sha = package
    from shengji.eval.singleton_challenger import load_singleton_challenger
    def build():
        recipe = dict(checkpoint=path, sha256=sha, seed=23, serving_budget_seconds=30,
                      name='pv-search-test', **SMALL)
        return load_singleton_challenger(**recipe) if challenger else pv.make_pv_search_bot(**recipe)
    bot = build()

    async def scenario():
        rnd = _play_state()
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code="PVSRCH", game=game, bot=bot,
                        seats=[srv.Seat(str(i), is_bot=True) for i in range(4)],
                        log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **data: events.append(kind)
        seat = rnd.turn
        before = bot.sampler.rng.getstate()
        direct = build()
        expected = direct.decide_play(copy.deepcopy(rnd), seat)
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None and room.bot is bot
        assert bot.sampler.rng.getstate() == before          # live bot never searched
        copied = prepared.decision.snapshot.bot_copy
        assert copied is not bot and copied.sampler is not bot.sampler
        assert isinstance(copied.predict, pv.NumpyPriorPredict) and copied.predict is not bot.predict
        assert copied.last_decision_record["schema"] == pv.RECORD_SCHEMA
        assert list(prepared.decision.cards) == expected
        assert any(kind == "model_search" for kind in events), events
        hand_before = len(rnd.hands[seat])
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == hand_before - len(expected)   # the cards left the live hand
        assert not srv._commit_bot_turn(room, prepared)

    asyncio.run(scenario())


# --------------------------------------------------------- the play budget

def test_expired_budget_returns_the_anchor_and_restores_the_sampler(package):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=29, serving_budget_seconds=1e-9, **SMALL)
    rnd = _play_state()
    seat = rnd.turn
    before = bot.sampler.rng.getstate()
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    assert played == list(anchor)
    record = bot.last_decision_record
    assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
    assert record["work_complete"] is False and record["action"] == list(anchor)
    assert bot.sampler.rng.getstate() == before
    # the same bot with a generous budget completes the search
    bot.serving_budget_seconds = 60.0
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA


def test_search_error_falls_back_and_is_labelled(package, monkeypatch):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=31, serving_budget_seconds=60, **SMALL)
    rnd = _play_state()
    seat = rnd.turn
    monkeypatch.setattr(bot, "_value_means", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == list(anchor)
    assert bot.last_decision_record["reason"] == "search-error"
    assert bot.last_decision_record["error_class"] == "RuntimeError"
    # without a budget the error is NOT hidden
    strict = pv.make_pv_search_bot(path, sha256=sha, seed=31, **SMALL)
    monkeypatch.setattr(strict, "_value_means", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        strict.decide_play(copy.deepcopy(rnd), seat)


# ------------------------------------ the deadline after the final value batch

class _ClockedEvaluator:
    """Finite zeros; advances a mocked clock so the LAST value batch crosses the deadline."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, clock, advance_to):
        self.clock, self.advance_to = clock, advance_to
        self.calls = 0

    def score(self, positions, seat, **kwargs):
        self.calls += 1
        self.clock[0] = self.advance_to
        return np.zeros(len(positions))


@pytest.mark.parametrize("advance_to,expect", [(2.0, "fallback"), (0.5, "decision")])
def test_final_value_batch_crossing_the_deadline_is_a_fallback(monkeypatch, advance_to, expect):
    """Codex's witness on #585: W1/K1, batch 128, 1 s budget, zero policy logits; the one
    value batch returns after the deadline.  Expiry must be classified once control returns:
    heuristic fallback, RNG restored, nothing published as complete work."""
    clock = [0.0]
    monkeypatch.setattr(pv.time, "perf_counter", lambda: clock[0])
    evaluator = _ClockedEvaluator(clock, advance_to)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=1, candidates=1, cap=400,
                               batch_size=128, serving_budget_seconds=1.0)
    bot = pv.PVSearchBot(lambda X: np.zeros((len(X), 54)), evaluator=evaluator, version=2,
                         config=config, checkpoint="/dev/null", seed=41)
    rnd = _play_state()
    seat = rnd.turn
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    before = bot.sampler.rng.getstate()
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert evaluator.calls == 1
    if expect == "fallback":
        assert played == list(anchor)
        assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
        assert record["work_complete"] is False and record["elapsed_seconds"] == 2.0
        assert bot.sampler.rng.getstate() == before
    else:
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"] is True
        assert record["value_batches"] == 1 and record["played"] == played
        assert bot.sampler.rng.getstate() != before        # the search consumed the stream


# ---------------------------------------- pickling (the screen's deadline worker IPC)

def test_served_bots_pickle_and_behave_identically_after_unpickling(package):
    """`screen_deadline._snapshot` pickles the bot state (``vars(bot)`` minus the evaluator)
    per move; the NumPy packages hold read-only mapping-proxy weights that deep-copy but
    did not pickle (lane v34pv aborted on it).  Both served bots' states must round-trip,
    the revived models must stay read-only, and their forwards must be bit-identical."""
    import pickle
    from shengji.ai.cwv_policy import shared_evaluator
    from shengji.train.cwv_prior_admission import CWVPriorAdmissionBot, CWVPriorAdmissionConfig

    def snapshot(bot):
        return {k: v for k, v in vars(bot).items() if k != "evaluator"}   # what the worker sends

    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=5, **SMALL)
    X = np.zeros((2, 833), dtype=np.float32)
    predict = pickle.loads(pickle.dumps(bot.predict))
    assert isinstance(predict, pv.NumpyPriorPredict) and predict.sha256 == sha and predict.version == 2
    np.testing.assert_array_equal(predict(X), bot.predict(X))
    state = pickle.loads(pickle.dumps(snapshot(bot)))
    assert state["predict"].sha256 == sha
    prior_bot = CWVPriorAdmissionBot(shared_evaluator(path, threads=1, max_batch=16, encoding="mlp-static"),
                                     seed=1, prior=CWVPriorAdmissionConfig(path, sha))
    revived = CWVPriorAdmissionBot.__new__(CWVPriorAdmissionBot)
    vars(revived).update(pickle.loads(pickle.dumps(snapshot(prior_bot))))
    assert revived._prior_kind == prior_bot._prior_kind and revived._prior_net is not prior_bot._prior_net
    for name in type(revived._prior_net)._PROXIED:                 # joint MLP or standalone prior
        proxy = getattr(revived._prior_net, name)
        assert type(proxy).__name__ == "mappingproxy" and all(not a.flags.writeable for a in proxy.values())
        for array in proxy.values():                               # bytes-backed: cannot be re-opened
            with pytest.raises(ValueError):
                array.setflags(write=True)
    np.testing.assert_array_equal(revived._prior_log_odds(X), prior_bot._prior_log_odds(X))
    model = pickle.loads(pickle.dumps(bot.evaluator.model)) if hasattr(bot.evaluator, "model") else None
    if model is not None:
        assert all(not a.flags.writeable for a in model._weights.values())


@pytest.mark.parametrize("first_import", ["shengji.ai.registry", "shengji.train.pv_search_policy",
                                         "shengji.eval.singleton_challenger", "shengji.api.server"])
def test_singleton_opt_in_registry_survives_fresh_process(package, first_import):
    import json
    import os
    import subprocess
    import sys
    import textwrap
    path, sha = package
    env = {k: v for k, v in os.environ.items() if not k.startswith('SHENGJI_PV_')}
    env.update(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha,
               SHENGJI_PV_WORLDS='3', SHENGJI_PV_CANDIDATES='4',
               SHENGJI_PV_CAP='400', SHENGJI_PV_BATCH_SIZE='16', SHENGJI_PV_SEED='79',
               SHENGJI_PV_BURY_ARM='hybrid', SHENGJI_PV_SERVING_BUDGET_SECONDS='3')
    code = textwrap.dedent('''
        import asyncio, copy, json, os
        from shengji.ai import registry
        from shengji.train import pv_search_policy as pv
        from shengji.eval.singleton_challenger import candidate_from_env
        from scripts.qualify_singleton_challenger import fixture, qualify_one
        base, = pv.pv_registry_entries(**pv.pv_env_recipe())
        name = base + '-sc8'
        enabled = os.environ.get('SHENGJI_PV_SINGLETON_CHALLENGER') == '1'
        assert (name in registry.REGISTRY) == enabled
        assert base in registry.REGISTRY
        if enabled:
            default_bot = registry.make_bot(name)
            seeded_bot = registry.make_bot(name, seed=79)
            assert default_bot.sampler.rng.getstate() == seeded_bot.sampler.rng.getstate()
            from shengji.api.server import Room
            os.environ['SHENGJI_BOT'] = name
            room = Room(code='SC8TEST', bot_seed=19)
            assert room.bot.policy_name == name
            assert room.bot.sampler.rng.getstate() == registry.make_bot(name, seed=19).sampler.rng.getstate()
            os.environ['SHENGJI_BOT'] = base
            reference = candidate_from_env(os.environ, seed=19)
            bot = registry.make_bot(name, seed=19)
            assert bot.policy_name == name and bot.config == reference.config
            assert isinstance(bot, pv.PVSearchBuryBot)
            root = fixture(rank='2', banker=0, seed=625091990)
            a = bot.decide_play(copy.deepcopy(root), root.turn)
            b = reference.decide_play(copy.deepcopy(root), root.turn)
            assert a == b
            for key in ('admitted', 'value_means', 'selected_index', 'singleton_challenger_applied'):
                assert bot.last_decision_record[key] == reference.last_decision_record[key]
            row = asyncio.run(qualify_one(root, registry.make_bot(name, seed=19)))
            assert row['healthy'], row
        print(json.dumps({'enabled': enabled}))
    ''')
    for value in ('0', '1', 'bogus'):
        result = subprocess.run([sys.executable, '-c', 'import ' + first_import + '\n' + code], env={**env, 'SHENGJI_PV_SINGLETON_CHALLENGER': value},
                                capture_output=True, text=True, timeout=60)
        if value == 'bogus':
            assert result.returncode != 0 and 'must be 0 or 1' in result.stderr
        else:
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)['enabled'] == (value == '1')
