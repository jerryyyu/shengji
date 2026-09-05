"""Value-at-leaf screen driver: the CPU-parity calibration is a function of
CPU only (with its witness), the real mirrored cluster runs through the
registry names and counts leaf work, summaries carry the declared fields."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai.registry import REGISTRY
from shengji.engine.cards import RANKS
from shengji.train import leaf_policy as L
from shengji.train import leaf_screen as S
from shengji.train.baselines import N_STRATA
from shengji.train.model import ValuePriorNet
from shengji.train.search_screen import _publish

from test_vleaf_leaf import prior_table, save, small_arch  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]

GRID = (30, 45, 60, 90)


# ------------------------------------------------------------ calibration

def fake_shards(n, *, ratio_of, utility_of, clusters=3):
    """Per-N shards whose CPU ratio is ``ratio_of(n)`` and whose outcomes are
    ``utility_of(n)`` — the outcomes are bait the calibration must not eat."""
    shards = []
    for cluster in range(clusters):
        records = []
        for mirror in (0, 1):
            base = 2.0 + 0.1 * cluster + 0.01 * mirror
            work = {"decision_cpu_seconds": base, "decision_wall_seconds": base, "play_calls": 50,
                    "search_calls": 20, "rollouts": 3000, "predicted_leaves": 0, "leaf_secs": 0.0}
            arm = dict(work, decision_cpu_seconds=base * ratio_of(n), predicted_leaves=2000,
                       leaf_secs=0.3)
            utility = utility_of(n)
            records.append({"cluster": cluster, "mirror": mirror, "arm_utility": utility,
                            "baseline_utility": -utility, "arm_won": int(utility > 0),
                            "arm_role": "banker", "attacker_points": 80,
                            "work": {"arm": arm, "baseline": work}})
        shards.append({"cluster": cluster, "records": records})
    return shards


def favours(best):
    return lambda n: 2.0 if n == best else -2.0


def test_calibration_is_a_function_of_cpu_only():
    ratio = lambda n: 0.5 + n / 100.0                    # unit ratio at N = 50
    variants = [favours(90), favours(30), lambda n: 0.0]
    choices = []
    for utility_of in variants:
        result = S.calibration_choice({n: fake_shards(n, ratio_of=ratio, utility_of=utility_of)
                                       for n in GRID})
        choices.append(result["choice"]["chosen_n"])
        flat = json.dumps(result)
        assert "utility" not in flat and "arm_won" not in flat and "attacker_points" not in flat
        assert [row["n"] for row in result["table"]] == list(GRID)
        assert [round(row["decision_cpu_ratio"], 6) for row in result["table"]] \
            == [round(ratio(n), 6) for n in GRID]
    assert choices == [50, 50, 50]
    choice = S.choose_n([(n, ratio(n)) for n in GRID])
    assert choice["chosen_n"] == 50 and choice["within_band"] and choice["within_grid"]
    assert choice["predicted_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert choice["fit"]["slope_per_world"] == pytest.approx(0.01)


def test_witness_outcome_driven_choice_is_caught(monkeypatch):
    """Mutant: the calibration picks the N whose deals went best."""
    def by_outcome(shards_by_n, *, band=S.PARITY_BAND):
        means = {n: np.mean([r["arm_utility"] for s in shards for r in s["records"]])
                 for n, shards in shards_by_n.items()}
        best = max(sorted(means), key=means.get)
        return {"table": [], "choice": {"chosen_n": best}}

    monkeypatch.setattr(S, "calibration_choice", by_outcome)
    ratio = lambda n: 0.5 + n / 100.0
    choices = [S.calibration_choice({n: fake_shards(n, ratio_of=ratio, utility_of=u)
                                     for n in GRID})["choice"]["chosen_n"]
               for u in (favours(90), favours(30))]
    assert choices != [50, 50]                      # the property above is RED


def test_choose_n_extrapolates_and_says_so():
    steep = S.choose_n([(n, 1.10 + 0.01 * (n - 30)) for n in GRID])    # unit ratio at N = 20
    assert steep["chosen_n"] == 20 and not steep["within_grid"] and steep["within_band"]
    flat = S.choose_n([(n, 1.3) for n in GRID])
    assert flat["chosen_n"] == 30 and not flat["within_band"]
    assert flat["method"].startswith("ratio did not increase")
    single = S.choose_n([(30, 0.97)])
    assert single["chosen_n"] == 30 and single["within_band"]
    with pytest.raises(S.ScreenError):
        S.choose_n([(30, float("nan"))])


def test_load_calibration_requires_the_blindness_attestation(tmp_path):
    good = {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False, "chosen_arm_select_worlds": 42}
    _publish(tmp_path / "ok.json", good)
    assert S.load_calibration(tmp_path / "ok.json")["chosen_arm_select_worlds"] == 42
    for bad in (dict(good, outcomes_read=True), dict(good, schema="other"),
                dict(good, chosen_arm_select_worlds=0)):
        _publish(tmp_path / "bad.json", bad)
        with pytest.raises(S.ScreenError):
            S.load_calibration(tmp_path / "bad.json")


def test_minimum_detectable_effect_scales_with_clusters():
    values = [1.0, -1.0, 0.5, -0.5, 0.0, 1.0, -1.0, 0.0]
    this = S.minimum_detectable_effect(values)
    big = S.minimum_detectable_effect(values, clusters=1024)
    assert this["clusters"] == 8 and big["clusters"] == 1024
    assert this["mde_levels_per_round"] == pytest.approx(
        (1.959964 + 0.841621) * np.std(values, ddof=1) / np.sqrt(8), rel=1e-5)
    assert big["mde_levels_per_round"] == pytest.approx(
        this["mde_levels_per_round"] * np.sqrt(8 / 1024), rel=1e-9)
    assert S.minimum_detectable_effect([1.0])["mde_levels_per_round"] is None


# ------------------------------------------------------ the real cluster

@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("vleaf")
    torch.manual_seed(21)
    checkpoint = save(root / "aux.pt", ValuePriorNet(small_arch(True)).eval())
    prior = root / "prior_points.json"
    _publish(prior, prior_table().to_dict())
    return {"checkpoint": checkpoint, "prior": str(prior)}


def threads(n):
    return ThreadPoolExecutor(max_workers=n)


def tiny_config(arm, artifacts, **kw):
    kw = {"baseline_select_worlds": 1, "report_worlds": 30, "bootstrap_replicates": 200,
          "clusters": 1, "arm_select_worlds": 1, **kw}
    return S.build_config(arm=arm, leaf_tricks=1, seed0=431, checkpoint=artifacts["checkpoint"],
                          prior=artifacts["prior"], **kw)


def test_real_cluster_through_registry_names_counts_leaf_work(monkeypatch, tmp_path, artifacts):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    summaries = {}
    for arm in S.ARMS:
        config = tiny_config(arm, artifacts)
        assert config["arm_policy"].startswith("mc-vleaf-")
        summary = S.run_arm(config, output=tmp_path / arm, workers=1, log=lambda s: None,
                            executor_factory=threads)
        summaries[arm] = summary
        # The learned arm is driven by its registry name; the control is built
        # from the bytes the config carries and only labelled with its name.
        assert (config["arm_policy"] in REGISTRY) == (arm == "learned")
        shard = json.loads((tmp_path / arm / "cluster-00000.json").read_text())
        assert [r["mirror"] for r in shard["records"]] == [0, 1]
        for row in shard["records"]:
            assert row["arm"] == arm and row["arm_policy"] == config["arm_policy"]
            assert row["plays"] > 20
            work = row["work"]["arm"]
            base = row["work"]["baseline"]
            assert work["leaf_calls"] == work["rollouts"] > 0
            assert work["predicted_leaves"] > 0 and work["terminal_leaves"] >= 0
            assert (work["terminal_leaves"] + work["exact_leaves"] + work["predicted_leaves"]
                    == work["leaf_calls"])
            assert work["continuation_rollouts"] == work["rollouts"] - work["predicted_leaves"]
            if arm == "learned":
                assert work["nn_calls"] == work["predicted_leaves"] and work["prior_lookups"] == 0
            else:
                assert work["prior_lookups"] == work["predicted_leaves"] and work["nn_calls"] == 0
            assert work["decision_cpu_seconds"] > 0 and work["leaf_secs"] > 0
            assert work["play_calls"] > 0 and base["play_calls"] > 0
            assert base["leaf_calls"] == base["predicted_leaves"] == 0
            assert base["decision_cpu_seconds"] > 0 and base["leaf_secs"] == 0
        traces = [t for t in shard["decision_traces"] if t["side"] == "arm"]
        assert traces and any(d.get("leaf", {}).get("predicted_leaves", 0) > 0
                              for t in traces for d in t["decisions"])
        assert summary["schema"] == S.SUMMARY_SCHEMA
        assert summary["complete"] and summary["equal_work_strength_claim"] is False
        assert summary["arm_over_baseline_decision_cpu"] > 0
        assert summary["leaf_counters"]["arm"]["predicted_leaves"] > 0
        assert summary["minimum_detectable_effect"]["projected_1024_clusters"]["clusters"] == 1024
        assert summary["arm_signed_level_utility"]["per_round"]["clusters"] == 1
        assert "work override in effect" in " ".join(summary["problems"])
        assert summary["trump_ranks"] == list(RANKS) and summary["trump_ranks_dealt"] == ["2"]
        # A rerun reopens the completed pair instead of replaying it.
        again = S.run_arm(config, output=tmp_path / arm, workers=1, log=lambda s: None,
                          executor_factory=threads)
        assert again["work_totals"] == summary["work_totals"]
        assert again["per_cluster_arm_utility"] == summary["per_cluster_arm_utility"]
    combined = S.combined_summary(summaries, seed0=431, replicates=50)
    assert set(combined["arms"]) == set(S.ARMS)
    assert combined["learned_minus_prior"]["clusters"] == 1
    assert combined["equal_work_strength_claim"] is False
    _publish(tmp_path / "summary.json", combined)


def test_build_config_refuses_missing_artifacts_and_unblinded_environment(monkeypatch, artifacts):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(S.ScreenError, match="--checkpoint"):
        S.build_config(arm="learned", leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=1)
    with pytest.raises(S.ScreenError, match="--prior"):
        S.build_config(arm="prior", leaf_tricks=1, seed0=1, clusters=1, arm_select_worlds=1)
    with pytest.raises(S.ScreenError, match="30 paired worlds"):
        tiny_config("learned", artifacts, report_worlds=10)
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS")
    with pytest.raises(S.ScreenError, match="SHENGJI_REQUIRE_VOIDS"):
        tiny_config("learned", artifacts)


def test_calibrate_freezes_a_cpu_only_choice_and_is_resumable(monkeypatch, tmp_path, artifacts):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    config = tiny_config("learned", artifacts)
    calibration = S.calibrate(config, output=tmp_path, workers=1, grid=(1, 2),
                              log=lambda s: None, executor_factory=threads)
    on_disk = S.load_calibration(tmp_path / "calibration.json")
    assert on_disk["outcomes_read"] is False and on_disk["schema"] == S.CALIBRATION_SCHEMA
    assert [row["n"] for row in on_disk["grid"]] == [1, 2]
    assert all(row["decision_cpu_ratio"] > 0 for row in on_disk["grid"])
    assert on_disk["chosen_arm_select_worlds"] == calibration["chosen_arm_select_worlds"] >= 1
    assert "utility" not in json.dumps(on_disk)
    assert (tmp_path / "n-001" / "cluster-00000.json").exists()
    again = S.calibrate(config, output=tmp_path, workers=1, grid=(1, 2), log=lambda s: None,
                        executor_factory=threads)
    assert again["grid"] == calibration["grid"]
    run_config = S.build_config(arm="learned", leaf_tricks=1, seed0=431, clusters=1,
                                arm_select_worlds=on_disk["chosen_arm_select_worlds"],
                                checkpoint=artifacts["checkpoint"], calibration=on_disk,
                                baseline_select_worlds=1, report_worlds=30)
    assert run_config["calibration"]["file_sha256"] == on_disk["file_sha256"]
    assert run_config["arm_select_worlds"] == on_disk["chosen_arm_select_worlds"]
    assert on_disk["trump_ranks"] == run_config["calibration"]["trump_ranks"] == list(RANKS)


# ------------------------------------------------------------ trump ranks

def test_trump_ranks_pin_every_round_and_the_summary(monkeypatch, artifacts):
    """--trump-ranks 2 on cluster 1, which #222's cycle would deal rank 3."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    config = tiny_config("prior", artifacts, clusters=2, trump_ranks=("2",))
    assert config["trump_ranks"] == ["2"]
    shard = S.run_cluster(config, 1)
    assert shard["rank"] == "2"
    assert [r["trump_rank"] for r in shard["records"]] == ["2", "2"]
    summary = S.summary_for([shard], config)
    assert summary["trump_ranks"] == ["2"] and summary["trump_ranks_dealt"] == ["2"]
    assert not any("outside the configured cycle" in p for p in summary["problems"])
    assert S.combined_summary({"prior": summary}, seed0=431, replicates=10)["arms"]["prior"][
        "trump_ranks"] == ["2"]
    default = tiny_config("prior", artifacts, clusters=2)
    assert default["trump_ranks"] == list(RANKS)
    assert S.cycle_rank(default, 1) == "3" and S.cycle_rank(default, 13) == "2"
    assert S.parse_trump_ranks("2, 9") == ("2", "9")
    for bad in ("", "2,2", "Z", "2,,3"):
        with pytest.raises(S.ScreenError):
            S.parse_trump_ranks(bad)
    with pytest.raises(S.ScreenError, match="unknown trump rank"):
        tiny_config("prior", artifacts, trump_ranks=("2", "Z"))


def test_witness_ignored_trump_ranks_flag_is_caught(monkeypatch, artifacts):
    """Mutant: the cluster driver deals #222's 13-rank cycle whatever the flag."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "cycle_rank", lambda config, cluster: RANKS[cluster % len(RANKS)])
    config = tiny_config("prior", artifacts, clusters=2, trump_ranks=("2",))
    shard = S.run_cluster(config, 1)
    assert shard["rank"] == "3"                               # the pin above is RED
    assert [r["trump_rank"] for r in shard["records"]] == ["3", "3"]
    summary = S.summary_for([shard], config)
    assert summary["trump_ranks"] == ["2"] and summary["trump_ranks_dealt"] == ["3"]
    assert any("outside the configured cycle" in p for p in summary["problems"])


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _calibration_file(path, artifacts, **extra):
    """A calibration bound to the test artifacts' matchup (tiny work), with
    ``extra`` overriding fields."""
    _publish(path, {"schema": S.CALIBRATION_SCHEMA, "outcomes_read": False,
                    "chosen_arm_select_worlds": 3,
                    "checkpoint_sha256": _sha(artifacts["checkpoint"]), "leaf_tricks": 1,
                    "baseline_policy": S.VLEAF_BASE_POLICY, "baseline_select_worlds": 1,
                    "report_worlds": 30, **extra})
    return S.load_calibration(path)


def test_run_refuses_a_calibration_made_on_other_trump_ranks(monkeypatch, artifacts, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rank2 = _calibration_file(tmp_path / "rank2.json", artifacts, trump_ranks=["2"])
    config = tiny_config("learned", artifacts, calibration=rank2, trump_ranks=("2",))
    assert config["trump_ranks"] == config["calibration"]["trump_ranks"] == ["2"]
    with pytest.raises(S.ScreenError, match="re-calibrate on the same ranks"):
        tiny_config("learned", artifacts, calibration=rank2)               # default cycle
    with pytest.raises(S.ScreenError, match="re-calibrate on the same ranks"):
        tiny_config("learned", artifacts, calibration=rank2, trump_ranks=("3",))
    # A calibration written before the option existed was made on the default cycle.
    legacy = _calibration_file(tmp_path / "legacy.json", artifacts)
    assert tiny_config("learned", artifacts, calibration=legacy)["trump_ranks"] == list(RANKS)
    with pytest.raises(S.ScreenError, match="re-calibrate on the same ranks"):
        tiny_config("learned", artifacts, calibration=legacy, trump_ranks=("2",))


def test_witness_removed_trump_rank_check_accepts_a_mismatch(monkeypatch, artifacts, tmp_path):
    """Mutant: the calibration/run rank check is a no-op."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_matching_trump_ranks", lambda calibration, trump_ranks: None)
    rank2 = _calibration_file(tmp_path / "rank2.json", artifacts, trump_ranks=["2"])
    config = tiny_config("learned", artifacts, calibration=rank2, trump_ranks=("3",))
    assert config["trump_ranks"] == ["3"] and config["calibration"]["trump_ranks"] == ["2"]


# ------------------------------------------------- bound artifacts (PR #226)

def test_worker_uses_the_bound_prior_bytes_and_refuses_tampering(monkeypatch, tmp_path, artifacts):
    """The file changes after the config bound it: a spawned worker (empty
    loader cache, no registered arm) still runs the bound bytes."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    path = tmp_path / "prior.json"
    _publish(path, prior_table().to_dict())
    config = tiny_config("prior", {**artifacts, "prior": str(path)})
    bound = config["prior_sha256"]
    assert bound == _sha(path) and json.loads(config["prior_bytes"])["schema"] == L.POINTS_PRIOR_SCHEMA
    _publish(path, prior_table(sums=[200.0] * N_STRATA, counts=[1] * N_STRATA).to_dict())
    L.load_points_prior.cache_clear()
    monkeypatch.delitem(REGISTRY, config["arm_policy"], raising=False)
    bot = S.make_side(config, "arm", 1)
    assert bot.leaf.table.provenance["file_sha256"] == bound != _sha(path)
    assert bot.leaf.table.prior.global_mean != 200.0
    assert bot.policy_name == config["arm_policy"] and bot.LEAF_TRICKS == 1
    # Tampered carried bytes, or none at all, refuse.
    with pytest.raises(S.ScreenError, match="prior table bytes differ"):
        S.make_side(dict(config, prior_bytes=path.read_text()), "arm", 1)
    with pytest.raises(S.ScreenError, match="carries no prior bytes"):
        S.make_side({k: v for k, v in config.items() if k != "prior_bytes"}, "arm", 1)
    # The learned arm: the file and the loaded head must be the bound bytes.
    learned = tiny_config("learned", artifacts)
    with pytest.raises(S.ScreenError, match="checkpoint file bytes differ"):
        S.make_side(dict(learned, checkpoint_sha256="0" * 64), "arm", 1)
    assert S.make_side(learned, "arm", 1).leaf.head.metadata["checkpoint_sha256"] \
        == learned["checkpoint_sha256"]


def test_witness_removed_bytes_binding_runs_tampered_prior_bytes(monkeypatch, tmp_path, artifacts):
    """Mutant: the bytes check is a no-op."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_bound_bytes", lambda what, actual, expected: None)
    path = tmp_path / "prior.json"
    _publish(path, prior_table().to_dict())
    config = tiny_config("prior", {**artifacts, "prior": str(path)})
    _publish(path, prior_table(sums=[200.0] * N_STRATA, counts=[1] * N_STRATA).to_dict())
    bot = S.make_side(dict(config, prior_bytes=path.read_text()), "arm", 1)
    assert bot.leaf.table.prior.global_mean == 200.0          # the refusal above is RED


def test_run_refuses_a_calibration_for_another_matchup(monkeypatch, tmp_path, artifacts):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    good = _calibration_file(tmp_path / "good.json", artifacts)
    learned = tiny_config("learned", artifacts, calibration=good)
    assert learned["calibration"]["checkpoint_sha256"] == learned["checkpoint_sha256"]
    prior = tiny_config("prior", artifacts, calibration=good)
    assert prior["companion_checkpoint_sha256"] == good["checkpoint_sha256"]
    with pytest.raises(S.ScreenError, match="binds the learned arm's checkpoint"):
        S.build_config(arm="prior", leaf_tricks=1, seed0=431, clusters=1, arm_select_worlds=1,
                       prior=artifacts["prior"], calibration=good, baseline_select_worlds=1,
                       report_worlds=30)
    for field, value in (("checkpoint_sha256", "a" * 64), ("leaf_tricks", 4),
                         ("baseline_policy", "mc-strong"), ("baseline_select_worlds", 30),
                         ("report_worlds", 300)):
        bad = _calibration_file(tmp_path / f"bad-{field}.json", artifacts, **{field: value})
        with pytest.raises(S.ScreenError, match=f"another matchup.*{field}"):
            tiny_config("learned", artifacts, calibration=bad)
        with pytest.raises(S.ScreenError, match=f"another matchup.*{field}"):
            tiny_config("prior", artifacts, calibration=bad)
    # Through the CLI the mismatch never reaches the compute-launch boundary.
    spec = importlib.util.spec_from_file_location("vleaf_cli", SERVER / "scripts/vleaf_screen.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    reached = []
    monkeypatch.setattr(S, "run_arm", lambda config, **kw: reached.append(config))
    bad = tmp_path / "bad-cli.json"
    _publish(bad, dict(json.loads((tmp_path / "bad-leaf_tricks.json").read_text()),
                       within_band=True, within_grid=True, predicted_decision_cpu_ratio=1.0))
    code = cli.main(["run", "--checkpoint", artifacts["checkpoint"], "--prior", artifacts["prior"],
                     "--calibration", str(bad), "--arms", "learned", "--out", str(tmp_path / "out"),
                     "--baseline-select-worlds", "1", "--report-worlds", "30"])
    assert code == 2 and not reached


def test_witness_removed_calibration_binding_accepts_another_matchup(monkeypatch, tmp_path,
                                                                     artifacts):
    """Mutant: the calibration identity check is a no-op."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "require_matching_calibration", lambda calibration, **kw: None)
    bad = _calibration_file(tmp_path / "bad.json", artifacts, checkpoint_sha256="a" * 64,
                            leaf_tricks=4)
    config = tiny_config("learned", artifacts, calibration=bad)
    assert config["calibration"]["checkpoint_sha256"] == "a" * 64 != config["checkpoint_sha256"]
    assert config["calibration"]["leaf_tricks"] == 4 != config["leaf_tricks"]   # refusal RED
