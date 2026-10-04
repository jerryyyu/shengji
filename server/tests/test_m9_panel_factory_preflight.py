"""Served factory wiring witness, not real-package/Linux qualification.

Only package identity/loading is substituted. Registry parsing, config, wrapper
construction, public-history reconstruction and collector sampler guards run
normally. Sampling dispatch is intercepted before any world draw or score.
"""
from pathlib import Path

import pytest

from shengji.eval import tactical
from shengji.eval.m9_panel_plan import ROOTS
from shengji.eval.m9_panel_recipe import MODEL_SHA256, panel_model_environ
from shengji.eval.public_fixture_panel import collect_public_fixture_panel
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_m9_panel_recipe import recipe


class _BeforeDraw(Exception):
    pass


@pytest.fixture(scope="module")
def public_fixtures():
    return {fixture.id: fixture for fixture in tactical.load_fixtures(
        Path(__file__).parent / "tactical/public_observations.jsonl")}


@pytest.mark.parametrize("root,mode", [(ROOTS[0], "fresh-root")] + [
    (root, "history-primed") for root in ROOTS])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_served_factory_passes_panel_sampler_guards_before_first_draw(
        monkeypatch, public_fixtures, root, mode, seed):
    from shengji.ai import cwv_policy

    loads, bots, dispatches = [], [], []

    class Prior:
        version = 2
        def __init__(self, path, sha):
            loads.append((path, sha))
        def __call__(self, *args, **kwargs):
            raise AssertionError("preflight must never predict")

    class Evaluator:
        backend = "numpy"
        max_batch = 128
        def score(self, *args, **kwargs):
            raise AssertionError("preflight must never score")

    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: MODEL_SHA256[:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: MODEL_SHA256)
    monkeypatch.setattr(pv, "NumpyPriorPredict", Prior)
    monkeypatch.setattr(pv, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    environment = panel_model_environ(recipe())
    fixture = public_fixtures[root]
    original = fixture.to_json()

    def factory():
        name, bot = tactical.bot_from_environ(environment, seed=seed)
        assert type(bot) is pv.PVSearchBuryBot
        assert bot._score_leaves.__func__ is pv.PVSearchBot._score_leaves
        assert bot._leaf.__func__ is PolicyValueBot._leaf
        assert name == bot.policy_name
        assert bot.config.worlds == 64 and bot.config.candidates == 8
        assert all(getattr(bot.config, field) for field in (
            "refusal_constraints", "admission_diversity", "tiebreak_points", "lead_anchor"))
        bots.append(bot)
        return bot

    def stop(kind):
        def intercept(sampler, rnd, seat, n, *args, **kwargs):
            dispatches.append(kind)
            assert len(bots) == 1 and sampler is bots[0].sampler
            assert seat == fixture.seat and n == 64
            assert bots[0]._refusals.key == tuple(rnd.deck)
            assert kind == ("refusal" if bots[0]._refusals.refusals else "plain")
            raise _BeforeDraw
        return intercept

    monkeypatch.setattr(pv, "sample_worlds", stop("plain"))
    monkeypatch.setattr(pv, "sample_worlds_refusal_aware", stop("refusal"))
    with pytest.raises(_BeforeDraw):
        collect_public_fixture_panel(factory, fixture, [["DK"]], [["D6"]],
                                     mode=mode, seed=seed, fill_seed=0)
    assert len(dispatches) == 1 and len(loads) == 1
    assert fixture.to_json() == original
    assert bots[0]._public_refusal_tape_consumed is True
