"""Integration witnesses for isolation of the opt-in CWV search modes."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_corrected_rollout import CWVCorrectedRolloutBot
from shengji.train.cwv_shortlist import CWVShortlistBot
from shengji.train.cwv_throw_aware import CWVThrowComponentsBot
from shengji.train.cwv_wide_tail import CWVWideTailBot, CWVWideTailConfig
from tests.test_cwv_shortlist_screen import cfg


def _evaluator(monkeypatch):
    evaluator = SimpleNamespace(checkpoint_sha256="sha")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: evaluator)


def test_each_opt_in_selects_its_actual_arm_and_keeps_flat_baseline(monkeypatch):
    _evaluator(monkeypatch)
    common = dict(arm="learned", checkpoint="m.pt", checkpoint_sha256="sha",
                  baseline="flat-shortlist")

    throw = cfg(**common, throw_components=True)
    assert type(S.make_side(throw, "arm", 17)) is CWVThrowComponentsBot
    assert type(S.make_side(throw, "baseline", 17)) is CWVShortlistBot

    corrected = cfg(**common, corrected_rollout={
        "mode": "corrected", "correction_worlds": 2, "residual_worlds": 1})
    assert type(S.make_side(corrected, "arm", 17)) is CWVCorrectedRolloutBot
    assert type(S.make_side(corrected, "baseline", 17)) is CWVShortlistBot

    wide = cfg(**common, shortlist={"worlds": 32, "selection_worlds": 30,
                                    "alternatives": 4, "batch_size": 128,
                                    "uniform": False},
               wide_tail=asdict(CWVWideTailConfig()))
    assert type(S.make_side(wide, "arm", 17)) is CWVWideTailBot
    assert type(S.make_side(wide, "baseline", 17)) is CWVShortlistBot


@pytest.mark.parametrize("extra", [
    {"throw_components": True},
    {"corrected_rollout": {"mode": "corrected", "correction_worlds": 2,
                            "residual_worlds": 1}},
])
def test_wide_tail_refuses_other_admission_modes_on_both_sides(extra, monkeypatch):
    _evaluator(monkeypatch)
    config = cfg("learned", checkpoint="m.pt", checkpoint_sha256="sha",
                 baseline="flat-shortlist",
                 shortlist={"worlds": 32, "selection_worlds": 30,
                            "alternatives": 4, "batch_size": 128,
                            "uniform": False},
                 wide_tail=asdict(CWVWideTailConfig()), **extra)
    for side in ("arm", "baseline"):
        with pytest.raises(ValueError):
            S.make_side(config, side, 17)


def test_mode_fields_bind_distinct_recipe_identities():
    base = cfg("learned", checkpoint="m.pt", checkpoint_sha256="sha",
               baseline="flat-shortlist")
    throw = dict(base, throw_components=True)
    wide = dict(base, wide_tail=asdict(CWVWideTailConfig()))
    assert S._recipe(throw) != S._recipe(base)
    assert S._recipe(wide) != S._recipe(base)
    assert S._recipe(throw) != S._recipe(wide)


@pytest.mark.parametrize("mode,description", [
    ("corrected", "model-corrected shared-world rollout shortlist"),
    ("levels", "levels-only shared-world rollout shortlist"),
])
def test_hybrid_summary_preserves_rollout_mode(monkeypatch, mode, description):
    monkeypatch.setattr(S.duel, "summarize", lambda *_a, **_k: {})
    config = cfg("learned", baseline="flat-shortlist", hybrid_bury=True,
                 corrected_rollout={"mode": mode, "correction_worlds": 2,
                                    "residual_worlds": 1})
    result = S.summary_for([], config)
    assert result["arm_description"] == (
        description + "; full-completion hybrid bury on both sides")
    assert result["baseline_description"] == "flat-shortlist"
