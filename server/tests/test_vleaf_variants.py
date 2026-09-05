"""The report-fold-only variant of the learned leaf on top of the cwv leaf
(``leaf_policy``): with ``leaf_stage="report"`` the leaf is consulted only
inside the report fold; selection rollouts are production's byte for byte.

The report fold's decision SE is production's raw ``_paired_se`` whatever
the variant: a same-sample-centred correction cannot shrink it (the Codex
HOLD on PR #232 removed the closed "control-variate" mode; the witness below
keeps it out).

Every property carries a mutation witness that must go RED."""
from __future__ import annotations

import hashlib
import math
import random

import pytest

torch = pytest.importorskip("torch")

from shengji.ai.mcbot import MCBot
from shengji.ai.registry import (REGISTRY, VLEAF_LEAF_TRICKS, make_bot, register_vleaf_arms,
                                 vleaf_policy_name, vleaf_policy_suffix)
from shengji.train import leaf_policy as L
from shengji.train import leaf_screen as S
from shengji.train.search_screen import _publish

from test_vleaf_cwv import mlp, save_cwv
from test_vleaf_leaf import BASE, Const, _strip, advance, deal, prior_table
from test_vleaf_screen import threads

SEEDS = (4_242, 4_243, 4_244)


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def cwv(tmp_path_factory):
    root = tmp_path_factory.mktemp("cwv-variants")
    model, aux = mlp(seed=41)
    path = save_cwv(root / "cwv.pt", model, aux)
    return {"path": path, "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()}


@pytest.fixture
def prior_path(tmp_path):
    path = tmp_path / "prior_points.json"
    _publish(path, prior_table().to_dict())
    return str(path)


def head(cwv):
    return L.CompleteWorldPointsHead.from_checkpoint(cwv["path"])


def small(bot, n=3):
    bot.N_DETERMINIZATIONS = n
    bot.REPORT_FOLD_WORLDS = 30
    return bot


def contested_state(seed):
    """A mid-round follow with a contested ballot (a search happens)."""
    rnd = deal(seed)
    probe = make_bot(BASE)
    seat = advance(rnd, lambda r: len(r.trick.plays) == 1 and len(r.history) >= 2
                   and len(probe._candidates(r, r.turn)) > 1)
    return rnd, seat


def decide(bot, seed):
    rnd, seat = contested_state(seed)
    play = bot.decide_play(rnd, seat)
    assert bot.last_decision_record is not None
    return play, bot.last_decision_record


SELECTION_FIELDS = ("means", "n_by_candidate", "paired_se", "alloc", "raw_winner_index",
                    "report_candidate_index", "worlds", "candidates", "eligible_indices",
                    "report_seed", "rng_state")


# ------------------- 1. report-only: selection is production's, net in the fold

def test_report_only_leaf_keeps_selection_production_and_calls_the_net_in_the_fold_only(cwv):
    for seed in SEEDS:
        prod = small(make_bot(BASE, seed=seed))
        arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                        leaf_tricks=1, leaf_stage="report"))
        assert arm.policy_name.endswith("-t1-report") and arm.leaf_stage == "report"
        _, prod_rec = decide(prod, seed)
        _, arm_rec = decide(arm, seed)
        assert prod_rec is not None and arm_rec is not None
        for field in SELECTION_FIELDS:
            assert arm_rec[field] == prod_rec[field], field
        assert arm.rng.getstate() == prod.rng.getstate()
        counts, stages = arm.leaf_counts, arm.stage_counts
        # every net call came from the report fold, none from selection
        assert stages["selection_net_calls"] == 0
        assert stages["report_net_calls"] == counts["predicted_leaves"] > 0
        assert stages["report_net_calls"] <= 2 * arm_rec["report_fold"]["worlds"]
        assert set(stages) == {"selection_net_calls", "report_net_calls"}
        # selection rollouts ran to round end (or the exact endgame): the
        # predicted leaves are exactly the fold's
        selection = arm_rec["work"]["selection_rollouts"]
        assert counts["leaf_calls"] == arm.rollouts == arm_rec["work"]["total_rollouts"]
        assert counts["terminal_leaves"] + counts["exact_leaves"] >= selection
        # and the fold itself did use the leaf: its gap is not production's
        assert arm_rec["report_fold"]["seed"] == prod_rec["report_fold"]["seed"]
    assert arm.leaf_counts["predicted_leaves"] > 0


def test_witness_ignored_stage_flag_puts_the_net_in_selection(monkeypatch, cwv):
    """Mutant: ``_rollout`` ignores the stage flag (the leaf is always on)."""
    monkeypatch.setattr(L.MCValueLeafSearch, "_leaf_on", lambda self: True)
    seed = SEEDS[0]
    prod = small(make_bot(BASE, seed=seed))
    arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                    leaf_tricks=1, leaf_stage="report"))
    _, prod_rec = decide(prod, seed)
    _, arm_rec = decide(arm, seed)
    assert arm.stage_counts["selection_net_calls"] > 0
    assert arm_rec["means"] != prod_rec["means"]


def test_report_only_leaf_with_a_stub_changes_only_the_fold(cwv):
    """A constant stub in the fold: selection identical, the fold's gap is
    the stub's (zero paired difference wherever both rollouts truncated)."""
    seed = SEEDS[1]
    prod = small(make_bot(BASE, seed=seed))
    stub = Const(50.0)
    arm = small(L.MCValueLeafSearch(stub, seed=seed, leaf_tricks=1, leaf_stage="report"))
    _, prod_rec = decide(prod, seed)
    _, arm_rec = decide(arm, seed)
    for field in SELECTION_FIELDS:
        assert arm_rec[field] == prod_rec[field], field
    assert stub.calls == arm.stage_counts["report_net_calls"] > 0
    assert arm.stage_counts["selection_net_calls"] == 0


# ------------ 2. the report fold's decision SE is production's raw _paired_se

def canned_fold(bot, ya, yb, *, seed=7):
    """``bot._report_fold_gap`` on canned per-world values: world i scores
    ``ya[i]`` for candidate A and ``yb[i]`` for B (attackers' units, the
    score map is the identity), so the paired deltas are ``ya - yb``."""
    values = {"A": list(ya), "B": list(yb)}
    bot._sample_hands = lambda rnd, seat, mem: ({}, [])
    bot._new_exact_world_session = lambda rnd, buried: None
    bot._prepare_report_world = lambda rnd, seat, hands, buried: None
    bot._score = lambda pts: pts
    bot._report_rollout = (lambda rnd, seat, hands, buried, cand, **kw:
                           values[cand[0]].pop(0))
    return bot._report_fold_gap(None, 0, None, True, ["A"], ["B"], len(ya),
                                seed=seed, keep_deltas=True)


def lcb_passes(bot, fold):
    """Production's report rule on a fold: ``gap - critical * se`` at or
    above REPORT_MIN_GAIN overrides the incumbent (mcbot.decide_play)."""
    critical = bot._report_critical(fold["worlds"])
    return not (fold["gap"] - critical * fold["se"] < bot.REPORT_MIN_GAIN)


def residual_se(deltas):
    """The SE a same-sample-centred control variate with X = D substitutes:
    the corrections ``X - mean X`` sum to zero, the mean is unchanged, and
    the per-world residual variance collapses."""
    mean = math.fsum(deltas) / len(deltas)
    corrected = [d - (d - mean) for d in deltas]
    return MCBot._paired_se(math.fsum(corrected), math.fsum(c * c for c in corrected),
                            len(corrected))


@pytest.mark.parametrize("ya,yb", [
    # Codex's construction: raw deltas [1, 3], X_a = [1, 3], X_b = [0, 0],
    # beta = 1 -> corrected [2, 2]: mean 2 unchanged, raw SE 1, residual SE 0
    ([1.0, 3.0], [0.0, 0.0]),
    # a 30-world fold: deltas [-0.9, 1.1] x 15 with X = D; the raw LCB is
    # below zero, the residual-SE LCB is the bare mean 0.1
    ([-0.9, 1.1] * 15, [0.0] * 30),
])
@pytest.mark.parametrize("leaf_stage", ["all", "report"])
def test_report_fold_decision_se_is_the_raw_paired_se(ya, yb, leaf_stage):
    """Same-sample centring cannot shrink the report SE: the fold's ``se``
    is ``_paired_se`` of the raw paired deltas and the LCB outcome is the
    raw outcome, for both stages, on a construction where the substituted
    residual SE would flip the decision."""
    arm = small(L.MCValueLeafSearch(Const(50.0), seed=1, leaf_tricks=1, leaf_stage=leaf_stage))
    prod = small(make_bot(BASE, seed=1))
    fold = canned_fold(arm, list(ya), list(yb))
    raw = canned_fold(prod, list(ya), list(yb))
    deltas = [a - b for a, b in zip(ya, yb)]
    raw_se = MCBot._paired_se(math.fsum(deltas), math.fsum(d * d for d in deltas), len(deltas))
    assert fold["deltas"] == deltas == raw["deltas"]
    assert fold["gap"] == raw["gap"] == pytest.approx(math.fsum(deltas) / len(deltas))
    assert fold["se"] == raw_se == raw["se"] > 0
    assert lcb_passes(arm, fold) == lcb_passes(prod, raw) is False
    # the construction discriminates: the residual SE is 0 and its LCB passes
    assert residual_se(deltas) == 0.0
    assert lcb_passes(arm, {**fold, "se": residual_se(deltas)}) is True
    assert "control_variate" not in fold


def test_live_report_fold_returns_productions_gap_and_se(monkeypatch, cwv):
    """With the live net in the fold, the variant's ``_report_fold_gap``
    returns exactly what production's fold computed (its gap, worlds and
    ``_paired_se`` of its deltas): nothing is rescaled between the two."""
    seen = []
    original = MCBot._report_fold_gap

    def spy(self, *args, seed, keep_deltas=False):
        out = original(self, *args, seed=seed, keep_deltas=True)
        seen.append(dict(out))
        if not keep_deltas:
            del out["deltas"]
        return out

    monkeypatch.setattr(MCBot, "_report_fold_gap", spy)
    for seed in SEEDS:
        arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                        leaf_tricks=1, leaf_stage="report"))
        seen.clear()
        _, rec = decide(arm, seed)
        (raw,) = seen
        fold = rec["report_fold"]
        deltas = raw["deltas"]
        assert fold["worlds"] == raw["worlds"] == len(deltas) >= 30
        assert fold["gap"] == raw["gap"] and fold["se"] == raw["se"]
        assert fold["se"] == pytest.approx(MCBot._paired_se(
            math.fsum(deltas), math.fsum(d * d for d in deltas), len(deltas)), rel=1e-12)
        assert fold["statistic"] == fold["gap"] - fold["critical"] * fold["se"]
        assert "control_variate" not in fold and "control_variate" not in rec


# -------------------------------------------- 3. names, config and calibration

def test_constructor_and_names_refuse_unknown_variants(cwv):
    leaf = L.CompleteWorldPointsLeaf(head(cwv))
    with pytest.raises(L.LeafError, match="leaf_stage"):
        L.MCValueLeafSearch(leaf, leaf_stage="selection")
    # the closed control-variate mode is not selectable anywhere
    with pytest.raises(TypeError):
        L.MCValueLeafSearch(leaf, leaf_mode="control-variate")
    with pytest.raises(TypeError):
        L.MCValueLeafSearch(leaf, beta=1.0)
    assert not hasattr(L, "LEAF_MODES") and not hasattr(L, "DEFAULT_CV_BETA")
    assert not hasattr(L.MCValueLeafSearch, "_cv_report_fold")
    assert vleaf_policy_suffix() == ""
    assert vleaf_policy_suffix(leaf_stage="report") == "-report"
    with pytest.raises(TypeError):
        vleaf_policy_suffix(leaf_mode="control-variate")
    assert vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234", leaf_model="cwv",
                             leaf_stage="report") == "mc-vleaf-cwv-abcd1234-t1-report"
    assert vleaf_policy_name(leaf_tricks=1, leaf_stage="report") == "mc-vleaf-prior-t1-report"
    with pytest.raises(ValueError, match="leaf_stage"):
        vleaf_policy_name(leaf_tricks=1, leaf_stage="fold")
    with pytest.raises(ValueError, match="leaf_stage"):
        register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_stage="x", registry={})
    with pytest.raises(TypeError):
        register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_mode="control-variate",
                            registry={})
    with pytest.raises(TypeError):
        S.build_config(arm="learned", leaf_mode="control-variate", leaf_tricks=1, seed0=1,
                       clusters=1, arm_select_worlds=7, checkpoint=cwv["path"])


def test_registry_builds_the_variants_by_name(cwv):
    registry = {BASE: REGISTRY[BASE]}
    names = register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_tricks=(1,),
                                leaf_stage="report", registry=registry)
    name = f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t1-report"
    assert names == {name: "cwv"}
    bot = registry[name](seed=5)
    assert bot.leaf_stage == "report"
    assert not hasattr(bot, "leaf_mode") and not hasattr(bot, "beta")
    assert bot.rng.getstate() == random.Random(5).getstate()
    record = L.leaf_record(bot)
    assert record["leaf_stage"] == "report"
    assert "leaf_mode" not in record and "beta" not in record
    assert record["stage_counts"] == {"selection_net_calls": 0, "report_net_calls": 0}
    # the plain name is a different policy and both coexist
    plain = register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_tricks=(1,),
                                registry=registry)
    assert set(plain) == {f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t1"} and name in registry


def config_kw(cwv, prior_path, **kw):
    return dict(leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=7, checkpoint=cwv["path"],
                prior=prior_path, baseline_select_worlds=1, report_worlds=30,
                bootstrap_replicates=100, trump_ranks=("2",), leaf_model="cwv", **kw)


def test_calibration_binds_the_variant(monkeypatch, cwv, prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    made = S.build_config(arm="learned", leaf_stage="report", **config_kw(cwv, prior_path))
    assert made["arm_policy"].endswith("-t1-report")
    assert made["leaf_stage"] == "report" and "leaf_mode" not in made and "cv_beta" not in made
    calibration = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
                   "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"],
                   "leaf_tricks": 1, "leaf_model": "cwv", "leaf_stage": "report",
                   "baseline_policy": BASE, "baseline_select_worlds": 1, "report_worlds": 30,
                   "trump_ranks": ["2"]}
    # the same variant is accepted ...
    config = S.build_config(arm="learned", leaf_stage="report", calibration=calibration,
                            **config_kw(cwv, prior_path))
    assert "leaf_mode" not in config and "cv_beta" not in config
    # ... the other stage is refused
    with pytest.raises(S.ScreenError, match="re-calibrate for this variant"):
        S.build_config(arm="learned", calibration=calibration, **config_kw(cwv, prior_path))
    # a calibration written before the option existed was made with the default
    legacy = {k: v for k, v in calibration.items() if k != "leaf_stage"}
    S.build_config(arm="learned", calibration=legacy, **config_kw(cwv, prior_path))
    with pytest.raises(S.ScreenError, match="re-calibrate for this variant"):
        S.build_config(arm="learned", leaf_stage="report", calibration=legacy,
                       **config_kw(cwv, prior_path))
    assert S.CALIBRATION_IDENTITY[:4] == ("checkpoint_sha256", "leaf_tricks", "leaf_model",
                                          "leaf_stage")
    assert "leaf_mode" not in S.CALIBRATION_IDENTITY and "cv_beta" not in S.CALIBRATION_IDENTITY


def test_witness_removed_variant_binding_accepts_the_other_calibration(monkeypatch, cwv, prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_matching_variant", lambda *a, **k: None)
    calibration = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
                   "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"],
                   "leaf_tricks": 1, "leaf_model": "cwv", "leaf_stage": "all",
                   "baseline_policy": BASE, "baseline_select_worlds": 1, "report_worlds": 30,
                   "trump_ranks": ["2"]}
    S.build_config(arm="learned", leaf_stage="report", calibration=calibration,
                   **config_kw(cwv, prior_path))


def test_legacy_control_variate_calibration_is_refused(monkeypatch, cwv, prior_path):
    """A calibration.json written by the removed control-variate mode (same
    sha / T / R / ranks) is not this arm's parity N: refused by name of the
    field; a legacy dict without ``leaf_mode`` or with the plain value is
    accepted; a config carrying the mode is refused wherever the identity is
    read."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    base = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
            "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"],
            "leaf_tricks": 1, "leaf_model": "cwv", "leaf_stage": "report",
            "baseline_policy": BASE, "baseline_select_worlds": 1, "report_worlds": 30,
            "trump_ranks": ["2"]}
    kw = dict(arm="learned", leaf_stage="report", **config_kw(cwv, prior_path))
    # absent, or the plain legacy value: accepted
    S.build_config(calibration=dict(base), **kw)
    S.build_config(calibration={**base, "leaf_mode": "replace", "cv_beta": 1.0}, **kw)
    # the removed mode, or a beta off the plain default: refused, field named
    with pytest.raises(S.ScreenError, match="leaf_mode='control-variate'"):
        S.build_config(calibration={**base, "leaf_mode": "control-variate", "cv_beta": 1.0}, **kw)
    with pytest.raises(S.ScreenError, match="leaf_mode='control-variate'"):
        S.require_matching_calibration(
            {**base, "leaf_mode": "control-variate"}, checkpoint_sha256=cwv["sha256"],
            leaf_tricks=1, base_policy=BASE, baseline_select_worlds=1, report_worlds=30,
            trump_ranks=("2",), leaf_model="cwv", leaf_stage="report")
    with pytest.raises(S.ScreenError, match="cv_beta=0.5"):
        S.build_config(calibration={**base, "leaf_mode": "replace", "cv_beta": 0.5}, **kw)
    # the same refusal wherever the identity is read from a config
    legacy_config = {"arm": "learned", "leaf_tricks": 1, "checkpoint_sha256": cwv["sha256"],
                     "leaf_model": "cwv", "leaf_stage": "report", "leaf_mode": "control-variate"}
    with pytest.raises(S.ScreenError, match="config carries leaf_mode='control-variate'"):
        S.arm_policy_name(legacy_config)
    with pytest.raises(S.ScreenError, match="leaf_mode='control-variate'"):
        S.config_variant(legacy_config)
    assert S.config_variant({**legacy_config, "leaf_mode": "replace"}) == {"leaf_stage": "report"}
    # a fresh calibration never carries the field
    assert "leaf_mode" not in S.build_config(**kw) and "cv_beta" not in S.build_config(**kw)


@pytest.mark.parametrize("variant", [dict(leaf_stage="report"), dict(leaf_stage="all")])
def test_real_cluster_counts_net_calls_per_stage(monkeypatch, tmp_path, cwv, prior_path, variant):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    config = S.build_config(arm="learned", **config_kw(cwv, prior_path), **variant)
    expected = vleaf_policy_name(leaf_tricks=1, checkpoint_id=cwv["sha256"][:8], leaf_model="cwv",
                                 **variant)
    assert config["arm_policy"] == expected
    summary = S.run_arm(config, output=tmp_path / "arm", workers=1, log=lambda s: None,
                        executor_factory=threads)
    assert summary["arm_policy"] == expected
    assert summary["leaf_stage"] == variant["leaf_stage"]
    assert "leaf_mode" not in summary and "cv_beta" not in summary
    arm = summary["leaf_counters"]["arm"]
    report_only = variant["leaf_stage"] == "report"
    assert arm["net_calls"] == arm["nn_calls"] == arm["selection_net_calls"] + arm["report_net_calls"] > 0
    assert arm["report_net_calls"] > 0
    assert (arm["selection_net_calls"] == 0) == report_only
    assert "control_variate_calls" not in arm and arm["predicted_leaves"] == arm["net_calls"]
    assert "control variate" not in summary["arm_description"]
    if report_only:
        assert "report fold only" in summary["arm_description"]
    assert summary["per_leaf_usecs"]["arm"] > 0
    assert arm["terminal_leaves"] + arm["exact_leaves"] + arm["predicted_leaves"] == arm["leaf_calls"]
    traces = __import__("json").loads((tmp_path / "arm" / "cluster-00000.json").read_text())
    stages = [d["stage"] for t in traces["decision_traces"] if t["side"] == "arm"
              for d in t["decisions"] if "stage" in d]
    assert stages and sum(s["report_net_calls"] for s in stages) == arm["report_net_calls"]
    # the prior control takes the same flags
    control = S.build_config(arm="prior", **config_kw(cwv, prior_path), **variant)
    assert control["arm_policy"] == vleaf_policy_name(leaf_tricks=1, **variant)
    bot = S.make_side(control, "arm", seed=1)
    assert bot.leaf_stage == variant["leaf_stage"]
