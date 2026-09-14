"""Consumer witnesses for opt-in component admission, not throw penalties."""
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.engine.cards import Ordering
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train.cwv_throw_aware import CWVThrowComponentsBot
from shengji.train import cwv_shortlist_screen as screen
from tests.test_cwv_shortlist_screen import cfg
from tests.test_world_shortlist import play_state


def bot():
    return CWVThrowComponentsBot(None, config=CWVShortlistConfig(uniform=True))


def test_components_are_deduplicated_incumbent_preserved_and_follows_bypass():
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]), ordering=Ordering("2", "S"))
    actions = [["H3"], ["H5", "H5", "H9"], ["H5", "H5"], ["H9"]]
    assert bot()._augment_selected(rnd, actions, [0, 1, 3]) == [0, 1, 3, 2]
    assert bot()._augment_selected(rnd, actions, [0, 2, 3]) == [0, 2, 3]
    rnd.trick.plays = [object()]
    assert bot()._augment_selected(rnd, actions, [0, 1]) == [0, 1]


def test_missing_component_refuses_instead_of_silent_partial_admission():
    rnd = SimpleNamespace(trick=None, ordering=Ordering("2", "S"))
    with pytest.raises(ValueError, match="^throw component missing from exhaustive legal population$"):
        bot()._augment_selected(rnd, [["H5", "H5", "H9"]], [0])


def test_real_shortlist_hook_keeps_scores_indices_and_counts_aligned(monkeypatch):
    from shengji.engine.combos import decompose
    class Evaluator:
        pass
    rnd = play_state()
    config = CWVShortlistConfig(worlds=1, selection_worlds=1, alternatives=1)
    b = CWVThrowComponentsBot(Evaluator(), config=config)
    # Rank a genuine multi-component lead first, then exercise actual exhaustive
    # enumeration, scoring dispatch, augmentation and serialized shortlist.
    def means(rnd, seat, actions, worlds):
        return np.array([len(a) if len(decompose(a, rnd.ordering).components) > 1
                         else -1 for a in actions], dtype=float)
    monkeypatch.setattr(b, "_means", means)
    candidates = b._candidates(rnd, rnd.turn)
    detail = b.last_shortlist
    assert detail["admission_extension"] == "direct-throw-components-v1"
    assert len(candidates) > 2
    assert candidates == detail["shortlist"]
    assert len(candidates) == len(detail["shortlist_indices"]) == len(detail["shortlist_means"])
    assert detail["counts"]["shortlisted_actions"] == len(candidates)
    assert candidates[0] == detail["incumbent"]


def test_screen_arm_only_and_recipe_identity(monkeypatch):
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64)
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **kw: evaluator)
    config = cfg("learned", checkpoint="m.pt", checkpoint_sha256="a" * 64,
                 baseline="flat-shortlist", throw_components=True)
    assert type(screen.make_side(config, "arm", 17)) is CWVThrowComponentsBot
    assert type(screen.make_side(config, "baseline", 17)) is CWVShortlistBot
    assert screen._recipe(config)["throw_components"] is True
    del config["throw_components"]
    assert "throw_components" not in screen._recipe(config)
    assert type(screen.make_side(config, "arm", 17)) is CWVShortlistBot


def test_hybrid_bury_is_identical_on_both_sides(monkeypatch):
    from shengji.train.cwv_bury_policy import CWVBuryBot, CWVBuryConfig
    from shengji.train.cwv_throw_aware import CWVThrowComponentsBuryBot
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64)
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **kw: evaluator)
    config = cfg("learned", checkpoint="m.pt", checkpoint_sha256="a" * 64,
                 baseline="flat-shortlist", throw_components=True, hybrid_bury=True)
    arm = screen.make_side(config, "arm", 17)
    baseline = screen.make_side(config, "baseline", 17)
    assert type(arm) is CWVThrowComponentsBuryBot
    assert type(baseline) is CWVBuryBot
    assert arm.bury_arm == baseline.bury_arm == "hybrid"
    assert arm.bury_config == baseline.bury_config == CWVBuryConfig()
    assert arm.decide_bury.__func__ is baseline.decide_bury.__func__
    assert screen._recipe(config)["hybrid_bury"] is True


def test_decide_play_really_scores_expanded_ballot_and_runs_report(monkeypatch):
    from shengji.engine.combos import decompose
    rnd = play_state()
    b = CWVThrowComponentsBot(object(), config=CWVShortlistConfig(
        worlds=1, selection_worlds=30, alternatives=1))
    b.REPORT_FOLD_WORLDS = 30
    monkeypatch.setattr(b, "_means", lambda rnd, seat, actions, worlds: np.array([
        len(a) if len(decompose(a, rnd.ordering).components) > 1 else -1
        for a in actions], dtype=float))
    seen = []
    def rollout(rnd, seat, hands, buried, action, *args, **kwargs):
        seen.append(tuple(sorted(action)))
        return len(action)
    monkeypatch.setattr(b, "_rollout", rollout)
    chosen = b.decide_play(rnd, rnd.turn)
    record = b.last_decision_record
    detail = record["cwv_shortlist"]
    assert len(record["candidates"]) > 2
    assert record["candidates"] == detail["shortlist"]
    assert all(tuple(sorted(a)) in seen for a in record["candidates"])
    assert len(record["means"]) == len(record["candidates"])
    assert record["work"]["report_rollouts"] == 60
    assert chosen in record["candidates"]


def test_capped_cli_binds_throw_and_hybrid_recipe(tmp_path, monkeypatch):
    import json
    from shengji.train.screen_deadline import RECIPE
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64, identity=lambda: {})
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **kw: evaluator)
    seen = []
    monkeypatch.setattr(screen, "_run_pending", lambda config, *a, **kw: seen.append(config))
    out = tmp_path / "capped"
    assert screen.main([
        "--arm", "learned", "--checkpoint", "unused", "--worlds", "32",
        "--throw-components", "--hybrid-bury", "--baseline", "flat-shortlist",
        "--decision-deadline", "300", "--seed0", "200260914", "--out", str(out),
    ]) == 0
    stored = json.loads((out / "config.json").read_text())
    for config in (stored, seen[0]):
        recipe = screen._recipe(config)
        assert recipe["decision_deadline"] == RECIPE
        assert recipe["throw_components"] is True
        assert recipe["hybrid_bury"] is True
    uncapped = dict(stored)
    del uncapped["decision_deadline"]
    assert screen._recipe(uncapped) != screen._recipe(stored)


def test_deadline_spawn_factory_retains_arm_and_matching_bury(monkeypatch):
    from shengji.train.cwv_bury_policy import CWVBuryBot
    from shengji.train.cwv_throw_aware import CWVThrowComponentsBuryBot
    from shengji.train.screen_deadline import RECIPE
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64)
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **kw: evaluator)
    config = cfg("learned", checkpoint="unused", checkpoint_sha256="a" * 64,
                 baseline="flat-shortlist", throw_components=True, hybrid_bury=True,
                 decision_deadline=RECIPE)
    arm = screen._deadline_side(config, "arm", 17)
    baseline = screen._deadline_side(config, "baseline", 17)
    assert isinstance(arm, screen.CwvTimedPolicy)
    assert type(arm.bot) is CWVThrowComponentsBuryBot
    assert type(baseline.bot) is CWVBuryBot
    assert arm.bot.bury_arm == baseline.bot.bury_arm == "hybrid"
    assert arm.bot.REPORT_FOLD_WORLDS == baseline.bot.REPORT_FOLD_WORLDS
