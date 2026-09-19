"""Selecting an epoch on the POLICY head's own quantity (Jerry 2026-09-18: "curious how we can
have best policy head possible").

Until now every selectable metric was a VALUE metric -- val_ce, rank regret, points MAE -- so the
policy head, including production's admission prior, was always carried by a checkpoint chosen for
a different head.  The exclusion was deliberate and documented; this makes it a CHOICE rather than
an impossibility, without moving the default.
"""
import math

import pytest

from shengji.train.train_cwv import SELECT_METRICS, Selector, DEFAULTS


def test_the_default_is_unchanged():
    """Adding a metric must not silently re-aim every existing recipe."""
    assert DEFAULTS["select_metric"] == "val_ce"


def test_the_policy_metric_is_selectable_and_lower_is_better():
    assert "val_policy_miss_at_64" in SELECT_METRICS
    key, criterion = SELECT_METRICS["val_policy_miss_at_64"]
    assert key == "policy_miss_at_64"
    assert "top-64" in criterion and "EQUALLY" in criterion
    sel = Selector("val_policy_miss_at_64", patience=2)
    # 0.10 miss then 0.08 miss: the SECOND epoch is better (lower is better)
    assert sel.observe(1, {"policy_miss_at_64": 0.10})[0] is True
    assert sel.observe(2, {"policy_miss_at_64": 0.08})[0] is True
    assert sel.best_epoch == 2
    assert sel.observe(3, {"policy_miss_at_64": 0.12})[0] is False
    assert sel.best_epoch == 2


def test_a_missing_policy_block_is_a_loud_refusal_not_a_silent_zero():
    """A run without --policy-head has no such block; selecting on it must fail, not pick
    epoch 1 forever."""
    sel = Selector("val_policy_miss_at_64", patience=2)
    with pytest.raises(Exception):
        sel.observe(1, {"loss": 0.6})


def test_equal_weighting_is_not_cosmetic_the_two_reductions_disagree():
    """The reduction had to pick a weighting.  Pin that it MATTERS: with realistic strata --
    easy small-action buckets at ~1.000 recall holding most deals, hard large-action buckets
    carrying the signal -- the deal-weighted mean is far flatter and would barely move between
    epochs, which is exactly why selection uses the equal-weighted one."""
    top64 = {"exhaustive 0-20": 1.000, "exhaustive 21-100": 0.992,
             "exhaustive 101-1000": 0.940, "partial 1001-10000": 0.900,
             "partial 10001-1000000": 0.860}
    deals = {"exhaustive 0-20": 5000, "exhaustive 21-100": 3000,
             "exhaustive 101-1000": 400, "partial 1001-10000": 60,
             "partial 10001-1000000": 20}
    equal = sum(1.0 - r for r in top64.values()) / len(top64)
    wsum = sum(deals.values())
    weighted = sum((1.0 - top64[k]) * deals[k] for k in top64) / wsum
    assert equal > 2 * weighted, (
        f"equal {equal:.4f} vs deal-weighted {weighted:.4f}: if these agreed the choice would "
        "not matter and the docstring would be overclaiming")


def test_the_producer_emits_both_reductions_and_counts_its_strata():
    """PolicyEval.run must report the weighted figure beside the selected one, so the choice is
    visible in the receipt rather than only in this file."""
    import inspect

    from shengji.train.policy_rows import PolicyEval
    src = inspect.getsource(PolicyEval.run)
    for field in ("miss_at_64", "miss_at_64_deal_weighted", "strata_counted"):
        assert f'"{field}"' in src, f"PolicyEval.run no longer reports {field}"
