from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from shengji.luna import benchmark_retention as retention
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, summarize_scheduled
from shengji.luna.benchmark_retained_content import validate_retained_content
from shengji.luna.canonical import canonical_json_bytes


SEEDS = list(range(10, 20))


@pytest.mark.parametrize('old_failures,expected_attempts,completed_count,failed,pending', [
    (1, 2, 39, 1, 0), (7, 1, 31, 8, 1), (8, 0, 30, 8, 2),
])
@pytest.mark.parametrize('prior_tokens', [0, 7])
def test_actual_runner_retention_report_satisfies_content_reader(
        tmp_path, old_failures, expected_attempts, completed_count, failed, pending, prior_tokens):
    """Bridge producer/reader contracts; hand-written reports alone miss fields."""
    import json
    from scripts import prepare_llm_panel_roots as producer
    from scripts import w32_llm_benchmark as runner
    from shengji.luna.benchmark_recipes import prepare_recipe
    from test_benchmark_retention import _repin_report

    roots = tmp_path / 'roots'
    producer.prepare_roots(output=roots, seeds=SEEDS)
    recipe = prepare_recipe('smart', {})
    options = dict(checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
                   prepared_roots_from=roots,
                   prepared_roots_sha256=hashlib.sha256((roots / 'result.json').read_bytes()).hexdigest(),
                   seeds=SEEDS, models=['sol'], output=tmp_path / 'out',
                   failure_protocol=PRESERVE_ILLEGAL, classify_final_action_failures=True)
    config = runner.run_benchmark(**options)['config']
    _, plan, _ = _source(tmp_path)
    source = tmp_path / 'source'
    old = json.loads((source / 'result.json').read_bytes())
    old['config'] = config
    for index, original in enumerate(old['mirrors']):
        kind = 'pending' if index < 2 else 'typed' if index >= 40 - old_failures else 'complete'
        row = _row(original['information'], original['seed'], original['flip'], kind)
        # Bind costs from both a completed row and a late typed failure. The
        # latter must survive even when the failure ceiling prevents dispatch.
        if prior_tokens and index in (2, 39):
            row['calls'] = [{'usage': {'input_tokens': 2 if index == 2 else 3,
                                      'output_tokens': 1}}]
        old['mirrors'][index] = row
        (source / f"mirror-sol-{row['information']}-{row['seed']}-{row['flip']}.json").write_bytes(
            canonical_json_bytes(row))
    pin = _repin_report(plan, source, old)
    source_bytes = {path.name: path.read_bytes() for path in source.iterdir()}
    auth = retention.load_retained_attempts(plan, pin, expected_config=config)
    assert auth['prior_cost_tokens'] == prior_tokens
    attempts = []
    def completed(game, **kwargs):
        attempts.append((kwargs['information'], kwargs['seed'], kwargs['flip']))
        if old_failures == 7:
            return _row(kwargs['information'], kwargs['seed'], kwargs['flip'], 'typed')
        return {'complete': True, 'signed_levels': 2}
    report = runner.run_benchmark(
        **options, run=True, token_limit=1000, retention_plan=str(plan),
        retention_plan_sha256=pin, runner=completed)
    assert attempts == [('actor-only', 10, flip) for flip in range(expected_attempts)]
    assert report['retained_attempts']['prior_cost_tokens'] == prior_tokens
    assert report['config']['retained_attempts'] == report['retained_attempts']
    assert report['budget']['prior_tokens'] == prior_tokens
    assert report['budget']['new_tokens'] == 0  # Fake runner makes no calls.
    assert report['budget']['combined_tokens'] == prior_tokens
    assert validate_retained_content(report, auth) == {
        'status': 'scheduled-terminal' if failed < 8 else 'failure-limit',
        'completed': completed_count, 'failed': failed,
        'unattempted': pending, 'scheduled': 40}
    assert all(row['lineage']['kind'] == 'retained-terminal-attempt'
               for row in report['mirrors'][2:])
    assert {path.name: path.read_bytes() for path in source.iterdir()} == source_bytes


def _row(mode: str, seed: int, flip: int, kind: str) -> dict:
    key = f"sol-{mode}-seed{seed}-flip{flip}"
    row = {
        "schema": "w32-llm-benchmark-mirror-v1", "key": key,
        "arm": f"sol-{mode}", "model": "sol", "information": mode,
        "seed": seed, "flip": flip, "calls": [], "events": [],
    }
    if kind == "complete":
        row.update(complete=True, signed_levels=1.5)
    elif kind == "typed":
        row.update(
            complete=False, error="IllegalPlay: must follow",
            events=[{"seat": flip, "attempted_cards": ["C2"]}],
            failure={"schema": "benchmark-action-failure-v1",
                     "category": "model_illegal_action", "stage": "engine_play",
                     "seat": flip, "attempted_cards": ["C2"], "event_index": 0})
    elif kind == "pending":
        row.update(complete=False, status="not_run")
    else:
        raise AssertionError(kind)
    return row


def _source(tmp_path: Path) -> tuple[dict, Path, str]:
    config = {
        "seeds": SEEDS, "models": ["sol"],
        "information": ["actor-only", "perfect"],
        "policy": "smart", "baseline_recipe": {"recipe": "smart"},
        "checkpoint": {"path": "/tmp/model.npz", "sha256": "a" * 64},
    }
    source = tmp_path / "source"
    source.mkdir()
    mirrors = []
    for mode in config["information"]:
        for seed in SEEDS:
            for flip in (0, 1):
                kind = "typed" if (mode, seed, flip) == ("actor-only", 10, 1) else (
                    "pending" if (mode, seed, flip) == ("perfect", 10, 0) else "complete")
                row = _row(mode, seed, flip, kind)
                mirrors.append(row)
                (source / f"mirror-sol-{mode}-{seed}-{flip}.json").write_bytes(
                    canonical_json_bytes(row))
    result = {"schema": "w32-llm-benchmark-v1", "mode": "run",
              "config": config, "mirrors": mirrors, "prior": None}
    result_raw = canonical_json_bytes(result)
    (source / "result.json").write_bytes(result_raw)
    plan = {"schema": "benchmark-retention-v1", "source_directory": str(source),
            "result_sha256": hashlib.sha256(result_raw).hexdigest(),
            "legacy_illegal_sha256": []}
    plan_path = tmp_path / "plan.json"
    plan_raw = canonical_json_bytes(plan)
    plan_path.write_bytes(plan_raw)
    plan_sha = hashlib.sha256(plan_raw).hexdigest()
    loaded = retention.load_retained_attempts(plan_path, plan_sha,
                                               expected_config=config)
    return loaded, plan_path, plan_sha


def _report(loaded: dict, plan_path: Path, plan_sha: str) -> dict:
    retained = {
        "plan": str(plan_path.resolve()), "plan_sha256": plan_sha,
        "source": loaded["path"], "result_sha256": loaded["result_sha256"],
        "prior_cost_tokens": loaded["prior_cost_tokens"],
    }
    config = {
        "schema": "w32-llm-benchmark-v1", "checkpoint": {"path": "/tmp/model.npz",
        "sha256": "a" * 64}, "policy": "smart",
        "seeds": SEEDS, "models": ["sol"],
        "information": ["actor-only", "perfect"],
        "failure_protocol": PRESERVE_ILLEGAL, "illegal_failure_limit": 8,
        "retained_attempts": retained,
    }
    mirrors = []
    for key, original in loaded["rows"].items():
        row = copy.deepcopy(original)
        if original.get("status") == "not_run":
            row.pop("status")
            row.update(complete=True, signed_levels=2.0)
        else:
            source = loaded["source_rows"][key]
            row["lineage"] = {
                "source": loaded["path"],
                "source_result_sha256": loaded["result_sha256"],
                "source_row": source["path"],
                "source_row_sha256": source["sha256"],
                "kind": "retained-terminal-attempt",
                "retention_plan_sha256": plan_sha,
            }
        mirrors.append(row)
    return {"schema": "w32-llm-benchmark-v1", "mode": "run", "config": config,
            "retained_attempts": copy.deepcopy(retained), "mirrors": mirrors,
            "scheduled_summary": summarize_scheduled(mirrors, failure_limit=8)}


def test_retained_content_accepts_exact_copy_and_returns_terminal_counts(tmp_path):
    loaded, plan, plan_sha = _source(tmp_path)
    report = _report(loaded, plan, plan_sha)
    counts = validate_retained_content(report, loaded)
    assert counts == {"status": "scheduled-terminal", "completed": 39,
                      "failed": 1, "unattempted": 0, "scheduled": 40}


def test_no_retention_binding_is_outside_content_validator():
    assert validate_retained_content({"config": {}}, None) is None


@pytest.mark.parametrize("mutation", [
    "score", "usage", "lineage", "extra_lineage", "source_row_sha",
    "top_level", "pending_lineage", "schedule_key",
])
def test_retained_content_rejects_content_or_binding_drift(tmp_path, mutation):
    loaded, plan, plan_sha = _source(tmp_path)
    report = _report(loaded, plan, plan_sha)
    attempted = "sol-actor-only-seed10-flip0"
    if mutation == "score":
        report["mirrors"][0]["signed_levels"] = 9.0
    elif mutation == "usage":
        report["mirrors"][0]["calls"] = [{"usage": {"input_tokens": 1}}]
    elif mutation == "lineage":
        del report["mirrors"][0]["lineage"]
    elif mutation == "extra_lineage":
        report["mirrors"][0]["lineage"]["extra"] = True
    elif mutation == "source_row_sha":
        report["mirrors"][0]["lineage"]["source_row_sha256"] = "b" * 64
    elif mutation == "top_level":
        report["retained_attempts"]["prior_cost_tokens"] += 1
    elif mutation == "pending_lineage":
        report["mirrors"][-1]["lineage"] = copy.deepcopy(report["mirrors"][0]["lineage"])
    elif mutation == "schedule_key":
        report["mirrors"][0]["key"] = attempted + "-changed"
    with pytest.raises(ValueError):
        validate_retained_content(report, loaded)


def test_retained_content_requires_authenticated_input(tmp_path):
    loaded, plan, plan_sha = _source(tmp_path)
    with pytest.raises(ValueError):
        validate_retained_content(_report(loaded, plan, plan_sha), None)
