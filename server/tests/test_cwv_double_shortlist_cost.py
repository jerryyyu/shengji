"""Can-fail parity and retained-error witnesses for the cache diagnostic."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import cwv_double_shortlist_cost as probe


def pair():
    row = {"ordinal": 12, "reuse": False, "complete": True, "wall_seconds": 2.0,
           "semantic": {"record": {"means": [1.0, 2.0], "report_fold": {"gap": 0.5}},
                        "played": ["C2"], "scores_sha256": "s", "batches": [128, 3],
                        "rng_sha256": "r", "input_sha256": "i"}}
    other = copy.deepcopy(row)
    other.update(reuse=True, wall_seconds=1.0)
    return [row, other]


def test_parity_excludes_only_named_telemetry():
    assert probe.compare_pairs(pair()) == [{"ordinal": 12, "status": "identical",
           "reference_wall_seconds": 2.0, "reuse_wall_seconds": 1.0, "speedup": 2.0}]
    assert probe.semantic_record({"search_secs": 1, "means": [1], "child": {
        "wall_seconds": 3, "successor_reuse": {}, "inner_successor_reuse": {}, "gap": 2}}) == {
            "means": [1], "child": {"gap": 2}}


@pytest.mark.parametrize("key,value", [
    ("scores_sha256", "wrong"), ("batches", [3, 128]), ("rng_sha256", "wrong"),
    ("played", ["S2"]), ("input_sha256", "wrong"), ("record", {"means": [1, 3]})])
def test_parity_rejects_every_semantic_drift(key, value):
    rows = pair()
    rows[1]["semantic"][key] = value
    with pytest.raises(ValueError, match="^inner reuse changed scores, batches, MC decision, input or RNG$"):
        probe.compare_pairs(rows)


def test_timeout_is_not_a_parity_pass_and_duplicates_refuse():
    rows = pair()
    rows[0]["complete"] = False
    assert probe.compare_pairs(rows) == [{"ordinal": 12, "status": "incomplete"}]
    with pytest.raises(ValueError, match="^duplicate cost case$"):
        probe.compare_pairs(rows + [rows[0]])


@pytest.mark.parametrize("seconds", ["nan", "inf", "0", "601"])
def test_bad_deadline_refuses_before_data_open(seconds):
    with pytest.raises(SystemExit):
        probe.main(["--panel", "absent", "--checkpoint", "absent", "--out", "absent",
                    "--seconds", seconds])


def test_actual_driver_keeps_timeout_and_later_case_and_resume(tmp_path, monkeypatch):
    panel = tmp_path / "panel.json"
    panel.write_text(json.dumps({"split": "fit", "coordinate": ["2", 0, 0],
                                 "stages": [{"decision_ordinal": 12, "snapshot": {"turn": 0}}]}))
    evaluator = SimpleNamespace(checkpoint_sha256="test-checkpoint",
        score_many=lambda positions, seats, **kwargs: np.asarray([1.0] * len(positions)))
    monkeypatch.setattr(probe, "shared_evaluator", lambda *a, **kw: evaluator)
    monkeypatch.setattr(probe, "execution_source_identity", lambda path: "test-source")
    monkeypatch.setattr(probe, "_round_from_snapshot", lambda s: SimpleNamespace(**s))
    monkeypatch.setattr(probe, "_state_snapshot", lambda rnd: vars(rnd))
    calls = []

    def make(config, side, seed):
        reuse = config["double_shortlist"]["reuse_successors"]
        bot = SimpleNamespace(evaluator=evaluator, inner_reuse_successors=reuse,
                              last_decision_record=None, double_shortlist_counts={},
                              rng=SimpleNamespace(getstate=lambda: (1, 2)))

        def decide(rnd, seat):
            calls.append(reuse)
            if not reuse:
                raise probe.ProbeTimeout("test expiry")
            evaluator.score_many([rnd, rnd], [seat, seat])
            bot.last_decision_record = {"means": [1, 2], "search_secs": 3}
            return ["C2"]
        bot.decide_play = decide
        return bot

    monkeypatch.setattr(probe, "make_side", make)
    out = tmp_path / "out"
    args = ["--panel", str(panel), "--checkpoint", "unused", "--out", str(out),
            "--ordinals", "12", "--seconds", "1"]
    assert probe.main(args) == 1
    assert calls == [False, True]
    failed = json.loads((out / "ordinal-0012-reuse-0.json").read_text())
    assert not failed["complete"] and failed["error"] == "ProbeTimeout: test expiry"
    passed_path = out / "ordinal-0012-reuse-1.json"
    saved = passed_path.read_bytes()
    passed = json.loads(saved)
    assert passed["complete"] and passed["semantic"]["batches"] == [2]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["complete"] is False
    assert summary["checks"] == [{"ordinal": 12, "status": "incomplete"}]
    assert probe.main(args) == 1
    assert calls == [False, True] and passed_path.read_bytes() == saved
