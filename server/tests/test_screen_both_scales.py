"""The screen summary reports BOTH outcome scales, and levels still decide (#487).

About 65% of mirrored deals tie on the level scale, so roughly two thirds of every
screen's sample carries no signal. Measured on sealed data, an attacker-points scale
agrees in sign with levels, cuts the tie fraction to ~19% and carries 1.4-1.8x the
signal-to-noise. Reporting it costs nothing and decides nothing on its own.

These witnesses pin the construction, not the conclusion: the sign convention, that
levels are untouched, and that a deal which ties on levels can still separate on points
-- which is the whole reason the second scale exists.
"""
from __future__ import annotations

from shengji.oracle import screen as S


def _rec(cluster, mirror, role, points, utility, won=0):
    return {"cluster": cluster, "mirror": mirror, "arm_role": role,
            "attacker_points": points, "arm_utility": utility, "arm_won": won,
            "work": {"arm": {"continuation_rollouts": 1, "total_rollouts": 1},
                     "baseline": {"continuation_rollouts": 1, "total_rollouts": 1}}}


def _summary(records):
    config = {"arm": "learned", "base_policy": "mc-s0-report-lcb",
              "base_class": "MCS0ReportLCB", "knobs": {},
              "work": {"production": True, "wide_cap": None,
                       "wide_require_complete": False}}
    return S.summarize(records, config, seed0=1, replicates=200)


def test_points_are_signed_from_the_arms_side_of_the_table():
    """Attacker wants points high, banker wants them low."""
    # arm attacks and takes 95; then banks and holds the opponent to 85 -> +10
    recs = [_rec(0, 0, "attacker", 95, +1, 1), _rec(0, 1, "banker", 85, -1, 0)]
    s = _summary(recs)
    assert s["arm_signed_attacker_points"]["per_cluster_sum"]["mean"] == 10.0
    assert s["arm_signed_attacker_points"]["per_round"]["mean"] == 5.0


def test_a_deal_that_ties_on_levels_can_separate_on_points():
    """The reason the second scale exists, stated as a witness."""
    recs = [_rec(0, 0, "attacker", 95, +1, 1), _rec(0, 1, "banker", 85, -1, 0)]
    s = _summary(recs)
    assert s["arm_signed_level_utility"]["per_cluster_sum"]["mean"] == 0.0
    assert s["arm_signed_level_utility"]["zero_clusters"] == 1      # a tie on levels
    assert s["arm_signed_attacker_points"]["zero_clusters"] == 0    # not on points
    assert s["arm_signed_attacker_points"]["positive_clusters"] == 1


def test_levels_are_untouched_and_still_the_stated_metric():
    recs = [_rec(0, 0, "attacker", 95, +2, 1), _rec(0, 1, "banker", 85, -1, 0),
            _rec(1, 0, "attacker", 40, -1, 0), _rec(1, 1, "banker", 120, -1, 0)]
    s = _summary(recs)
    assert s["metric"].startswith("arm signed level utility per round")
    # cluster 0 sums (+2) + (-1) = +1; cluster 1 sums (-1) + (-1) = -2; mean -0.5
    assert s["arm_signed_level_utility"]["per_cluster_sum"]["mean"] == -0.5
    # the secondary metric says plainly that it does not decide anything
    assert "levels remain the promotion criterion" in s["metric_secondary"]


def test_both_scales_count_the_same_clusters():
    recs = []
    for c in range(4):
        recs += [_rec(c, 0, "attacker", 80 + c, +1, 1), _rec(c, 1, "banker", 80, -1, 0)]
    s = _summary(recs)
    lev, pts = s["arm_signed_level_utility"], s["arm_signed_attacker_points"]
    for block in (lev, pts):
        assert (block["positive_clusters"] + block["zero_clusters"]
                + block["negative_clusters"]) == 4
    assert lev["per_cluster_sum"]["clusters"] == pts["per_cluster_sum"]["clusters"] == 4


def test_the_two_scales_share_bootstrap_seeds_so_the_comparison_is_paired():
    """Shared seeds PAIR the resamples across scales, which is what we want.

    An earlier version of this file asserted the opposite and justified it as
    stopping the intervals correlating and hiding a disagreement. That was
    backwards, and muse caught it. Both scales are computed on the same
    clusters, so a shared seed draws the same resample per replicate and the
    common cluster-sampling noise cancels when the two are compared -- the same
    paired-versus-unpaired argument used everywhere else in this project.
    Independent seeds would make a level-versus-points disagreement harder to
    see, and that disagreement is a declared check in the generation-2
    pre-registration.
    """
    recs = [_rec(0, 0, "attacker", 95, +1, 1), _rec(0, 1, "banker", 85, -1, 0),
            _rec(1, 0, "attacker", 60, -1, 0), _rec(1, 1, "banker", 90, +1, 1)]
    s = _summary(recs)
    lev, pts = s["arm_signed_level_utility"], s["arm_signed_attacker_points"]
    assert lev["per_round"]["seed"] == pts["per_round"]["seed"]
    assert lev["per_cluster_sum"]["seed"] == pts["per_cluster_sum"]["seed"]
