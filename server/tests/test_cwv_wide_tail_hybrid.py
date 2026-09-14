"""Screen wiring tests for the opt-in full-completion hybrid bury arm."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_bury_policy import CWVBuryBot, CWVBuryConfig
from shengji.train.cwv_wide_tail import CWVWideTailBot, CWVWideTailConfig


def _config(**overrides):
    config = {
        "schema": "cwv-shortlist-config-v1", "arm": "learned",
        "checkpoint": "checkpoint.pt", "checkpoint_sha256": "sha",
        "shortlist": {"worlds": 32, "selection_worlds": 30,
                       "alternatives": 4, "batch_size": 128, "uniform": False},
        "report_worlds": 300, "production_multiplier": 1,
        "target_wall_multiplier": 1, "seed0": 17, "clusters": 1,
        "baseline": "flat-shortlist", "hybrid_bury": True,
    }
    config.update(overrides)
    return config


class _Evaluator:
    checkpoint_sha256 = "sha"

    def score(self, positions, _seat, **_kwargs):
        return [0.0] * len(positions)


def _bind_evaluator(monkeypatch):
    monkeypatch.setattr(S, "shared_evaluator", lambda *_a, **_k: _Evaluator())


def test_hybrid_wide_factory_uses_bury_first_mro_and_flat_bury_baseline(monkeypatch):
    _bind_evaluator(monkeypatch)
    config = _config(wide_tail={"threshold": 10_000, "coarse_worlds": 2, "pool": 256})
    arm = S.make_side(config, "arm", 17)
    baseline = S.make_side(config, "baseline", 17)

    assert type(arm) is S.CWVWideTailBuryBot
    assert type(baseline) is CWVBuryBot
    assert S.CWVWideTailBuryBot.__bases__ == (CWVBuryBot, CWVWideTailBot)
    assert S.CWVWideTailBuryBot.__mro__[1:3] == (CWVBuryBot, CWVWideTailBot)
    assert arm.decide_bury.__func__ is CWVBuryBot.decide_bury
    assert arm._candidates.__func__ is CWVWideTailBot._candidates
    assert baseline.decide_bury.__func__ is CWVBuryBot.decide_bury
    assert arm.bury_arm == baseline.bury_arm == "hybrid"
    assert arm.serving_budget_seconds is baseline.serving_budget_seconds is None
    assert arm.bury_config == baseline.bury_config == CWVBuryConfig()
    assert arm.wide_tail_config == CWVWideTailConfig()


def test_normal_wide_factory_and_methods_remain_unchanged(monkeypatch):
    _bind_evaluator(monkeypatch)
    config = _config(hybrid_bury=False,
                     wide_tail={"threshold": 10_000, "coarse_worlds": 2, "pool": 256})
    arm = S.make_side(config, "arm", 17)
    assert type(arm) is CWVWideTailBot
    assert not hasattr(arm, "bury_arm")
    assert CWVWideTailBot._candidates is not CWVBuryBot._candidates
    assert arm._candidates.__func__ is CWVWideTailBot._candidates


@pytest.mark.parametrize("bad", [
    {"arm": "uniform"},
    {"baseline": "production"},
    {"double_shortlist": {"mode": "learned"}},
])
def test_programmatic_hybrid_config_refuses_invalid_combinations(monkeypatch, bad):
    _bind_evaluator(monkeypatch)
    config = _config(**bad)
    with pytest.raises(ValueError, match="hybrid-bury requires learned"):
        S.make_side(config, "arm", 17)


def test_programmatic_hybrid_refuses_custom_wide_recipe(monkeypatch):
    _bind_evaluator(monkeypatch)
    config = _config(wide_tail={"threshold": 9_999, "coarse_worlds": 2, "pool": 256})
    with pytest.raises(ValueError, match="default wide-tail recipe"):
        S.make_side(config, "arm", 17)


def test_recipe_and_summary_bind_full_completion_hybrid(monkeypatch):
    config = _config(wide_tail={"threshold": 10_000, "coarse_worlds": 2, "pool": 256})
    assert S._recipe(config)["hybrid_bury"] is True

    monkeypatch.setattr(S.duel, "summarize", lambda *_a, **_k: {
        "arm": "learned", "arm_description": "old",
        "work_totals": {"arm": {}, "baseline": {}},
    })
    result = S.summary_for([{"records": []}], config)
    assert "full-completion hybrid bury on both sides" in result["arm_description"]
    assert result["hybrid_bury"] == {
        "arm": "hybrid", "scope": "both sides",
        "serving_budget_seconds": None, "completion": "full",
    }
    assert "not Fly 2s serving-budget parity" in result["work_caveat"]


def test_cli_persists_hybrid_bury_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *_a, **_k: SimpleNamespace(
        checkpoint_sha256="sha", identity=lambda: {"checkpoint": "checkpoint.pt"}))
    seen = []
    monkeypatch.setattr(S, "_run_pending",
                        lambda config, pending, *_a, **_k: seen.append(config))
    out = tmp_path / "screen"
    assert S.main([
        "--arm", "learned", "--checkpoint", "checkpoint.pt",
        "--baseline", "flat-shortlist", "--hybrid-bury", "--worlds", "32",
        "--clusters", "1", "--workers", "1", "--seed0", "17", "--out", str(out),
    ]) == 0
    assert seen[0]["hybrid_bury"] is True
    assert json.loads((out / "config.json").read_text())["hybrid_bury"] is True


@pytest.mark.parametrize("extra", [
    ["--arm", "uniform", "--baseline", "flat-shortlist"],
    ["--arm", "learned", "--checkpoint", "checkpoint.pt"],
    ["--arm", "learned", "--checkpoint", "checkpoint.pt",
     "--baseline", "flat-shortlist", "--inner-mode", "learned"],
])
def test_cli_hybrid_refuses_invalid_combinations(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        S.main([*extra, "--hybrid-bury", "--seed0", "17", "--out", str(tmp_path)])


def test_bury_witness_uses_shared_inherited_decision_and_preserves_play_rng(
        monkeypatch):
    # Reuse the real declared-round fixture from the existing bury policy tests.
    from test_cwv_bury_policy import _bury_state
    rnd = _bury_state(23)
    _bind_evaluator(monkeypatch)
    config = _config(wide_tail={"threshold": 10_000, "coarse_worlds": 2, "pool": 256})
    bots = [S.make_side(config, side, 17) for side in ("arm", "baseline")]
    calls = []

    def counted(self, current, seat, **_kwargs):
        calls.append(type(self))
        from shengji.ai.smart import SmartBot
        return SmartBot().decide_bury(current, seat)

    monkeypatch.setattr(CWVBuryBot, "_decide_bury", counted)
    states = [bot.rng.getstate() for bot in bots]
    for bot in bots:
        assert bot.decide_bury(rnd, rnd.banker)
    assert calls == [S.CWVWideTailBuryBot, CWVBuryBot]
    assert [bot.rng.getstate() for bot in bots] == states
