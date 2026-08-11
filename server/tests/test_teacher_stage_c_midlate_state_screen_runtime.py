from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_midlate_state_screen_runtime as RUNTIME  # noqa: E402


def _counters(accepted: int) -> dict:
    return {
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }


def test_evaluation_fold_reuses_iid_sampler_and_exact_logical_slots(
        monkeypatch) -> None:
    seen = []
    sampler = {
        "seed": 99, "requested": 300, "accepted": 300,
        "complete": True, "counters": _counters(300),
    }

    def draw(rnd, seat, count, seed, *, fold, ledger):
        seen.append(("draw", rnd, seat, count, seed, fold, ledger))
        full_sampler = {
            **sampler,
            "schema": RUNTIME.LABEL.SAMPLER_SCHEMA,
            "fold": "report",
            "accepted_draws": 300,
            "attempts": 300,
            "attempt_cap": 12_000,
            "world_key_sha256s": [f"{index:064x}" for index in range(300)],
            "world_keys_sha256": RUNTIME.LABEL.sha256_bytes(
                RUNTIME.LABEL.canonical_json(
                    [f"{index:064x}" for index in range(300)])),
            "unique_worlds": 300,
            "duplicate_draws_retained": 0,
            "prior_fold_overlap_draws_retained": 0,
            "sampling_with_replacement": True,
            "domain_separated_stream": True,
        }
        ledger.record_sampler("report", full_sampler)
        return object(), [object()] * 300, full_sampler

    def score(_bot, _rnd, state, worlds, indices, *, fold, ledger):
        seen.append(("score", state, worlds, indices, fold, ledger))
        for _index in indices:
            for _world in worlds:
                ledger.begin_candidate_world("report")
                ledger.finish_candidate_world("report")
        return {
            "worlds": 300,
            "candidate_worlds": 900,
            "actions": [{
                "logical_index": index,
                "candidate_index": index,
                "cards": state["candidates"][index]["cards"],
                "sources": state["candidates"][index]["sources"],
                "raw_attacker_points": [80.0] * 300,
                "signed_level_utility": [0.5] * 300,
                "mean_signed_level_utility": 0.5,
            } for index in indices],
        }

    monkeypatch.setattr(RUNTIME.LABEL, "draw_common_worlds", draw)
    monkeypatch.setattr(RUNTIME.LABEL, "score_actions", score)
    rnd = SimpleNamespace()
    result = RUNTIME.evaluation_fold(
        rnd, 2, [["HA"], ["S3"], ["H2"]], 99)
    assert result["schema"] == RUNTIME.SCREEN.EVALUATION_FOLD_SCHEMA
    assert result["candidate_worlds"] == 900
    assert result["work"]["total_candidate_worlds_attempted"] == 900
    assert result["work"]["total_candidate_worlds_completed"] == 900
    assert result["actions"][0]["cards"] == ["HA"]
    assert RUNTIME.SCREEN._logical_fold(
        result, [["HA"], ["S3"], ["H2"]], 99, attacker=True,
    )[0][0] == 0.5
    assert seen[0][1:6] == (rnd, 2, 300, 99, "report")
    assert seen[1][3:5] == ([0, 1, 2], "report")


def test_evaluation_fold_refuses_shared_sampler_failure(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise RUNTIME.LABEL.LabelRefused("underfilled")

    monkeypatch.setattr(RUNTIME.LABEL, "draw_common_worlds", refuse)
    with pytest.raises(RUNTIME.MidlateScreenRuntimeError,
                       match="shared Stage-C evaluation fold refused"):
        RUNTIME.evaluation_fold(
            SimpleNamespace(), 0, [["HA"], ["S3"], ["H2"]], 99)


def test_evaluation_fold_refuses_inexact_candidate_work(monkeypatch) -> None:
    sampler = {
        "seed": 99, "requested": 300, "accepted": 300,
        "complete": True, "counters": _counters(300),
    }

    def draw(_rnd, _seat, _count, _seed, *, fold, ledger):
        return object(), [object()] * 300, sampler

    def short(_bot, _rnd, state, _worlds, indices, *, fold, ledger):
        for _ in range(899):
            ledger.begin_candidate_world("report")
            ledger.finish_candidate_world("report")
        return {
            "worlds": 300, "candidate_worlds": 899,
            "actions": [{"logical_index": index,
                         "cards": state["candidates"][index]["cards"],
                         "signed_level_utility": [0.0] * 300}
                        for index in indices],
        }

    monkeypatch.setattr(RUNTIME.LABEL, "draw_common_worlds", draw)
    monkeypatch.setattr(RUNTIME.LABEL, "score_actions", short)
    with pytest.raises(RUNTIME.MidlateScreenRuntimeError, match="work drift"):
        RUNTIME.evaluation_fold(
            SimpleNamespace(), 0, [["HA"], ["S3"], ["H2"]], 99)
