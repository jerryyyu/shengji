"""Bounded witnesses for W32 proposal/prior coverage diagnostics."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.harvest.legal import enumerate_legal as real_enumerate_legal
from shengji.train import cwv_shortlist
from scripts import cwv_prior_coverage as C
from tests.test_world_shortlist import play_state


def test_prefix_ties_excludes_incumbent_and_deduplicates():
    actions = [["SA"], ["HK"], ["D2"], ["C3"], ["H2"]]
    # Incumbent is tied for the highest prior score, but is mandatory and does
    # not consume the requested comparison prefix.
    got = C.prior_prefix_indices(actions, [1, 1, 1, .5, .5], ["SA"], 2)
    assert got == [0, 2, 1]
    assert len(set(got)) == 3


def test_prefix_retention_has_known_positive_and_negative_directions():
    actions = [["SA"], ["HK"], ["D2"], ["C3"], ["H2"]]
    baseline = {C.action_key(actions[i]) for i in (1, 2)}
    positive = C.prior_prefix_indices(actions, [.0, .9, .8, .1, .0], actions[0], 2)
    negative = C.prior_prefix_indices(actions, [.0, .1, .0, .9, .8], actions[0], 1)
    assert len(baseline & {C.action_key(actions[i]) for i in positive}) == 2
    assert len(baseline & {C.action_key(actions[i]) for i in negative}) == 0


def test_hybrid_dedup_and_value_fill_keeps_incumbent():
    actions = [["SA"], ["HK"], ["D2"], ["C3"], ["H2"], ["S2"]]
    got = C.hybrid_indices(actions, [0, 9, 8, 1, 0, -1],
                           [0, 9, 0, 8, 7, 6], ["SA"])
    assert got == [0, 1, 2, 3, 4]
    assert len(got) == len(set(got)) == 5


def test_published_metric_counts_success_and_missed_best_exactly():
    actions = [["SA"], ["HK"], ["D2"], ["C3"], ["H2"]]
    common = dict(stage="test", prior_rank={1: 4, 2: 3, 3: 2, 4: 1},
                  value_rank={1: 1, 2: 2, 3: 3, 4: 4}, legal_count=5,
                  ranking_seconds=2.0, prior_seconds=.01)
    positive = C._metric(actions, [0, 1, 2], [1, 2], 1, **common)
    negative = C._metric(actions, [0, 3, 4], [1, 2], 1, **common)
    assert positive["top4_baseline_retention"] == 1.0
    assert positive["best_w32_alternative_retained"] is True
    assert negative["top4_baseline_retained"] == 0
    assert negative["top4_baseline_retention"] == 0.0
    assert negative["best_w32_alternative_retained"] is False
    assert negative["selected_value_ranks"] == [3, 4]


class _Cheap:
    def __init__(self):
        self.rows = 0

    def score(self, states, seat, **kwargs):
        self.rows += len(states)
        return np.arange(len(states), dtype=float)

    def identity(self):
        return {"kind": "cheap-test"}


class _Prior:
    def __init__(self, scores):
        self.scores = np.asarray(scores, dtype=float)
        self.calls = []

    def probabilities(self, rnd, seat, actions):
        self.calls.append((rnd, seat, len(actions)))
        return self.scores

    def identity(self):
        return {"kind": "prior-test"}


def test_actual_candidates_wiring_scores_full_legal_population_and_restores_input(monkeypatch):
    rnd = play_state()
    original_legal = real_enumerate_legal(rnd, rnd.turn, cap=None).actions
    # Keep the real production ballot and only constrain the diagnostic's
    # exhaustive population to a tiny valid witness.
    production = C.MCBot(seed=1)._candidates(rnd, rnd.turn)
    actions = production[:1] + [a for a in original_legal
                                if C.action_key(a) not in {C.action_key(production[0])}][:4]
    fake_legal = SimpleNamespace(actions=actions, count=len(actions))
    monkeypatch.setattr(C, "enumerate_legal", lambda *args, **kwargs: fake_legal)
    monkeypatch.setattr(cwv_shortlist, "enumerate_legal",
                        lambda *args, **kwargs: fake_legal)
    cheap = _Cheap()
    prior = _Prior([.1, .4, .2, .2, .1])
    before = C.digest(C._state_snapshot(rnd))
    row = C.analyze_snapshot(rnd and C._state_snapshot(rnd), evaluator=cheap,
                             prior_head=prior, seed=17, prefixes=(2,))
    assert row["status"] == "complete"
    assert row["legal_count"] == 5
    assert len(prior.calls) == 1
    assert prior.calls[0][1:] == (rnd.turn, 5)
    assert cheap.rows == 32 * 5
    assert row["state_hash"] == before


def _patch_tiny_legal(monkeypatch, rnd, count=5):
    original_legal = real_enumerate_legal(rnd, rnd.turn, cap=None).actions
    production = C.MCBot(seed=1)._candidates(rnd, rnd.turn)
    if count == 1:
        actions = production[:1]
    else:
        actions = production[:1] + [a for a in original_legal
                                    if C.action_key(a) != C.action_key(production[0])][:count - 1]
    fake_legal = SimpleNamespace(actions=actions, count=len(actions))
    monkeypatch.setattr(C, "enumerate_legal", lambda *args, **kwargs: fake_legal)
    monkeypatch.setattr(cwv_shortlist, "enumerate_legal",
                        lambda *args, **kwargs: fake_legal)
    return actions


def test_tractor_lock_lead_is_still_analyzed(monkeypatch):
    rnd = next(play_state(i) for i in range(20)
               if C.production_tractor_lock(play_state(i), play_state(i).turn))
    _patch_tiny_legal(monkeypatch, rnd)
    row = C.analyze_snapshot(C._state_snapshot(rnd), evaluator=_Cheap(),
                             prior_head=_Prior([.1, .4, .2, .2, .1]), seed=3,
                             prefixes=(2,))
    assert row["status"] == "complete"
    assert row["production_tractor_lock"] is True


def test_one_production_candidate_does_not_skip_when_legal_population_is_wide(monkeypatch):
    rnd = play_state()
    _patch_tiny_legal(monkeypatch, rnd)
    original = C.W32ProposalBot._candidates

    def one_production(self, state, seat):
        selected = original(self, state, seat)
        self.last_shortlist["production_count"] = 1
        return selected

    monkeypatch.setattr(C.W32ProposalBot, "_candidates", one_production)
    row = C.analyze_snapshot(C._state_snapshot(rnd), evaluator=_Cheap(),
                             prior_head=_Prior([.1, .4, .2, .2, .1]), seed=4,
                             prefixes=(2,))
    assert row["status"] == "complete"
    assert row["legal_count"] == 5


def test_true_single_legal_population_is_skipped(monkeypatch):
    rnd = play_state()
    _patch_tiny_legal(monkeypatch, rnd, count=1)
    prior = _Prior([1.0])
    row = C.analyze_snapshot(C._state_snapshot(rnd), evaluator=_Cheap(),
                             prior_head=prior, seed=5)
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "forced"
    assert not prior.calls


def _cli_inputs(tmp_path):
    value = tmp_path / "value.pt"
    prior = tmp_path / "prior.pt"
    panel = tmp_path / "panel.json"
    value.write_bytes(b"value")
    prior.write_bytes(b"prior")
    panel.write_text(json.dumps({"entries": [{"id": "root-0", "snapshot": {},
                                                "provenance": {"split": "fit"}}]}))
    return value, prior, panel


def test_cli_row_error_returns_nonzero_and_persists_status(tmp_path, monkeypatch):
    value, prior, panel = _cli_inputs(tmp_path)
    monkeypatch.setattr(C, "shared_evaluator", lambda *args, **kwargs: object())
    monkeypatch.setattr(C, "PublicPriorHead", lambda *args, **kwargs: object())
    monkeypatch.setattr(C, "analyze_snapshot", lambda *args, **kwargs:
                        (_ for _ in ()).throw(RuntimeError("synthetic")))
    out = tmp_path / "out"
    assert C.main(["--value-checkpoint", str(value), "--prior-checkpoint", str(prior),
                   "--panel", str(panel), "--out", str(out)]) == 1
    progress = json.loads((out / "progress.json").read_text())
    assert progress["status"] == "complete_with_errors"
    assert progress["completed_rows"] == 1


def test_cli_deadline_returns_nonzero(tmp_path, monkeypatch):
    value, prior, panel = _cli_inputs(tmp_path)
    monkeypatch.setattr(C, "shared_evaluator", lambda *args, **kwargs: object())
    monkeypatch.setattr(C, "PublicPriorHead", lambda *args, **kwargs: object())
    ticks = iter((0.0, 1.0))
    monkeypatch.setattr(C.time, "monotonic", lambda: next(ticks))
    out = tmp_path / "out"
    assert C.main(["--value-checkpoint", str(value), "--prior-checkpoint", str(prior),
                   "--panel", str(panel), "--out", str(out),
                   "--deadline-seconds", "0.5"]) == 1
    assert json.loads((out / "progress.json").read_text())["status"] == "deadline"


def test_truncated_prior_population_and_wrong_actor_refuse(monkeypatch):
    rnd = play_state()
    actions = real_enumerate_legal(rnd, rnd.turn, cap=None).actions[:3]
    with pytest.raises(C.PriorCoverageError, match="truncated"):
        C._prior_scores(_Prior([.3, .3, .4]), rnd, rnd.turn,
                        actions, legal_count=4)
    with pytest.raises(C.PriorCoverageError, match="root actor"):
        C._prior_scores(_Prior([1.0]), rnd, (rnd.turn + 1) % 4,
                        [actions[0]], legal_count=1)
