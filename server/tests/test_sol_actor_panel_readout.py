import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import sol_actor_panel_readout as readout
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, summarize_scheduled


SEEDS = list(range(10))
ROOTS = {str(seed): f"{seed + 1:064x}" for seed in SEEDS}
SOURCE = "a" * 64


def _config(policy, *, run=True):
    return {
        "checkpoint": {"path": f"/synthetic/{policy}.npz", "sha256": "b" * 64},
        "policy": f"registered-{policy}",
        "seeds": list(SEEDS), "models": ["sol"], "information": ["actor-only"],
        "wall_seconds": 60, "soft_token_limit": 1_000_000, "run": run,
        "source": {"schema": "synthetic-source-v1", "tree": "a"},
        "claim": "benchmark execution only",
        "baseline_recipe": {"benchmark_id": policy, "policy": policy},
        "prepared_roots_from": {"path": "/synthetic/roots", "result_sha256": SOURCE,
                                "root_hashes": dict(ROOTS)},
        "failure_protocol": PRESERVE_ILLEGAL, "illegal_failure_limit": 8,
        "invalid_action_feedback": True, "classify_final_action_failures": True,
    }


def _report(policy, *, offset=0, rows=None):
    rows = [] if rows is None else rows
    if not rows:
        for seed in SEEDS:
            for flip in (0, 1):
                # The producer's signed score is opponent-perspective; a
                # negative value becomes a positive policy-perspective score.
                signed = -(seed + 1 + offset)
                rows.append({
                    "schema": "w32-llm-benchmark-mirror-v1",
                    "key": f"sol-actor-only-seed{seed}-flip{flip}",
                    "arm": "sol-actor-only", "model": "sol",
                    "information": "actor-only", "seed": seed, "flip": flip,
                    "complete": True, "signed_levels": signed,
                    "events": [], "calls": [],
                })
    result = {"schema": "w32-llm-benchmark-v1", "mode": "run",
              "config": _config(policy), "roots": dict(ROOTS),
              "prepared_roots": {"result_sha256": SOURCE, "root_hashes": dict(ROOTS)},
              "mirrors": rows}
    result["scheduled_summary"] = summarize_scheduled(rows)
    return result


def _expected_configs():
    return {policy: _config(policy) for policy in readout.POLICIES}


@pytest.mark.parametrize("field", ["wall_seconds", "serving_budget_seconds",
                                   "bury_serving_budget_seconds"])
@pytest.mark.parametrize("actual,accepted", [(3.0, True), (3.5, False),
                                             (True, False), (float("inf"), False),
                                             (float("nan"), False)])
def test_config_duration_numeric_equivalence_only(field, actual, accepted):
    expected = _config("smv3-pv")
    target = expected if field == "wall_seconds" else expected["baseline_recipe"]
    target[field] = 3
    observed = copy.deepcopy(expected)
    target = observed if field == "wall_seconds" else observed["baseline_recipe"]
    target[field] = actual
    if accepted:
        readout._validate_expected_config("smv3-pv", observed, expected, seeds=SEEDS)
    else:
        with pytest.raises(readout.ActorPanelReadoutError):
            readout._validate_expected_config("smv3-pv", observed, expected, seeds=SEEDS)


def test_config_duration_missing_key_and_unrelated_float_still_refuse():
    expected = _config("smv3-pv")
    for observed in (dict(expected, soft_token_limit=1_000_000.0),
                     {k: v for k, v in expected.items() if k != "wall_seconds"}):
        with pytest.raises(readout.ActorPanelReadoutError):
            readout._validate_expected_config("smv3-pv", observed, expected, seeds=SEEDS)


def test_valid_pair_negates_scores_uses_deal_clusters_and_classifies_positive():
    reports = {"smv3-pv": _report("smv3-pv", offset=0),
               "release46-pv": _report("release46-pv", offset=1)}
    result = readout.analyze_actor_panel_reports(reports, _expected_configs(), bootstrap_seed=17)

    assert result["status"] == "complete"
    assert result["comparison"]["complete_deal_seeds"] == SEEDS
    assert result["comparison"]["mean"] == 1.0
    assert result["comparison"]["ci95"][0] == 1.0
    assert result["comparison"]["classification"] == "POSITIVE"
    assert result["policies"]["smv3-pv"]["deal_mean"]["mean"] == 5.5
    assert result["policies"]["release46-pv"]["deal_mean"]["mean"] == 6.5
    assert result["policies"]["smv3-pv"]["coverage"]["complete_mirrors"] == 20


@pytest.mark.parametrize(("offset", "classification"), [
    (-1, "NEGATIVE"), (0, "INCONCLUSIVE"),
])
def test_clean_transfer_classification_requires_ci_direction(offset, classification):
    reports = {"smv3-pv": _report("smv3-pv"),
               "release46-pv": _report("release46-pv", offset=offset)}
    result = readout.analyze_actor_panel_reports(reports, _expected_configs())
    assert result["comparison"]["classification"] == classification


@pytest.mark.parametrize("mutation", ["keys", "mode", "roots", "model", "config",
                                       "recipe", "checkpoint", "registered-name", "seed-order"])
def test_invalid_report_identity_refuses(mutation):
    reports = {"smv3-pv": _report("smv3-pv"), "release46-pv": _report("release46-pv", offset=1)}
    if mutation == "keys":
        reports["extra"] = reports.pop("smv3-pv")
    elif mutation == "mode":
        reports["smv3-pv"]["config"]["information"] = ["perfect"]
    elif mutation == "roots":
        reports["release46-pv"]["roots"]["0"] = "c" * 64
    elif mutation == "model":
        reports["smv3-pv"]["config"]["models"] = ["luna"]
    elif mutation == "config":
        reports["release46-pv"]["config"]["wall_seconds"] = 61
    elif mutation == "recipe":
        reports["release46-pv"]["config"]["baseline_recipe"]["benchmark_id"] = "smv3-pv"
    elif mutation == "checkpoint":
        reports["release46-pv"]["config"]["checkpoint"]["sha256"] = "c" * 64
    elif mutation == "registered-name":
        reports["release46-pv"]["config"]["policy"] = "wrong-policy"
    else:
        reports["release46-pv"]["config"]["seeds"] = list(reversed(SEEDS))
    with pytest.raises(readout.ActorPanelReadoutError):
        readout.analyze_actor_panel_reports(reports, _expected_configs())


def _retained_failure(seed, flip):
    seat = flip
    event = {"seat": seat, "attempted_cards": ["SA"]}
    return {
        "schema": "w32-llm-benchmark-mirror-v1",
        "key": f"sol-actor-only-seed{seed}-flip{flip}",
        "arm": "sol-actor-only", "model": "sol", "information": "actor-only",
        "seed": seed, "flip": flip, "complete": False, "error": "synthetic illegal",
        "events": [event], "calls": [], "invalid_action_feedback": True,
        "classify_final_action_failures": True,
        "failure": {"schema": "benchmark-action-failure-v1", "category": "model_illegal_action",
                     "stage": "engine_play", "seat": seat, "attempted_cards": ["SA"],
                     "event_index": 0},
    }


def test_terminal_failure_contract_preserves_unattempted_coverage_and_blocks_positive_claim():
    rows = []
    for seed in SEEDS:
        for flip in (0, 1):
            rows.append(_retained_failure(seed, flip) if seed < 4 else {
                "schema": "w32-llm-benchmark-mirror-v1",
                "key": f"sol-actor-only-seed{seed}-flip{flip}",
                "arm": "sol-actor-only", "model": "sol", "information": "actor-only",
                "seed": seed, "flip": flip, "complete": False, "status": "not_run",
                "error": "stopped", "events": [], "calls": [],
            })
    reports = {"smv3-pv": _report("smv3-pv", rows=copy.deepcopy(rows)),
               "release46-pv": _report("release46-pv", offset=1)}
    # Terminal accounting is per policy; the complete endpoint remains valid
    # but the transfer is descriptive because one side has stopped slots.
    result = readout.analyze_actor_panel_reports(reports, _expected_configs())
    coverage = result["policies"]["smv3-pv"]["coverage"]
    assert coverage["failed_mirrors"] == 8
    assert coverage["unattempted_mirrors"] == 12
    assert result["status"] == "partial"
    assert result["comparison"]["classification"] == "PARTIAL"


def test_arbitrary_wall_partial_fails_terminal_contract():
    reports = {"smv3-pv": _report("smv3-pv"), "release46-pv": _report("release46-pv", offset=1)}
    reports["smv3-pv"]["mirrors"][0].update(complete=False, status="not_run", error="stopped")
    reports["smv3-pv"]["mirrors"][0].pop("signed_levels")
    reports["smv3-pv"]["scheduled_summary"] = summarize_scheduled(
        reports["smv3-pv"]["mirrors"])
    with pytest.raises(readout.ActorPanelReadoutError, match="terminal validation"):
        readout.analyze_actor_panel_reports(reports, _expected_configs())


def test_main_refuses_raw_disk_access():
    with pytest.raises(readout.ActorPanelReadoutError, match="decoded reports"):
        readout.main(["--reports", "/tmp/reports.json"])


@pytest.mark.parametrize("through_supervisor", [False, True])
def test_real_synthetic_transport_pipeline_reaches_actor_readout(tmp_path, monkeypatch,
                                                               through_supervisor):
    """Prepared roots, engine mirrors, and terminal accounting reach the pure reader."""
    from scripts import prepare_llm_panel_roots as root_producer
    from scripts import production_llm_panel as panel
    from shengji.ai.heuristic import HeuristicBot
    from shengji.luna.benchmark_recipes import PreparedRecipe
    from test_llm_benchmark_games import planner

    seeds = list(range(10))
    roots = tmp_path / "roots"
    root_producer.prepare_roots(output=roots, seeds=seeds)
    roots_sha = hashlib.sha256((roots / "result.json").read_bytes()).hexdigest()

    def prepare(policy, _paths):
        identity = {
            "schema": "sol-panel-recipe-v1", "benchmark_id": policy,
            "policy": policy, "kind": "synthetic", "checkpoint": f"/synthetic/{policy}.npz",
            "sha256": "b" * 64, "play_only": True, "engine": "current",
        }
        return PreparedRecipe(policy=f"registered-{policy}",
                              factory=lambda seed=0: HeuristicBot(), identity=identity)

    monkeypatch.setattr(panel, "prepare_recipe", prepare)

    class FakeTransport:
        def __init__(self, **_kwargs):
            self.calls = []

        def __call__(self, packet):
            response = planner(packet)
            self.calls.append(packet)
            return response

    real_run_benchmark = panel.run_benchmark
    monkeypatch.setattr(
        panel, "run_benchmark",
        lambda **kwargs: real_run_benchmark(**kwargs, transport_factory=FakeTransport))

    expected = {}
    reports = {}
    outputs = tmp_path / "campaign-output" if through_supervisor else tmp_path
    for policy in readout.POLICIES:
        dry = panel.run_row(
            row=policy, model_paths={}, prepared_roots_from=roots,
            prepared_roots_sha256=roots_sha, output=tmp_path / f"dry-{policy}",
            seeds=seeds, actor_only=True, run=False,
            failure_protocol=PRESERVE_ILLEGAL, invalid_action_feedback=True,
            classify_final_action_failures=True, wall_seconds=21600.0,
            token_limit=20_000_000, timeout_seconds=300)
        expected[policy] = copy.deepcopy(dry["config"])
        expected[policy]["run"] = True
        if not through_supervisor:
            reports[policy] = panel.run_row(
                row=policy, model_paths={}, prepared_roots_from=roots,
                prepared_roots_sha256=roots_sha, output=outputs / policy, seeds=seeds,
                actor_only=True, run=True,
                failure_protocol=PRESERVE_ILLEGAL, invalid_action_feedback=True,
                classify_final_action_failures=True, wall_seconds=21600.0,
                token_limit=20_000_000, timeout_seconds=300)
    if through_supervisor:
        from scripts import launch_production_llm_panel as launcher
        from test_launch_production_llm_panel import _real_validation_fixture
        fixture = tmp_path / "launch-fixture"
        fixture.mkdir()
        config_path, _, _ = _real_validation_fixture(fixture)
        config = json.loads(config_path.read_text())
        config.update(
            schema=launcher.ACTOR_PANEL_SCHEMA, rows=list(readout.POLICIES),
            row_wall_seconds=21600, row_soft_tokens=20_000_000,
            provider_call_seconds=300, seeds=seeds, output=str(outputs),
            prepared_roots=str(roots), prepared_roots_sha256=roots_sha,
            failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8,
            provider_capacity_retry_delays=[], recovery_controls={
                "capacity_retries": False, "accept_recovered_reconnects": False,
                "invalid_action_feedback": True, "classify_final_action_failures": True})
        config_path.write_text(json.dumps(config, sort_keys=True))
        config_sha = _plan_pin(config_path)
        (fixture / "RELEASE").write_text(config_sha)
        monkeypatch.setattr(launcher, "LOCK", tmp_path / "host-lock")
        monkeypatch.setattr(launcher.os, "nice", lambda _: 10)
        monkeypatch.setattr(launcher, "_require_recovery_memory", lambda _: None)
        commands = []

        def supervise(command, **kwargs):
            from contextlib import redirect_stdout
            commands.append(command)
            assert command[3] == "scripts.production_llm_panel"
            assert kwargs["wall"] == 21630
            with redirect_stdout(kwargs["log"]):
                assert panel.main(command[4:]) == 0
            return {"row": kwargs["row"], "pid": 123, "returncode": 0,
                    "status": "exited", "elapsed_seconds": 0.1}

        monkeypatch.setattr(launcher, "supervise", supervise)
        terminal = launcher.run(config_path, config_sha, arm=True)
        assert terminal["status"] == "scheduled-terminal"
        assert len(commands) == 2
        assert not (outputs / "panel-readout.json").exists()
        assert not (tmp_path / "host-lock").exists()
        reports = {policy: json.loads((outputs / policy / "result.json").read_text())
                   for policy in readout.POLICIES}
    result = readout.analyze_actor_panel_reports(reports, expected, bootstrap_seed=23)

    assert result["status"] == "complete"
    assert result["comparison"]["clean_complete_coverage"] is True
    assert result["comparison"]["complete_deal_seeds"] == seeds
    assert all(report["config"]["information"] == ["actor-only"] for report in reports.values())
    refs = {}
    for policy in readout.POLICIES:
        path = outputs / policy / "result.json"
        refs[policy] = {"path": str(path), "sha256": _plan_pin(path)}
    plan_path = tmp_path / "sealed-pipeline-plan.json"
    plan_path.write_text(json.dumps({"schema": readout.PLAN_SCHEMA,
                                    "report_refs": refs, "expected_configs": expected}))
    sealed = readout.read_sealed_actor_panel(plan_path, _plan_pin(plan_path))
    assert sealed["status"] == "complete"
    assert sealed["comparison"]["complete_deal_seeds"] == seeds
    assert sealed["comparison"]["clean_complete_coverage"] is True


def test_opposite_mirror_effects_are_clustered_before_bootstrap():
    reports = {policy: _report(policy) for policy in readout.POLICIES}
    for row in reports["smv3-pv"]["mirrors"]:
        row["signed_levels"] = 0
    for row in reports["release46-pv"]["mirrors"]:
        row["signed_levels"] = -3 if row["flip"] == 0 else 1
    for report in reports.values():
        report["scheduled_summary"] = summarize_scheduled(report["mirrors"])
    result = readout.analyze_actor_panel_reports(reports, _expected_configs())
    paired = result["comparison"]["paired_delta"]
    assert paired["count"] == 10
    assert paired["values"] == [1.0] * 10
    assert paired["ci95"] == [1.0, 1.0]


def _sealed_plan(tmp_path):
    reports = {"smv3-pv": _report("smv3-pv"),
               "release46-pv": _report("release46-pv", offset=1)}
    refs = {}
    for policy, report in reports.items():
        path = tmp_path / f"{policy}.json"
        path.write_bytes(json.dumps(report, separators=(",", ":")).encode())
        refs[policy] = {"path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    plan = {"schema": readout.PLAN_SCHEMA, "report_refs": refs,
            "expected_configs": _expected_configs()}
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(json.dumps(plan, separators=(",", ":")).encode())
    return plan, plan_path, reports


def test_sealed_reader_accepts_cli_float_durations_with_integer_plan(tmp_path):
    plan, plan_path, reports = _sealed_plan(tmp_path)
    for policy, report in reports.items():
        expected = plan["expected_configs"][policy]
        expected["baseline_recipe"]["serving_budget_seconds"] = 3
        expected["baseline_recipe"]["bury_serving_budget_seconds"] = None
        report["config"]["wall_seconds"] = float(expected["wall_seconds"])
        report["config"]["baseline_recipe"]["serving_budget_seconds"] = 3.0
        report["config"]["baseline_recipe"]["bury_serving_budget_seconds"] = None
        if policy == "release46-pv":
            expected["baseline_recipe"]["bury_serving_budget_seconds"] = 2
            report["config"]["baseline_recipe"]["bury_serving_budget_seconds"] = 2.0
        path = Path(plan["report_refs"][policy]["path"])
        path.write_text(json.dumps(report))
        plan["report_refs"][policy]["sha256"] = _plan_pin(path)
    plan_path.write_text(json.dumps(plan))
    result = readout.read_sealed_actor_panel(plan_path, _plan_pin(plan_path))
    assert result["status"] == "complete"
    assert result["comparison"]["mean"] == 1.0


def _plan_pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sealed_entrypoint_authenticates_plan_and_reads_each_report_once(tmp_path, monkeypatch):
    _, plan_path, _ = _sealed_plan(tmp_path)
    reads = []
    original = Path.read_bytes

    def tracked(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    result = readout.read_sealed_actor_panel(plan_path, _plan_pin(plan_path))
    assert result["comparison"]["classification"] == "POSITIVE"
    assert result["seals"]["metadata_and_content_validated"] is True
    assert sum(path.name == "smv3-pv.json" for path in reads) == 1
    assert sum(path.name == "release46-pv.json" for path in reads) == 1


@pytest.mark.parametrize("mutation", ["wrong-plan-pin", "wrong-ref-set",
                                       "relative-path", "report-digest",
                                       "wrong-expected-config"])
def test_sealed_entrypoint_refuses_invalid_plan_before_report_reads(tmp_path, mutation,
                                                                    monkeypatch):
    plan, plan_path, _ = _sealed_plan(tmp_path)
    report_reads = []
    original = Path.read_bytes

    def tracked(path):
        if path.name in {"smv3-pv.json", "release46-pv.json"}:
            report_reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    if mutation == "wrong-plan-pin":
        pin = "0" * 64
    else:
        if mutation == "wrong-ref-set":
            plan["report_refs"]["extra"] = plan["report_refs"].pop("smv3-pv")
        elif mutation == "relative-path":
            plan["report_refs"]["smv3-pv"]["path"] = "relative/report.json"
        elif mutation == "report-digest":
            plan["report_refs"]["smv3-pv"]["sha256"] = "0" * 64
        else:
            plan["expected_configs"]["smv3-pv"]["models"] = ["luna"]
        plan_path.write_bytes(json.dumps(plan, separators=(",", ":")).encode())
        pin = _plan_pin(plan_path)
    with pytest.raises(readout.ActorPanelReadoutError):
        readout.read_sealed_actor_panel(plan_path, pin)
    # A digest mismatch is discovered by hashing that pinned report's bytes;
    # malformed metadata is rejected before either report is opened.
    if mutation != "report-digest":
        assert report_reads == []


def test_sealed_entrypoint_rejects_symlink_report(tmp_path):
    _, plan_path, _ = _sealed_plan(tmp_path)
    target = tmp_path / "smv3-pv.json"
    link = tmp_path / "smv3-link.json"
    link.symlink_to(target)
    plan = json.loads(plan_path.read_text())
    plan["report_refs"]["smv3-pv"]["path"] = str(link)
    plan["report_refs"]["smv3-pv"]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    plan_path.write_text(json.dumps(plan, separators=(",", ":")))
    with pytest.raises(readout.ActorPanelReadoutError):
        readout.read_sealed_actor_panel(plan_path, _plan_pin(plan_path))


def test_sealed_cli_emits_validated_result_without_writing_files(tmp_path, capsys):
    _, path, _ = _sealed_plan(tmp_path)
    before = set(tmp_path.iterdir())
    assert readout.main(["--plan", str(path), "--plan-sha256", _plan_pin(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["comparison"]["classification"] == "POSITIVE"
    assert set(tmp_path.iterdir()) == before
