import copy
import pytest

from shengji.eval.refusal_readout_summary import (
    attach_five_window_summaries, five_window_extension, summarize_refusal_observations,
    observe_refusal_max,
)


def census(valid=0, positive=0, observations=0, missing=0, partial=0, invalid=0):
    return dict(schema="pv-refusal-sampler-census-v1", denominator="validrecords",
                outcome_filter_applied=False, decisions=valid + missing + partial + invalid,
                valid_records=valid, missing_records=missing, partial_records=partial,
                invalid_records=invalid, refusal_observations=observations,
                observations_positive_decisions=positive)


def test_max_tracks_complete_arm_tuples():
    def rec(n):
        return dict(refusal_observations=n, refusal_rejections=0,
                    refusal_fallback_worlds=0, refusal_pinned_codes=0)
    out = {}
    observe_refusal_max(out, {})
    assert out['max_refusal_observations'] is None
    observe_refusal_max(out, {'decision_traces': [{'side': 'arm', 'decisions': [rec(0)]}]})
    assert out['max_refusal_observations'] == 0
    observe_refusal_max(out, {'decision_traces': [
        {'side': 'baseline', 'decisions': [rec(1000)]},
        {'side': 'arm', 'decisions': [rec(4), rec(2), rec(True), rec(-1),
                                    {'refusal_observations': 500}, None]}]})
    assert out['max_refusal_observations'] == 4


def test_pooled_max_preserves_unknown():
    a = dict(census(2, 2, 6), max_refusal_observations=4)
    b = dict(census(1, 1, 9), max_refusal_observations=9)
    assert summarize_refusal_observations([a, b])['max_observations'] == 9
    assert summarize_refusal_observations([a, census(missing=2)])['max_observations'] == 4
    assert summarize_refusal_observations([a, census(1)])['max_observations'] is None
    assert summarize_refusal_observations([census(missing=2)])['max_observations'] is None
    assert summarize_refusal_observations([dict(census(1), max_refusal_observations=0)])['max_observations'] == 0


@pytest.mark.parametrize('maximum', [True, -1, 0, 1, 7, 1.5])
def test_invalid_maximum_refused(maximum):
    with pytest.raises(ValueError, match='maximum'):
        summarize_refusal_observations([dict(census(2, 2, 6), max_refusal_observations=maximum)])


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


SEEDS = (52060910, 52160910, 52260910, 52360910, 52460910)
PREFIXES = ('PVSEARCH-r38rcec-v52ec', 'PVSEARCH-r38-v52ec')


def readout():
    return dict(integrity='PASS', outcome_filter_applied=False,
                triage={'mean': .02, 'ci95': [-.01, .05]}, statistical_result='INCONCLUSIVE',
                strength_verdict='WITHHELD_PENDING_HEALTH_AND_PROVENANCE_REVIEW',
                windows=[{'delta': .02}], receipts=[{'sha256': 'synthetic'}],
                descriptive_health={f'/synthetic/{prefix}-{seed}': {
                    'refusal_census': census(1, 0, 0) if side == 0 else census(1, 1, 5)}
                    for side, prefix in enumerate(PREFIXES) for seed in SEEDS})


def attach(result):
    return attach_five_window_summaries(result, seeds=SEEDS, prefixes=PREFIXES)


def test_attach_preserves_primary_and_health_and_allows_lower_candidate_counts():
    result = readout()
    before = copy.deepcopy(result)
    output = attach(result)
    assert result == before
    for key in before:
        assert output[key] == before[key]
    assert output['refusal_observation_summary']['candidate']['mean_observations'] == 0
    assert output['refusal_observation_summary']['comparator']['mean_observations'] == 5
    assert 'may be proposed' in output['extension']


@pytest.mark.parametrize('problem', ['missing', 'extra', 'duplicate', 'no_census', 'filtered', 'unvalidated'])
def test_attach_refuses_incomplete_or_ambiguous_population(problem):
    result = readout()
    health = result['descriptive_health']
    path = next(iter(health))
    if problem == 'missing':
        del health[path]
    elif problem == 'extra':
        health['/synthetic/unplanned-1'] = health[path]
    elif problem == 'duplicate':
        health['/another/' + path.rsplit('/', 1)[1]] = health[path]
    elif problem == 'no_census':
        health[path] = {}
    elif problem == 'filtered':
        result['outcome_filter_applied'] = True
    else:
        result['integrity'] = 'FAIL'
    with pytest.raises(ValueError):
        attach(result)


def test_positive_interval_replaces_old_extension_without_changing_primary():
    result = readout()
    result['triage']['ci95'] = [.001, .05]
    result['statistical_result'] = 'POSITIVE'
    result['extension'] = 'obsolete point-only extension'
    output = attach(result)
    assert output['extension'].startswith('no extension')
    assert output['triage'] == result['triage']
    assert output['statistical_result'] == 'POSITIVE'
    assert output['strength_verdict'] == result['strength_verdict']


def test_rendered_arm_name_collision_refused():
    with pytest.raises(ValueError, match='colliding'):
        attach_five_window_summaries(readout(), seeds=(-1, 1, 2, 3, 4), prefixes=('arm', 'arm-'))
