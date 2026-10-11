import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_log_delta.py"
SPEC = importlib.util.spec_from_file_location("production_log_delta", SCRIPT)
assert SPEC and SPEC.loader
delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delta)


def _line(**fields):
    return (json.dumps(fields, sort_keys=True) + "\n").encode()


def test_delta_attributes_late_rows_to_recorded_policy_not_current_config(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    old = _line(t=1.0, e="round_start", round=7)
    appended = b"".join([
        _line(t=2.0, e="model_search", round=7, phase="play", event="completed",
              policy="old-policy", elapsed_seconds=0.2),
        _line(t=2.1, e="play", round=7, bot=True, cards=["S2"],
              decision={"schema": "pv-search-decision-v1", "policy": "old-policy",
                        "seconds": 0.21, "work_complete": True,
                        "refusal_fallback_worlds": 0}),
        _line(t=2.2, e="bot_timing", round=7, phase="play", acted=True,
              policy="old-policy", compute_seconds=0.22, turn_seconds=0.7),
    ])
    before.write_bytes(old)
    after.write_bytes(old + appended)

    report = delta.summarize(delta.appended_events(before, after))

    assert report["appended_events"] == 3
    assert report["decision_policy_counts"] == {"old-policy": 1}
    assert report["observed_event_policy_counts"] == {"old-policy": 3}
    assert report["unknown_policy_plays"] == 0
    assert report["search_fallbacks"] == 0
    assert report["latency_seconds_p50"] == {
        "decision": 0.21, "model_search_completed": 0.2,
        "bot_compute": 0.22, "turn": 0.7,
    }


def test_delta_refuses_rewritten_history(tmp_path):
    before = tmp_path / "before.jsonl"
    after = tmp_path / "after.jsonl"
    before.write_bytes(_line(t=1, e="play"))
    after.write_bytes(_line(t=1, e="round_start"))

    with pytest.raises(delta.DeltaError, match="exact prefix"):
        delta.appended_events(before, after)


def test_summary_exposes_unknown_policy_and_fallbacks():
    report = delta.summarize([
        {"t": 1, "e": "play", "round": 1, "bot": True,
         "decision": {"schema": "pv-search-fallback-v1", "work_complete": False,
                      "refusal_fallback_worlds": 4}},
    ])

    assert report["unknown_policy_plays"] == 1
    assert report["search_fallbacks"] == 1
    assert report["refusal_fallback_worlds"] == 4
    assert report["decision_policy_counts"] == {}
