"""Synthetic tests for direction-suppressed S8 recovery diagnostics."""
import importlib.util
import json
import math
from pathlib import Path

import pytest


CLUSTERS = 520
KEYS = tuple(f"cluster-{index:03d}" for index in range(CLUSTERS))


@pytest.fixture
def diagnostics():
    script = Path(__file__).resolve().parents[1] / "scripts/v52ec_recovery_diagnostics.py"
    spec = importlib.util.spec_from_file_location("v52ec_recovery_diagnostics_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def population(candidate_value, comparator_value):
    return (
        {key: candidate_value for key in KEYS},
        {key: comparator_value for key in KEYS},
    )


@pytest.mark.parametrize(
    ("candidate_value", "comparator_value", "expected_nonzero", "expected_constant"),
    [
        (3, 3, 0, False),
        (2, 0, CLUSTERS, True),
        (0, 2, CLUSTERS, True),
    ],
)
def test_zero_and_constant_differences_are_counted(diagnostics, candidate_value,
                                                    comparator_value, expected_nonzero,
                                                    expected_constant):
    candidate, comparator = population(candidate_value, comparator_value)
    result = diagnostics.numeric_diagnostics(
        candidate, comparator, bootstrap_se=0.25
    )

    assert result["cluster_count"] == {"candidate": CLUSTERS, "comparator": CLUSTERS}
    assert result["all_finite"] == {"candidate": True, "comparator": True}
    assert result["paired_deltas_finite"] is True
    assert result["bootstrap_se_finite"] is True
    assert result["bootstrap_se_nonnegative"] is True
    assert result["n_nonzero_delta"] == expected_nonzero
    assert result["se_zero"] is False
    assert result["constant_nonzero"] is expected_constant


def test_mixed_positive_and_negative_differences_are_not_constant(diagnostics):
    candidate = {
        key: 4 if index < CLUSTERS // 2 else 0
        for index, key in enumerate(KEYS)
    }
    comparator = {
        key: 0 if index < CLUSTERS // 2 else 4
        for index, key in enumerate(KEYS)
    }

    result = diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=0)

    assert result["cluster_count"] == {"candidate": CLUSTERS, "comparator": CLUSTERS}
    assert result["n_nonzero_delta"] == CLUSTERS
    assert result["constant_nonzero"] is False
    assert result["se_zero"] is True


def test_sign_reversal_does_not_change_direction_suppressed_output(diagnostics):
    candidate, comparator = population(2, 0)
    reversed_candidate, reversed_comparator = population(-2, 0)

    result = diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=1.5)
    reversed_result = diagnostics.numeric_diagnostics(
        reversed_candidate, reversed_comparator, bootstrap_se=1.5
    )

    assert reversed_result == result


def test_nonfinite_utility_leaves_outcome_dependent_counts_null(diagnostics):
    candidate, comparator = population(1, 0)
    candidate[KEYS[0]] = math.nan

    result = diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=0)

    assert result["all_finite"] == {"candidate": False, "comparator": True}
    assert result["paired_deltas_finite"] is False
    assert result["bootstrap_se_finite"] is True
    assert result["bootstrap_se_nonnegative"] is True
    assert result["n_nonzero_delta"] is None
    assert result["constant_nonzero"] is None
    assert result["se_zero"] is True


@pytest.mark.parametrize("bootstrap_se", [math.nan, math.inf, -math.inf])
def test_nonfinite_bootstrap_se_has_null_se_flags(diagnostics, bootstrap_se):
    candidate, comparator = population(2, 0)

    result = diagnostics.numeric_diagnostics(
        candidate, comparator, bootstrap_se=bootstrap_se
    )

    assert result["all_finite"] == {"candidate": True, "comparator": True}
    assert result["paired_deltas_finite"] is True
    assert result["bootstrap_se_finite"] is False
    assert result["bootstrap_se_nonnegative"] is None
    assert result["se_zero"] is None
    assert result["n_nonzero_delta"] == CLUSTERS
    assert result["constant_nonzero"] is True


@pytest.mark.parametrize("bad_value", [True, "2"])
def test_rejects_bool_and_string_utility_values(diagnostics, bad_value):
    candidate, comparator = population(2, 0)
    candidate[KEYS[0]] = bad_value

    with pytest.raises(ValueError, match="invalid utility type"):
        diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=0)


@pytest.mark.parametrize("bad_se", [True, "0"])
def test_rejects_bool_and_string_bootstrap_se(diagnostics, bad_se):
    candidate, comparator = population(2, 0)

    with pytest.raises(ValueError, match="invalid bootstrap SE type"):
        diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=bad_se)


@pytest.mark.parametrize("bad_clusters", [True, "520"])
def test_rejects_bool_and_string_cluster_count(diagnostics, bad_clusters):
    candidate, comparator = population(2, 0)

    with pytest.raises(ValueError, match="invalid expected population"):
        diagnostics.numeric_diagnostics(
            candidate, comparator, bootstrap_se=0, clusters=bad_clusters
        )


def test_rejects_mismatched_keys(diagnostics):
    candidate, comparator = population(2, 0)
    del comparator[KEYS[-1]]
    comparator["cluster-extra"] = 0

    with pytest.raises(ValueError, match="paired population mismatch"):
        diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=0)


@pytest.mark.parametrize("which", ["candidate", "comparator"])
def test_rejects_mismatched_population_count(diagnostics, which):
    candidate, comparator = population(2, 0)
    del (candidate if which == "candidate" else comparator)[KEYS[-1]]

    with pytest.raises(ValueError, match="paired population mismatch"):
        diagnostics.numeric_diagnostics(candidate, comparator, bootstrap_se=0)


def test_output_is_strict_json_and_contains_no_raw_measurements(diagnostics):
    candidate, comparator = population(987654321, 123456789)
    bootstrap_se = 314159.26
    result = diagnostics.numeric_diagnostics(
        candidate, comparator, bootstrap_se=bootstrap_se
    )

    expected_keys = {
        "cluster_count",
        "all_finite",
        "paired_deltas_finite",
        "bootstrap_se_finite",
        "bootstrap_se_nonnegative",
        "n_nonzero_delta",
        "se_zero",
        "constant_nonzero",
        "exact_committed_play_equality",
    }
    assert set(result) == expected_keys
    assert set(result["cluster_count"]) == {"candidate", "comparator"}
    assert set(result["all_finite"]) == {"candidate", "comparator"}
    assert set(result["exact_committed_play_equality"]) == {
        "status", "count", "reason"
    }

    def keys(node):
        if isinstance(node, dict):
            return set(node).union(*(keys(value) for value in node.values()))
        return set()

    assert not keys(result).intersection(
        {"mean", "means", "delta", "deltas", "se", "utility", "utilities", "verdict"}
    )

    encoded = json.dumps(result, allow_nan=False, sort_keys=True)
    assert str(987654321) not in encoded
    assert str(123456789) not in encoded
    assert str(bootstrap_se) not in encoded
    assert "UNIDENTIFIABLE" in encoded
