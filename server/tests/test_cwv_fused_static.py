"""Fused card traversal preserves the existing MLP inputs and refusals."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from scripts.cwv_shortlist_cost import ScoreTrace
from scripts import cwv_prepared_lead_probe as probe
from shengji.ai import cwv_static_encoding as static
from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.engine.cards import Ordering
from shengji.rl.value_afterstate import ValueAfterstateError, tensors_from_round
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.luna.game import _state_snapshot
from tests.test_cwv_static_public import _state_after
from tests.test_world_shortlist import round_signature


@pytest.mark.parametrize("plies", [1, 35, 70])
def test_fused_inputs_cover_all_seats_history_depths_and_trumps(plies):
    original = _state_after(41, plies)
    assert original.phase == "play", "fixture must reach the requested live phase"
    for rank, suit in (("2", "S"), ("7", "H"), ("A", "D"), ("5", None)):
        rnd = copy.deepcopy(original)
        rnd.trump_rank, rnd.trump_suit, rnd.trump_is_nt = rank, suit, suit is None
        rnd.ordering = Ordering(suit, rank)
        before = round_signature(rnd)
        for seat in range(4):
            expected = tensors_from_round(rnd, seat)
            actual = static._fused_static_tensors(rnd, seat)
            assert actual is not None, "fixture must exercise fused path"
            for name in ("public", "world", "perspective"):
                assert np.array_equal(getattr(actual, name), getattr(expected, name)), name
            assert actual.history.shape == (1, expected.history.shape[1])
            assert not actual.history.any()
            if plies == 70:
                assert expected.public[511:531].any(), "late fixture must expose void facts"
        assert round_signature(rnd) == before


def test_fused_conservation_guard_catches_extra_public_card():
    # World tensors alone are still valid. Skipping the joint physical count
    # would accept this duplicate played card; this is not a world-count test.
    rnd = _state_after(61, 35)
    play = rnd.history[0].plays[0]
    play.cards.append(play.cards[0])
    assert static._fused_static_tensors(rnd, 0) is None
    with pytest.raises(ValueAfterstateError,
                       match="^afterstate violates physical deck conservation$"):
        static.tensors_from_round_static(rnd, 0)


@pytest.mark.parametrize("kind", ["no-history", "terminal", "missing-card", "unknown-card",
                                 "float-seat", "bad-declaration", "empty-event"])
def test_fused_fallback_preserves_preexisting_result_or_exact_exception(kind, monkeypatch):
    rnd = _state_after(61, 0 if kind == "no-history" else 100 if kind == "terminal" else 35)
    if kind == "terminal":
        assert rnd.phase == "round_end"
    if kind == "missing-card":
        rnd.hands[0].pop()
    elif kind == "unknown-card":
        rnd.hands[0][0] = "not-a-card"
    elif kind == "float-seat":
        rnd.history[0].plays[0].seat = float(rnd.history[0].plays[0].seat)
    elif kind == "bad-declaration":
        rnd.declaration = []
    elif kind == "empty-event":
        play = rnd.history[0].plays[0]
        rnd.hands[play.seat].extend(play.cards)
        play.cards.clear()
    assert static._fused_static_tensors(rnd, 0) is None

    def outcome():
        try:
            row = static.tensors_from_round_static(rnd, 0)
        except Exception as exc:
            return type(exc), str(exc)
        return tuple(getattr(row, name).tobytes()
                     for name in ("public", "history", "world", "perspective"))

    actual = outcome()
    monkeypatch.setattr(static, "_fused_static_tensors", lambda *_: None)
    assert outcome() == actual


def _model():
    import torch
    torch.manual_seed(19)
    return ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))


def test_evaluator_wiring_uses_fused_checks_not_second_card_traversal(monkeypatch):
    rnd = _state_after(61, 35)
    model = _model()
    expected = CompleteWorldEvaluator(None, model=model, encoding="reference").score([rnd], 0)

    def old_traversal(*_):
        raise AssertionError("second physical card traversal")

    monkeypatch.setattr(static, "_validate_complete_round", old_traversal)
    actual = CompleteWorldEvaluator(None, model=model, encoding="mlp-static").score([rnd], 0)
    assert np.array_equal(actual, expected)
    # This explicit disconnected-wiring mutation must fail in the consumer.
    monkeypatch.setattr(static, "_fused_static_tensors", lambda *_: None)
    with pytest.raises(AssertionError, match="^second physical card traversal$"):
        CompleteWorldEvaluator(None, model=model, encoding="mlp-static").score([rnd], 0)


def test_actual_shortlist_keeps_scores_batches_report_and_rng(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = _state_after(73, 40)
    before = round_signature(rnd)
    model = _model()
    fused = static._fused_static_tensors
    runs = []
    for enabled in (False, True):
        monkeypatch.setattr(static, "_fused_static_tensors", fused if enabled else lambda *_: None)
        trace = ScoreTrace(CompleteWorldEvaluator(None, model=model, encoding="mlp-static",
                                                 max_batch=13))
        bot = CWVShortlistBot(trace, seed=13, config=CWVShortlistConfig(
            worlds=2, selection_worlds=2, batch_size=17), reuse_successors=True)
        bot.REPORT_FOLD_WORLDS = 30
        played = bot.decide_play(rnd, rnd.turn)
        runs.append((played, trace.digest.hexdigest(), trace.batches, bot.rng.getstate(),
                     {k: v for k, v in bot.last_shortlist.items() if k != "wall_seconds"},
                     bot.last_decision_record["report_fold"], bot.shortlist_counts))
        assert round_signature(rnd) == before
    assert runs[0] == runs[1]


def test_probe_switches_only_encoder_and_restores_it_on_error():
    original = static._fused_static_tensors
    factory = probe.cwv_shortlist.WorldSuccessorCache
    with probe._optimization_context("fused-static", False):
        assert static._fused_static_tensors(None, 0) is None
        assert probe.cwv_shortlist.WorldSuccessorCache is factory
    assert static._fused_static_tensors is original
    with pytest.raises(RuntimeError, match="^interrupted diagnostic$"):
        with probe._optimization_context("fused-static", False):
            raise RuntimeError("interrupted diagnostic")
    assert static._fused_static_tensors is original
    with probe._optimization_context("fused-static", True):
        assert static._fused_static_tensors is original
        assert probe.cwv_shortlist.WorldSuccessorCache is factory
    with probe._optimization_context("prepared-lead", False):
        assert probe.cwv_shortlist.WorldSuccessorCache.keywords == {"prepare_leads": False}
        assert static._fused_static_tensors is original
    assert probe.cwv_shortlist.WorldSuccessorCache is factory


def test_probe_publishes_actual_consumer_parity_and_reopens_without_replay(
        tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    states = tmp_path / "states.json"
    states.write_text(json.dumps([_state_snapshot(_state_after(73, 40))]))
    evaluator = CompleteWorldEvaluator(None, model=_model(), encoding="mlp-static")
    monkeypatch.setattr(probe, "CompleteWorldEvaluator", lambda *a, **kw: evaluator)
    # Small source-wiring test, not a W32 performance receipt. The recorded
    # recipe must reflect this test budget and all scoring remains real.
    monkeypatch.setattr(probe, "CWVShortlistConfig", lambda **kw:
                        CWVShortlistConfig(worlds=2, selection_worlds=2))
    output = tmp_path / "probe"
    args = ["--states-json", str(states), "--checkpoint", str(tmp_path / "unused.pt"),
            "--out", str(output), "--repetitions", "1", "--optimization", "fused-static"]
    assert probe.main(args) == 0
    config = json.loads((output / "config.json").read_text())
    assert config["optimization"] == "fused-static"
    assert config["recipe"]["worlds"] == 2
    rows = [json.loads((output / f"r00-state-0000-{int(enabled)}.json").read_text())
            for enabled in (False, True)]
    assert [row["fused"] for row in rows] == [False, True]
    assert all(row["error"] is None for row in rows)
    assert rows[0]["semantic"] == rows[1]["semantic"]
    assert rows[0]["semantic"]["input_unchanged"]
    assert rows[0]["semantic"]["batches"]
    assert json.loads((output / "summary.json").read_text())["pairs_identical"] == 1

    def forbid_replay(*_):
        raise AssertionError("completed consumer must not replay")

    monkeypatch.setattr(probe.CWVShortlistBot, "decide_play", forbid_replay)
    assert probe.main(args) == 0
