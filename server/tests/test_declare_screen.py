import copy
import json

import pytest

from shengji.ai.smart import SmartBot
from shengji.train import declare_screen as screen


def test_population_starts_before_deal_and_covers_real_rank_first_round():
    specs = [screen.deal_spec(i) for i in range(53)]
    assert len({s["seed"] for s in specs}) == 53
    assert len({(s["rank"], s["initial_banker"]) for s in specs}) == 53
    assert specs[-1]["initial_banker"] is None
    assert specs[-1]["rank"] == "2"
    assert screen.deal_spec(53)["seed"] != specs[0]["seed"]


def test_baseline_matches_literal_deal_and_final_calls():
    import random
    from shengji.engine.round import Round
    for i in (0, 9, 24, 51, 52):
        spec = screen.deal_spec(i)
        actual, events = screen.prepare_round(spec, "baseline", 0)
        expected = Round(spec["rank"], spec["initial_banker"], random.Random(spec["seed"]))
        bot = SmartBot()
        while expected.phase == "deal":
            seat, _, _ = expected.deal_next()
            cards = bot.decide_declare(expected, seat)
            if cards:
                expected.declare(seat, cards)
        for seat in range(4):
            cards = bot.decide_declare(expected, seat, final=True)
            if cards:
                expected.declare(seat, cards)
        expected.finalize_declare()
        assert (actual.declaration, actual.banker, actual.trump_suit, actual.hands) == (
            expected.declaration, expected.banker, expected.trump_suit, expected.hands)
        assert all(not e["changed"] for e in events)


def test_focal_utility_tracks_team_not_selected_banker():
    rnd, _ = screen.prepare_round(screen.deal_spec(52), "baseline", 0)
    other = copy.deepcopy(rnd)
    a = screen.finish_round(rnd, [SmartBot() for _ in range(4)], 0)
    b = screen.finish_round(other, [SmartBot() for _ in range(4)], 1)
    assert a["focal_signed_levels"] == -b["focal_signed_levels"] != 0
    assert a["focal_won"] + b["focal_won"] == 1
    assert a["transcript"] == b["transcript"]
    assert rnd.phase == other.phase == "round_end"


def test_real_census_reopens_and_does_not_play(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError("census must never construct play/model bots")
    monkeypatch.setattr(screen, "make_bots", forbidden)
    config = {"output": str(tmp_path), "start_index": 0, "mode": "census",
              "config_sha256": "test", "deals": 1}
    first = screen.run_cluster(config, 0)
    assert len(first["records"]) == 4
    assert all("outcome" not in r for r in first["records"])
    monkeypatch.setattr(screen, "prepare_round", forbidden)
    assert screen.run_cluster(config, 0) == first
    result = screen.summarize([first], config)
    assert result["completed_independent_deals"] == 1
    assert result["comparisons"] == {}


def test_completed_arm_retained_after_failure(tmp_path, monkeypatch):
    original = screen.prepare_round
    def failing(spec, arm, team):
        if arm == "pair-eager":
            raise RuntimeError("injected after first valid arm")
        return original(spec, arm, team)
    config = {"output": str(tmp_path), "start_index": 0, "mode": "census",
              "config_sha256": "test", "deals": 1}
    monkeypatch.setattr(screen, "prepare_round", failing)
    with pytest.raises(RuntimeError, match="^injected after first valid arm$"):
        screen.run_cluster(config, 0)
    saved = tmp_path / "arm-00000-0-baseline.json"
    before = saved.read_bytes()
    monkeypatch.setattr(screen, "prepare_round", original)
    assert len(screen.run_cluster(config, 0)["records"]) == 4
    assert saved.read_bytes() == before
    row = json.loads(before)
    row["focal_team"] = 1
    saved.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="^completed declaration arm mismatch$"):
        screen.run_cluster(config, 0)


def test_mirrors_not_counted_as_independent_games():
    records = []
    for team in (0, 1):
        for arm in screen.ARMS:
            outcome = {k: 0 for k in ("focal_signed_levels", "focal_won", "kitty_bonus", "kitty_ge80")}
            outcome["focal_signed_levels"] = (2 if team == 0 else 0) if arm == "pair-eager" else 0
            records.append({"focal_team": team, "arm": arm, "events": [],
                            "trump_suit": "S", "banker": 0, "declaration": None, "outcome": outcome,
                            "cpu_seconds": 1, "wall_seconds": 1})
    result = screen.summarize([{"records": records}], {"mode": "play", "deals": 1})
    assert result["comparisons"]["focal_signed_levels"]["mean"] == 1
    assert result["comparisons"]["focal_signed_levels"]["n_independent_states"] == 1


def test_gameplay_wiring_retains_actual_outcomes(tmp_path, monkeypatch):
    # Exercise real complete rounds with a cheap continuation, not a mock
    # scorer. This is a wiring test, not evidence for W32 declaration strength.
    monkeypatch.setattr(screen, "make_bots", lambda *_: [SmartBot() for _ in range(4)])
    config = {"output": str(tmp_path), "start_index": 52, "mode": "play",
              "config_sha256": "test", "deals": 1}
    shard = screen.run_cluster(config, 0)
    assert all(r["outcome"]["transcript"] for r in shard["records"])
    assert all(r["outcome"]["focal_signed_levels"] != 0 for r in shard["records"])
    assert screen.run_cluster(config, 0) == shard
