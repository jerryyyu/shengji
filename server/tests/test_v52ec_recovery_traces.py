"""Synthetic tests for mirrored attempted-action trace diagnostics."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


SEED = 401
CLUSTER = 7


@pytest.fixture
def diagnostics():
    script = Path(__file__).resolve().parents[1] / "scripts/v52ec_recovery_diagnostics.py"
    spec = importlib.util.spec_from_file_location("v52ec_recovery_traces_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decision_traces(plays):
    tricks = plays // 4
    traces = []
    for mirror in (0, 1):
        for side in ("arm", "baseline"):
            seats = (mirror, mirror + 2) if side == "arm" else (1 - mirror, 3 - mirror)
            for seat in seats:
                decisions = [
                    {
                        "seat": seat,
                        "trick": trick,
                        "played": [f"S{seat + trick + 2}", f"H{seat + trick + 2}"],
                    }
                    for trick in range(tricks)
                ]
                traces.append({"mirror": mirror, "side": side, "decisions": decisions})
    return traces


def _shard(plays=4):
    return {
        "seed": SEED,
        "cluster": CLUSTER,
        "records": [
            {
                "mirror": mirror,
                "seed": SEED,
                "cluster": CLUSTER,
                "plays": plays,
                "history_sha256_16": "ab" * 8 if mirror == 0 else "cd" * 8,
            }
            for mirror in (0, 1)
        ],
        "decision_traces": _decision_traces(plays),
    }


def _fingerprint(diagnostics, shard, covered=True):
    return diagnostics.trace_fingerprint(shard, coverage={"covered": covered})


@pytest.mark.parametrize("plays", [4, 8])
def test_one_and_two_trick_two_mirror_fixtures_are_valid(diagnostics, plays):
    result = _fingerprint(diagnostics, _shard(plays))

    assert set(result) == {(SEED, CLUSTER, 0), (SEED, CLUSTER, 1)}
    for mirror in (0, 1):
        assert result[(SEED, CLUSTER, mirror)]["attempts"] is not None
        assert len(result[(SEED, CLUSTER, mirror)]["attempts"]) == 4 * (plays // 4)


@pytest.mark.parametrize("field", ["seed", "cluster"])
def test_rejects_mirror_record_identity_mismatch(diagnostics, field):
    shard = _shard()
    shard["records"][1][field] += 1

    with pytest.raises(ValueError, match="trace record identity mismatch"):
        _fingerprint(diagnostics, shard)


def test_rejects_duplicate_mirror_record(diagnostics):
    shard = _shard()
    shard["records"][1]["mirror"] = 0

    with pytest.raises(ValueError, match="invalid mirrored trace records"):
        _fingerprint(diagnostics, shard)


def test_changed_digest_does_not_change_attempt_agreement(diagnostics):
    original = _fingerprint(diagnostics, _shard())
    changed_shard = _shard()
    changed_shard["records"][0]["history_sha256_16"] = "ef" * 8
    changed = _fingerprint(diagnostics, changed_shard)

    assert original[(SEED, CLUSTER, 0)]["attempts"] == changed[(SEED, CLUSTER, 0)]["attempts"]
    report = diagnostics.trace_agreement(original, changed)
    assert report["history_digest_agreement"] == {
        "label": "HASH AGREEMENT ONLY",
        "matched_mirrors": 2,
        "agreeing_play_count_and_digest": 1,
    }
    assert report["attempt_trace_equality"]["comparable_mirrors"] == 2
    assert report["attempt_trace_equality"]["equal_mirrors"] == 2


def test_changed_attempt_does_not_change_digest_agreement(diagnostics):
    original = _fingerprint(diagnostics, _shard())
    changed_shard = _shard()
    changed_shard["decision_traces"][0]["decisions"][0]["played"][0] = "D9"
    changed = _fingerprint(diagnostics, changed_shard)

    assert original[(SEED, CLUSTER, 0)]["history"] == changed[(SEED, CLUSTER, 0)]["history"]
    assert original[(SEED, CLUSTER, 0)]["attempts"] != changed[(SEED, CLUSTER, 0)]["attempts"]
    report = diagnostics.trace_agreement(original, changed)
    assert report["history_digest_agreement"]["agreeing_play_count_and_digest"] == 2
    assert report["attempt_trace_equality"]["comparable_mirrors"] == 2
    assert report["attempt_trace_equality"]["equal_mirrors"] == 1


def test_trace_container_reorder_and_card_order_are_normalized(diagnostics):
    original = _fingerprint(diagnostics, _shard())
    reordered_shard = _shard()
    reordered_shard["decision_traces"].reverse()
    reordered_shard["decision_traces"][0]["decisions"][0]["played"].reverse()
    reordered = _fingerprint(diagnostics, reordered_shard)

    assert reordered == original


def test_missing_played_is_unavailable_not_inequality(diagnostics):
    missing_shard = _shard()
    del missing_shard["decision_traces"][0]["decisions"][0]["played"]
    missing = _fingerprint(diagnostics, missing_shard)
    complete = _fingerprint(diagnostics, _shard())

    assert missing[(SEED, CLUSTER, 0)]["attempts"] is None
    assert missing[(SEED, CLUSTER, 1)]["attempts"] is not None
    report = diagnostics.trace_agreement(missing, complete)
    assert report["attempt_trace_equality"] == {
        "label": "ATTEMPTED CARD MULTISETS BY SIDE/SEAT/TRICK ONLY",
        "matched_mirrors": 2,
        "comparable_mirrors": 1,
        "unavailable_mirrors": 1,
        "equal_mirrors": 1,
    }


def test_coverage_false_makes_all_attempts_unavailable(diagnostics):
    uncovered = _fingerprint(diagnostics, _shard(), covered=False)
    complete = _fingerprint(diagnostics, _shard(), covered=True)

    assert all(uncovered[key]["attempts"] is None for key in uncovered)
    report = diagnostics.trace_agreement(uncovered, complete)
    assert report["history_digest_agreement"]["agreeing_play_count_and_digest"] == 2
    assert report["attempt_trace_equality"] == {
        "label": "ATTEMPTED CARD MULTISETS BY SIDE/SEAT/TRICK ONLY",
        "matched_mirrors": 2,
        "comparable_mirrors": 0,
        "unavailable_mirrors": 2,
        "equal_mirrors": None,
    }


def test_chronological_per_seat_trick_order_is_required(diagnostics):
    shard = _shard(plays=8)
    shard["decision_traces"][0]["decisions"].reverse()

    result = _fingerprint(diagnostics, shard)

    assert result[(SEED, CLUSTER, 0)]["attempts"] is None
    assert result[(SEED, CLUSTER, 1)]["attempts"] is not None


@pytest.mark.parametrize("mutation", ["duplicate", "mixed"])
def test_duplicate_or_mixed_seat_is_invalid(diagnostics, mutation):
    shard = _shard(plays=8 if mutation == "mixed" else 4)
    if mutation == "duplicate":
        shard["decision_traces"][1] = copy.deepcopy(shard["decision_traces"][0])
    else:
        shard["decision_traces"][0]["decisions"][1]["seat"] = 2

    result = _fingerprint(diagnostics, shard)

    assert result[(SEED, CLUSTER, 0)]["attempts"] is None
    assert result[(SEED, CLUSTER, 1)]["attempts"] is not None


def test_missing_baseline_is_invalid(diagnostics):
    shard = _shard()
    del shard["decision_traces"][2]

    result = _fingerprint(diagnostics, shard)

    assert result[(SEED, CLUSTER, 0)]["attempts"] is None
    assert result[(SEED, CLUSTER, 1)]["attempts"] is not None


def test_agreement_output_contains_no_raw_action_or_hash_data(diagnostics):
    fingerprints = _fingerprint(diagnostics, _shard())
    report = diagnostics.trace_agreement(fingerprints, fingerprints)

    assert report == {
        "history_digest_agreement": {
            "label": "HASH AGREEMENT ONLY",
            "matched_mirrors": 2,
            "agreeing_play_count_and_digest": 2,
        },
        "attempt_trace_equality": {
            "label": "ATTEMPTED CARD MULTISETS BY SIDE/SEAT/TRICK ONLY",
            "matched_mirrors": 2,
            "comparable_mirrors": 2,
            "unavailable_mirrors": 0,
            "equal_mirrors": 2,
        },
    }
    encoded = json.dumps(report, allow_nan=False, sort_keys=True)
    assert "abababababababab" not in encoded
    assert "cdcdcdcdcdcdcdcd" not in encoded
    assert "S2" not in encoded
    assert "H2" not in encoded


@pytest.mark.parametrize('cards', [['garbage'], ['S2'] * 3, [], [True]])
def test_malformed_card_multisets_are_unavailable(diagnostics, cards):
    shard = _shard()
    shard['decision_traces'][0]['decisions'][0]['played'] = cards
    result = _fingerprint(diagnostics, shard)
    assert result[(SEED, CLUSTER, 0)]['attempts'] is None
