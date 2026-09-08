"""Witness prior/width configuration in the actual screen worker and receipt."""
import copy
import json
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_shortlist import CWVShortlistBot
from shengji.train.cwv_prior_union import CWVPriorUnionBot
from tests.test_cwv_shortlist_screen import cfg, identity_summary


def install_models(monkeypatch):
    evaluator = SimpleNamespace(checkpoint_sha256="value-sha", identity=lambda: {})
    prior = SimpleNamespace(checkpoint_sha256="prior-sha")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: evaluator)
    monkeypatch.setattr(S, "shared_prior_head", lambda *a, **k: prior)
    return evaluator, prior


def union_config():
    return cfg("learned", checkpoint="value.pt", checkpoint_sha256="value-sha",
               baseline="flat-shortlist", baseline_alternatives=6,
               prior_union={"checkpoint": "prior.pt", "checkpoint_sha256": "prior-sha",
                            "alternatives": 2})


def test_worker_uses_union_only_on_arm_and_independent_width_on_baseline(monkeypatch):
    install_models(monkeypatch)
    config = union_config()
    arm = S.make_side(config, "arm", 7)
    baseline = S.make_side(config, "baseline", 7)
    assert isinstance(arm, CWVPriorUnionBot)
    assert type(baseline) is CWVShortlistBot
    assert arm.shortlist_config.alternatives == 4
    assert arm.prior_alternatives == 2
    assert baseline.shortlist_config.alternatives == 6
    assert (arm.N_DETERMINIZATIONS, arm.REPORT_FOLD_WORLDS) == (30, 300)
    assert (baseline.N_DETERMINIZATIONS, baseline.REPORT_FOLD_WORLDS) == (30, 300)


def test_worker_refuses_substituted_prior(monkeypatch):
    install_models(monkeypatch)
    config = union_config()
    config["prior_union"]["checkpoint_sha256"] = "wrong"
    with pytest.raises(ValueError, match="^prior checkpoint changed between configuration and worker$"):
        S.make_side(config, "arm", 7)


def test_cli_preserves_union_identity_and_width_to_worker(tmp_path, monkeypatch):
    install_models(monkeypatch)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "_run_pending", lambda *a, **k: None)
    out = tmp_path / "run"
    assert S.main(["--arm", "learned", "--checkpoint", "value.pt",
                   "--prior-checkpoint", "prior.pt", "--baseline", "flat-shortlist",
                   "--baseline-alternatives", "6", "--worlds", "32", "--seed0", "17",
                   "--clusters", "1", "--out", str(out)]) == 0
    config = json.loads((out / "config.json").read_text())
    assert config["prior_union"]["checkpoint_sha256"] == "prior-sha"
    assert config["prior_union"]["selection"] == "top-prior-excluding-incumbent-and-value-shortlist-v1"
    assert S.make_side(config, "baseline", 0).shortlist_config.alternatives == 6
    assert isinstance(S.make_side(config, "arm", 0), CWVPriorUnionBot)
    changed = copy.deepcopy(config)
    changed["baseline_alternatives"] = 4
    assert S._recipe(config) != S._recipe(changed)
    changed = copy.deepcopy(config)
    changed["prior_union"]["checkpoint_sha256"] = "different"
    assert S._recipe(config) != S._recipe(changed)


def test_summary_names_actual_proposals_and_width(monkeypatch):
    monkeypatch.setattr(S.duel, "summarize", identity_summary)
    summary = S.summary_for([], union_config())
    assert "4 value alternatives + 2 distinct public-prior" in summary["arm_description"]
    assert summary["baseline_description"].endswith("incumbent + 6 alternatives")
    assert summary["outcome_sentinel"] == {"utility": 7}
    assert "Inner finalist" not in summary["work_caveat"]
    assert "Inner choices" not in summary["work_caveat"]


def test_summary_counts_prior_challenger_and_played_not_value_moves(monkeypatch):
    monkeypatch.setattr(S.duel, "summarize", identity_summary)
    detail = {"shortlist_indices": [5, 2, 9], "shortlist": [["S2"], ["S3"], ["S4"]],
              "prior_union": {"added_prior_indices": [9], "added_prior_count": 1}}
    rows = [{"cwv_shortlist": detail, "challenger": ["S4"], "played": ["S2"]},
            {"cwv_shortlist": detail, "challenger": ["S4"], "played": ["S4"]},
            {"cwv_shortlist": detail, "challenger": ["S3"], "played": ["S3"]}]
    shard = {"records": [], "decision_traces": [{"side": "arm", "decisions": rows},
                                                 {"side": "baseline", "decisions": rows}]}
    summary = S.summary_for([shard], union_config())
    assert summary["prior_attribution"] == {"decisions_with_prior": 3,
        "prior_candidates_added": 3, "prior_challengers": 2, "prior_played": 1}


def test_bounded_execution_slice_preserves_full_resume_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, pending, shards, **kw:
                        seen.append((copy.deepcopy(config), list(pending))))
    args = ["--arm", "uniform", "--seed0", "17", "--clusters", "26",
            "--out", str(tmp_path / "run")]
    assert S.main([*args, "--max-new-clusters", "1", "--workers", "1"]) == 0
    assert S.main([*args, "--workers", "16"]) == 0
    assert seen[0][0] == seen[1][0]
    assert seen[0][0]["clusters"] == 26
    assert seen[0][1] == [0]
    assert seen[1][1] == list(range(26))


@pytest.mark.parametrize("extra", [
    ["--baseline-alternatives", "6"],
    ["--prior-alternatives", "3"],
    ["--prior-checkpoint", "prior.pt"],
])
def test_cli_refuses_ambiguous_combinations(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit) as exc:
        S.main(["--arm", "uniform", "--seed0", "17", "--out", str(tmp_path), *extra])
    assert exc.value.code == 2
