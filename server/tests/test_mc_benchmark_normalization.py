"""Native identity differs by design; semantic ballot differences must not vanish."""

import copy

import pytest

from scripts.bench_mc_hotpath import normalized


def _record():
    return {"schema": "mc-decision-v2", "search_secs": 0.5,
            "code": {"mcbot_sha256": "source"},
            "ballot": {"source_digest": "binary-a", "digest": "a",
                       "display": "mc[a]", "config": [["limit", 14]],
                       "name": "mc_candidates", "source": "MCBot._candidates"},
            "candidates": [["S2"], ["S3"]], "means": [1.0, 2.0],
            "work": {"report_rollouts": 600}}


def test_native_fingerprints_only_are_normalized_when_explicitly_requested():
    first = _record()
    second = copy.deepcopy(first)
    second["search_secs"] = 1.0
    second["ballot"].update(source_digest="binary-b", digest="b", display="mc[b]")
    assert normalized(first) != normalized(second)
    assert normalized(first, ignore_ballot_build_identity=True) == normalized(
        second, ignore_ballot_build_identity=True)
    assert first["ballot"]["source_digest"] == "binary-a"


@pytest.mark.parametrize("field,value", [
    ("candidates", [["S3"], ["S2"]]),
    ("means", [1.0, 2.00000000001]),
    ("work", {"report_rollouts": 598}),
    ("code", {"mcbot_sha256": "other-source"}),
])
def test_semantic_differences_survive_normalization(field, value):
    first, second = _record(), _record()
    second[field] = value
    assert normalized(first, ignore_ballot_build_identity=True) != normalized(
        second, ignore_ballot_build_identity=True)


def test_ballot_configuration_is_still_compared():
    first, second = _record(), _record()
    second["ballot"]["config"] = [["limit", 15]]
    assert normalized(first, ignore_ballot_build_identity=True) != normalized(
        second, ignore_ballot_build_identity=True)
