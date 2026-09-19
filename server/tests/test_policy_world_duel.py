"""Focused contract tests for the bounded DEV policy-world duel."""
from __future__ import annotations

import hashlib
import json
import pytest

from shengji.train import policy_world_duel as duel


def _row(seed, *, error=None):
    return {"seed": seed, "utility": 1.0, "max_rss_kib": 7,
            "sides": {"policy": duel._empty_side(),
                      "control": duel._empty_side()},
            "error": error}


def test_parser_defaults_and_control_contracts():
    args = duel.build_parser().parse_args(
        ["--checkpoint", "model.pt", "--checkpoint-sha256", "a" * 64,
         "--out", "out", "--seed0", "10"])
    assert (args.deals, args.workers, args.worlds, args.control) == (1, 1, 4, "mc-lcb")
    lcb = duel.make_control("mc-lcb", 3)
    assert (lcb.N_DETERMINIZATIONS, lcb.REPORT_FOLD_WORLDS,
            lcb.REPORT_RULE, lcb.REQUIRE_EXACT_WORK) == (30, 300, "lcb", True)
    smart = duel.make_control("mc-smart4", 3)
    assert type(smart) is duel.MCSmartRoll
    assert smart.N_DETERMINIZATIONS == 4
    policy = duel.full_control_config('policy-world')
    assert policy['worlds'] == 'same as arm'
    assert policy['checkpoint'] == 'same as arm'
    assert policy['rollout_policy'] is None


@pytest.mark.parametrize("rows", [
    [_row(1)],
    [_row(1), _row(1)],
    [_row(1, error={"type": "TimeoutError"})],
])
def test_aggregate_refuses_incomplete_duplicate_or_error_pairs(rows):
    with pytest.raises(ValueError):
        duel.aggregate_records(rows, [1, 2])


@pytest.mark.parametrize("row", [
    {**_row(1), "utility": float("nan")},
    {**_row(1), "timeout": True, "error": None},
])
def test_aggregate_refuses_nonfinite_or_timeout_rows(row):
    with pytest.raises(ValueError):
        duel.aggregate_records([row], [1])


def test_injected_fast_pair_smoke(monkeypatch):
    def fast(seed, parity, checkpoint, checksum, worlds, control, mode, candidates):
        return {"utility": float(1 if parity == 0 else -1),
                "sides": {"policy": duel._empty_side(),
                          "control": duel._empty_side()}}

    monkeypatch.setattr(duel, "_play_one", fast)
    row = duel.play_pair(9, "unused", "0" * 64)
    assert row["seed"] == 9
    assert row["mirrors"] == [1.0, -1.0]
    summary = duel.aggregate_records([row], [9])
    assert summary["expected"] == 1
    assert summary["paired_bootstrap"]["replicates"] == 10_000


def test_worker_pair_keeps_keyword_only_configuration(monkeypatch):
    seen = {}

    def fake(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return {"seed": args[0]}

    monkeypatch.setattr(duel, "play_pair", fake)
    assert duel._worker_pair((4, "ck", "sha", 8, "mc-smart4", "policy-value", 12)) == {"seed": 4}
    assert seen == {"args": (4, "ck", "sha"),
                    "kwargs": {"worlds": 8, "control": "mc-smart4",
                               "mode": "policy-value", "candidates": 12}}


def test_value_work_survives_decision_pair_summary():
    from types import SimpleNamespace
    bot = SimpleNamespace(last_decision_record={
        'worlds': 4, 'sample_attempts': 5, 'legal_complete': True,
        'value_evaluations': 32, 'value_batches': 1})
    row = _row(7)
    duel._record_decision(row['sides']['policy'], .01,
                          duel._decision_telemetry(bot, 'policy'), 'policy')
    summary = duel.aggregate_records([row], [7])
    assert summary['policy']['value_evaluations'] == 32
    assert summary['policy']['value_batches'] == 1


def test_value_factory_uses_checked_evaluator(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(duel, '_value_evaluator', lambda p, s: sentinel)
    seen = {}
    def fake(p, s, **kwargs):
        seen.update(kwargs)
        return sentinel
    monkeypatch.setattr(duel.PolicyValueBot, 'from_checkpoint', fake)
    assert duel.make_policy('ck', 'sha', 4, 7, 'policy-value', 12) is sentinel
    assert seen['evaluator'] is sentinel
    assert seen['candidates'] == 12
    assert seen['worlds'] == 4


def test_lookahead_factory_and_continuation_accounting(monkeypatch):
    from types import SimpleNamespace
    evaluator = object()
    monkeypatch.setattr(duel, '_value_evaluator', lambda *a: evaluator)
    def factory(p, s, **kwargs):
        assert kwargs['evaluator'] is evaluator
        assert kwargs['worlds'] == 4 and kwargs['candidates'] == 8
        return SimpleNamespace(last_decision_record={
            'worlds': 4, 'sample_attempts': 4, 'legal_complete': True,
            'value_evaluations': 32, 'value_batches': 1,
            'continuation_work': {'plies': 128, 'worlds': 128,
                                  'sample_attempts': 130, 'capped_decisions': 2}})
    monkeypatch.setattr(duel.PolicyLookaheadBot, 'from_checkpoint', factory)
    bot = duel.make_policy('ck', 'sha', 4, 7, 'policy-lookahead', 8)
    row = _row(7)
    duel._record_decision(row['sides']['policy'], .1,
                          duel._decision_telemetry(bot, 'policy'), 'policy')
    result = duel.aggregate_records([row], [7])['policy']
    assert result['worlds'] == 4
    assert result['continuation_worlds'] == result['continuation_plies'] == 128
    assert result['continuation_sample_attempts'] == 130
    assert result['continuation_capped_decisions'] == 2


def test_policy_control_work_is_not_reported_as_mc_work():
    from types import SimpleNamespace
    bot = SimpleNamespace(last_decision_record={
        'worlds': 4, 'sample_attempts': 6, 'legal_complete': False})
    row = _row(8)
    duel._record_decision(row['sides']['control'], .02,
                          duel._decision_telemetry(bot, 'policy'), 'policy')
    control = duel.aggregate_records([row], [8])['control']
    assert control['decisions'] == 1
    assert control['mc_decisions'] == control['worlds'] == control['rollouts'] == 0
    assert control['policy_work']['worlds'] == 4
    assert control['policy_work']['sample_attempts'] == 6
    assert control['policy_work']['capped_decisions'] == 1


def test_cli_writes_recipe_pair_and_summary_with_injected_pool(monkeypatch, tmp_path):
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"test-checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    class Future:
        def __init__(self, row):
            self.row = row

        def result(self):
            return self.row

    class Pool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            fake_pool.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, item):
            assert fn is duel._worker_pair
            return Future(_row(item[0]))

    fake_pool = type("FakePoolState", (), {})()
    monkeypatch.setattr(duel, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(duel, "as_completed", lambda futures: futures)
    out = tmp_path / "out"
    assert duel.main(["--checkpoint", str(checkpoint), "--checkpoint-sha256", digest,
                      "--out", str(out), "--deals", "1", "--seed0", "9",
                      "--workers", "2", "--worlds", "3", "--control", "mc-smart4"]) == 0
    assert fake_pool.kwargs["max_workers"] == 2
    recipe = json.loads((out / "recipe.json").read_text())
    assert recipe["control"] == "mc-smart4"
    assert json.loads((out / "summary.json").read_text())["complete"] == 1
    assert len((out / "pairs.jsonl").read_text().splitlines()) == 1
