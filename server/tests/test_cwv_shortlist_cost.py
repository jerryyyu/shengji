"""The existing cost probe must compare the real encoding consumer path."""
import copy
import json

import pytest

from scripts import cwv_shortlist_cost as cost
from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.harvest.legal import enumerate_legal
from shengji.luna.game import _state_snapshot
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from tests.test_cwv_static_encoding import _state_after


def test_cost_probe_reuses_states_and_checks_actual_encoding_parity(tmp_path, monkeypatch):
    import torch

    torch.manual_seed(29)
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    monkeypatch.setattr(cost, "shared_evaluator", lambda _path, **kwargs:
                        CompleteWorldEvaluator(None, model=model, **kwargs))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")

    def no_recapture(*_args, **_kwargs):
        raise AssertionError("retained states must not drive a new game")

    monkeypatch.setattr(cost, "play_round", no_recapture)
    candidates = [_state_after(41, ply) for ply in range(33, 37)]
    rnd = next(r for r in candidates if len(enumerate_legal(r, r.turn, cap=None).actions) > 1)
    source = tmp_path / "states.json"
    source.write_text(json.dumps([_state_snapshot(rnd)]))
    out = tmp_path / "out"
    args = ["--checkpoint", "fixture", "--out", str(out),
            "--states-json", str(source), "--world-grid", "1",
            "--selection-grid", "1", "--encoding-grid", "reference,mlp-static"]
    assert cost.main(args) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["encoding_pairs_bit_identical"] == 1
    rows = [json.loads(p.read_text()) for p in out.glob("state-*.json")]
    learned = [r for r in rows if r["encoding"] is not None]
    assert len(learned) == 2
    assert all(r["counts"]["cheap_evaluations"] > 0 for r in learned)
    assert all(r["process_peak_rss_bytes"] > 0 for r in rows)
    assert all(r["effective_cpu_cores"] > 0 for r in rows)
    # Existing completed measurements reopen without any scoring work.
    monkeypatch.setattr(cost.CWVShortlistBot, "decide_play", no_recapture)
    assert cost.main(args) == 0

    changed = copy.deepcopy(learned)
    changed[0]["semantic"]["played"] = ["mutated"]
    with pytest.raises(ValueError, match="^encoding changed scores, shortlist, decision or RNG$"):
        cost.encoding_parity(changed)
    changed = copy.deepcopy(learned)
    changed[0]["semantic"]["scores_sha256"] = "mutated"
    with pytest.raises(ValueError, match="^encoding changed scores, shortlist, decision or RNG$"):
        cost.encoding_parity(changed)
