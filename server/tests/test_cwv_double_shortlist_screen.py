"""Consumer wiring for the opt-in double-shortlist screen, not a strength test."""
import copy
import json

import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_double_shortlist import CWVDoubleShortlistBot
from shengji.train.cwv_shortlist import CWVShortlistBot
from tests.test_cwv_double_shortlist import PointsNet
from tests.test_cwv_shortlist_screen import cfg
from tests.test_world_shortlist import play_state


class Evaluator(PointsNet):
    checkpoint_sha256 = "a" * 64

    def identity(self):
        return {"checkpoint_sha256": self.checkpoint_sha256}


def test_cli_persists_inner_recipe_and_constructs_actual_comparator(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **kw: Evaluator())
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *a, **kw: seen.append(config))
    out = tmp_path / "screen"
    assert S.main([
        "--arm", "learned", "--checkpoint", str(tmp_path / "unused.pt"),
        "--worlds", "1", "--selection-worlds", "30", "--report-worlds", "30",
        "--inner-mode", "learned", "--inner-worlds", "1",
        "--inner-batch-size", "7", "--baseline", "flat-shortlist",
        "--clusters", "1", "--seed0", "17", "--out", str(out),
    ]) == 0
    config = json.loads((out / "config.json").read_text())
    assert config == seen[0]
    arm = S.make_side(config, "arm", 23)
    baseline = S.make_side(config, "baseline", 23)
    assert type(arm) is CWVDoubleShortlistBot
    assert type(baseline) is CWVShortlistBot
    assert arm.inner_mode == "learned" and arm.inner_worlds == 1
    assert arm.inner_batch_size == 7
    assert arm.N_DETERMINIZATIONS == baseline.N_DETERMINIZATIONS == 30
    assert arm.REPORT_FOLD_WORLDS == baseline.REPORT_FOLD_WORLDS == 30
    assert arm.shortlist_config == baseline.shortlist_config
    assert S._recipe(config)["double_shortlist"] == config["double_shortlist"]
    assert config["double_shortlist"]["guidance"] == "selection-fraction-ceil-v2"
    assert S._recipe(config)["baseline"] == "flat-shortlist"

    # Exercise the timed worker's real decision consumer, not just the helper.
    state = play_state()
    wrapped = S.CwvTimedPolicy(arm)
    wrapped.decide_play(state, state.turn)
    detail = wrapped.decisions[-1]["cwv_double_shortlist"]
    assert {row["stage"] for row in detail["stages"]} == {"selection", "report"}
    assert all(row["worlds"] == 30 and row["actual_inner_worlds"] == 1
               for row in detail["stages"])
    assert detail["inner_full_rollouts"] > 0
    counts = S.work_counters([wrapped])
    assert counts["double_inner_full_rollouts"] == detail["inner_full_rollouts"]
    assert counts["total_rollouts"] == (
        counts["outer_continuation_rollouts"] + counts["inner_continuation_rollouts"])
    assert counts["inner_continuation_rollouts"] > 0


def test_inner_recipe_changes_cannot_reopen_completed_pairs(tmp_path):
    config = cfg("learned", double_shortlist={"mode": "learned", "worlds": 4,
                 "guidance": "selection-fraction-ceil-v2"},
                 baseline="flat-shortlist")
    shard = {
        "schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
        "rank": "2", "recipe": S._recipe(config),
        "records": [{"cluster": 0, "seed": 17, "mirror": mirror,
                     "trump_rank": "2", "arm": "learned"} for mirror in (0, 1)],
    }
    path = tmp_path / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    changed = copy.deepcopy(config)
    changed["double_shortlist"]["worlds"] = 5
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, changed, 0)
    changed = copy.deepcopy(config)
    del changed["double_shortlist"]["guidance"]
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, changed, 0)
    changed = copy.deepcopy(config)
    changed["baseline"] = "production"
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, changed, 0)


def test_legacy_same_count_recipe_cannot_execute_as_equal_fraction(monkeypatch):
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **kw: Evaluator())
    config = cfg("learned", double_shortlist={"mode": "learned", "worlds": 4,
                 "batch_size": 128}, checkpoint_sha256="a" * 64)
    with pytest.raises(ValueError, match="^double-shortlist guidance recipe is not selection-fraction-ceil-v2$"):
        S.make_side(config, "arm", 23)


@pytest.mark.parametrize("extra", [
    ["--arm", "uniform", "--inner-mode", "uniform"],
    ["--arm", "learned", "--checkpoint", "unused", "--alternatives", "8",
     "--inner-mode", "learned"],
    ["--arm", "learned", "--checkpoint", "unused", "--inner-mode", "learned",
     "--inner-worlds", "0"],
    ["--arm", "uniform", "--baseline", "flat-shortlist"],
])
def test_invalid_inner_combinations_refuse_before_evaluator(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid configuration must not load the model")

    monkeypatch.setattr(S, "shared_evaluator", forbidden)
    with pytest.raises(SystemExit):
        S.main(["--seed0", "17", "--out", str(tmp_path / "out"), *extra])


def test_flat_default_keeps_legacy_recipe_and_production_baseline():
    config = cfg()
    assert "double_shortlist" not in S._recipe(config)
    assert "baseline" not in S._recipe(config)
    baseline = S.make_side(config, "baseline", 9)
    assert not isinstance(baseline, CWVShortlistBot)
    assert baseline.N_DETERMINIZATIONS == 30 and baseline.REPORT_FOLD_WORLDS == 300
