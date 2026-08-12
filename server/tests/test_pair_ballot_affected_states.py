from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_states as CAPTURE  # noqa: E402


@pytest.fixture(scope="module")
def witness() -> dict:
    rows = CAPTURE._deal_rows(861_614)
    assert len(rows) == 1
    return rows[0]


def test_named_opening_pair_omission_becomes_exact_replay_asset(witness):
    assert witness["state_id"] == "861614:0:1"
    assert witness["band"] == "early"
    assert witness["search_eligible"] is True
    assert witness["missing_pairs"] == [
        ["C2", "C2"], ["D2", "D2"], ["D5", "D5"],
        ["DA", "DA"], ["DK", "DK"], ["LJ", "LJ"],
    ]
    assert witness["current_ballot"][0] == witness["retained_ballot"][0]
    assert len(witness["current_ballot"]) == \
        len(witness["retained_ballot"]) == 14
    rnd = CAPTURE.replay_state(witness)
    assert rnd.turn == witness["seat"]
    assert len(rnd.history) == witness["trick"]


def test_replay_record_contains_no_outcomes_or_materialized_hidden_hands(witness):
    encoded = json.dumps(witness, sort_keys=True)
    for forbidden in (
            '"utility"', '"score"', '"winner"', '"attacker_points"',
            '"hands"', '"kitty"'):
        assert forbidden not in encoded
    assert witness["replay"]["setup"]["buried"]
    # The replay seed/deck/history reconstructs the state for later evaluation,
    # but the row does not attach a materialized hand view or outcome value.
    assert set(witness["replay"]) == {
        "schema", "seed", "split", "trick", "role", "seat", "ply",
        "setup", "plays",
    }


def test_search_reachability_matches_the_real_tractor_lock(witness):
    rnd = CAPTURE.replay_state(witness)
    bot = CAPTURE.make_bot("mc", seed=0)
    assert CAPTURE.search_reachable(bot, rnd, witness["seat"]) is True

    bot.canonical_lead = lambda _rnd, _seat: ["H5", "H5", "H6", "H6"]
    assert CAPTURE.search_reachable(bot, rnd, witness["seat"]) is False


@pytest.mark.parametrize(("mutate", "needle"), [
    (lambda row: row["current_ballot"].pop(), "digest"),
    (lambda row: row.__setitem__("split", "report"), "digest"),
    (lambda row: row["missing_pairs"].clear(), "digest"),
    (lambda row: row["replay"].__setitem__("seat", 3), "digest"),
])
def test_mutated_state_refuses_before_replay(witness, mutate, needle):
    bad = copy.deepcopy(witness)
    mutate(bad)
    with pytest.raises(CAPTURE.CaptureRefused, match=needle):
        CAPTURE.replay_state(bad)


def test_rehashed_structural_mutations_still_refuse(witness):
    bad = copy.deepcopy(witness)
    bad["current_ballot"].pop()
    body = dict(bad)
    body.pop("state_sha256")
    bad["state_sha256"] = CAPTURE.sha256_bytes(CAPTURE.canonical_json(body))
    with pytest.raises(CAPTURE.CaptureRefused, match="equal-width"):
        CAPTURE.replay_state(bad)

    bad = copy.deepcopy(witness)
    bad["missing_pairs"] = []
    body = dict(bad)
    body.pop("state_sha256")
    bad["state_sha256"] = CAPTURE.sha256_bytes(CAPTURE.canonical_json(body))
    with pytest.raises(CAPTURE.CaptureRefused, match="ballot delta"):
        CAPTURE.replay_state(bad)


def test_split_is_preplay_deterministic_and_roughly_balanced():
    assignments = [CAPTURE.split_for_seed(seed) for seed in range(10_000)]
    assert set(assignments) == set(CAPTURE.SPLITS)
    counts = {split: assignments.count(split) for split in CAPTURE.SPLITS}
    assert all(3_100 < count < 3_600 for count in counts.values())


def test_global_selection_is_independent_of_shard_completion_order(witness):
    rows = []
    for split_index, split in enumerate(CAPTURE.SPLITS):
        for band_index, band in enumerate(CAPTURE.BANDS):
            for offset in range(3):
                row = copy.deepcopy(witness)
                seed = 1_000_000 + split_index * 10_000 + band_index * 100 + offset
                row.update({
                    "state_id": f"{seed}:{band_index * 4}:{row['seat']}",
                    "deal_seed": seed,
                    "split": split,
                    "band": band,
                    "trick": band_index * 4,
                })
                rows.append(row)
    selected, shortages = CAPTURE.select_population(
        list(reversed(rows)), quotas={band: 2 for band in CAPTURE.BANDS})
    assert shortages == {}
    assert len(selected) == 18
    chosen = {(row["split"], row["band"]): row["deal_seed"]
              for row in selected[::2]}
    for split_index, split in enumerate(CAPTURE.SPLITS):
        for band_index, band in enumerate(CAPTURE.BANDS):
            assert chosen[(split, band)] == \
                1_000_000 + split_index * 10_000 + band_index * 100


def test_natural_dose_weights_are_not_balanced_capture_weights():
    weights = {
        band: CAPTURE.NATURAL_DOSE_COUNTS[band]
        / CAPTURE.NATURAL_DOSE_DENOMINATOR
        for band in CAPTURE.BANDS
    }
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["early"] > 0.97
    assert weights["mid"] < 0.024
    assert weights["late"] < 0.001
    assert CAPTURE.QUOTA_PER_SPLIT == {"early": 448, "mid": 48, "late": 16}


def test_real_runtime_refuses_dirty_or_uncompiled(monkeypatch):
    monkeypatch.setattr(CAPTURE, "git", lambda *args: "dirty")
    with pytest.raises(CAPTURE.CaptureRefused, match="dirty"):
        CAPTURE._runtime(smoke=False)
