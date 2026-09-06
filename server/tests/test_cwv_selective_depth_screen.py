"""CLI/worker/receipt witnesses for selective depth, not a strength test."""
import copy
import json

import numpy as np
import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_selective_depth import CWVSelectiveDepthBot
from shengji.train.cwv_shortlist import CWVShortlistBot
from tests.test_cwv_double_shortlist_screen import Evaluator
from tests.test_world_shortlist import fixed_world, play_state, round_signature


def configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **kw: Evaluator())
    monkeypatch.setattr(S, "_run_pending", lambda *a, **kw: None)
    out = tmp_path / "screen"
    assert S.main([
        "--arm", "learned", "--checkpoint", "fixture.pt",
        "--worlds", "1", "--selection-worlds", "2", "--report-worlds", "30",
        "--inner-mode", "learned", "--inner-worlds", "4", "--selective-depth",
        "--inner-legal-limit", "1", "--baseline", "flat-shortlist",
        "--clusters", "1", "--seed0", "17", "--out", str(out),
    ]) == 0
    return json.loads((out / "config.json").read_text())


def test_cli_persists_gate_and_worker_keeps_flat_baseline(tmp_path, monkeypatch):
    config = configuration(tmp_path, monkeypatch)
    assert config["selective_depth"] == {
        "gate": "paired-flat-gap-v1", "z": 1.7,
        "inner_legal_limit": 1, "raw_follow_limit": 4096,
    }
    assert S._recipe(config)["selective_depth"] == config["selective_depth"]
    arm = S.make_side(config, "arm", 7)
    baseline = S.make_side(config, "baseline", 7)
    assert type(arm) is CWVSelectiveDepthBot
    assert type(baseline) is CWVShortlistBot
    assert arm.ADAPTIVE_ALLOCATION is True  # existing uniform lockstep hook
    assert baseline.ADAPTIVE_ALLOCATION is False
    assert arm.gate_z == 1.7 and arm.inner_legal_limit == 1
    assert arm.REPORT_FOLD_WORLDS == baseline.REPORT_FOLD_WORLDS == 30
    assert arm.shortlist_config == baseline.shortlist_config


@pytest.mark.parametrize("ambiguous", [False, True])
def test_real_worker_decision_emits_gate_and_extra_work(tmp_path, monkeypatch, ambiguous):
    config = configuration(tmp_path, monkeypatch)
    bot = S.make_side(config, "arm", 7)
    state = play_state()
    before = round_signature(state)
    pilot_calls = []

    def pilot(rnd, seat, worlds, candidates, *, stage, **kwargs):
        pilot_calls.append(stage)
        matrix = np.full((len(worlds), len(candidates)), 100.0)
        if ambiguous and stage == "selection":
            matrix[0, 1:] += 1
            matrix[1, 1:] -= 1
        return matrix

    # Only expensive flat simulation returns are synthetic. The persisted
    # config, factory, real decision/samplers, gate, inner fallback, paired
    # report, and timed consumer remain live. No gate-result monkeypatch.
    monkeypatch.setattr(bot, "_flat_matrix", pilot, raising=False)
    wrapped = S.CwvTimedPolicy(bot)
    wrapped.decide_play(state, state.turn)
    trace = wrapped.decisions[-1]
    detail = trace["cwv_selective_depth"]
    assert detail["triggered"] is ambiguous
    assert detail["pilot_worlds"] == 2
    assert trace["report"]["complete"] is True
    assert trace["report"]["worlds"] == 30
    assert detail["stages"][0]["guided"] is ambiguous
    assert detail["stages"][1]["guided"] is ambiguous
    assert round_signature(state) == before
    counts = S.work_counters([wrapped])
    assert counts["selective_triggered"] == int(ambiguous)
    assert counts["selective_decisions"] == 1
    work = bot.last_decision_record["work"]
    assert counts["total_rollouts"] == work["total_rollouts_including_selective_depth"]
    assert counts["total_rollouts"] == (
        work["selection_rollouts"] + work["report_rollouts"]
        + counts["double_inner_full_rollouts"] + counts["selective_extra_rollouts"])
    if ambiguous:
        assert detail["inner_skipped"] > 0
        assert counts["selective_extra_rollouts"] > 0
        assert counts["selective_extra_rollouts"] == 2 * len(bot.last_decision_record["candidates"])
        assert pilot_calls == ["selection"]
    else:
        assert detail["inner_eligible"] == detail["inner_skipped"] == 0
        assert counts["selective_extra_rollouts"] == 0
        assert counts["double_inner_full_rollouts"] == 0
        assert pilot_calls == ["selection", "report"]


def test_changed_gate_cannot_reopen_pair(tmp_path, monkeypatch):
    config = configuration(tmp_path, monkeypatch)
    shard = {
        "schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
        "rank": "2", "recipe": S._recipe(config),
        "records": [{"cluster": 0, "seed": 17, "mirror": mirror,
                     "trump_rank": "2", "arm": "learned"} for mirror in (0, 1)],
    }
    path = tmp_path / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    for field, value in (("z", 2.0), ("inner_legal_limit", 2), ("raw_follow_limit", 8192)):
        changed = copy.deepcopy(config)
        changed["selective_depth"][field] = value
        with pytest.raises(ValueError, match="completed shard"):
            S.reopen_shard(path, changed, 0)
    changed = copy.deepcopy(config)
    del changed["selective_depth"]
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, changed, 0)


def test_false_gate_matches_flat_decision_and_independent_report(tmp_path, monkeypatch):
    config = configuration(tmp_path, monkeypatch)
    state = play_state()
    before = round_signature(state)
    bots = [S.make_side(config, side, 7) for side in ("arm", "baseline")]
    for bot in bots:
        monkeypatch.setattr(bot, "_sample_hands", lambda rnd, seat, mem: fixed_world(rnd, seat))
        bot.decide_play(state, state.turn)
    arm, baseline = [bot.last_decision_record for bot in bots]
    assert arm["cwv_selective_depth"]["triggered"] is False
    assert arm["cwv_selective_depth"]["inner_rollouts"] == 0
    for key in ("candidates", "means", "paired_se", "played", "reason", "report_seed",
                "allocation_seed", "rng_state", "report_fold", "work"):
        if key == "work":
            assert {k: arm[key][k] for k in baseline[key]} == baseline[key]
        else:
            assert arm[key] == baseline[key], key
    assert bots[0].rng.getstate() == bots[1].rng.getstate()
    assert round_signature(state) == before


@pytest.mark.parametrize("ambiguous", [False, True])
def test_opposite_report_evidence_cannot_change_selection_gate(tmp_path, monkeypatch, ambiguous):
    config = configuration(tmp_path, monkeypatch)
    state = play_state()
    bots = []
    for report_gap in (-100., 100.):
        bot = S.make_side(config, "arm", 7)
        def pilot(rnd, seat, worlds, candidates, *, stage, **kwargs):
            matrix = np.full((len(worlds), len(candidates)), 100.)
            if ambiguous and stage == "selection":
                matrix[0, 1:] += 1
                matrix[1, 1:] -= 1
            return matrix
        monkeypatch.setattr(bot, "_flat_matrix", pilot)
        original = bot._lockstep_values
        def values(*args, _original=original, _bot=bot, _gap=report_gap, **kwargs):
            matrix = _original(*args, **kwargs)
            if kwargs["stage"] == "report":
                assert _bot.last_selective_depth["triggered"] is ambiguous
                matrix = matrix.copy()
                matrix[:, 0], matrix[:, 1] = 100. + _gap, 100.
            return matrix
        monkeypatch.setattr(bot, "_lockstep_values", values)
        bot.decide_play(state, state.turn)
        bots.append(bot)
    records = [bot.last_decision_record for bot in bots]
    assert records[0]["report_fold"]["gap"] * records[1]["report_fold"]["gap"] < 0
    for record in records:
        assert record["cwv_selective_depth"]["triggered"] is ambiguous
    for key in ("rng_state", "report_seed", "allocation_seed", "report_candidate_index"):
        assert records[0][key] == records[1][key]
    assert records[0]["report_seed"] != records[0]["allocation_seed"]
    assert bots[0].rng.getstate() == bots[1].rng.getstate()


@pytest.mark.parametrize("extra", [
    ["--selective-depth"],
    ["--selective-depth", "--inner-mode", "uniform"],
    ["--selective-depth", "--inner-mode", "learned", "--selection-allocation", "adaptive"],
    ["--selective-depth", "--inner-mode", "learned", "--inner-worlds", "8"],
    ["--selective-depth", "--inner-mode", "learned", "--inner-legal-limit", "0"],
    ["--inner-legal-limit", "128"],
])
def test_invalid_cli_refuses_before_loading_model(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid CLI must not load a model")
    monkeypatch.setattr(S, "shared_evaluator", forbidden)
    with pytest.raises(SystemExit):
        S.main(["--arm", "learned", "--checkpoint", "unused.pt", "--seed0", "17",
                "--out", str(tmp_path / "out"), *extra])


def test_probe_retains_a_failed_case_without_retry_or_success_promotion(tmp_path, monkeypatch):
    from scripts import cwv_selective_depth_probe as probe
    panel = tmp_path / "panel.json"
    panel.write_text(json.dumps({"split": "fit", "coordinate": ["2", 0, 0],
                                "stages": [{"decision_ordinal": i, "snapshot": {}}
                                           for i in (0, 12, 24)]}))
    out = tmp_path / "timings"
    monkeypatch.setattr(probe, "shared_evaluator", lambda *a, **k: Evaluator())
    monkeypatch.setattr(probe, "execution_source_identity", lambda *a: "test-source")
    monkeypatch.setattr(probe, "_round_from_snapshot", lambda *a: play_state())
    monkeypatch.setattr(probe, "_state_snapshot", lambda *a: {})
    calls = []
    class FailingBot:
        last_decision_record = None
        def decide_play(self, *args):
            calls.append(1)
            raise TimeoutError("fixture")
    monkeypatch.setattr(probe, "make_side", lambda *a: FailingBot())
    argv = ["--panel", str(panel), "--checkpoint", "fixture.pt", "--out", str(out)]
    assert probe.main(argv) == 1
    receipt = out / "ordinal-0000-baseline.json"
    original = receipt.read_bytes()
    assert json.loads(original)["error"] == "TimeoutError: fixture"
    assert probe.main(argv) == 1
    assert len(calls) == 1 and receipt.read_bytes() == original
    assert not (out / "summary.json").exists()
