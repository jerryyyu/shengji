from __future__ import annotations

import copy
import importlib.util
import json
import random
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay


SCRIPT = Path(__file__).parents[1] / "scripts" / \
    "s5_final_champion_replay.py"
SPEC = importlib.util.spec_from_file_location("s5_final_champion_replay", SCRIPT)
assert SPEC and SPEC.loader
s5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s5)


def _late_losing_state() -> Round:
    """Seat two's teammate led; opponent one owns the trick with the ace."""
    rnd = Round("2", 0, random.Random(31))
    rnd.trump_suit = "S"
    rnd.trump_is_nt = False
    rnd.ordering = Ordering("S", "2")
    rnd.phase = "play"
    rnd.turn = 2
    rnd.hands = [["C3"], ["C4"], ["H5", "H3"], ["C5"]]
    rnd.trick = Trick(leader=0, plays=[
        TrickPlay(0, ["H3"]),
        TrickPlay(1, ["HA"]),
    ])
    return rnd


class _Champion:
    def __init__(self, *, complete: bool = True):
        self.complete = complete
        self.last_decision_record = None

    def _current_winner(self, rnd):
        return HeuristicBot()._current_winner(rnd)

    def _candidates(self, _rnd, _seat):
        return [["H5"], ["H3"]]

    def decide_play(self, _rnd, _seat):
        selection = 60 if self.complete else 10
        report = 600 if self.complete else 0
        self.last_decision_record = {
            "policy": s5.CHAMPION,
            "candidates": [["H5"], ["H3"]],
            "played": ["H5"],
            "played_index": 0,
            "raw_winner_index": 1,
            "reason": ("report_lcb_below_min_gain" if self.complete
                       else "selection_underfilled"),
            "work": {
                "selection_rollouts": selection,
                "report_rollouts": report,
                "total_rollouts": selection + report,
                "complete": self.complete,
            },
            "sampler_counters": {"delta": {
                "sample_attempts": 30,
                "accepted_worlds": 30 if self.complete else 5,
                "failed_worlds": 0,
                "rejected_worlds": 0,
                "impossible_worlds": 0,
            }},
        }
        return ["H5"]


def _factory(*_args, complete: bool = True, **_kwargs):
    return _Champion(complete=complete)


def _design() -> dict:
    return s5.build_design()


def _decision(witness: str, replicate: int, *, donated: bool = True,
              complete: bool = True) -> dict:
    target = next(row for row in _design()["selection"]["target_witnesses"]
                  if row["witness_sha256"] == witness)
    chosen = 5 if donated else 0
    minimum = 0
    candidate_count = 2
    selection = 60 if complete else 10
    report = 600 if complete else 0
    return {
        "witness_sha256": witness,
        "replicate": replicate,
        "seed": s5.seed_for(witness, replicate),
        "role": target["role"],
        "follow_position": target["follow_position"],
        "candidate_count": candidate_count,
        "candidate0_card_points": chosen,
        "chosen_card_points": chosen,
        "minimum_legal_card_points": minimum,
        "minimum_ballot_card_points": minimum,
        "avoidable_legal_point_delta": chosen - minimum,
        "avoidable_ballot_point_delta": chosen - minimum,
        "played_index": 0,
        "raw_winner_index": 1,
        "reason": ("report_lcb_below_min_gain" if complete
                   else "selection_underfilled"),
        "donated_points": donated,
        "lower_point_action_on_ballot": donated,
        "selection_rollouts": selection,
        "report_rollouts": report,
        "total_rollouts": selection + report,
        "work_complete": complete,
        "sampler_counters": {
            "accepted_worlds": 30 if complete else 5,
            "failed_worlds": 0,
            "impossible_worlds": 0,
            "rejected_worlds": 0,
            "sample_attempts": 30,
        },
    }


def _all_decisions(*, donated: bool = True) -> list[dict]:
    return [
        _decision(witness, replicate, donated=donated)
        for witness in s5.TARGET_WITNESSES
        for replicate in range(s5.SEEDS_PER_TARGET)
    ]


def _result(*, donated: bool = True) -> dict:
    design = _design()
    return s5.build_result(
        design,
        {"git": "a" * 40, "script_sha256": "b" * 64,
         "tree_dirty": False},
        {"python": "3.14", "implementation": "CPython", "machine": "arm64",
         "fast_engine": True, "fast_binary_sha256": "c" * 64,
         "live_parent_sha256": "d" * 64},
        {"manifest_sha256": s5.SOURCE_MANIFEST_SHA256, "member_count": 30,
         "total_bytes": 123, "members_commitment_sha256": "e" * 64,
         "source_names_published": False},
        _all_decisions(donated=donated),
    )


def test_design_freezes_reviewed_late_surface_and_seed_schedule() -> None:
    design = _design()
    assert s5.design_problems(design) == []
    assert design["selection"]["target_count"] == 10
    assert design["rng"]["total_decisions"] == 320
    assert [row["follow_position"]
            for row in design["selection"]["target_witnesses"]] == \
        [4, 4, 3, 4, 4, 4, 3, 4, 4, 4]
    seeds = {
        s5.seed_for(witness, replicate)
        for witness in s5.TARGET_WITNESSES
        for replicate in range(s5.SEEDS_PER_TARGET)
    }
    assert len(seeds) == 320


def test_design_and_result_publication_schemas_fail_closed() -> None:
    design = _design()
    mutated = copy.deepcopy(design)
    mutated["selection"]["target_witnesses"][0]["cards"] = ["H5"]
    mutated_without_hash = dict(mutated)
    mutated_without_hash.pop("design_sha256")
    mutated["design_sha256"] = s5.sha256_bytes(
        s5.canonical_json(mutated_without_hash))
    assert any("target_witnesses[0] fields differ" in problem
               for problem in s5.design_problems(mutated))

    result = _result()
    leaked = copy.deepcopy(result)
    leaked["decisions"][0]["hand"] = ["H5", "H3"]
    leaked_without_hash = dict(leaked)
    leaked_without_hash.pop("result_sha256")
    leaked["result_sha256"] = s5.sha256_bytes(
        s5.canonical_json(leaked_without_hash))
    assert any("decisions[0] fields differ" in problem
               for problem in s5.result_problems(leaked, design))


def test_final_champion_row_uses_final_action_and_exact_work() -> None:
    witness = s5.TARGET_WITNESSES[0]
    row = s5._decision_row(
        _late_losing_state(), 2, witness, 0, bot_factory=_factory)
    assert row["chosen_card_points"] == 5
    assert row["minimum_legal_card_points"] == 0
    assert row["donated_points"] is True
    assert row["lower_point_action_on_ballot"] is True
    assert row["played_index"] == 0
    assert row["raw_winner_index"] == 1
    assert row["work_complete"] is True
    assert row["total_rollouts"] == 660


def test_incomplete_production_fallback_is_retained_as_learning() -> None:
    witness = s5.TARGET_WITNESSES[0]

    def factory(*_args, **_kwargs):
        return _Champion(complete=False)

    row = s5._decision_row(
        _late_losing_state(), 2, witness, 0, bot_factory=factory)
    assert row["reason"] == "selection_underfilled"
    assert row["work_complete"] is False
    assert row["total_rollouts"] == 10
    assert row["donated_points"] is True


def test_result_recomputes_schedule_statistics_and_decision() -> None:
    design = _design()
    result = _result()
    assert s5.result_problems(result, design) == []
    assert result["stats"]["donation_decisions"] == 320
    assert result["stats"]["donation_witnesses"] == 10
    assert result["decision"] == "S5_RANKING_TREATMENT_DESIGN_ELIGIBLE"

    clean = _result(donated=False)
    assert clean["decision"] == \
        "S5_CURRENT_CHAMPION_NOT_REPRODUCED_ON_FROZEN_DEV"

    forged = copy.deepcopy(result)
    forged["decisions"][0]["seed"] += 1
    forged_without_hash = dict(forged)
    forged_without_hash.pop("result_sha256")
    forged["result_sha256"] = s5.sha256_bytes(
        s5.canonical_json(forged_without_hash))
    assert any("seed derivation drift" in problem
               for problem in s5.result_problems(forged, design))


def test_review_marker_is_exact_and_one_shot(tmp_path: Path) -> None:
    design = _design()
    git = "a" * 40
    marker = {
        "schema": "s5-final-champion-replay-review-v1",
        "git": git,
        "script_sha256": s5.sha256_file(SCRIPT),
        "census_artifact_sha256": s5.CENSUS_SHA256,
        "design_sha256": design["design_sha256"],
        "target_count": 10,
        "seeds_per_target": 32,
        "total_decisions": 320,
        "final_champion_action_replayed": True,
        "partner_already_acted_only": True,
        "closed_public_schema": True,
        "one_diagnostic_execution_authorized": True,
        "strength_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }
    record = tmp_path / "review.md"
    census_marker = {
        "artifact_sha256": s5.CENSUS_SHA256,
        "bot_follow_rows": 4363,
        "design_authorized": True,
        "lower_point_on_current_ballot": 57,
        "producer_git": "2351b3643a5c0231ad829b9d1cff6f96e50d035f",
        "production_deployment": False,
        "production_promotion": False,
        "reproduced_by_current_surface": 16,
        "rounds_replayed": 122,
        "schema": "s5-point-protection-census-review-v1",
        "score_free": True,
        "source_manifest_sha256": s5.SOURCE_MANIFEST_SHA256,
        "strength_execution_authorized": False,
        "structural_triggers": 58,
        "training_authorized": False,
        "verdict": "PASS",
    }
    census_line = s5.CENSUS_REVIEW_PREFIX + json.dumps(
        census_marker, sort_keys=True, separators=(",", ":")) + "\n"
    assert s5.sha256_bytes(census_line.encode()) == \
        s5.CENSUS_REVIEW_MARKER_SHA256
    record.write_text(census_line + s5.REVIEW_PREFIX + json.dumps(
        marker, sort_keys=True, separators=(",", ":")) + "\n")
    assert s5._census_review_marker(record) == census_marker
    assert s5._review_marker(record, expected_git=git, design=design) == marker

    record.write_text(record.read_text() + record.read_text())
    with pytest.raises(s5.ReplayRefused, match="exactly one"):
        s5._review_marker(record, expected_git=git, design=design)
