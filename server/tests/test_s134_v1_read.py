"""The S134 V1 reader's predeclared rules (``scripts/s134_v1_read.py``) on synthetic rows: the sample rule,
the verdict thresholds, the paired deal bootstrap and the guards that run before any outcome."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "s134_v1_read.py"
_spec = importlib.util.spec_from_file_location("s134_v1_read", _PATH)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


def test_the_predeclared_constants():
    assert rd.SAMPLE_SALT == "s134-v1|" and rd.SAMPLE_N == 300 and rd.SPLIT_SALT == "g3-yhold|" and rd.BAR_HALF == 1
    assert (rd.STRONG_PASS_POINT, rd.KILL_POINT) == (-0.010, 0.010)
    assert (rd.BOOT, rd.BOOT_SEED) == (10_000, 1) and rd.WORLDS == 64 and rd.RELEASE == 52
    assert rd.B1_CALIB_LL_MAX == 0.98982 and rd.B1_QEFF_PAIRED_LB_MIN == -0.010
    assert len(rd.CHOSEN_SHA256) == 64 and rd.STORE["bar_deals"] == 1488


def test_the_sample_rule_is_a_hash_order_and_ignores_input_order():
    bar = list(range(0, 3000, 2))
    got = rd.choose_clusters(bar, n=300)
    assert got == rd.choose_clusters(list(reversed(bar)), n=300)
    assert len(got) == 300 and len(set(got)) == 300 and set(got) <= set(bar)
    ranks = [hashlib.sha256(f"s134-v1|{c}".encode()).hexdigest() for c in got]
    assert ranks == sorted(ranks)
    rest = set(bar) - set(got)
    assert min(rd.sample_rank(c) for c in rest) > ranks[-1]
    assert rd.list_sha([1, 22]) == hashlib.sha256(b"1\n22").hexdigest()


def test_the_split_is_g4bs():
    key = "deck:52747c87366aff2b3b19b52fb9fdfb7b75cf81555530b7cea56715d397dffbc0"
    assert rd.half_of(key) == int(hashlib.sha256(("g3-yhold|" + key).encode()).hexdigest()[:8], 16) % 2


@pytest.mark.parametrize("point,upper,want", [
    (-0.011, -0.001, "STRONG_PASS"), (-0.010, -1e-9, "STRONG_PASS"), (-0.011, 0.0, "PARITY"),
    (-0.009, -0.001, "PARITY"), (0.0, 0.02, "PARITY"), (0.010, 0.03, "PARITY"), (0.0101, 0.03, "KILL"),
    (0.5, 0.6, "KILL"), (float("nan"), 0.0, "DEV_INVALID"), (0.0, float("inf"), "DEV_INVALID")])
def test_verdict_thresholds(point, upper, want):
    assert rd.verdict_of(point, upper) == want


def test_the_bootstrap_is_paired_by_deal_and_seeded():
    rng = np.random.default_rng(0)
    cl = np.repeat(np.arange(50), 20)
    deal_effect = rng.normal(size=50)[cl]
    a = deal_effect + 0.1 + 0.01 * rng.normal(size=len(cl))
    b = deal_effect
    p, lo, hi = rd.deal_bootstrap(cl, a, b)
    assert abs(p - 0.1) < 0.005 and lo < p < hi and hi - lo < 0.01      # the shared deal effect cancels
    _, ulo, uhi = rd.deal_bootstrap(cl, a)
    assert uhi - ulo > 10 * (hi - lo)
    assert rd.deal_bootstrap(cl, a, b) == (p, lo, hi)
    assert rd.deal_bootstrap(cl, np.full(len(cl), 0.25)) == (0.25, 0.25, 0.25)


def _rows(n_deals=6, per=8):
    ref, q = [], []
    for c in range(n_deals):
        for k in range(per):
            r = f"run:{c}:0:{k % 4}:{k}"
            ref.append(dict(ref=r, cluster=c, decision=k, round=f"run:{c}:0", seat=k % 4, ply=k, cards_left=25 - k // 4,
                            lead=k % 4 == 0, role_attacker=k % 2 == 1, target=100, terminal=k == per - 1, worlds=64,
                            belief_fallback=False, banker=0, nll_true=0.8, nll_mix=0.9, nll_world_mean=1.0,
                            outcome=dict(attacker_points=90, kitty_bonus=0, winner_team=1, level_change=0),
                            ft1_rank=k % 3, n_legal=10, legal_sha="ab"))
            q.append(dict(ref=r, cluster=c, decision=k, q_target=100, nll_q=0.85, q_policy_rank=k % 5, legal_sha="ab"))
    return ref, q


def test_guards_pass_clean_rows_and_the_bar_is_computed_on_non_terminal_rows():
    ref, q = _rows()
    anchors = {r["ref"]: r["nll_true"] for r in ref}
    ok, reasons, checks = rd.guards(ref, q, anchors=anchors)
    assert ok, reasons
    res = rd.analysis(ref, q)
    assert res["rows"] == 6 * 7 and res["terminal_excluded"] == 6
    assert res["d_q_minus_mix"]["point"] == pytest.approx(-0.05)
    assert res["verdict"] == "STRONG_PASS"
    assert res["p1_y_bar_descriptive"]["legal_sets_equal"]


@pytest.mark.parametrize("fault", ["target", "missing_q", "worlds", "fallbacks", "anchor", "outcome", "nan_mix",
                                   "duplicate"])
def test_guards_refuse_before_any_outcome(fault):
    ref, q = _rows()
    anchors = {r["ref"]: r["nll_true"] for r in ref}
    if fault == "target":
        q[3]["q_target"] = 101
    elif fault == "missing_q":
        q.pop(5)
    elif fault == "worlds":
        ref[2]["worlds"] = 63
    elif fault == "fallbacks":
        for r in ref[:2]:
            r["belief_fallback"] = True
    elif fault == "anchor":
        anchors[ref[0]["ref"]] += 1e-12
    elif fault == "outcome":
        for r in ref:
            if r["round"] == "run:0:0":
                r["outcome"] = dict(r["outcome"], winner_team=0)
    elif fault == "nan_mix":
        ref[1]["nll_mix"] = float("inf")
    elif fault == "duplicate":
        q.append(dict(q[0]))
    ok, reasons, _ = rd.guards(ref, q, anchors=anchors)
    assert not ok and reasons


def test_a_full_read_refuses_to_skip_the_anchor_check(tmp_path):
    assert rd.main(["analyze", "--out", str(tmp_path), "--no-anchors"]) == 2
    assert "--no-anchors is smoke only" in (tmp_path / "status").read_text()
