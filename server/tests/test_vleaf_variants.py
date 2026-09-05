"""Two variants of the learned leaf on top of the cwv leaf (``leaf_policy``):

* ``leaf_stage="report"``: the leaf is consulted only inside the report
  fold; selection rollouts are production's byte for byte.
* ``leaf_mode="control-variate"``: the rollout runs to round end and the
  net's estimate at the horizon is subtracted as a per-candidate centred
  control variate; with beta=0 (or a constant stub) the decision is
  production's byte for byte, otherwise only the report fold's paired SE
  changes.

Every property carries a mutation witness that must go RED."""
from __future__ import annotations

import hashlib
import math
import random

import pytest

torch = pytest.importorskip("torch")

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


def without_cv(record):
    """The production-shaped record: the variant's own telemetry removed."""
    rec = {k: v for k, v in _strip(record).items() if k != "control_variate"}
    if rec.get("report_fold"):
        rec["report_fold"] = {k: v for k, v in rec["report_fold"].items() if k != "control_variate"}
    return rec


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
        assert stages["control_variate_calls"] == 0
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


# ------------------------------ 2. control variate: beta=0 is production exactly

def test_control_variate_beta_zero_is_production_byte_for_byte(cwv):
    for seed in SEEDS:
        prod = small(make_bot(BASE, seed=seed))
        arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                        leaf_tricks=1, leaf_mode="control-variate", beta=0.0))
        assert arm.policy_name.endswith("-t1-cv-b0")
        prod_play, prod_rec = decide(prod, seed)
        arm_play, arm_rec = decide(arm, seed)
        assert arm_play == prod_play
        assert without_cv(arm_rec) == without_cv(prod_rec)
        assert arm.rng.getstate() == prod.rng.getstate()
        # the net WAS called (the cost is production's plus the calls) ...
        stages = arm.stage_counts
        assert stages["control_variate_calls"] == (stages["selection_net_calls"]
                                                   + stages["report_net_calls"]) > 0
        assert stages["report_net_calls"] > 0
        # ... and never replaced a leaf: every rollout ran to round end / exact
        counts = arm.leaf_counts
        assert counts["predicted_leaves"] == 0
        assert counts["terminal_leaves"] + counts["exact_leaves"] == counts["leaf_calls"] == arm.rollouts
        cv = arm_rec["control_variate"]
        assert cv["beta"] == 0.0 and cv["report"]["variance_ratio"] == 1.0
        assert cv["report"]["se"] == cv["report"]["raw_se"] == arm_rec["report_fold"]["se"]


def test_control_variate_beta_one_changes_only_the_folds_se(cwv):
    """With a live net the gap and every selection field are production's;
    the paired SE (hence the LCB statistic) is recomputed from the corrected
    deltas, which is where the control variate acts."""
    changed = 0
    for seed in SEEDS:
        prod = small(make_bot(BASE, seed=seed))
        arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                        leaf_tricks=1, leaf_mode="control-variate", beta=1.0))
        assert arm.policy_name.endswith("-t1-cv")
        _, prod_rec = decide(prod, seed)
        _, arm_rec = decide(arm, seed)
        for field in SELECTION_FIELDS:
            assert arm_rec[field] == prod_rec[field], field
        fold, pfold = arm_rec["report_fold"], prod_rec["report_fold"]
        assert fold["gap"] == pfold["gap"] and fold["worlds"] == pfold["worlds"]
        cv = fold["control_variate"]
        assert abs(cv["correction_sum"]["a"]) < 1e-9 and abs(cv["correction_sum"]["b"]) < 1e-9
        assert cv["gap_from_corrected"] == pytest.approx(pfold["gap"], abs=1e-9)
        assert cv["raw_se"] == pfold["se"]
        assert cv["variance_ratio"] == pytest.approx((fold["se"] / pfold["se"]) ** 2)
        assert fold["statistic"] == fold["gap"] - fold["critical"] * fold["se"]
        changed += fold["se"] != pfold["se"]
        assert arm_rec["control_variate"]["selection_means_unchanged"] is True
        sel = arm_rec["control_variate"]["selection"]
        assert sum(v["net_calls"] for v in sel.values()) == arm.stage_counts["selection_net_calls"]
    assert changed > 0, "beta=1 with a live net never moved the paired SE"


def test_witness_correction_applied_regardless_of_beta_is_caught(monkeypatch, cwv):
    """Mutant: the fold corrects with beta=1 whatever the constructor said."""
    original = L.MCValueLeafSearch._cv_report_fold

    def always_one(self, *args, **kw):
        beta, self.beta = self.beta, 1.0
        try:
            return original(self, *args, **kw)
        finally:
            self.beta = beta

    monkeypatch.setattr(L.MCValueLeafSearch, "_cv_report_fold", always_one)
    differs = 0
    for seed in SEEDS:
        prod = small(make_bot(BASE, seed=seed))
        arm = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                        leaf_tricks=1, leaf_mode="control-variate", beta=0.0))
        _, prod_rec = decide(prod, seed)
        _, arm_rec = decide(arm, seed)
        differs += without_cv(arm_rec) != without_cv(prod_rec)
    assert differs > 0


# ------------------------ 3. a constant estimate: the correction is exactly zero

def test_constant_stub_correction_is_exactly_zero(cwv):
    for seed in SEEDS:
        prod = small(make_bot(BASE, seed=seed))
        stub = Const(50.0)
        arm = small(L.MCValueLeafSearch(stub, seed=seed, leaf_tricks=1,
                                        leaf_mode="control-variate", beta=1.0))
        prod_play, prod_rec = decide(prod, seed)
        arm_play, arm_rec = decide(arm, seed)
        assert arm_play == prod_play
        assert without_cv(arm_rec) == without_cv(prod_rec)
        cv = arm_rec["control_variate"]["report"]
        assert stub.calls > 0 and cv["net_calls"]["a"] + cv["net_calls"]["b"] > 0
        assert cv["max_abs_correction"] == 0.0
        assert cv["correction_sum"] == {"a": 0.0, "b": 0.0}
        assert cv["se"] == cv["raw_se"] and cv["variance_ratio"] == 1.0
        assert cv["mean_estimate"] == {"a": 50.0, "b": 50.0}


def test_witness_dropped_centring_is_caught(monkeypatch, cwv):
    """Mutant: the raw estimate is subtracted, not the centred one."""
    monkeypatch.setattr(L.MCValueLeafSearch, "_cv_centred", staticmethod(
        lambda values: ([0.0 if x is None else x for x in values], 50.0)))
    seed = SEEDS[0]
    arm = small(L.MCValueLeafSearch(Const(50.0), seed=seed, leaf_tricks=1,
                                    leaf_mode="control-variate", beta=1.0))
    _, arm_rec = decide(arm, seed)
    cv = arm_rec["control_variate"]["report"]
    assert cv["max_abs_correction"] == 50.0
    assert cv["correction_sum"]["a"] == 50.0 * cv["net_calls"]["a"] > 0
    # with a live net the uncentred mutant also moves the gap off production's
    monkeypatch.setattr(L.MCValueLeafSearch, "_cv_centred", staticmethod(
        lambda values: ([0.0 if x is None else x for x in values], None)))
    prod = small(make_bot(BASE, seed=seed))
    live = small(L.MCValueLeafSearch(L.CompleteWorldPointsLeaf(head(cwv)), seed=seed,
                                     leaf_tricks=1, leaf_mode="control-variate", beta=1.0))
    _, prod_rec = decide(prod, seed)
    _, live_rec = decide(live, seed)
    cv = live_rec["report_fold"]["control_variate"]
    assert abs(cv["correction_sum"]["a"]) > 1e-6
    assert cv["gap_from_corrected"] != pytest.approx(prod_rec["report_fold"]["gap"], abs=1e-6)


def test_control_variate_refuses_a_stub_that_lost_its_estimates(monkeypatch, cwv):
    """A buffer that does not line up with the fold's worlds fails closed."""
    seed = SEEDS[0]
    arm = small(L.MCValueLeafSearch(Const(50.0), seed=seed, leaf_tricks=1,
                                    leaf_mode="control-variate"))
    original = arm._rollout

    def leaky(*args, **kw):
        value = original(*args, **kw)
        for buffered in arm._cv_buffer.values():
            buffered.clear()
        return value

    monkeypatch.setattr(arm, "_rollout", leaky)
    with pytest.raises(L.LeafError, match="control variate"):
        decide(arm, seed)


# -------------------------------------------- 4. names, config and calibration

def test_constructor_and_names_refuse_unknown_variants(cwv):
    leaf = L.CompleteWorldPointsLeaf(head(cwv))
    with pytest.raises(L.LeafError, match="leaf_stage"):
        L.MCValueLeafSearch(leaf, leaf_stage="selection")
    with pytest.raises(L.LeafError, match="leaf_mode"):
        L.MCValueLeafSearch(leaf, leaf_mode="cv")
    with pytest.raises(L.LeafError, match="beta"):
        L.MCValueLeafSearch(leaf, leaf_mode="control-variate", beta=float("nan"))
    assert vleaf_policy_suffix() == ""
    assert vleaf_policy_suffix(leaf_stage="report") == "-report"
    assert vleaf_policy_suffix(leaf_mode="control-variate") == "-cv"
    assert vleaf_policy_suffix(leaf_stage="report", leaf_mode="control-variate", beta=0.5) \
        == "-report-cv-b0.5"
    assert vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234", leaf_model="cwv",
                             leaf_stage="report") == "mc-vleaf-cwv-abcd1234-t1-report"
    assert vleaf_policy_name(leaf_tricks=1, checkpoint_id="abcd1234", leaf_model="cwv",
                             leaf_mode="control-variate") == "mc-vleaf-cwv-abcd1234-t1-cv"
    assert vleaf_policy_name(leaf_tricks=1, leaf_stage="report") == "mc-vleaf-prior-t1-report"
    with pytest.raises(ValueError, match="leaf_stage"):
        vleaf_policy_name(leaf_tricks=1, leaf_stage="fold")
    with pytest.raises(ValueError, match="leaf_mode"):
        register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_mode="x", registry={})


def test_registry_builds_the_variants_by_name(cwv):
    registry = {BASE: REGISTRY[BASE]}
    names = register_vleaf_arms(checkpoint=cwv["path"], leaf_model="cwv", leaf_tricks=(1,),
                                leaf_stage="report", leaf_mode="control-variate", beta=0.5,
                                registry=registry)
    name = f"mc-vleaf-cwv-{cwv['sha256'][:8]}-t1-report-cv-b0.5"
    assert names == {name: "cwv"}
    bot = registry[name](seed=5)
    assert (bot.leaf_stage, bot.leaf_mode, bot.beta) == ("report", "control-variate", 0.5)
    assert bot.rng.getstate() == random.Random(5).getstate()
    record = L.leaf_record(bot)
    assert (record["leaf_stage"], record["leaf_mode"], record["beta"]) == ("report", "control-variate", 0.5)
    assert record["stage_counts"] == {"selection_net_calls": 0, "report_net_calls": 0,
                                      "control_variate_calls": 0}
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
    assert (made["leaf_stage"], made["leaf_mode"], made["cv_beta"]) == ("report", "replace", 1.0)
    calibration = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
                   "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"],
                   "leaf_tricks": 1, "leaf_model": "cwv", "leaf_stage": "report",
                   "leaf_mode": "replace", "cv_beta": 1.0, "baseline_policy": BASE,
                   "baseline_select_worlds": 1, "report_worlds": 30, "trump_ranks": ["2"]}
    # the same variant is accepted ...
    S.build_config(arm="learned", leaf_stage="report", calibration=calibration,
                   **config_kw(cwv, prior_path))
    # ... every other is refused: stage, mode, beta
    for kw in (dict(), dict(leaf_stage="report", leaf_mode="control-variate"),
               dict(leaf_stage="report", beta=0.5)):
        with pytest.raises(S.ScreenError, match="re-calibrate for this variant"):
            S.build_config(arm="learned", calibration=calibration, **config_kw(cwv, prior_path), **kw)
    # a calibration written before the options existed was made with the defaults
    legacy = {k: v for k, v in calibration.items() if k not in ("leaf_stage", "leaf_mode", "cv_beta")}
    S.build_config(arm="learned", calibration=legacy, **config_kw(cwv, prior_path))
    with pytest.raises(S.ScreenError, match="re-calibrate for this variant"):
        S.build_config(arm="learned", leaf_stage="report", calibration=legacy,
                       **config_kw(cwv, prior_path))
    assert S.CALIBRATION_IDENTITY[:6] == ("checkpoint_sha256", "leaf_tricks", "leaf_model",
                                          "leaf_stage", "leaf_mode", "cv_beta")


def test_witness_removed_variant_binding_accepts_the_other_calibration(monkeypatch, cwv, prior_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_matching_variant", lambda *a, **k: None)
    calibration = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
                   "chosen_arm_select_worlds": 7, "checkpoint_sha256": cwv["sha256"],
                   "leaf_tricks": 1, "leaf_model": "cwv", "leaf_stage": "all",
                   "leaf_mode": "replace", "cv_beta": 1.0, "baseline_policy": BASE,
                   "baseline_select_worlds": 1, "report_worlds": 30, "trump_ranks": ["2"]}
    S.build_config(arm="learned", leaf_stage="report", leaf_mode="control-variate",
                   calibration=calibration, **config_kw(cwv, prior_path))


@pytest.mark.parametrize("variant", [dict(leaf_stage="report"),
                                     dict(leaf_mode="control-variate"),
                                     dict(leaf_stage="report", leaf_mode="control-variate")])
def test_real_cluster_counts_net_calls_per_stage(monkeypatch, tmp_path, cwv, prior_path, variant):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    config = S.build_config(arm="learned", **config_kw(cwv, prior_path), **variant)
    expected = vleaf_policy_name(leaf_tricks=1, checkpoint_id=cwv["sha256"][:8], leaf_model="cwv",
                                 **variant)
    assert config["arm_policy"] == expected
    summary = S.run_arm(config, output=tmp_path / "arm", workers=1, log=lambda s: None,
                        executor_factory=threads)
    assert summary["arm_policy"] == expected
    assert summary["leaf_stage"] == variant.get("leaf_stage", "all")
    assert summary["leaf_mode"] == variant.get("leaf_mode", "replace")
    arm = summary["leaf_counters"]["arm"]
    report_only = variant.get("leaf_stage") == "report"
    cv = variant.get("leaf_mode") == "control-variate"
    assert arm["net_calls"] == arm["nn_calls"] == arm["selection_net_calls"] + arm["report_net_calls"] > 0
    assert arm["report_net_calls"] > 0
    assert (arm["selection_net_calls"] == 0) == report_only
    if cv:
        assert arm["control_variate_calls"] == arm["net_calls"] and arm["predicted_leaves"] == 0
        assert arm["continuation_rollouts"] == arm["rollouts"]
        assert "control variate" in summary["arm_description"]
    else:
        assert arm["control_variate_calls"] == 0 and arm["predicted_leaves"] == arm["net_calls"]
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
    assert (bot.leaf_stage, bot.leaf_mode) == (variant.get("leaf_stage", "all"),
                                               variant.get("leaf_mode", "replace"))
