from __future__ import annotations

import copy

import pytest

from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, summarize_scheduled
from shengji.luna.benchmark_terminal import validate_scheduled_terminal


SEEDS = list(range(10))


def _row(mode, seed, flip, kind="complete"):
    key = f"sol-{mode}-seed{seed}-flip{flip}"
    row = {"schema": "w32-llm-benchmark-mirror-v1", "key": key,
           "arm": f"sol-{mode}", "model": "sol", "information": mode,
           "seed": seed, "flip": flip, "events": [], "calls": []}
    if kind == "complete":
        row.update(complete=True, signed_levels=1)
    elif kind == "pending":
        row.update(complete=False, status="not_run")
    elif kind == "failed":
        row.update(
            complete=False, error="IllegalPlay: must follow",
            events=[{"seat": flip, "attempted_cards": ["C2"]}],
            failure={"schema": "benchmark-action-failure-v1",
                     "category": "model_illegal_action", "stage": "engine_play",
                     "seat": flip, "attempted_cards": ["C2"], "event_index": 0})
    return row


def _report(*, failed=1, pending=0):
    rows = []
    index = 0
    for mode in ("actor-only", "perfect"):
        for seed in SEEDS:
            for flip in (0, 1):
                kind = "complete"
                if index < failed:
                    kind = "failed"
                elif index < failed + pending:
                    kind = "pending"
                rows.append(_row(mode, seed, flip, kind))
                index += 1
    summary = summarize_scheduled(rows, failure_limit=8)
    return {"schema": "w32-llm-benchmark-v1", "mode": "run",
            "config": {"failure_protocol": PRESERVE_ILLEGAL,
                        "illegal_failure_limit": 8, "models": ["sol"],
                        "information": ["actor-only", "perfect"],
                        "seeds": SEEDS},
            "mirrors": rows, "scheduled_summary": summary}


def test_full_schedule_with_typed_failure_is_terminal():
    assert validate_scheduled_terminal(_report(failed=1), seeds=SEEDS) == {
        "status": "scheduled-terminal", "completed": 39, "failed": 1,
        "unattempted": 0, "scheduled": 40}


def test_exact_failure_limit_accepts_remaining_pending_slots():
    assert validate_scheduled_terminal(_report(failed=8, pending=32), seeds=SEEDS) == {
        "status": "failure-limit", "completed": 0, "failed": 8,
        "unattempted": 32, "scheduled": 40}


def test_new_attempts_after_eighth_failure_refuse():
    with pytest.raises(ValueError, match='after failure limit'):
        validate_scheduled_terminal(_report(failed=8), seeds=SEEDS)


def test_retained_terminals_after_limit_are_not_new_spend():
    report = _report(failed=8)
    binding = {'source': '/sealed', 'result_sha256': 'a' * 64,
               'plan_sha256': 'b' * 64}
    report['config']['retained_attempts'] = binding
    for row in report['mirrors']:
        row['lineage'] = dict(kind='retained-terminal-attempt', source='/sealed',
                              source_result_sha256='a' * 64,
                              retention_plan_sha256='b' * 64)
    with pytest.raises(ValueError, match='not authorized'):
        validate_scheduled_terminal(report, seeds=SEEDS)
    with pytest.raises(ValueError, match='launcher binding'):
        validate_scheduled_terminal(report, seeds=SEEDS,
                                    retention_binding={**binding, 'plan_sha256': 'f' * 64})
    assert validate_scheduled_terminal(report, seeds=SEEDS,
                                      retention_binding=binding)['status'] == 'failure-limit'
    report['mirrors'][0]['lineage']['retention_plan_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='lineage'):
        validate_scheduled_terminal(report, seeds=SEEDS, retention_binding=binding)


@pytest.mark.parametrize("mutation", [
    lambda report: report["mirrors"].pop(),
    lambda report: report["mirrors"].append(copy.deepcopy(report["mirrors"][0])),
    lambda report: report["mirrors"][0].update(key="sol-perfect-seed0-flip0"),
    lambda report: report["mirrors"][0].update(seed=True),
])
def test_duplicate_missing_and_identity_drift_refuse(mutation):
    report = _report()
    mutation(report)
    with pytest.raises(ValueError):
        validate_scheduled_terminal(report, seeds=SEEDS)


def test_tampered_summary_refuses():
    report = _report()
    report["scheduled_summary"]["failed"] = 0
    with pytest.raises(ValueError, match="summary"):
        validate_scheduled_terminal(report, seeds=SEEDS)


@pytest.mark.parametrize('field,value', [('illegal_failure_limit', 8.0),
                                      ('seeds', [False, *range(1, 10)])])
def test_configuration_scalar_type_drift_refuses(field, value):
    report = _report()
    report['config'][field] = value
    with pytest.raises(ValueError, match='configuration drift'):
        validate_scheduled_terminal(report, seeds=SEEDS)


def test_unknown_infrastructure_failure_refuses():
    report = _report()
    row = report["mirrors"][0]
    row.update(complete=False, error="RuntimeError: provider", events=[])
    with pytest.raises(ValueError):
        validate_scheduled_terminal(report, seeds=SEEDS)


def test_pending_below_failure_limit_refuses():
    report = _report(failed=7, pending=1)
    with pytest.raises(ValueError, match="pending"):
        validate_scheduled_terminal(report, seeds=SEEDS)


@pytest.mark.parametrize("field,value", [
    ("signed_levels", True), ("signed_levels", float("inf")),
    ("failure", {"unexpected": True}),
])
def test_malformed_terminal_row_refuses(field, value):
    report = _report()
    report["mirrors"][1][field] = value
    with pytest.raises(ValueError):
        validate_scheduled_terminal(report, seeds=SEEDS)


def _late_retained_failures(count):
    report = _report(failed=0)
    binding = {'source': '/synthetic/sealed', 'result_sha256': 'a' * 64,
               'plan_sha256': 'b' * 64}
    report['config']['retained_attempts'] = binding
    for index, row in enumerate(report['mirrors']):
        kind = 'pending' if index < 40 - count else 'failed'
        replacement = _row(row['information'], row['seed'], row['flip'], kind)
        if kind == 'failed':
            replacement['lineage'] = {
                'kind': 'retained-terminal-attempt', 'source': binding['source'],
                'source_result_sha256': binding['result_sha256'],
                'retention_plan_sha256': binding['plan_sha256'],
            }
        report['mirrors'][index] = replacement
    report['scheduled_summary'] = summarize_scheduled(report['mirrors'])
    return report, binding


def test_late_retained_failures_exhaust_budget_before_first_slot():
    report, binding = _late_retained_failures(8)
    before = copy.deepcopy(report)
    assert validate_scheduled_terminal(
        report, seeds=SEEDS, retention_binding=binding) == {
            'status': 'failure-limit', 'completed': 0, 'failed': 8,
            'unattempted': 32, 'scheduled': 40}
    assert report == before
    # Serialized row order must not change the schedule interpretation.
    report['mirrors'].reverse()
    assert validate_scheduled_terminal(
        report, seeds=SEEDS, retention_binding=binding)['unattempted'] == 32


def test_new_first_slot_refused_when_late_retained_failures_used_budget():
    report, binding = _late_retained_failures(8)
    report['mirrors'][0] = _row('actor-only', 0, 0)
    report['scheduled_summary'] = summarize_scheduled(report['mirrors'])
    with pytest.raises(ValueError, match='new attempt after failure limit'):
        validate_scheduled_terminal(report, seeds=SEEDS, retention_binding=binding)


def test_seven_retained_failures_allow_exactly_one_new_failure():
    report, binding = _late_retained_failures(7)
    report['mirrors'][0] = _row('actor-only', 0, 0, 'failed')
    report['scheduled_summary'] = summarize_scheduled(report['mirrors'])
    assert validate_scheduled_terminal(
        report, seeds=SEEDS, retention_binding=binding)['failed'] == 8
    report['mirrors'][1] = _row('actor-only', 0, 1)
    report['scheduled_summary'] = summarize_scheduled(report['mirrors'])
    with pytest.raises(ValueError, match='new attempt after failure limit'):
        validate_scheduled_terminal(report, seeds=SEEDS, retention_binding=binding)
