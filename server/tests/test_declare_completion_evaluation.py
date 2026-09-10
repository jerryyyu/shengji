from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from shengji.engine.round import Round
from shengji.train import declare_completion_evaluation as evaluation
from shengji.train.declare_completion import capture_observation


def _observation(*, seat=0, final=True, options=(), own_hand=()):
    return SimpleNamespace(
        seat=seat, rank="2", banker=0, deal_pos=100 if final else 20,
        final=final, own_hand=tuple(own_hand), shown=(),
        options=tuple(tuple(option) for option in options), passed=(),
    )


def _deal_round(seed=1, count=100):
    rnd = Round("2", 0, random.Random(seed))
    for _ in range(count):
        rnd.deal_next()
    return rnd


def test_baseline_uses_smartbot_scoring_and_returns_tuple():
    rnd = _deal_round(1)
    obs = capture_observation(rnd, 0, (), final=True)
    assert obs.options and evaluation.baseline_action(obs) == obs.options[0]

    # A legal but weak pair remains available while SmartBot waits.
    weak = _deal_round(22)
    weak_obs = capture_observation(weak, 0, (), final=True)
    assert weak_obs.options and evaluation.baseline_action(weak_obs) is None


def test_wait_during_deal_runs_every_future_card_callback(monkeypatch):
    rnd = _deal_round(9, 20)
    obs = _observation(final=False, seat=0, own_hand=tuple(rnd.hands[0]))
    calls = []

    class FakeBot:
        def decide_declare(self, current, seat, final=False):
            calls.append((seat, final, current._deal_pos, current.phase))
            return None

    monkeypatch.setattr(evaluation, "SmartBot", FakeBot)
    result = evaluation.finish_declarations(rnd, obs, None)

    assert result.phase == "bury"
    assert len(calls) == 84
    assert all(not final for _, final, _, _ in calls[:80])
    assert calls[79][2:] == (100, "declare")  # the last card is not skipped
    assert [seat for seat, final, _, _ in calls[80:] if final] == [0, 1, 2, 3]


def test_final_cursor_starts_after_current_seat(monkeypatch):
    rnd = _deal_round(12)
    obs = _observation(seat=1, final=True, own_hand=tuple(rnd.hands[1]))
    calls = []

    class FakeBot:
        def decide_declare(self, current, seat, final=False):
            calls.append((seat, final))
            return None

    monkeypatch.setattr(evaluation, "SmartBot", FakeBot)
    evaluation.finish_declarations(rnd, obs, None)
    assert calls == [(2, True), (3, True)]


class _CounterfactualRound:
    def __init__(self, seed):
        self.phase = "bury"
        self.seed = seed
        self.action = None


def test_evaluate_samples_once_per_seed_and_selects_better_action(monkeypatch):
    obs = _observation(options=(("S2",), ("H2",)), own_hand=("S2", "H2"))
    monkeypatch.setattr(evaluation, "baseline_action", lambda _: ("S2",))
    built = []

    def sample(_, seed):
        built.append(seed)
        return _CounterfactualRound(seed)

    def finish(rnd, _, action):
        rnd.action = action
        return rnd

    monkeypatch.setattr(evaluation, "build_sampled_prefix", sample)
    monkeypatch.setattr(evaluation, "finish_declarations", finish)
    seen = []

    def score(rnd, *, focal_team, seed):
        assert rnd.phase == "bury"
        seen.append((rnd.seed, rnd.action, focal_team, seed))
        return {"focal_signed_levels":
                2 if rnd.action == ("H2",) else 0,
                "focal_won": rnd.action == ("H2",), "kitty_bonus": 4}

    report = evaluation.evaluate_actions(obs, seeds=(31, 47), evaluator=score)
    assert built == [31, 47]
    assert [entry["action"] for entry in report["actions"]] == [
        ["S2"], None, ["H2"]]
    assert report["selected_action"] == ["H2"]
    assert len(seen) == 6
    assert all(entry[2] == 0 for entry in seen)
    assert all(entry[0] == entry[3] for entry in seen)
    assert all(row["metrics"]["kitty_bonus"] == 4
               for result in report["actions"] for row in result["rows"])


def test_baseline_first_tie_and_no_option_wait(monkeypatch):
    obs = _observation(options=(("S2",), ("H2",)))
    monkeypatch.setattr(evaluation, "baseline_action", lambda _: ("S2",))
    monkeypatch.setattr(evaluation, "build_sampled_prefix",
                        lambda _, seed: _CounterfactualRound(seed))
    monkeypatch.setattr(evaluation, "finish_declarations",
                        lambda rnd, _, action: rnd)
    report = evaluation.evaluate_actions(
        obs, seeds=(5,), evaluator=lambda *_args, **_kwargs: {
            "focal_signed_levels": 1, "focal_won": False, "kitty_bonus": 0})
    assert report["selected_action"] == ["S2"]

    empty = _observation(options=())
    monkeypatch.setattr(evaluation, "baseline_action", lambda _: None)
    report = evaluation.evaluate_actions(
        empty, seeds=(5,), evaluator=lambda *_args, **_kwargs: {
            "focal_signed_levels": 0, "focal_won": False, "kitty_bonus": 0})
    assert report["actions"] == [{"action": None,
                                   "rows": [{"seed": 5, "metrics": {
                                       "focal_signed_levels": 0,
                                       "focal_won": False,
                                       "kitty_bonus": 0}}],
                                   "mean_signed_levels": 0.0}]


def test_duplicate_or_empty_seeds_and_invalid_action_refused():
    obs = _observation(options=(("S2",),))
    with pytest.raises(ValueError):
        evaluation.evaluate_actions(obs, seeds=(), evaluator=lambda *_a, **_k: {})
    with pytest.raises(ValueError):
        evaluation.evaluate_actions(obs, seeds=(1, 1), evaluator=lambda *_a, **_k: {})

    rnd = _deal_round(1)
    with pytest.raises(ValueError):
        evaluation.finish_declarations(rnd, _observation(options=()), ("S2",))


def test_nonfinite_signed_levels_refused_before_selection(monkeypatch):
    obs = _observation(options=())
    monkeypatch.setattr(evaluation, "baseline_action", lambda _: None)
    monkeypatch.setattr(evaluation, "build_sampled_prefix",
                        lambda _, seed: _CounterfactualRound(seed))
    monkeypatch.setattr(evaluation, "finish_declarations",
                        lambda rnd, _, action: rnd)
    with pytest.raises(ValueError, match="finite number"):
        evaluation.evaluate_actions(
            obs, seeds=(5,), evaluator=lambda *_args, **_kwargs: {
                "focal_signed_levels": float("nan"),
                "focal_won": False, "kitty_bonus": 0})
