import ast
import math
from pathlib import Path

import numpy as np

from shengji.train import cwv_eval
from shengji.train import train_cwv
from shengji.train.train_cwv import ranking_block


def _rows():
    return [
        {"spearman": None, "top1": 0.5, "regret": 2.0, "candidates": 2},
        {"spearman": 1.0, "top1": 1.0, "regret": 0.0, "candidates": 10},
        {"spearman": -1.0, "top1": 0.0, "regret": 3.0, "candidates": 3},
        {"spearman": None, "top1": 0.25, "regret": 1.5, "candidates": 2},
    ]


def test_agreement_columns_preserve_numeric_order_and_payload_size():
    rows = _rows()
    compact = cwv_eval._AgreementColumns()
    for row in rows:
        compact.append(row)

    assert len(compact) == len(rows)
    assert list(compact.column("candidates")) == [2, 10, 3, 2]
    assert math.isnan(compact.column("spearman")[0])
    assert list(compact.column("top1")) == [0.5, 1.0, 0.0, 0.25]
    assert compact.nbytes == len(rows) * 4 * 8


def test_compact_summary_and_paired_metrics_match_legacy_rows():
    rows = _rows()
    other = [{**row, "top1": row["top1"] - 0.1, "regret": row["regret"] + 0.75}
             for row in rows]
    compact = cwv_eval._AgreementColumns()
    compact_other = cwv_eval._AgreementColumns()
    for row, other_row in zip(rows, other):
        compact.append(row)
        compact_other.append(other_row)
    clusters = ["z/2", "10", "z/2", "2"]

    assert cwv_eval.summarize_agreement(rows, clusters, n_boot=40, seed=11) == \
        cwv_eval.summarize_agreement(compact, clusters, n_boot=40, seed=11)
    assert cwv_eval.paired_agreement(rows, other, clusters, n_boot=40, seed=11) == \
        cwv_eval.paired_agreement(compact, compact_other, clusters, n_boot=40, seed=11)
    for left, right in ((rows, compact_other), (compact, other)):
        assert cwv_eval.paired_agreement(left, right, clusters, n_boot=40, seed=11) == \
            cwv_eval.paired_agreement(rows, other, clusters, n_boot=40, seed=11)

    undefined = [{**row, "spearman": None} for row in rows]
    undefined_compact = cwv_eval._AgreementColumns()
    for row in undefined:
        undefined_compact.append(row)
    assert cwv_eval.summarize_agreement(undefined, clusters, n_boot=10, seed=3) == \
        cwv_eval.summarize_agreement(undefined_compact, clusters, n_boot=10, seed=3)
    assert cwv_eval.summarize_agreement([], [], n_boot=10, seed=3) == {"n": 0}


def test_candidate_pass_compact_matches_list_and_ranking_block(monkeypatch):
    entries = []
    for i, means in enumerate(([0.0, 1.0, 1.0], [2.0, 0.0])):
        means = np.asarray(means, dtype=np.float64)
        entries.append({
            "means": means,
            "terminal": np.zeros(means.size, dtype=bool),
            "terminal_level": np.zeros(means.size, dtype=np.float64),
            "deal_key": ("z/2", "10")[i],
        })

    class Result:
        source_ref = []
        deal_key = []
        decision_obs = np.zeros((0, 1), dtype=np.float32)
        search = entries

    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, **kwargs: [Result()])
    kwargs = dict(shard_keys=[("shard", None)], score_fn=lambda entry: entry["means"],
                  public_head=None, prior=None, device="cpu", workers=1, rank_limit=None,
                  history=False)
    legacy = cwv_eval.candidate_pass(**kwargs)
    compact = cwv_eval.candidate_pass(**kwargs, compact_agreement=True)
    legacy_block = ranking_block(legacy, n_boot=20, seed=7)
    compact_block = ranking_block(compact, n_boot=20, seed=7)
    legacy_block.pop("secs")
    compact_block.pop("secs")
    assert legacy_block == compact_block


def test_candidate_pass_compact_multi_scorer_parity_and_empty_omission(monkeypatch):
    entries = []
    for deal_key, means in (("z/2", [1.0, 2.0, 2.0]), ("10", [3.0, 0.0])):
        means = np.asarray(means, dtype=np.float64)
        k = means.size
        entries.append({
            "means": means,
            "public": np.arange(k, dtype=np.float32)[:, None],
            "terminal": np.zeros(k, dtype=bool),
            "terminal_level": np.zeros(k, dtype=np.float64),
            "role_attacker": True,
            "successor_ply": np.arange(k, dtype=np.int32),
            "successor_points": np.arange(k, dtype=np.float32),
            "deal_key": deal_key,
        })

    class Result:
        source_ref = []
        deal_key = []
        decision_obs = np.zeros((0, 1), dtype=np.float32)
        search = entries

    class Head:
        arch = {"obs_dim": 1}

    class Prior:
        @staticmethod
        def predict(ply, role, points):
            return np.asarray(points, dtype=np.float64) * 0.5

    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, **kwargs: [Result()])
    monkeypatch.setattr(cwv_eval, "public_values",
                        lambda model, obs, device: np.asarray(obs[:, 0], dtype=np.float64) * 0.25)
    kwargs = dict(shard_keys=[("shard", None)],
                  score_fn=lambda entry: entry["means"] * 0.75,
                  public_head=Head(), prior=Prior(), device="cpu", workers=1,
                  rank_limit=None, history=False)
    legacy = cwv_eval.candidate_pass(**kwargs)
    compact = cwv_eval.candidate_pass(**kwargs, compact_agreement=True)
    for name in ("cwv", "public_head", "stratified_prior"):
        assert isinstance(compact["agreement"][name], cwv_eval._AgreementColumns)
    legacy_block = ranking_block(legacy, n_boot=20, seed=7)
    compact_block = ranking_block(compact, n_boot=20, seed=7)
    legacy_block.pop("secs")
    compact_block.pop("secs")
    assert legacy_block == compact_block

    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, **kwargs: [
        type("EmptyResult", (), {"source_ref": [], "deal_key": [],
                                  "decision_obs": np.zeros((0, 1), dtype=np.float32),
                                  "search": []})()
    ])
    empty_kwargs = dict(shard_keys=[("shard", None)], score_fn=None, public_head=None,
                        prior=None, device="cpu", workers=1, rank_limit=None, history=False)
    assert cwv_eval.candidate_pass(**empty_kwargs, compact_agreement=True)["agreement"] == {}


def test_all_production_candidate_pass_calls_opt_into_compact_mode():
    tree = ast.parse(Path(train_cwv.__file__).read_text())
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "candidate_pass"]
    assert len(calls) == 4
    assert all(any(keyword.arg == "compact_agreement"
                   and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is True
                   for keyword in call.keywords) for call in calls)
