import json
import math
import random
from pathlib import Path

import pytest

from shengji.eval import paired_window_stats as S

FIXTURE = Path(__file__).parent / 'fixtures' / 'sealed_screen_windows.json'
SEALED = json.loads(FIXTURE.read_text())['contrasts']


def frozen_dl(deltas, ses):
    """The body of vol_re.dl (sha256 ce161623...), the reducer every sealed lane pinned, verbatim."""
    k = len(deltas)
    if k < 2: raise SystemExit("need >= 2 windows")
    w0 = [1.0/s**2 for s in ses]
    mu0 = sum(w*t for w, t in zip(w0, deltas))/sum(w0)
    Q = sum(w*(t-mu0)**2 for w, t in zip(w0, deltas))
    S1, S2 = sum(w0), sum(w*w for w in w0)
    tau2 = max(0.0, (Q - (k-1)) / (S1 - S2/S1))
    w = [1.0/(s**2 + tau2) for s in ses]
    mu = sum(wi*t for wi, t in zip(w, deltas))/sum(w)
    se = 1.0/math.sqrt(sum(w))
    I2 = max(0.0, (Q-(k-1))/Q)*100 if Q > 0 else 0.0
    return mu, se, math.sqrt(tau2), Q, I2


def lane_pool(deltas, ses):
    """The lane readers' pool() around the frozen reducer."""
    mu, se, tau, q, i2 = frozen_dl(deltas, ses)
    return dict(mean=mu, se=se, ci95=[mu-1.96*se, mu+1.96*se], tau=tau, Q=q, I2=i2)


def same_bits(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def random_windows(rng, k):
    sd = rng.choice((0.002, 0.01, 0.03))
    deltas = [rng.gauss(rng.uniform(-0.05, 0.05), sd * rng.uniform(0.5, 2.5)) for _ in range(k)]
    ses = [sd * rng.uniform(0.6, 1.6) for _ in range(k)]
    return deltas, ses


def label(ci):
    return 'POSITIVE' if ci[0] > 0 else 'NEGATIVE' if ci[1] < 0 else 'INCONCLUSIVE'


def test_fixture_is_every_sealed_paired_contrast():
    assert len(SEALED) == 50
    assert sum(len(c['deltas']) for c in SEALED if c['kind'] == 'primary') == 375
    assert all(label(c['stored']['ci95']) == c['label'] for c in SEALED)


# ---- the default estimator is the frozen reducer ----

def test_default_is_bit_identical_to_the_lane_pool_on_every_sealed_contrast():
    for c in SEALED:
        assert same_bits(S.pool_windows(c['deltas'], c['ses']), lane_pool(c['deltas'], c['ses'])), c['lane']
        assert S.dl(c['deltas'], c['ses']) == frozen_dl(c['deltas'], c['ses'])


def test_default_reproduces_the_stored_pools():
    # Bit equality with the stored numbers needs the readers' interpreter (3.9, uncompensated float sum)
    # and their window order, which some readers did not store; the gap is a few ulps, never a label.
    for c in SEALED:
        got = S.pool_windows(c['deltas'], c['ses'])
        for key in ('mean', 'se', 'tau', 'Q', 'I2'):
            assert got[key] == pytest.approx(c['stored'][key], rel=1e-11, abs=1e-13), (c['lane'], key)
        assert got['ci95'] == pytest.approx(c['stored']['ci95'], abs=1e-13)
        assert label(got['ci95']) == c['label']


def test_default_is_bit_identical_to_the_lane_pool_on_random_windows():
    rng = random.Random(20261015)
    for _ in range(3000):
        deltas, ses = random_windows(rng, rng.randint(2, 15))
        assert same_bits(S.pool_windows(deltas, ses, estimator='dl'), lane_pool(deltas, ses))


# ---- the Q-gated fixed-effect estimator ----

def gated_cases():
    rng = random.Random(7)
    cases = [(c['deltas'], c['ses']) for c in SEALED]
    cases += [random_windows(rng, rng.randint(2, 15)) for _ in range(3000)]
    return cases


def test_gated_equals_the_default_whenever_q_is_at_most_df():
    hits = 0
    for deltas, ses in gated_cases():
        g, d = S.pool_windows(deltas, ses, estimator='fe-q-gated'), S.pool_windows(deltas, ses)
        if g['Q'] <= g['df']:
            hits += 1
            assert g['fired'] == 'fixed-effect'
            assert (g['mean'], g['se'], g['ci95']) == (d['mean'], d['se'], d['ci95'])
    assert hits > 100


def test_gate_fires_dersimonian_laird_exactly_when_q_rejects_homogeneity():
    fired = {'fixed-effect': 0, 'dersimonian-laird': 0}
    for deltas, ses in gated_cases():
        g, d = S.pool_windows(deltas, ses, estimator='fe-q-gated'), S.pool_windows(deltas, ses)
        assert g['Q_p'] == S.chi2_sf(g['Q'], len(deltas) - 1)
        expect = 'dersimonian-laird' if g['Q_p'] < S.Q_GATE_ALPHA else 'fixed-effect'
        assert g['fired'] == expect
        fired[expect] += 1
        if expect == 'dersimonian-laird':
            assert (g['mean'], g['se'], g['ci95']) == (d['mean'], d['se'], d['ci95'])
        else:
            assert g['se'] <= d['se']
        assert (g['Q'], g['tau'], g['I2']) == (d['Q'], d['tau'], d['I2'])
    assert min(fired.values()) > 100


def test_gated_pooling_flips_no_sealed_verdict():
    dl_fired = set()
    for c in SEALED:
        g = S.pool_windows(c['deltas'], c['ses'], estimator='fe-q-gated')
        assert label(g['ci95']) == c['label'], c['lane']
        if g['fired'] == 'dersimonian-laird':
            dl_fired.add((c['lane'], c['contrast']))
    assert dl_fired == {('v76bwv44', 'primary'), ('v78orc45', 'information'), ('v78orc45', 'w64_to_w1'),
                        ('v85vdef45', 'primary')}


CHI2_REFERENCE = (   # scipy.stats.chi2.sf
    (0.5, 1, 0.47950012218695337),
    (3.841458820694124, 1, 0.04999999999999994),
    (2.0, 2, 0.36787944117144245),
    (7.779440339734858, 4, 0.09999999999999999),
    (4.0, 4, 0.40600584970983794),
    (1.5, 3, 0.6822703303362125),
    (11.0, 5, 0.05137998348306955),
    (14.683656573259835, 9, 0.10000000000000005),
    (9.0, 9, 0.43727418891386727),
    (25.0, 9, 0.002971180485917624),
    (21.064144212997057, 14, 0.09999999999999988),
    (3.0, 7, 0.8850022316431506),
    (40.0, 12, 7.190884052842887e-05),
    (0.1, 6, 0.9999799325063756),
)


@pytest.mark.parametrize('x, df, expected', CHI2_REFERENCE)
def test_chi2_sf_matches_reference(x, df, expected):
    assert S.chi2_sf(x, df) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize('df', [1, 4, 9, 14])
def test_chi2_isf_inverts_the_tail(df):
    assert S.chi2_sf(S.chi2_isf(0.10, df), df) == pytest.approx(0.10, rel=1e-12)


def test_pooling_line_reports_q_tau2_and_the_estimator_that_fired():
    by_lane = {(c['lane'], c['contrast']): c for c in SEALED}
    v85 = by_lane[('v85vdef45', 'primary')]
    g = S.pool_windows(v85['deltas'], v85['ses'], estimator='fe-q-gated')
    line = S.pooling_line(g)
    assert 'Q 14.80 on 9 df (Q/df 1.64, p 0.097;' in line and 'the DerSimonian-Laird estimator fired' in line
    assert 'DerSimonian-Laird fires above Q 14.68' in line and 'tau^2' in line
    v72 = by_lane[('v72vdev43', 'primary')]
    line = S.pooling_line(S.pool_windows(v72['deltas'], v72['ses'], estimator='fe-q-gated'))
    assert 'Q 14.53 on 9 df (Q/df 1.61, p 0.105;' in line and 'the fixed-effect estimator fired' in line
    tampered = dict(g, fired='fixed-effect')
    with pytest.raises(ValueError):
        S.pooling_line(tampered)
    with pytest.raises(ValueError):
        S.pooling_line(S.pool_windows(v85['deltas'], v85['ses']))


@pytest.mark.parametrize('deltas, ses', [
    ([0.01], [0.01]),
    ([0.01, 0.02], [0.01]),
    ([0.01, float('nan')], [0.01, 0.01]),
    ([0.01, 0.02], [0.01, 0.0]),
    ([0.01, 0.02], [0.01, -0.01]),
    ([0.01, True], [0.01, 0.01]),
    ([0.01, 0.02], [0.01, float('inf')]),
])
@pytest.mark.parametrize('estimator', S.ESTIMATORS)
def test_degenerate_windows_are_refused(deltas, ses, estimator):
    with pytest.raises(ValueError):
        S.pool_windows(deltas, ses, estimator=estimator)


def test_unknown_estimator_is_refused():
    with pytest.raises(ValueError):
        S.pool_windows([0.01, 0.02], [0.01, 0.01], estimator='fe')


# ---- the two-look design ----

def test_operating_characteristics():
    null = S.two_look_operating_characteristics(0.0)
    assert null['any_rejection'] == pytest.approx(0.0276, abs=2e-4)
    assert null['positive'] == pytest.approx(0.0247, abs=2e-4)
    assert null['positive'] < 0.03 and null['any_rejection'] < 0.03
    assert null['expected_windows'] == pytest.approx(7.49, abs=0.01)
    at_fixed = S.two_look_operating_characteristics(S.Z_POWER)
    assert at_fixed['positive'] == pytest.approx(0.794, abs=1e-3)
    for o in (null, at_fixed):
        parts = ('positive_at_5', 'negative_at_5', 'not_ahead_at_5', 'positive_at_10', 'negative_at_10', 'inconclusive_at_10')
        assert sum(o[p] for p in parts) == pytest.approx(1.0, abs=1e-12)


def test_design_mde80_solves_power_080():
    lo, hi = 2.0, 4.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if S.two_look_operating_characteristics(mid)['positive'] < 0.8 else (lo, mid)
    assert S.TWO_LOOK_MDE80_Z == pytest.approx((lo + hi) / 2, abs=1e-4)


def five(z, se=0.01):
    """Five equal-SE windows whose fixed-effect z is z."""
    return [z * se / math.sqrt(5)] * 5, [se] * 5


@pytest.mark.parametrize('z, decision, lbl', [
    (3.0, 'STOP_POSITIVE', 'POSITIVE'),
    (-3.0, 'STOP_NEGATIVE', 'NEGATIVE'),
    (-1.0, 'STOP_NOT_AHEAD', 'NOT AHEAD'),
    (0.0, 'STOP_NOT_AHEAD', 'NOT AHEAD'),
    (0.5, 'CONTINUE', None),
    (2.79, 'CONTINUE', None),
])
@pytest.mark.parametrize('estimator', S.ESTIMATORS)
def test_interim_decisions(z, decision, lbl, estimator):
    r = S.two_look_interim(*five(z), estimator=estimator)
    assert (r['decision'], r['label']) == (decision, lbl)
    assert r['z'] == pytest.approx(z)
    lines = S.two_look_lines(r)
    assert lines
    if decision == 'STOP_NOT_AHEAD':
        assert 'NOT AHEAD' in lines[1] and 'not a null result' in lines[1]
    if decision == 'CONTINUE':
        assert len(lines) == 1 and 'No estimate is quoted' in lines[0]
        assert f"{r['pooled']['mean']:+.4f}" not in lines[0]


def test_interim_reads_exactly_five_windows():
    with pytest.raises(ValueError):
        S.two_look_interim([0.01] * 6, [0.01] * 6, estimator='fe-q-gated')
    with pytest.raises(ValueError):
        S.two_look_final([0.01] * 9, [0.01] * 9, estimator='fe-q-gated')


def ten(z5, z10, se=0.01):
    """Ten equal-SE windows: the first five give interim z5, all ten give final z10."""
    first = z5 * se / math.sqrt(5)
    last = 2 * z10 * se / math.sqrt(10) - first
    return [first] * 5 + [last] * 5, [se] * 10


@pytest.mark.parametrize('z5, z10, lbl', [(1.0, 2.5, 'POSITIVE'), (1.0, 1.97, 'INCONCLUSIVE'), (1.0, 0.3, 'INCONCLUSIVE'),
                                          (0.2, -2.5, 'NEGATIVE')])
def test_final_labels_use_the_adjusted_critical_value(z5, z10, lbl):
    deltas, ses = ten(z5, z10)
    r = S.two_look_final(deltas, ses, estimator='fe-q-gated')
    assert r['pooled']['fired'] == 'fixed-effect'
    assert r['z'] == pytest.approx(z10) and r['label'] == lbl
    assert r['interim_decision'] == 'CONTINUE' and r['critical_z'] == S.TWO_LOOK_Z_FINAL
    assert r['mde80'] == pytest.approx(S.TWO_LOOK_MDE80_Z * r['pooled']['se'])
    assert label(r['rci95']) == lbl
    assert lbl in S.two_look_lines(r)[1]


def test_final_falls_back_to_dersimonian_laird_when_the_halves_disagree():
    r = S.two_look_final(*ten(1.0, -2.5), estimator='fe-q-gated')
    assert r['pooled']['fired'] == 'dersimonian-laird'
    assert r['pooled']['se'] == r['pooled']['se_dersimonian_laird'] > r['pooled']['se_fixed_effect']
    assert r['label'] == 'INCONCLUSIVE'


def test_final_refuses_a_lane_the_interim_stopped():
    for z5 in (-0.5, 3.5, -3.5):
        deltas, ses = ten(z5, 2.5)
        with pytest.raises(ValueError, match='there is no final look'):
            S.two_look_final(deltas, ses, estimator='fe-q-gated')


def test_lines_refuse_a_result_that_does_not_follow_from_its_numbers():
    interim = S.two_look_interim(*five(-1.0), estimator='fe-q-gated')
    for bad in (dict(interim, decision='CONTINUE'), dict(interim, rci95=[-0.01, 0.01]), dict(interim, critical_z=1.96),
                dict(interim, design='other')):
        with pytest.raises(ValueError):
            S.two_look_lines(bad)
    final = S.two_look_final(*ten(1.0, 1.97), estimator='fe-q-gated')
    for bad in (dict(final, label='POSITIVE'), dict(final, interim_decision='STOP_NOT_AHEAD'), dict(final, windows=5)):
        with pytest.raises(ValueError):
            S.two_look_lines(bad)


# The rule applied to every sealed primary with at least ten windows: the first ten in ascending seed
# order (the dispatch order of an interleaved launcher), fe-q-gated at both looks.
RETROSPECTIVE = {
    ('v47tree', 'primary'): ('INCONCLUSIVE', 10), ('v51t38', 'primary'): ('NOT AHEAD', 5),
    ('v57dts', 'primary'): ('NOT AHEAD', 5), ('v66lead42', 'primary'): ('NOT AHEAD', 5),
    ('v67dtrg', 'primary'): ('INCONCLUSIVE', 10), ('v69vd42c', 'primary'): ('POSITIVE', 5),
    ('v70vd43', 'primary'): ('POSITIVE', 5), ('v71vd43lr', 'primary'): ('POSITIVE', 5),
    ('v72vdev43', 'primary'): ('POSITIVE', 5), ('v73asap43', 'primary'): ('POSITIVE', 10),
    ('v75lpft44', 'primary'): ('NOT AHEAD', 5), ('v76bwv44', 'primary'): ('POSITIVE', 5),
    ('v77bwv2r45', 'primary'): ('NOT AHEAD', 5), ('v78orc45', 'information'): ('POSITIVE', 5),
    ('v78orc45', 'true_world_vs_served'): ('POSITIVE', 5), ('v78orc45', 'w64_to_w1'): ('NEGATIVE', 5),
    ('v79vdsb45', 'primary'): ('NOT AHEAD', 5), ('v80decl45', 'primary'): ('INCONCLUSIVE', 10),
    ('v81bts45', 'primary'): ('INCONCLUSIVE', 10), ('v82vdw45', 'primary'): ('NOT AHEAD', 5),
    ('v83sorc45', 'k16_vs_r45'): ('POSITIVE', 5), ('v83sorc45', 'k4_vs_r45'): ('POSITIVE', 5),
    ('v83sorc45', 'q50_vs_r45'): ('POSITIVE', 5), ('v84c14r45', 'e2_vs_r45'): ('NOT AHEAD', 5),
    ('v84c14r45', 'e5_vs_r45'): ('NOT AHEAD', 5), ('v85vdef45', 'primary'): ('POSITIVE', 10),
}


def test_retrospective_two_look_on_the_sealed_ten_window_contrasts():
    seen = {}
    for c in SEALED:
        if c['kind'] != 'primary' or len(c['deltas']) < 10:
            continue
        order = sorted(range(len(c['deltas'])), key=lambda i: c['seeds'][i])[:10]
        deltas, ses = [c['deltas'][i] for i in order], [c['ses'][i] for i in order]
        interim = S.two_look_interim(deltas[:5], ses[:5], estimator='fe-q-gated')
        if interim['decision'] == 'CONTINUE':
            got = (S.two_look_final(deltas, ses, estimator='fe-q-gated')['label'], 10)
        else:
            got = (interim['label'], 5)
        seen[(c['lane'], c['contrast'])] = got
        if len(c['deltas']) == 10:
            # a two-look verdict never contradicts the sealed fixed-design label
            assert got[0] == c['label'] or (got[0] == 'NOT AHEAD' and c['label'] in ('INCONCLUSIVE', 'NEGATIVE'))
            if c['label'] == 'POSITIVE':
                assert got[0] == 'POSITIVE'
    assert seen == RETROSPECTIVE
