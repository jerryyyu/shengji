import pytest

from shengji.eval.refusal_readout_summary import (
    five_window_extension, summarize_refusal_observations,
)


def census(valid=0, positive=0, observations=0, missing=0, partial=0, invalid=0):
    return dict(schema="pv-refusal-sampler-census-v1", denominator="validrecords",
                outcome_filter_applied=False, decisions=valid + missing + partial + invalid,
                valid_records=valid, missing_records=missing, partial_records=partial,
                invalid_records=invalid, refusal_observations=observations,
                observations_positive_decisions=positive)


def test_pool_counts_not_window_rates():
    result = summarize_refusal_observations([census(1, 1, 4), census(9, 0, 0, missing=2)])
    assert result["mean_observations"] == 0.4
    assert result["share_with_observations"] == 0.1
    assert result["valid_record_share"] == 10 / 12
    assert result["event_complete_activation"] is None
    assert result["observe_public_calls"] is None


@pytest.mark.parametrize("rows", [[], [census(missing=3)], [census(partial=2, invalid=1)]])
def test_missing_is_not_zero(rows):
    result = summarize_refusal_observations(rows)
    assert result["mean_observations"] is None
    assert result["share_with_observations"] is None


def test_measured_zero_is_zero():
    result = summarize_refusal_observations([census(valid=4)])
    assert result["mean_observations"] == result["share_with_observations"] == 0


@pytest.mark.parametrize("field,value", [
    ("valid_records", True), ("decisions", -1), ("decisions", 7),
    ("refusal_observations", 0.5), ("observations_positive_decisions", 2),
    ("refusal_observations", 0), ("denominator", "completed_pv"),
    ("schema", "other"), ("outcome_filter_applied", True),
])
def test_bad_census_refused(field, value):
    row = census(1, 1, 3)
    row[field] = value
    with pytest.raises(ValueError):
        summarize_refusal_observations([row])


@pytest.mark.parametrize("point,interval,propose", [
    (.02, (-.01, .04), True), (.02, (0, .04), True),
    (.015, (-.01, .04), False), (.014, (-.01, .04), False),
    (.02, (.001, .04), False), (-.02, (-.04, -.001), False),
    (-.02, (-.04, .01), False),
])
def test_extension_boundaries(point, interval, propose):
    assert ("may be proposed" in five_window_extension(point, interval)) is propose


@pytest.mark.parametrize("point,interval", [
    (float("nan"), (-1, 1)), (.02, (float("inf"), 1)),
    (True, (0, 1)), (.02, (.04, -.01)), (.05, (-.01, .04)),
])
def test_bad_interval_refused(point, interval):
    with pytest.raises(ValueError):
        five_window_extension(point, interval)
