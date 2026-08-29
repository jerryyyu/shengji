"""Boundary tests for the score-free pair-aware root-dose census."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import pair_aware_rollout_root_dose as DOSE  # noqa: E402


RESULT = Path(__file__).parent / "data/pair_aware_rollout_root_dose.v1.json"


def test_phase_band_covers_exact_round_without_overlap():
    assert [DOSE.phase_band(index) for index in range(25)] == (
        ["early"] * 8 + ["mid"] * 9 + ["late"] * 8
    )
    with pytest.raises(DOSE.DoseRefused):
        DOSE.phase_band(-1)
    with pytest.raises(DOSE.DoseRefused):
        DOSE.phase_band(25)
    with pytest.raises(DOSE.DoseRefused):
        DOSE.phase_band(True)


def test_score_free_validator_rejects_outcome_fields_recursively():
    safe = {
        "point_pair_triggers": 3,
        "rows": [{"root_action_changed": True, "accepted_worlds": 330}],
    }
    DOSE._assert_score_free(safe)
    for key in sorted(DOSE.SCORE_FIELDS):
        bad = copy.deepcopy(safe)
        bad["rows"].append({key: 0})
        with pytest.raises(DOSE.DoseRefused, match="outcome fields"):
            DOSE._assert_score_free(bad)


def test_cell_completion_requires_every_role_and_phase():
    counts = {
        (phase, role): 2
        for phase in DOSE.PHASES for role in DOSE.ROLES
    }
    assert DOSE._all_cells_full(counts, 2)
    counts[("late", "defender")] = 1
    assert not DOSE._all_cells_full(counts, 2)


def test_evaluate_state_same_seed_preserves_root_ballot_and_exact_work():
    rnd, _ = DOSE._start_round(333_123_456)
    seat = rnd.turn
    assert seat is not None
    row = DOSE.evaluate_state(rnd, seat, decision_seed=991_123_456)
    assert row["root_candidate_count"] >= 1
    assert row["work"]["sample_attempts"] == (
        row["work"]["accepted_worlds"] + row["work"]["failed_worlds"]
    )
    assert row["treatment_dose"]["mode"] == "treatment"
    assert row["matched_null_dose"]["mode"] == "matched_null"
    assert row["public_state_sha256"] == DOSE._public_state_digest(rnd, seat)


def test_public_digest_ignores_other_hands_but_binds_actor_hand():
    rnd, _ = DOSE._start_round(333_654_321)
    seat = rnd.turn
    assert seat is not None
    baseline = DOSE._public_state_digest(rnd, seat)
    other = next(index for index in range(4) if index != seat)
    mutated = copy.deepcopy(rnd)
    mutated.hands[other][0] = (
        "BJ" if mutated.hands[other][0] != "BJ" else "LJ"
    )
    assert DOSE._public_state_digest(mutated, seat) == baseline
    mutated.hands[seat] = list(reversed(mutated.hands[seat]))
    # Canonical sorting makes list order irrelevant; card identity still binds.
    assert DOSE._public_state_digest(mutated, seat) == baseline
    mutated.hands[seat][0] = "BJ" if mutated.hands[seat][0] != "BJ" else "LJ"
    assert DOSE._public_state_digest(mutated, seat) != baseline


def test_exclusive_writer_refuses_overwrite(tmp_path: Path):
    target = tmp_path / "dose.json"
    DOSE.write_exclusive(target, {"schema": DOSE.SCHEMA})
    with pytest.raises(DOSE.DoseRefused, match="overwrite"):
        DOSE.write_exclusive(target, {"schema": DOSE.SCHEMA})


def test_preserved_air_census_is_score_free_and_recomputes_exactly():
    raw = RESULT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "e530da6a55e53cb29f941a4b539870d15b45bb279d8265f72a6276b80cfbbbb8"
    )
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert DOSE.stable_digest(payload) == internal == (
        "1914ef6d8db4ef3da2db6896962093a31884a6dafd6440d8e9ed1962c19f398f"
    )
    DOSE._assert_score_free(payload)
    rows = payload["rows"]
    assert len(rows) == len({row["state_id"] for row in rows}) == 24
    assert payload["aggregate"] == {
        "accepted_worlds": 7590,
        "cell_counts": {
            "early_attacker": 4,
            "early_defender": 4,
            "late_attacker": 4,
            "late_defender": 4,
            "mid_attacker": 4,
            "mid_defender": 4,
        },
        "elapsed_seconds": 32.61224741698243,
        "matched_null_triggered_states": 17,
        "matched_null_triggers": 4833,
        "root_action_changes": 1,
        "searched_states": 23,
        "searches": 23,
        "states": 24,
        "treatment_triggered_states": 17,
        "treatment_triggers": 4038,
    }
    changed = [row for row in rows if row["root_action_changed"]]
    assert [(row["state_id"], row["matched_null_action"],
             row["treatment_action"]) for row in changed] == [
        ("333000000:3:1", ["CA"], ["H10", "H10"]),
    ]
