from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_retention_census as CENSUS  # noqa: E402
import pair_ballot_retention_census_review as REVIEW  # noqa: E402


def _counts() -> dict:
    rows = CENSUS._empty_counts()
    rows["early"].update({
        "lead_states": 4_000_000,
        "lead_states_with_pairs": 3_000_000,
        "cap_saturated_states": 2_000_000,
        "pair_actions": 8_000_000,
        "missing_pair_states": 14_000,
        "missing_pair_actions": 19_000,
        "retention_repairs": 14_000,
    })
    rows["mid"].update({
        "lead_states": 8_000_000,
        "lead_states_with_pairs": 5_000_000,
        "cap_saturated_states": 3_000_000,
        "pair_actions": 12_000_000,
    })
    rows["late"].update({
        "lead_states": 6_000_000,
        "lead_states_with_pairs": 2_000_000,
        "cap_saturated_states": 1_000_000,
        "pair_actions": 5_000_000,
    })
    return rows


def _result() -> dict:
    return {
        "schema": CENSUS.SCHEMA,
        "git": REVIEW.SOURCE_GIT,
        "script_sha256": REVIEW.PRODUCER_SHA256,
        "host": REVIEW.EXPECTED_HOST,
        "python": REVIEW.EXPECTED_PYTHON,
        "fast_engine": True,
        "seed0": REVIEW.EXPECTED_SEED0,
        "games": REVIEW.EXPECTED_GAMES,
        "workers": REVIEW.EXPECTED_WORKERS,
        "chunks": REVIEW.EXPECTED_CHUNKS,
        "elapsed_seconds": 777.25,
        "counts": _counts(),
        "score_free": True,
        "outcomes_published": False,
        "strength_claim": False,
        "production_authority": False,
    }


def test_preserved_producer_is_byte_identical_and_score_free():
    assert REVIEW.producer_problems() == []
    rows = CENSUS._chunk(861_614, 1)
    assert set(rows) == set(CENSUS.BANDS)
    assert all(set(row) == set(CENSUS.FIELDS) for row in rows.values())
    assert sum(row["lead_states"] for row in rows.values()) > 0


def test_content_review_claim_grants_read_only_not_rerun_or_strength():
    claim = REVIEW.review_claim(reviewed_git="a" * 40)
    assert claim["content_read_authorized"] is True
    assert claim["rerun_authorized"] is False
    assert claim["score_free"] is True
    assert claim["strength_claim"] is False
    assert claim["production_promotion"] is False
    assert claim["production_deployment"] is False


def test_result_schema_closes_count_arithmetic_without_outcomes():
    assert REVIEW.result_problems(_result()) == []


@pytest.mark.parametrize(("mutate", "needle"), [
    (lambda value: value.__setitem__("utility", 1), "field set"),
    (lambda value: value.__setitem__("outcomes_published", True),
     "outcomes_published"),
    (lambda value: value.__setitem__("git", "0" * 40), "git"),
    (lambda value: value["counts"]["early"].__setitem__(
        "retention_repairs", 0), "repair count"),
    (lambda value: value["counts"]["early"].__setitem__(
        "missing_pair_actions", 1), "missing actions undercount"),
])
def test_result_mutations_refuse(mutate, needle):
    value = copy.deepcopy(_result())
    mutate(value)
    assert any(needle in problem for problem in REVIEW.result_problems(value))
