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


def test_real_synthetic_transport_pipeline_reaches_actor_readout(tmp_path, monkeypatch):
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
    for policy in readout.POLICIES:
        dry = panel.run_row(
            row=policy, model_paths={}, prepared_roots_from=roots,
            prepared_roots_sha256=roots_sha, output=tmp_path / f"dry-{policy}",
            seeds=seeds, actor_only=True, run=False,
            failure_protocol=PRESERVE_ILLEGAL, invalid_action_feedback=True,
            classify_final_action_failures=True, wall_seconds=60,
            token_limit=1_000_000, timeout_seconds=10)
        expected[policy] = copy.deepcopy(dry["config"])
        expected[policy]["run"] = True
        output = tmp_path / policy
        reports[policy] = panel.run_row(
            row=policy, model_paths={}, prepared_roots_from=roots,
            prepared_roots_sha256=roots_sha, output=output, seeds=seeds,
            actor_only=True, run=True,
            failure_protocol=PRESERVE_ILLEGAL, invalid_action_feedback=True,
            classify_final_action_failures=True, wall_seconds=60,
            token_limit=1_000_000, timeout_seconds=10)
    result = readout.analyze_actor_panel_reports(reports, expected, bootstrap_seed=23)

    assert result["status"] == "complete"
    assert result["comparison"]["clean_complete_coverage"] is True
    assert result["comparison"]["complete_deal_seeds"] == seeds
    assert all(report["config"]["information"] == ["actor-only"] for report in reports.values())
    refs = {}
    for policy in readout.POLICIES:
        path = tmp_path / policy / "result.json"
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
