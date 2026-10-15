"""Pooling and stopping rules for the windows of a paired served-bot screen.

Each window gives one paired contrast ``delta_i`` (candidate minus comparator,
each against the common control, averaged over the window's mirrored
clusters) and its within-window bootstrap standard error ``se_i``.  A reader
pools the windows into one estimate and classifies its interval.  Every rule
here is a predeclared option: a lane names its estimator and design before any
outcome, and a reader that names nothing gets ``dl``, the arithmetic every
sealed lane used.

Estimators (``pool_windows(..., estimator=...)``):

``dl``
    DerSimonian-Laird random effects with the arithmetic of the frozen
    reducer ``vol_re.dl`` (same expressions in the same summation order), and
    the result dict of the lane readers' ``pool()``.  Bit equality holds
    against that reducer run in the same interpreter: Python 3.12 made the
    float ``sum()`` compensated, so 3.9 and 3.12 can differ in the last bits.

``fe-q-gated``
    The fixed-effect (inverse-variance) estimate, unless Cochran's Q rejects
    homogeneity at ``Q_GATE_ALPHA`` (the upper chi-square tail on k-1 degrees
    of freedom), in which case DerSimonian-Laird.  DL already returns the
    fixed-effect answer whenever Q <= k-1, because its tau^2 is truncated at
    zero; a gate at Q/df <= 1 would therefore never change a result.  This
    gate narrows exactly the reads with 1 < Q/df <= chi2_crit/df, where the
    moment estimate of tau^2 is positive but homogeneity is not rejected.

Two-look design (``two_look_interim`` at 5 windows, ``two_look_final`` at 10):
O'Brien-Fleming efficacy bounds for two equally spaced looks (two-sided 0.05)
plus a binding futility stop at the interim:

* interim, 5 windows: POSITIVE if z > 2.797, NEGATIVE if z < -2.797,
  otherwise NOT AHEAD if the pooled point estimate is <= 0, otherwise CONTINUE;
* final, 10 windows (only after an interim CONTINUE): POSITIVE if z > 1.977,
  NEGATIVE if z < -1.977, otherwise INCONCLUSIVE.

The interval a look reports is its 95% repeated-confidence interval,
mean +/- (critical z) * SE, so the label always follows from the interval.
A futility stop reads "not ahead": it is not a null result, not equivalence
and not a harm finding.  ``two_look_operating_characteristics`` integrates
the design's exact error rates under equal per-window information.
"""
from __future__ import annotations

import math
from numbers import Real

ESTIMATORS = ('dl', 'fe-q-gated')
DEFAULT_ESTIMATOR = 'dl'
Q_GATE_ALPHA = 0.10
CI95_Z = 1.96                                      # the multiplier of every sealed lane's ci95
Z_POWER = 1.959963984540054 + 0.8416212335729143   # fixed-design MDE80 multiplier the readers report

TWO_LOOK_DESIGN = 'two-look-obf-futility-v1'
TWO_LOOK_INTERIM_WINDOWS = 5
TWO_LOOK_FINAL_WINDOWS = 10
TWO_LOOK_Z_INTERIM = 2.797
TWO_LOOK_Z_FINAL = 1.977
# Drift (final z, in units of the 10-window SE) at which the design declares POSITIVE with
# probability 0.80; test_paired_window_stats re-solves it from two_look_operating_characteristics.
TWO_LOOK_MDE80_Z = 2.8230
TWO_LOOK_LABELS = ('POSITIVE', 'NEGATIVE', 'NOT AHEAD', 'INCONCLUSIVE')


def _windows(deltas, ses):
    deltas, ses = list(deltas), list(ses)
    if len(deltas) != len(ses) or len(deltas) < 2:
        raise ValueError('need at least two windows, each with one SE')
    for value in (*deltas, *ses):
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError('degenerate/nonfinite window; no substitute statistic')
    if not all(s > 0 for s in ses):
        raise ValueError('degenerate/nonfinite window; no substitute statistic')
    return deltas, ses


def dl(deltas, ses):
    """(mean, se, tau, Q, I2): the frozen reducer's arithmetic, expression for expression."""
    deltas, ses = _windows(deltas, ses)
    k = len(deltas)
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


def _components(deltas, ses):
    """Both estimators from one pass.  The fixed-effect weights are the DL weights at tau^2 = 0
    (s**2 + 0.0 == s**2 exactly), so the two agree bit for bit whenever DL's tau^2 is zero."""
    deltas, ses = _windows(deltas, ses)
    k = len(deltas)
    w0 = [1.0/s**2 for s in ses]
    mu0 = sum(w*t for w, t in zip(w0, deltas))/sum(w0)
    Q = sum(w*(t-mu0)**2 for w, t in zip(w0, deltas))
    S1, S2 = sum(w0), sum(w*w for w in w0)
    tau2 = max(0.0, (Q - (k-1)) / (S1 - S2/S1))
    out = {'k': k, 'Q': Q, 'tau2': tau2}
    for name, t2 in (('fixed-effect', 0.0), ('dersimonian-laird', tau2)):
        w = [1.0/(s**2 + t2) for s in ses]
        out[name] = (sum(wi*t for wi, t in zip(w, deltas))/sum(w), 1.0/math.sqrt(sum(w)))
    out['I2'] = max(0.0, (Q-(k-1))/Q)*100 if Q > 0 else 0.0
    return out


def chi2_sf(x, df):
    """Upper tail P(X >= x) of chi-square with integer df >= 1, in closed form."""
    if type(df) is not int or df < 1:
        raise ValueError('df must be a positive integer')
    if not math.isfinite(x):
        raise ValueError('x must be finite')
    if x <= 0:
        return 1.0
    h = x / 2.0
    if df % 2 == 0:
        term, total = 1.0, 1.0
        for i in range(1, df // 2):
            term *= h / i
            total += term
        return min(1.0, math.exp(-h) * total)
    total = 0.0
    term = math.sqrt(2.0 * x / math.pi)            # h**0.5 / Gamma(3/2)
    for i in range(1, (df - 1) // 2 + 1):
        total += term
        term *= h / (i + 0.5)
    return min(1.0, math.erfc(math.sqrt(h)) + math.exp(-h) * total)


def chi2_isf(p, df):
    """The x with chi2_sf(x, df) == p, by bisection (reporting only; the gate compares p-values)."""
    if not 0.0 < p < 1.0:
        raise ValueError('p must lie in (0, 1)')
    lo, hi = 0.0, float(df)
    while chi2_sf(hi, df) > p:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if chi2_sf(mid, df) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def pool_windows(deltas, ses, *, estimator=DEFAULT_ESTIMATOR):
    """Pool paired windows.  ``dl`` returns exactly the lane readers' pool() dict; ``fe-q-gated``
    returns the same keys plus the gate's evidence and which estimator fired."""
    if estimator not in ESTIMATORS:
        raise ValueError(f'unknown estimator {estimator!r}; one of {ESTIMATORS}')
    if estimator == 'dl':
        mu, se, tau, q, i2 = dl(deltas, ses)
        return dict(mean=mu, se=se, ci95=[mu-1.96*se, mu+1.96*se], tau=tau, Q=q, I2=i2)
    c = _components(deltas, ses)
    df = c['k'] - 1
    p = chi2_sf(c['Q'], df)
    fired = 'dersimonian-laird' if p < Q_GATE_ALPHA else 'fixed-effect'
    mu, se = c[fired]
    return dict(mean=mu, se=se, ci95=[mu-1.96*se, mu+1.96*se], tau=math.sqrt(c['tau2']), Q=c['Q'], I2=c['I2'],
                estimator=estimator, fired=fired, windows=c['k'], df=df, Q_over_df=c['Q'] / df, Q_p=p,
                Q_gate_alpha=Q_GATE_ALPHA, Q_gate_critical=chi2_isf(Q_GATE_ALPHA, df), tau2=c['tau2'],
                mean_fixed_effect=c['fixed-effect'][0], se_fixed_effect=c['fixed-effect'][1],
                mean_dersimonian_laird=c['dersimonian-laird'][0], se_dersimonian_laird=c['dersimonian-laird'][1])


def pooling_line(pooled):
    """The canonical sentence for a ``fe-q-gated`` pool: Q, Q/df, its p-value, tau^2 and which estimator fired."""
    if pooled.get('estimator') != 'fe-q-gated':
        raise ValueError('pooling_line reports a fe-q-gated pool only')
    if pooled['fired'] not in ('fixed-effect', 'dersimonian-laird'):
        raise ValueError('unknown estimator fired')
    if pooled['fired'] != ('dersimonian-laird' if pooled['Q_p'] < pooled['Q_gate_alpha'] else 'fixed-effect'):
        raise ValueError('pooling_line: the fired estimator does not match the gate')
    name = {'fixed-effect': 'fixed-effect', 'dersimonian-laird': 'DerSimonian-Laird'}[pooled['fired']]
    return (f"Pooling (predeclared fixed-effect, gated on Cochran's Q at p < {pooled['Q_gate_alpha']:.2f}): "
            f"Q {pooled['Q']:.2f} on {pooled['df']} df (Q/df {pooled['Q_over_df']:.2f}, p {pooled['Q_p']:.3f}; "
            f"DerSimonian-Laird fires above Q {pooled['Q_gate_critical']:.2f}); DerSimonian-Laird tau^2 "
            f"{pooled['tau2']:.3g}; the {name} estimator fired (SE {pooled['se']:.5f}; fixed-effect "
            f"{pooled['se_fixed_effect']:.5f}, DerSimonian-Laird {pooled['se_dersimonian_laird']:.5f}).")


def _phi_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _phi_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def two_look_operating_characteristics(drift, *, z_interim=TWO_LOOK_Z_INTERIM, z_final=TWO_LOOK_Z_FINAL,
                                       steps=2000):
    """Exact outcome probabilities of the two-look design when the final z has mean ``drift``.

    Equal information per window: Z5 ~ N(drift/sqrt2, 1); the last five windows' own z, W, is an
    independent N(drift/sqrt2, 1); Z10 = (Z5 + W)/sqrt2.  The continuation integrals over
    0 < Z5 <= z_interim use Simpson's rule."""
    if not math.isfinite(drift) or steps < 2 or steps % 2:
        raise ValueError('finite drift and an even number of steps')
    m = drift / math.sqrt(2.0)
    cut = z_final * math.sqrt(2.0)
    h = z_interim / steps
    pos10 = neg10 = 0.0
    for i in range(steps + 1):
        z = i * h
        weight = 1 if i in (0, steps) else (4 if i % 2 else 2)
        dens = _phi_pdf(z - m)
        pos10 += weight * dens * (1.0 - _phi_cdf(cut - z - m))
        neg10 += weight * dens * _phi_cdf(-cut - z - m)
    pos10 *= h / 3.0
    neg10 *= h / 3.0
    pos5 = 1.0 - _phi_cdf(z_interim - m)
    neg5 = _phi_cdf(-z_interim - m)
    not_ahead5 = _phi_cdf(-m) - neg5
    cont = _phi_cdf(z_interim - m) - _phi_cdf(-m)
    return dict(positive_at_5=pos5, negative_at_5=neg5, not_ahead_at_5=not_ahead5, continue_to_10=cont,
                positive_at_10=pos10, negative_at_10=neg10, inconclusive_at_10=cont - pos10 - neg10,
                positive=pos5 + pos10, negative=neg5 + neg10, any_rejection=pos5 + pos10 + neg5 + neg10,
                expected_windows=TWO_LOOK_INTERIM_WINDOWS + (TWO_LOOK_FINAL_WINDOWS - TWO_LOOK_INTERIM_WINDOWS) * cont)


def two_look_interim(deltas, ses, *, estimator):
    """The interim look over the first five windows in the predeclared seed order."""
    deltas, ses = list(deltas), list(ses)
    if len(deltas) != TWO_LOOK_INTERIM_WINDOWS or len(ses) != TWO_LOOK_INTERIM_WINDOWS:
        raise ValueError(f'the interim look reads exactly {TWO_LOOK_INTERIM_WINDOWS} windows')
    pooled = pool_windows(deltas, ses, estimator=estimator)
    mean, se = pooled['mean'], pooled['se']
    z = mean / se
    if z > TWO_LOOK_Z_INTERIM:
        decision, label = 'STOP_POSITIVE', 'POSITIVE'
    elif z < -TWO_LOOK_Z_INTERIM:
        decision, label = 'STOP_NEGATIVE', 'NEGATIVE'
    elif mean <= 0:
        decision, label = 'STOP_NOT_AHEAD', 'NOT AHEAD'
    else:
        decision, label = 'CONTINUE', None
    return dict(design=TWO_LOOK_DESIGN, look='interim', windows=TWO_LOOK_INTERIM_WINDOWS, estimator=estimator,
                pooled=pooled, z=z, critical_z=TWO_LOOK_Z_INTERIM,
                rci95=[mean - TWO_LOOK_Z_INTERIM * se, mean + TWO_LOOK_Z_INTERIM * se],
                decision=decision, label=label)


def two_look_final(deltas, ses, *, estimator):
    """The final look over all ten windows; refuses unless the interim (recomputed from the first
    five windows) continued, so a stopped lane can never acquire a final verdict."""
    deltas, ses = list(deltas), list(ses)
    if len(deltas) != TWO_LOOK_FINAL_WINDOWS or len(ses) != TWO_LOOK_FINAL_WINDOWS:
        raise ValueError(f'the final look reads exactly {TWO_LOOK_FINAL_WINDOWS} windows')
    interim = two_look_interim(deltas[:TWO_LOOK_INTERIM_WINDOWS], ses[:TWO_LOOK_INTERIM_WINDOWS], estimator=estimator)
    if interim['decision'] != 'CONTINUE':
        raise ValueError(f"the interim look stopped this lane ({interim['decision']}); there is no final look")
    pooled = pool_windows(deltas, ses, estimator=estimator)
    mean, se = pooled['mean'], pooled['se']
    lo, hi = mean - TWO_LOOK_Z_FINAL * se, mean + TWO_LOOK_Z_FINAL * se
    label = 'POSITIVE' if lo > 0 else 'NEGATIVE' if hi < 0 else 'INCONCLUSIVE'
    return dict(design=TWO_LOOK_DESIGN, look='final', windows=TWO_LOOK_FINAL_WINDOWS, estimator=estimator,
                interim_decision=interim['decision'], pooled=pooled, z=mean / se, critical_z=TWO_LOOK_Z_FINAL,
                rci95=[lo, hi], mde80=TWO_LOOK_MDE80_Z * se, label=label)


def _check_look(result):
    """Refuse a look whose decision or label does not follow from its own numbers."""
    pooled = result['pooled']
    mean, se = pooled['mean'], pooled['se']
    look = result.get('look')
    expected = {'interim': (TWO_LOOK_INTERIM_WINDOWS, TWO_LOOK_Z_INTERIM), 'final': (TWO_LOOK_FINAL_WINDOWS, TWO_LOOK_Z_FINAL)}
    if look not in expected or result.get('design') != TWO_LOOK_DESIGN:
        raise ValueError('not a two-look result')
    if (result.get('windows'), result.get('critical_z')) != expected[look]:
        raise ValueError('window count or critical value is not the design\'s')
    c = result['critical_z']
    lo, hi = result['rci95']
    if (lo, hi) != (mean - c * se, mean + c * se):
        raise ValueError('the interval does not follow from the pool')
    if look == 'interim':
        z = mean / se
        expect = ('STOP_POSITIVE' if z > c else 'STOP_NEGATIVE' if z < -c
                  else 'STOP_NOT_AHEAD' if mean <= 0 else 'CONTINUE')
        if result['decision'] != expect:
            raise ValueError('the interim decision does not follow from the pool')
    else:
        expect = 'POSITIVE' if lo > 0 else 'NEGATIVE' if hi < 0 else 'INCONCLUSIVE'
        if result['label'] != expect or result.get('interim_decision') != 'CONTINUE':
            raise ValueError('the final label does not follow from the interval')


def two_look_lines(result):
    """Canonical sentences for one look.  A CONTINUE quotes no estimate: the interim number is not
    a result, and only the final look's is."""
    _check_look(result)
    mean, lo, hi, z, c = result['pooled']['mean'], *result['rci95'], result['z'], result['critical_z']
    if result['look'] == 'interim':
        head = (f"Two-look design, interim look (windows 1-{TWO_LOOK_INTERIM_WINDOWS} of {TWO_LOOK_FINAL_WINDOWS} in "
                f"the predeclared seed order)")
        decision = result['decision']
        if decision == 'CONTINUE':
            return [f"{head}: CONTINUE. The point estimate is above zero and z is inside the efficacy bound "
                    f"+/-{c}; the lane runs windows {TWO_LOOK_INTERIM_WINDOWS + 1}-{TWO_LOOK_FINAL_WINDOWS}. "
                    "No estimate is quoted at this look; only the final look gives a result."]
        first = (f"{head}: estimated {mean:+.4f}, z {z:+.2f}; 95% repeated-confidence interval "
                 f"[{lo:+.4f}, {hi:+.4f}] (critical z {c}).")
        if decision == 'STOP_POSITIVE':
            return [first, f"POSITIVE at the interim: z {z:+.2f} > {c}, lower bound {lo:+.4f} > 0; the lane stops "
                           "early for efficacy."]
        if decision == 'STOP_NEGATIVE':
            return [first, f"NEGATIVE at the interim: z {z:+.2f} < -{c}, upper bound {hi:+.4f} < 0; the lane stops "
                           "early."]
        return [first, f"NOT AHEAD: the five-window point estimate {mean:+.4f} is at or below zero, so the lane "
                       "stops for futility. This is not a null result, not equivalence and not a harm finding; "
                       f"an effect between {lo:+.4f} and {hi:+.4f} remains compatible."]
    first = (f"Two-look design, final look ({TWO_LOOK_FINAL_WINDOWS} windows; the interim look continued): "
             f"estimated {mean:+.4f}, z {z:+.2f}; 95% repeated-confidence interval [{lo:+.4f}, {hi:+.4f}] "
             f"(critical z {c}, O'Brien-Fleming); design MDE80 {result['mde80']:.4f}.")
    label = result['label']
    if label == 'POSITIVE':
        return [first, f"POSITIVE: the interval excludes zero (lower bound {lo:+.4f})."]
    if label == 'NEGATIVE':
        return [first, f"NEGATIVE: the interval lies below zero (upper bound {hi:+.4f})."]
    return [first, "INCONCLUSIVE: the interval includes zero; this establishes neither benefit nor "
                   f"noninferiority; an effect as low as {lo:+.4f} or as high as {hi:+.4f} remains compatible."]
