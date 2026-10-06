from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from scripts import production_llm_panel_readout as readout
from scripts import prepare_llm_panel_roots as root_producer
from scripts import w32_llm_benchmark as benchmark
from shengji.luna.benchmark_recipes import prepare_recipe

from test_llm_benchmark_games import planner
from test_luna_transport import trace

SCHEMA = "w32-llm-benchmark-v1"


SEEDS = list(range(10))
ROOTS = {str(seed): f"{seed:064x}" for seed in SEEDS}
SOURCE_SHA = "a" * 64


def _report(tmp_path, benchmark_id, *, offset=0, failed=False, source=SOURCE_SHA,
            roots=None, omit_rollouts=False):
    roots = ROOTS if roots is None else roots
    mirrors = []
    for information in ("actor-only", "perfect"):
        for seed in SEEDS:
            for flip in (0, 1):
                # The producer stores opponent-perspective values.  A negative
                # value therefore becomes a positive policy-minus-Sol readout.
                raw_score = -(seed + 1 + offset) if information == "perfect" else seed + 1 + offset
                row = {
                    "schema": "w32-llm-benchmark-mirror-v1",
                    "key": f"sol-{information}-seed{seed}-flip{flip}",
                    "arm": f"sol-{information}", "model": "sol",
                    "information": information, "seed": seed, "flip": flip,
                    "complete": True, "signed_levels": raw_score,
                    "wall_seconds": 1.0 + seed / 10,
                    "events": [{"wall_seconds": 0.1}],
                    "calls": [{"usage": {"input_tokens": 2, "output_tokens": 3}}],
                }
                if not omit_rollouts:
                    row["rollout_usage"] = {
                        "requested_batches": 1, "attempted_evaluations": 2,
                        "completed_evaluations": 2, "completed_world_rollouts": 16,
                    }
                if failed and information == "actor-only" and seed == 0 and flip == 1:
                    row.update(complete=False, error="synthetic failure")
                    row.pop("signed_levels")
                mirrors.append(row)
    result = {
        "schema": SCHEMA, "mode": "run",
        "config": {
            "seeds": SEEDS, "models": ["sol"],
            "information": ["actor-only", "perfect"],
            "policy": "registered-" + benchmark_id,
            "baseline_recipe": {"benchmark_id": benchmark_id, "policy": benchmark_id},
            "prepared_roots_from": {"result_sha256": source, "root_hashes": roots},
        },
        "roots": roots,
        "prepared_roots": {"result_sha256": source, "root_hashes": roots},
        "mirrors": mirrors,
    }
    path = tmp_path / benchmark_id
    path.mkdir()
    (path / "result.json").write_text(json.dumps(result))
    return path


def _panel(tmp_path, *, failed=False, omit_rollouts=False):
    return {benchmark_id: _report(tmp_path, benchmark_id, offset=index,
                                   failed=failed and index == 0,
                                   omit_rollouts=omit_rollouts and index == 0)
            for index, benchmark_id in enumerate(readout.POLICIES)}


def _stage1_reports(tmp_path):
    from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, summarize_scheduled
    reports, contexts = {}, {}
    for index, key in enumerate(('smv3-pv', 'm1-prior')):
        path = _report(tmp_path, key, offset=index)
        report = json.loads((path / 'result.json').read_text())
        report['config'].update(invalid_action_feedback=True,
                                failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8)
        for row in report['mirrors']:
            row['invalid_action_feedback'] = True
            row['final_action_feedback_counts'] = dict(
                decisions_with_rejections=1, rejected_attempts=1,
                corrected_decisions=1, exhausted_decisions=0, interrupted_decisions=0)
        report['scheduled_summary'] = summarize_scheduled(report['mirrors'])
        reports[key] = report
        contexts[key] = dict(seeds=SEEDS, source_result_sha256=SOURCE_SHA, root_hashes=ROOTS)
    return reports, contexts


def test_stage1_reuses_paired_scoring_without_historical_rows(tmp_path):
    reports, contexts = _stage1_reports(tmp_path)
    result = readout.analyze_stage1_reports(reports, contexts)
    assert result['schema'] == 'sol-feedback-on-stage1-readout-v1'
    assert result['panel_size'] == 2
    assert len(result['row_differences']) == 1
    assert result['policies']['smv3-pv']['sol']['paired_signed_levels']['mean'] == -5.5
    assert result['policies']['smv3-pv']['pt_sol']['paired_signed_levels']['mean'] == 5.5
    assert result['row_differences'][0]['sol']['mean'] == 1
    counts = result['policies']['smv3-pv']['sol']['final_action_feedback_counts']
    assert counts['corrected_decisions'] == 20
    assert counts['exhausted_decisions'] == counts['interrupted_decisions'] == 0


@pytest.mark.parametrize('mutation', ['off', 'missing', 'extra', 'retained', 'roots', 'unknown_failure',
                                      'mirror_off', 'counts_missing', 'counts_drift'])
def test_stage1_refuses_mixed_or_unadmitted_results(tmp_path, mutation):
    reports, contexts = _stage1_reports(tmp_path)
    report = reports['smv3-pv']
    if mutation == 'off':
        report['config']['invalid_action_feedback'] = False
    elif mutation == 'missing':
        reports.pop('m1-prior')
    elif mutation == 'extra':
        reports['smart'] = report
    elif mutation == 'retained':
        report['config']['retained_attempts'] = {'source': 'old-OFF'}
    elif mutation == 'roots':
        contexts['smv3-pv'] = dict(contexts['smv3-pv'], source_result_sha256='b' * 64)
    elif mutation == 'mirror_off':
        report['mirrors'][0]['invalid_action_feedback'] = False
    elif mutation == 'counts_missing':
        report['mirrors'][0].pop('final_action_feedback_counts')
    elif mutation == 'counts_drift':
        report['mirrors'][0]['final_action_feedback_counts']['interrupted_decisions'] = 1
    else:
        report['mirrors'][0].update(complete=False, error='unknown')
    with pytest.raises(ValueError):
        readout.analyze_stage1_reports(reports, contexts)


@pytest.mark.parametrize('outcome', ['legal', 'corrected', 'exhausted', 'interrupted', 'tool_overflow'])
def test_stage1_real_runner_to_reader(tmp_path, monkeypatch, outcome):
    """Real roots, scheduler, engine, feedback and terminal; synthetic policy/provider.

    Static factories stand in for neural recipes. This is a consumer contract
    witness, not model-load qualification or a scientific result.
    """
    from dataclasses import replace
    from scripts import production_llm_panel as panel
    from scripts import launch_production_llm_panel as launcher
    from test_launch_production_llm_panel import _real_validation_fixture
    from test_launch_sol_recovery import _stage1

    config_path, _, _ = _real_validation_fixture(tmp_path)
    config = _stage1(json.loads(config_path.read_text()))
    roots = tmp_path / 'real-roots'
    root_producer.prepare_roots(output=roots, seeds=SEEDS)
    config.update(prepared_roots=str(roots),
                  prepared_roots_sha256=hashlib.sha256((roots / 'result.json').read_bytes()).hexdigest())
    config_path.write_text(json.dumps(config))
    digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    (tmp_path / 'RELEASE').write_text(digest + '\n')
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    monkeypatch.setattr(launcher.os, 'nice', lambda increment: 10)
    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom', lambda: True)

    class FakeTransport:
        def __init__(self, **kwargs):
            self.calls = []
        def __call__(self, packet):
            if outcome == 'tool_overflow':
                return {'evaluations': [{'cards': [], 'continuation': 'heuristic-all'}],
                        'memory': ''}
            if outcome == 'interrupted' and packet['final_action_errors']:
                raise RuntimeError('synthetic provider interruption after feedback')
            if outcome == 'exhausted' or (outcome in ('corrected', 'interrupted')
                                          and not packet['final_action_errors']):
                return {'cards': [], 'memory': ''}
            return planner(packet)

    real_runner = panel.run_benchmark
    monkeypatch.setattr(panel, 'run_benchmark', lambda **kwargs: real_runner(
        **kwargs, transport_factory=FakeTransport))
    static = prepare_recipe('smart', {})
    monkeypatch.setattr(panel, 'prepare_recipe', lambda row, paths: replace(
        static, identity=dict(static.identity, benchmark_id=row)))
    reports, contexts = {}, {}

    def supervise(command, *, row, output, **kwargs):
        assert '--invalid-action-feedback' in command
        assert '--retention-plan' not in command
        reports[row] = panel.run_row(
            row=row, model_paths={}, seeds=SEEDS, output=output,
            prepared_roots_from=roots,
            prepared_roots_sha256=config['prepared_roots_sha256'],
            codex_binary=config['codex_binary'], run=True,
            capacity_retries=True, invalid_action_feedback=True,
            classify_final_action_failures=True, failure_protocol=launcher.PRESERVE_ILLEGAL)
        contexts[row] = dict(seeds=SEEDS, source_result_sha256=config['prepared_roots_sha256'],
                             root_hashes=reports[row]['roots'])
        return {'returncode': 0, 'status': 'exited', 'row': row}

    monkeypatch.setattr(launcher, 'supervise', supervise)
    if outcome == 'interrupted':
        with pytest.raises(ValueError):
            launcher.run(config_path, digest, arm=True)
        assert list(reports) == ['smv3-pv']
        failed = reports['smv3-pv']['mirrors'][0]
        assert failed['final_action_feedback_counts']['interrupted_decisions'] == 1
        assert failed['final_action_feedback_counts']['exhausted_decisions'] == 0
        assert (Path(config['output']) / 'smv3-pv' / 'result.json').exists()
        assert not (tmp_path / 'lock').exists()
        return
    terminal = launcher.run(config_path, digest, arm=True)
    assert terminal['status'] == 'scheduled-terminal'
    result = readout.analyze_stage1_reports(reports, contexts)
    for row in launcher.STAGE1_ROWS:
        counts = result['policies'][row]['sol']['final_action_feedback_counts']
        assert counts['exhausted_decisions'] == (8 if outcome == 'exhausted' else 0)
        assert (counts['corrected_decisions'] > 0) is (outcome == 'corrected')
        assert result['terminal_accounting'][row]['failed'] == (8 if outcome in ('exhausted', 'tool_overflow') else 0)
        assert result['terminal_accounting'][row]['completed'] == (0 if outcome in ('exhausted', 'tool_overflow') else 40)
        assert result['policies'][row]['sol']['tool_budget_exhausted_mirrors'] == (8 if outcome == 'tool_overflow' else 0)
    assert not (tmp_path / 'lock').exists()
    from scripts import sealed_production_llm_panel_readout as sealed
    def ref(path):
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    output = Path(config['output'])
    from scripts.prepare_stage1_seal_plan import prepare_stage1_seal_plan
    plan_dir = tmp_path / 'seal-plan'
    plan = prepare_stage1_seal_plan(config_path, digest, plan_dir)
    plan_path = plan_dir / 'result.json'
    admitted = sealed.read_sealed_stage1(plan_path, ref(plan_path)['sha256'])
    assert admitted['terminal_accounting'] == result['terminal_accounting']
    assert admitted['panel_size'] == 2
    # An authenticated but nonterminal campaign must refuse before result access.
    terminal_path = output / 'terminal.json'
    bad_terminal = json.loads(terminal_path.read_text())
    bad_terminal['status'] = 'failed'
    terminal_path.write_text(json.dumps(bad_terminal))
    plan['campaign']['terminal'] = ref(terminal_path)
    plan_path = tmp_path / 'bad-plan.json'
    plan_path.write_text(json.dumps(plan))
    real_metadata = sealed._metadata
    def no_results(reference, label):
        assert not label.endswith(' result'), 'raw results opened before metadata admission'
        return real_metadata(reference, label)
    monkeypatch.setattr(sealed, '_metadata', no_results)
    with pytest.raises(ValueError, match='not terminal'):
        sealed.read_sealed_stage1(plan_path, ref(plan_path)['sha256'])


def test_readout_negates_producer_sign_and_keeps_sol_pt_columns(tmp_path):
    result = readout.analyze_panel(_panel(tmp_path))
    row = result["policies"]["smv3-pv"]
    assert result["status"] == "complete"
    assert row["sol"]["information"] == "actor-only"
    assert row["pt_sol"]["information"] == "perfect"
    assert row["sol"]["paired_signed_levels"]["mean"] == -5.5
    assert row["pt_sol"]["paired_signed_levels"]["mean"] == 5.5
    assert row["sol"]["complete_pairs"] == row["pt_sol"]["complete_pairs"] == 10
    assert row["sol"]["rollout_usage"]["completed_world_rollouts"]["total"] == 320


def test_partial_failures_are_retained_and_differences_match_completed_deals(tmp_path):
    result = readout.analyze_panel(_panel(tmp_path, failed=True))
    row = result["policies"]["smv3-pv"]
    assert result["status"] == "partial"
    assert row["status"] == "partial"
    assert row["sol"]["failure_count"] == 1
    assert row["sol"]["failures"][0]["error"] == "synthetic failure"
    difference = next(item for item in result["row_differences"]
                      if item["left"] == "smv3-pv" and item["right"] == "soft-pv")
    assert difference["sol"]["count"] == 9
    assert difference["sol"]["ci95"] is not None


def test_missing_rollout_usage_is_unknown_not_zero(tmp_path):
    result = readout.analyze_panel(_panel(tmp_path, omit_rollouts=True))
    usage = result["policies"]["smv3-pv"]["sol"]["rollout_usage"]
    assert usage["completed_evaluations"]["total"] is None
    assert usage["completed_evaluations"]["unknown_mirrors"] == 20


def test_asymmetric_mirrors_are_averaged_once_per_deal(tmp_path):
    rows = _panel(tmp_path)
    path = rows["smv3-pv"] / "result.json"
    report = json.loads(path.read_text())
    for row in report["mirrors"]:
        # Deliberately unequal mirrors: a first-mirror-only implementation
        # would report -seed rather than -(seed + 2).
        row["signed_levels"] = row["seed"] + 4 * row["flip"]
        if row["information"] == "perfect":
            row["signed_levels"] *= -1
    report["mirrors"].reverse()
    path.write_text(json.dumps(report))
    result = readout.analyze_panel(rows)["policies"]["smv3-pv"]
    expected = [-(seed + 2.0) for seed in SEEDS]
    assert result["sol"]["paired_signed_levels"]["values"] == expected
    assert result["pt_sol"]["paired_signed_levels"]["values"] == [-v for v in expected]
    assert result["sol"]["paired_signed_levels"]["count"] == 10
    assert result["sol"]["deal_cluster_ci95"] == readout._bootstrap(
        expected, seed=readout.BOOTSTRAP_SEED)


def test_cross_policy_pairing_joins_seed_ids_not_survivor_positions(tmp_path):
    rows = _panel(tmp_path)
    for policy, missing_seed in (("smv3-pv", 0), ("soft-pv", 1)):
        path = rows[policy] / "result.json"
        report = json.loads(path.read_text())
        for row in report["mirrors"]:
            if row["seed"] == missing_seed and row["flip"] == 1:
                row.update(complete=False, error="synthetic missing mirror")
                row.pop("signed_levels")
        report["mirrors"].reverse()
        path.write_text(json.dumps(report))
    result = readout.analyze_panel(rows)
    difference = next(item for item in result["row_differences"]
                      if item["left"] == "smv3-pv" and item["right"] == "soft-pv")
    assert result["status"] == "partial"
    # Both rows have nine completed deals, but only eight COMMON deals.
    assert difference["sol"]["values"] == [1.0] * 8
    assert difference["pt_sol"]["values"] == [-1.0] * 8
    assert difference["sol"]["count"] == difference["pt_sol"]["count"] == 8


@pytest.mark.parametrize("foreign_roots", [False, True])
def test_split_serial_tail_continuation_layout_preserves_panel_contract(tmp_path, foreign_roots):
    """Synthetic only: the future tail does not require copying raw results."""
    locations = {name: tmp_path / name for name in ("serial", "tail", "continuation")}
    for location in locations.values():
        location.mkdir()
    rows = {}
    for index, policy in enumerate(readout.POLICIES):
        lane = ("serial" if policy in ("smv3-pv", "soft-pv") else
                "tail" if policy in ("smart", "mc") else "continuation")
        rows[policy] = _report(locations[lane], policy, offset=index,
                               source="b" * 64 if foreign_roots and policy == "smart" else SOURCE_SHA)
    if foreign_roots:
        with pytest.raises(readout.PanelReadoutError, match="share prepared-root"):
            readout.analyze_panel(rows)
        return
    result = readout.analyze_panel(rows)
    assert result["status"] == "complete"
    assert result["benchmark_ids"] == list(readout.POLICIES)
    assert sum(row["complete_mirrors"] for row in result["policies"].values()) == 360
    assert len(result["row_differences"]) == 36
    for policy, path in rows.items():
        row = result["policies"][policy]
        assert row["identity"]["directory"] == str(path.resolve())
        assert row["sol"]["complete_pairs"] == row["pt_sol"]["complete_pairs"] == 10
    difference = next(item for item in result["row_differences"]
                      if item["left"] == "smv3-pv" and item["right"] == "smart")
    assert difference["sol"]["values"] == [8.0] * 10
    assert difference["pt_sol"]["values"] == [-8.0] * 10


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), True, "1"])
def test_completed_mirror_rejects_nonfinite_or_non_numeric_score(tmp_path, bad_score):
    rows = _panel(tmp_path)
    path = rows["smv3-pv"] / "result.json"
    report = json.loads(path.read_text())
    report["mirrors"][0]["signed_levels"] = bad_score
    path.write_text(json.dumps(report))
    with pytest.raises(readout.PanelReadoutError, match="lacks signed_levels"):
        readout.analyze_panel(rows)


def test_duplicate_mirror_cannot_replace_missing_slot(tmp_path):
    rows = _panel(tmp_path)
    path = rows["smv3-pv"] / "result.json"
    report = json.loads(path.read_text())
    report["mirrors"][-1] = dict(report["mirrors"][0])
    path.write_text(json.dumps(report))
    with pytest.raises(readout.PanelReadoutError, match="not unique"):
        readout.analyze_panel(rows)


def test_common_root_identity_and_slot_validation_refuse(tmp_path):
    rows = _panel(tmp_path)
    # Reuse the valid identity but alter one admitted row directory's root hash.
    smart_result = rows["smart"] / "result.json"
    value = json.loads(smart_result.read_text())
    value["prepared_roots"]["root_hashes"]["0"] = "b" * 64
    smart_result.write_text(json.dumps(value))
    with pytest.raises(readout.PanelReadoutError, match="roots disagree"):
        readout.analyze_panel(rows)

    missing_root = tmp_path / "missing"
    missing_root.mkdir()
    rows = _panel(missing_root)
    report_path = rows["smart"] / "result.json"
    value = json.loads(report_path.read_text())
    value["mirrors"].pop()
    report_path.write_text(json.dumps(value))
    with pytest.raises(readout.PanelReadoutError, match="40 unique attempted slots"):
        readout.analyze_panel(rows)


@pytest.mark.parametrize("reconnect", [False, True])
def test_capacity_refusal_recovers_inside_real_game_without_replaying_root(tmp_path, monkeypatch, reconnect):
    from shengji.luna.benchmark_transport import BenchmarkTransport
    from shengji.luna.transport import InvocationResult
    monkeypatch.setattr("shengji.luna.benchmark_transport.time.sleep", lambda seconds: None)
    roots = tmp_path / "roots"
    root_producer.prepare_roots(output=roots, seeds=[7123])
    source_sha = hashlib.sha256((roots / "result.json").read_bytes()).hexdigest()
    recipe = prepare_recipe("smart", {})
    attempts = []

    def invoke(command, prompt, workspace, timeout):
        attempts.append(prompt)
        if len(attempts) == 1:
            message = "Selected model is at capacity. Please try a different model."
            raw = b"\n".join(json.dumps(row).encode() for row in [
                {"type": "thread.started", "thread_id": "synthetic"},
                {"type": "turn.started"},
                {"type": "error", "message": message},
                {"type": "turn.failed", "error": {"message": message}},
            ])
            return InvocationResult(1, raw, b"", 1)
        packet = json.loads(prompt.split(b"\n", 1)[1])
        final = {"cards": None, "evaluations": None, "memory": "", **planner(packet)}
        (workspace / "final.json").write_text(json.dumps(final))
        raw = trace(final)
        if reconnect and len(attempts) == 2:
            from test_benchmark_reconnect import NOTICE
            rows = [json.loads(line) for line in raw.splitlines()]
            rows.insert(3, {"type": "error", "message": NOTICE})
            raw = b"\n".join(json.dumps(row).encode() for row in rows)
        return InvocationResult(0, raw, b"", 1)

    def transport_factory(**kwargs):
        kwargs["codex_binary"] = "/usr/bin/true"
        return BenchmarkTransport(**kwargs, run_command=invoke,
            runtime_attestor=lambda _: {"schema": "pt-luna-codex-tool-catalog-v1"})

    report = benchmark.run_benchmark(
        checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
        prepared_roots_from=roots, prepared_roots_sha256=source_sha,
        output=tmp_path / "smart", seeds=[7123], models=["sol"],
        information=["actor-only", "perfect"], wall_seconds=300,
        token_limit=1000000, run=True, capacity_retries=True,
        accept_recovered_reconnects=True,
        transport_factory=transport_factory)
    assert len(report["mirrors"]) == 4
    assert all(row["complete"] for row in report["mirrors"])
    assert attempts[0] == attempts[1]
    calls = [call for row in report["mirrors"] for call in row["calls"]]
    assert sum(call.get("error_type") == "provider_capacity" for call in calls) == 1
    known_tokens = sum(call.get("usage", {}).get("input_tokens", 0) +
                       call.get("usage", {}).get("output_tokens", 0) for call in calls)
    assert report["budget"]["tokens"] == known_tokens > 0
    # Consume actual engine/transport-produced rows, not hand-assembled scores.
    arm = readout._arm_report(report["mirrors"], "actor-only")
    assert arm["complete_pairs"] == 1
    health = arm["transport_health"]
    assert health["recorded_reconnect_events"] == int(reconnect)
    assert health["calls_with_recorded_reconnects"] == int(reconnect)
    assert health["unknown_calls"] == 1  # the failed capacity attempt
    assert health["malformed_calls"] == 0


def test_reconnect_census_preserves_unknown_legacy_and_malformed_receipts():
    assert readout._transport_health([{}]) == {
        "known_calls": 0, "unknown_calls": 1, "malformed_calls": 0,
        "recorded_reconnect_events": None,
        "calls_with_recorded_reconnects": None, "complete": False}
    zero = readout._transport_health([{"recovered_reconnects": []}])
    assert zero["complete"] and zero["recorded_reconnect_events"] == 0
    mixed = readout._transport_health([
        {}, {"recovered_reconnects": []}, {"recovered_reconnects": "bad"}])
    assert mixed["known_calls"] == 1
    assert mixed["unknown_calls"] == 2 and mixed["malformed_calls"] == 1
    assert not mixed["complete"]


def test_panel_reconnect_census_never_selects_or_changes_game_scores(tmp_path):
    from test_benchmark_reconnect import NOTICE
    directories = _panel(tmp_path)
    baseline = readout.analyze_panel(directories)
    path = directories["smart"] / "result.json"
    report = json.loads(path.read_text())
    for mirror in report["mirrors"]:
        for call in mirror["calls"]:
            call["recovered_reconnects"] = []
    report["mirrors"][0]["calls"][0]["recovered_reconnects"] = [
        {"type": "error", "message": NOTICE}]
    path.write_text(json.dumps(report))
    result = readout.analyze_panel(directories)
    assert result["status"] == baseline["status"] == "complete"
    for policy in readout.POLICIES:
        for mode in ("sol", "pt_sol"):
            actual = result["policies"][policy][mode]
            old = baseline["policies"][policy][mode]
            assert actual["paired_signed_levels"] == old["paired_signed_levels"]
            assert actual["complete_deal_seeds"] == old["complete_deal_seeds"]
            if policy != "smart":
                assert actual["transport_health"]["recorded_reconnect_events"] is None
    assert result["policies"]["smart"]["sol"]["transport_health"] == {
        "known_calls": 20, "unknown_calls": 0, "malformed_calls": 0,
        "recorded_reconnect_events": 1, "calls_with_recorded_reconnects": 1,
        "complete": True}
    assert result["policies"]["smart"]["pt_sol"]["transport_health"]["recorded_reconnect_events"] == 0


def test_atomic_output_does_not_clobber(tmp_path):
    from shengji.luna.atomic_io import AtomicPublishError, publish_exclusive_bytes
    rows = _panel(tmp_path)
    output = tmp_path / "readout.json"
    raw = json.dumps(readout.analyze_panel(rows), sort_keys=True).encode()
    publish_exclusive_bytes(output, raw, mode=0o400)
    first = output.read_bytes()
    with pytest.raises(AtomicPublishError, match='slot occupied'):
        publish_exclusive_bytes(output, raw, mode=0o400)
    assert output.read_bytes() == first


@pytest.mark.parametrize('has_manifest', [False, True])
def test_directory_cli_refuses_before_data_access_in_any_layout(tmp_path, monkeypatch, has_manifest):
    monkeypatch.setattr(readout, '__file__', str(tmp_path / 'source/scripts/readout.py'))
    if has_manifest:
        (tmp_path / 'manifest.json').write_text('{}')
    output = tmp_path / 'readout.json'
    output.write_bytes(b'preserve existing output')
    def forbidden(*args, **kwargs):
        raise AssertionError('raw mapping or panel must not be opened')
    monkeypatch.setattr(readout, '_load_mapping', forbidden)
    monkeypatch.setattr(readout, 'analyze_panel', forbidden)
    monkeypatch.setattr(readout, '_read_json', forbidden)
    with pytest.raises(readout.PanelReadoutError, match='forbids the directory CLI'):
        readout.main(['--rows', str(tmp_path / 'unread.json'), '--output', str(output)])
    assert output.read_bytes() == b'preserve existing output'


def test_partial_campaign_rows_and_explicit_not_run_are_labeled(tmp_path):
    rows_root = tmp_path / "rows"
    rows_root.mkdir()
    rows = _panel(rows_root)
    campaign_root = tmp_path / "campaign"
    prepared = campaign_root / "prepared"
    prepared.mkdir(parents=True)
    root_result = {"schema": "sol-panel-root-source-v1", "mode": "roots-only",
                   "roots": ROOTS}
    root_raw = json.dumps(root_result, sort_keys=True).encode()
    source_sha = hashlib.sha256(root_raw).hexdigest()
    (prepared / "result.json").write_bytes(root_raw)
    (campaign_root / "config.json").write_text(json.dumps({
        "schema": "sol-nine-policy-campaign-v1", "rows": list(readout.POLICIES),
        "seeds": SEEDS, "prepared_roots": str(prepared),
        "prepared_roots_sha256": source_sha}))
    for path in rows.values():
        result_path = path / "result.json"
        value = json.loads(result_path.read_text())
        value["config"]["prepared_roots_from"]["result_sha256"] = source_sha
        value["prepared_roots"]["result_sha256"] = source_sha
        result_path.write_text(json.dumps(value))
    partial = campaign_root / "smv3-pv"
    partial.mkdir()
    source_value = json.loads(rows["smv3-pv"].joinpath("result.json").read_text())
    (partial / "config.json").write_text(json.dumps(source_value["config"]))
    for mirror in source_value["mirrors"][:3]:
        (partial / f"mirror-{mirror['model']}-{mirror['information']}-{mirror['seed']}-{mirror['flip']}.json").write_text(json.dumps(mirror))
    rows["smv3-pv"] = partial
    rows["smart"] = None
    result = readout.analyze_panel(rows)
    assert result["status"] == "partial"
    assert result["policies"]["smv3-pv"]["missing_mirrors"] == 37
    assert result["policies"]["smart"]["attempted_mirrors"] == 0
    assert result["policies"]["smart"]["failure_count"] == 40


@pytest.mark.parametrize("capacity_retries", [False, True])
def test_real_smart_row_flows_through_terminal_readout_with_absent_rows(tmp_path, capacity_retries):
    seeds = [1000 + index for index in range(10)]
    roots = tmp_path / "roots"
    root_producer.prepare_roots(output=roots, seeds=seeds)
    source_sha = hashlib.sha256((roots / "result.json").read_bytes()).hexdigest()
    recipe = prepare_recipe("smart", {})

    class FakeTransport:
        def __init__(self, **_kwargs):
            if capacity_retries:
                assert _kwargs["capacity_retry_delays"] == (15, 30, 60)
            self.calls = []

        def __call__(self, packet):
            return planner(packet)

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    smart_output = campaign / "smart"
    smart_result = benchmark.run_benchmark(
        checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
        prepared_roots_from=roots, prepared_roots_sha256=source_sha,
        output=smart_output, seeds=seeds, models=["sol"],
        information=["actor-only", "perfect"], wall_seconds=600,
        token_limit=1000000, run=True, transport_factory=FakeTransport,
        capacity_retries=capacity_retries)
    assert len(smart_result["mirrors"]) == 40
    assert all(row["complete"] is True for row in smart_result["mirrors"])

    (campaign / "config.json").write_text(json.dumps({
        "schema": "sol-nine-policy-campaign-v2" if capacity_retries else "sol-nine-policy-campaign-v1",
        "rows": list(readout.POLICIES), "seeds": seeds,
        "prepared_roots": str(roots), "prepared_roots_sha256": source_sha}))
    mapping = {benchmark_id: (str(smart_output) if benchmark_id == "smart"
                              else str(campaign / benchmark_id))
               for benchmark_id in readout.POLICIES}
    result = readout.analyze_panel(mapping)
    smart = result["policies"]["smart"]
    assert smart["status"] == "complete"
    assert smart["attempted_mirrors"] == smart["complete_mirrors"] == 40
    assert smart["sol"]["complete_pairs"] == smart["pt_sol"]["complete_pairs"] == 10
    assert all(result["policies"][benchmark_id]["status"] == "partial"
               for benchmark_id in readout.POLICIES if benchmark_id != "smart")
    assert all(result["policies"][benchmark_id]["complete_pairs"] == 0
               for benchmark_id in readout.POLICIES if benchmark_id != "smart")
    assert all(result["policies"][benchmark_id]["sol"]["paired_signed_levels"]["mean"] is None
               for benchmark_id in readout.POLICIES if benchmark_id != "smart")

    def fail_first_mirror(prepared_game, **kwargs):
        if (kwargs["information"], kwargs["seed"], kwargs["flip"]) == ("actor-only", seeds[0], 0):
            raise RuntimeError("synthetic first-mirror failure")
        return benchmark.play_mirror(prepared_game, **kwargs)

    failed_output = campaign / "smart-failure"
    failed = benchmark.run_benchmark(
        checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
        prepared_roots_from=roots, prepared_roots_sha256=source_sha,
        output=failed_output, seeds=seeds, models=["sol"],
        information=["actor-only", "perfect"], wall_seconds=600,
        token_limit=1000000, run=True, runner=fail_first_mirror,
        transport_factory=FakeTransport, capacity_retries=capacity_retries)
    assert len(failed["mirrors"]) == 40
    assert sum(row["complete"] is not True for row in failed["mirrors"]) == 40
    failed_mapping = {benchmark_id: (str(failed_output) if benchmark_id == "smart"
                                     else str(campaign / benchmark_id))
                      for benchmark_id in readout.POLICIES}
    failed_readout = readout.analyze_panel(failed_mapping)
    failed_smart = failed_readout["policies"]["smart"]
    assert failed_smart["attempted_mirrors"] == 1
    assert failed_smart["failure_count"] == 40
    assert failed_smart["sol"]["complete_pairs"] == 0
    assert failed_smart["pt_sol"]["complete_pairs"] == 0
