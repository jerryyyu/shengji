"""Witness bounded reuse in real shortlist → evaluator → MC wiring."""
from __future__ import annotations

import copy
import json

import pytest

from scripts.cwv_shortlist_cost import ScoreTrace
from shengji.ai import cwv_policy
from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.harvest.legal import enumerate_legal
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train import cwv_shortlist_screen as screen
from tests.test_cwv_static_public import _state_after
from tests.test_cwv_shortlist_screen import cfg
from tests.test_world_shortlist import round_signature


@pytest.mark.parametrize("architecture,encoding", [
    ("mlp", "reference"), ("mlp", "mlp-static"), ("transformer", "reference")])
def test_real_decision_reuses_work_but_keeps_cross_world_batches(architecture, encoding, monkeypatch):
    import torch

    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    torch.manual_seed(29)
    model = ValueNetwork(ValueModelConfig(
        architecture=architecture, width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    rnd = _state_after(73, 40)
    original = round_signature(rnd)
    legal_count = len(enumerate_legal(rnd, rnd.turn, cap=None).actions)
    assert 17 < legal_count < 300 and legal_count % 17 != 0
    calls = {"finish": 0, "encode": 0}
    finish = cwv_policy.finish_current_trick
    encoder_name = ("tensors_from_round_static" if encoding == "mlp-static"
                    else "tensors_from_round")
    encoder = getattr(cwv_policy, encoder_name)

    def count_finish(leaf, policy=None):
        calls["finish"] += 1
        return finish(leaf, policy)

    def count_encode(leaf, seat):
        calls["encode"] += 1
        return encoder(leaf, seat)

    monkeypatch.setattr(cwv_policy, "finish_current_trick", count_finish)
    monkeypatch.setattr(cwv_policy, encoder_name, count_encode)
    config = CWVShortlistConfig(worlds=3, selection_worlds=2, batch_size=17)
    runs = []
    for reuse in (False, True):
        calls.update(finish=0, encode=0)
        evaluator = CompleteWorldEvaluator(None, model=model, encoding=encoding, max_batch=13)
        trace = ScoreTrace(evaluator)
        bot = CWVShortlistBot(trace, seed=13, config=config, reuse_successors=reuse)
        bot.REPORT_FOLD_WORLDS = 30
        played = bot.decide_play(rnd, rnd.turn)
        runs.append((bot, played, trace, evaluator, dict(calls)))
        assert round_signature(rnd) == original
    (a, played_a, trace_a, evaluator_a, counts_a), (b, played_b, trace_b, evaluator_b, counts_b) = runs
    assert played_a == played_b and a.rng.getstate() == b.rng.getstate()
    assert trace_a.digest.hexdigest() == trace_b.digest.hexdigest()
    assert trace_a.batches == trace_b.batches
    assert evaluator_a.forward_calls == evaluator_b.forward_calls
    assert evaluator_a.model_rows == evaluator_b.model_rows == legal_count * 3
    assert a.shortlist_counts == b.shortlist_counts
    # Cache telemetry is not a policy change. Every other deterministic
    # shortlist field, including means and sampler counters, stays identical.
    clean = lambda value: {k: v for k, v in value.items()
                           if k not in ("wall_seconds", "successor_reuse")}
    assert clean(a.last_shortlist) == clean(b.last_shortlist)
    receipt = b.last_shortlist["successor_reuse"]
    assert counts_a == {"finish": legal_count * 3, "encode": legal_count * 3}
    assert 0 < counts_b["finish"] < counts_a["finish"]
    assert 0 < counts_b["encode"] < counts_a["encode"]
    assert receipt["root_actions"] == legal_count * 3
    assert receipt["leaf_completions"] == counts_b["finish"]
    assert receipt["leaf_hits"] == legal_count * 3 - counts_b["finish"]
    assert receipt["tensor_completions"] == counts_b["encode"]
    assert receipt["tensor_hits"] == legal_count * 3 - counts_b["encode"]
    assert 0 < receipt["peak_entries"] <= 128
    assert 0 < receipt["peak_tensor_entries"] <= 128


def test_screen_cli_worker_and_resume_bind_opt_in(tmp_path, monkeypatch):
    evaluator = type("Evaluator", (), {
        "checkpoint_sha256": "fixture-sha", "identity": lambda self: {"fixture": True}})()
    monkeypatch.setattr(screen, "shared_evaluator", lambda *args, **kwargs: evaluator)
    monkeypatch.setattr(screen, "_run_pending", lambda *args, **kwargs: None)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    out = tmp_path / "out"
    assert screen.main(["--arm", "learned", "--checkpoint", "fixture.pt",
                        "--seed0", "17", "--out", str(out),
                        "--reuse-successors"]) == 0
    # Inspect the actual published config, not the parser Namespace alone.
    config = json.loads((out / "config.json").read_text())
    assert config["reuse_successors"] is True
    assert screen.make_side(config, "arm", 13).reuse_successors is True
    assert not hasattr(screen.make_side(config, "baseline", 13), "reuse_successors")
    assert screen._recipe(config)["reuse_successors"] is True
    legacy = cfg("learned", checkpoint="fixture.pt", checkpoint_sha256="fixture-sha")
    assert screen.make_side(legacy, "arm", 13).reuse_successors is False
    assert "reuse_successors" not in screen._recipe(legacy)
    shard = {"schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
             "rank": "2", "recipe": screen._recipe(config),
             "records": [{"cluster": 0, "seed": 17, "mirror": m,
                          "trump_rank": "2", "arm": "learned"} for m in (0, 1)]}
    path = tmp_path / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert screen.reopen_shard(path, config, 0) == shard
    changed = copy.deepcopy(config)
    changed["reuse_successors"] = False
    with pytest.raises(ValueError, match="^completed shard does not match"):
        screen.reopen_shard(path, changed, 0)


def test_uniform_cannot_silently_accept_reuse():
    with pytest.raises(ValueError, match="^successor reuse requires the learned shortlist$"):
        CWVShortlistBot(None, config=CWVShortlistConfig(uniform=True), reuse_successors=True)
