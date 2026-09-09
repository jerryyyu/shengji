import json
from types import SimpleNamespace

import pytest

from shengji.ai.smart import SmartBot
from shengji.train import cwv_bury_screen as screen


def test_three_arm_driver_preserves_completed_arms_after_failure(tmp_path, monkeypatch):
    config = {"output": str(tmp_path), "checkpoint": "unused", "checkpoint_sha256": "test",
              "config_sha256": "config", "deals": 1}
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    calls = []
    fail = [True]

    class Control(SmartBot):
        def decide_bury(self, rnd, seat):
            chosen = super().decide_bury(rnd, seat)
            self.last_bury_record = {"elapsed_seconds": 0.0}
            return chosen

    def factory(evaluator, *, seed, arm):
        calls.append((arm, seed))
        if arm == "hybrid" and fail[0]:
            raise RuntimeError("injected third-arm failure")
        return Control()

    monkeypatch.setattr(screen, "make_cwv_bury_bot", factory)
    with pytest.raises(RuntimeError, match="^injected third-arm failure$"):
        screen.run_cluster(config, 0)
    assert {p.name for p in tmp_path.glob("arm-*.json")} == {
        "arm-0000-heuristic.json", "arm-0000-mc.json"}
    saved = {p.name: p.read_bytes() for p in tmp_path.glob("arm-*.json")}
    calls.clear()
    fail[0] = False
    shard = screen.run_cluster(config, 0)
    assert len(calls) == 4 and all(arm == "hybrid" for arm, _ in calls)
    assert all((tmp_path / name).read_bytes() == raw for name, raw in saved.items())
    records = shard["records"]
    assert [r["arm"] for r in records] == list(screen.ARMS)
    assert len({r["attacker_points"] for r in records}) == 1
    assert records[0]["transcript"] == records[1]["transcript"] == records[2]["transcript"]
    result = screen.summarize([shard], config)
    assert result["complete"]
    assert result["comparisons"]["hybrid_minus_mc"]["utility"]["mean"] == 0
    old = json.loads((tmp_path / "arm-0000-mc.json").read_text())
    old["config_sha256"] = "wrong"
    (tmp_path / "arm-0000-mc.json").write_text(json.dumps(old))
    with pytest.raises(ValueError, match="^completed arm binding mismatch$"):
        screen.run_cluster(config, 0)


def test_gameplay_metric_is_screen_metric_not_half_level_model_support():
    assert [screen.banker_utility(p) for p in (0, 35, 75, 80, 120, 160)] == [3, 2, 1, -1, -1, -2]
