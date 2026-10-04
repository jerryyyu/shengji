import copy
from types import SimpleNamespace

import pytest

from shengji.harvest.legal import LegalSet
from shengji.eval import public_fixture_panel as module
from shengji.eval.public_fixture_panel import collect_public_fixture_panel
from test_pv_tiebreak_points import RankEvaluator, last_position, predict
from shengji.train import pv_search_policy as pv


ACTIONS = [["DK"], ["D6"]]


def _inputs(monkeypatch, *, mode="fresh-root", config_changes=None):
    root = last_position()
    worlds = [(copy.deepcopy(root.hands), list(root.buried)) for _ in range(3)]
    fixture = SimpleNamespace(id="synthetic-fixture", seat=root.turn)
    calls = {"sample": [], "factory": 0, "legal": []}
    config_changes = {} if config_changes is None else dict(config_changes)

    def factory():
        calls["factory"] += 1
        options = {"worlds": 3, "candidates": 4, "cap": 400,
                   "batch_size": 16, "refusal_constraints": True}
        options.update(config_changes)
        config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **options)
        return pv.PVSearchBot(predict, evaluator=RankEvaluator(), version=2,
                              config=config, checkpoint="/dev/null", seed=17)

    def sample(bot, fixture_, **kwargs):
        calls["sample"].append((bot, fixture_, kwargs))
        return root, copy.deepcopy(worlds), {
            "schema": "public-refusal-tape-v1", "mode": mode,
            "seed": 17, "fill_seed": kwargs["fill_seed"],
        }

    def legal(root_, seat_, *, cap):
        calls["legal"].append((root_, seat_, cap))
        return LegalSet("follow", copy.deepcopy(ACTIONS), 2, True)

    monkeypatch.setattr(module, "sample_public_refusal_tape", sample)
    monkeypatch.setattr(module, "enumerate_legal", legal)
    return fixture, factory, calls, root, worlds


@pytest.mark.parametrize("mode,expected_factories", [("fresh-root", 4),
                                                     ("history-primed", 2)])
def test_composes_mode_with_one_sampler_and_fresh_real_scoring_bots(
        monkeypatch, mode, expected_factories):
    fixture, factory, calls, root, worlds = _inputs(monkeypatch, mode=mode)
    original = copy.deepcopy((fixture.__dict__, ACTIONS))
    collection_calls = []

    def collect(name):
        original_fn = getattr(module, name)

        def wrapped(*args, **kwargs):
            collection_calls.append(name)
            return original_fn(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    collect("collect_fixed_tape_panel")
    collect("collect_history_primed_panel")
    out = collect_public_fixture_panel(
        factory, fixture, ACTIONS[:1], ACTIONS[1:], mode=mode, seed=17,
        fill_seed=4)

    assert calls["factory"] == expected_factories
    assert len(calls["sample"]) == 1
    assert calls["sample"][0][2] == {"mode": mode, "seed": 17, "fill_seed": 4,
                                      "check_budget": None}
    assert collection_calls == ["collect_history_primed_panel" if mode == "history-primed"
                                else "collect_fixed_tape_panel"]
    assert out["schema"] == "public-fixture-panel-v1"
    assert out["fixture_id"] == fixture.id
    assert out["mode"] == mode and out["seed"] == 17 and out["fill_seed"] == 4
    assert out["legal_count"] == 2 and out["actions"] == ACTIONS
    assert len(out["worlds"]) == 3
    assert out["effective"] == {
        "worlds": 3, "cap": 400, "batch_size": 16, "candidates": 4}
    assert out["tape_receipt"]["mode"] == mode
    assert out["provenance_verified"] is False
    assert out["model_verified"] is False
    assert out["serving_choice_assessed"] is False
    assert (fixture.__dict__, ACTIONS) == original
    assert calls["legal"] == [(root, root.turn, 400)]


def test_budget_propagates_to_sampler_and_scoring(monkeypatch):
    fixture, factory, calls, _root, _worlds = _inputs(monkeypatch)
    seen = []
    budget = lambda: seen.append(("callback", None))

    def sample(bot, fixture_, **kwargs):
        seen.append(("sample", kwargs["check_budget"]))
        return _root, copy.deepcopy(_worlds), {"schema": "x", "mode": "fresh-root"}

    # Keep this test at the composition boundary: the synthetic sampler only
    # records the callback; fixed-tape capture receives the same callback.
    monkeypatch.setattr(module, "sample_public_refusal_tape", sample)
    original = module.collect_fixed_tape_panel

    def panel(*args, **kwargs):
        seen.append(("panel", kwargs["check_budget"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "collect_fixed_tape_panel", panel)
    collect_public_fixture_panel(
        factory, fixture, ACTIONS[:1], ACTIONS[1:], mode="fresh-root", seed=17,
        check_budget=budget)
    assert seen[:2] == [("sample", budget), ("panel", budget)]


@pytest.mark.parametrize("bad", [
    {"mode": "auto", "seed": 17, "fill_seed": 0},
    {"mode": "fresh-root", "seed": True, "fill_seed": 0},
    {"mode": "fresh-root", "seed": -1, "fill_seed": 0},
    {"mode": "fresh-root", "seed": 17, "fill_seed": True},
])
def test_malformed_mode_seed_and_ballots_refuse_before_factory(monkeypatch, bad):
    factory_calls = []

    def fail():
        factory_calls.append(1)
        pytest.fail("factory called before validation")

    fixture = SimpleNamespace(id="fx", seat=0)
    with pytest.raises(ValueError):
        collect_public_fixture_panel(
            fail, fixture, [], [["DK"]], **bad)
    assert factory_calls == []

    root = last_position()
    fixture = SimpleNamespace(id="fx", seat=root.turn)
    for control in ([], [["DK"], ["DK"]], [("DK",)]):
        with pytest.raises(ValueError):
            collect_public_fixture_panel(fail, fixture, control, [["D6"]],
                                         mode="fresh-root", seed=17)
    assert factory_calls == []


def test_recipe_drift_and_reused_sampler_refuse(monkeypatch):
    fixture, factory, calls, _root, _worlds = _inputs(monkeypatch)
    count = []

    def drift_factory():
        count.append(1)
        cap = 400 if len(count) == 1 else 401
        config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=3,
                                   candidates=4, cap=cap, batch_size=16,
                                   refusal_constraints=True)
        return pv.PVSearchBot(predict, evaluator=RankEvaluator(), version=2,
                              config=config, checkpoint="/dev/null", seed=17)

    with pytest.raises(ValueError, match="drift"):
        collect_public_fixture_panel(
            drift_factory,
            fixture, ACTIONS[:1], ACTIONS[1:], mode="fresh-root", seed=17)
    assert count == [1, 1]

    fixture, factory, calls, _root, _worlds = _inputs(monkeypatch)
    reused = [factory()]
    with pytest.raises(ValueError, match="reuse"):
        collect_public_fixture_panel(
            lambda: reused[0], fixture, ACTIONS[:1], ACTIONS[1:],
            mode="fresh-root", seed=17)
    assert calls["factory"] == 1


def test_missing_ballot_and_partial_pool_refuse_before_scoring_factory(monkeypatch):
    fixture, factory, calls, _root, _worlds = _inputs(monkeypatch)
    with pytest.raises(ValueError, match="absent"):
        collect_public_fixture_panel(
            factory, fixture, [["SA"]], ACTIONS[1:],
            mode="fresh-root", seed=17)
    assert calls["factory"] == 1

    fixture, factory, calls, _root, _worlds = _inputs(monkeypatch)
    monkeypatch.setattr(module, "enumerate_legal",
                        lambda root, seat, cap: LegalSet("follow", ACTIONS[:1], 2, False))
    with pytest.raises(ValueError, match="complete"):
        collect_public_fixture_panel(
            factory, fixture, ACTIONS[:1], ACTIONS[1:], mode="fresh-root", seed=17)
    assert calls["factory"] == 1
