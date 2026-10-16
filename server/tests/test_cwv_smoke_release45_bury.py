"""The release-45 bury smoke's receipt validator and its durable receipt (#983 HOLD).

Only ``build_production_bot`` and ``_one_round`` are mocked, as the reviewer did: the
validator must refuse candidate drift, a play-turn shortfall, non-finite or negative
timings and a fallback; a failure after a completed round must leave that round, a
typed terminal failure row and the room logs on disk, and exit non-zero.
"""
import asyncio
import json
import math
from types import SimpleNamespace

import pytest

import scripts.cwv_serving_smoke as cwv_serving_smoke
import scripts.smoke_release45_bury as smoke

NAME = "pv-search-test-bury-hybrid-bwv-000000000000"
ENV = {"SHENGJI_BOT": NAME, "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
       "SHENGJI_PV_BURY_WIDE_VALUE": "1", "SHENGJI_PV_BURY_WIDE_K": "64"}
FIRST = 4500


def good_row(seed=FIRST, plays=4, **changes):
    row = {
        "deal_seed": seed, "banker": 0, "trump": "S", "declared": True,
        "bury_wall_seconds": 0.1, "bury_compute_seconds": 0.09, "bury_elapsed_seconds": 0.09,
        "wide_seconds": 0.08, "schema": "cwv-bury-policy-v1", "arm": "hybrid",
        "chooser": "wide-value", "candidates": 64, "wide_k": 64, "wide_swaps": 1,
        "ballot_count": 30, "pre_bury_hand_size": 33, "pool_size": 180, "pool_size_exact": True,
        "chosen_is_incumbent": False, "fallback_reason": None,
        "committed": True, "recommit_refused": True, "bury_events": 1,
        "phase_after_bury": "play", "kitty_size": 8,
        "declare_calls": 26, "declare_max_call_seconds": 0.05,
        "value_declare_decisions": 1, "value_declare_search_seconds": [0.2],
        "plays_requested": plays,
        "plays": [{"seat": i % 4, "seconds": 0.03, "committed": True} for i in range(plays)],
        "play_stop": None,
    }
    row.update(changes)
    return row


def bot_info(**changes):
    info = {"kind": "bot", "policy": NAME, "env_bury_wide_value": "1", "env_bury_wide_k": "64",
            "bot_bury_wide_value": True, "bot_bury_wide_k": 64, "bot_bury_wide_swaps": 1}
    info.update(changes)
    return info


def expected(rounds=1, plays=4, **changes):
    out = {"policy": NAME, "k": 64, "rounds": rounds, "plays": plays, "first_seed": FIRST,
           "budget_seconds": 2.0}
    out.update(changes)
    return out


def full_row(seed=FIRST, **changes):
    max_plays = smoke.MAX_PLAYS
    row = good_row(seed, plays=max_plays)
    row.update({
        "plays_requested": max_plays,
        "full_round": True,
        "plays": [{"seat": i % 4, "seconds": 0.03, "committed": True}
                  for i in range(96)],
        "play_stop": {"reason": "round_end", "phase": "round_end"},
        "terminal_phase": "round_end",
        "hands_empty": True,
        "trick_empty": True,
        "round_result": {"attacker_points": 80, "kitty_points": 20,
                          "winner_team": 0, "level_change": 1, "next_banker": 1,
                          "new_levels": ["2", "2"], "game_over": False,
                          "games_won": [0, 0], "point_scored": False},
    })
    row.update(changes)
    return row


def types_of(failures):
    return {f["type"] for f in failures}


def test_a_complete_row_passes():
    assert smoke.validate_receipt(bot_info(), [good_row()], expected()) == []


def test_full_round_accepts_terminal_before_the_100_action_bound():
    # Kitty multipliers can legitimately make the reported attacker score
    # exceed 200; terminal validation must preserve the engine's result.
    assert smoke.validate_receipt(bot_info(), [full_row(round_result={
        **full_row()["round_result"], "attacker_points": 4120})],
                                  expected(full_round=True)) == []


@pytest.mark.parametrize("change", [
    {"play_stop": {"reason": "phase", "phase": "play"}},
    {"terminal_phase": "play"},
    {"hands_empty": False},
    {"trick_empty": False},
    {"round_result": None},
])
def test_full_round_requires_engine_terminal_witness(change):
    assert "terminal" in types_of(smoke.validate_receipt(
        bot_info(), [full_row(**change)], expected(full_round=True)))


def test_full_round_rejects_uncommitted_action():
    row = full_row()
    row["plays"][12]["committed"] = False
    assert "plays" in types_of(smoke.validate_receipt(
        bot_info(), [row], expected(full_round=True)))


def test_full_round_real_engine_path_reaches_terminal_with_multicard_plays(tmp_path):
    """The bounded producer uses the server snapshot/commit path, not direct Round.play."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv

    bot = HeuristicBot()
    # _one_round records the bury contract for the served policy; the cheap
    # engine bot has no policy record, so supply the empty optional witness.
    bot.last_bury_record = {}
    row = asyncio.run(smoke._one_round(srv, bot, FIRST, 4, tmp_path,
                                       full_round=True))
    assert row["play_stop"] == {"reason": "round_end", "phase": "round_end"}
    assert row["terminal_phase"] == "round_end"
    assert row["hands_empty"] is True and row["trick_empty"] is True
    assert row["round_result"]["winner_team"] in (0, 1)
    assert len(row["plays"]) < smoke.MAX_PLAYS
    assert any(len(event.get("cards", [])) > 1
               for event in smoke._events(tmp_path / f"S{FIRST}.jsonl", "play"))

    # Reuse the real producer's play/terminal fields with only the unrelated
    # wide-bury witness supplied by this validator's fixture, then prove that
    # removing terminal evidence is rejected.
    receipt_row = good_row(plays=smoke.MAX_PLAYS)
    receipt_row.update({key: row[key] for key in (
        "plays_requested", "full_round", "plays", "play_stop",
        "terminal_phase", "hands_empty", "trick_empty", "round_result")})
    assert smoke.validate_receipt(bot_info(), [receipt_row],
                                  expected(full_round=True)) == []
    receipt_row["terminal_phase"] = "play"
    assert "terminal" in types_of(smoke.validate_receipt(
        bot_info(), [receipt_row], expected(full_round=True)))


@pytest.mark.parametrize("candidates", [32, 63, 65, None, "64"])
def test_candidate_drift_fails(candidates):
    failures = smoke.validate_receipt(bot_info(), [good_row(candidates=candidates)], expected())
    assert types_of(failures) == {"candidates"}


def test_tiny_pool_scores_the_whole_pool_and_no_less():
    assert smoke.validate_receipt(bot_info(), [good_row(pool_size=40, candidates=40)], expected()) == []
    assert types_of(smoke.validate_receipt(bot_info(), [good_row(pool_size=40, candidates=32)],
                                           expected())) == {"candidates"}
    assert types_of(smoke.validate_receipt(bot_info(), [good_row(pool_size=None)],
                                           expected())) == {"candidates"}


def test_record_k_or_swaps_drift_fails():
    assert "recipe" in types_of(smoke.validate_receipt(bot_info(), [good_row(wide_k=32)], expected()))
    assert "recipe" in types_of(smoke.validate_receipt(bot_info(), [good_row(wide_swaps=2)], expected()))


@pytest.mark.parametrize("info", [bot_info(policy="pv-search-release44"), bot_info(env_bury_wide_k="32"),
                                  bot_info(bot_bury_wide_k=32), bot_info(bot_bury_wide_value=False),
                                  bot_info(bot_bury_wide_swaps=2), None])
def test_recipe_drift_fails(info):
    assert "recipe" in types_of(smoke.validate_receipt(info, [good_row()], expected()))


@pytest.mark.parametrize("row", [
    good_row(chooser="fallback", candidates=None, wide_k=None, wide_swaps=None, fallback_reason="budget"),
    good_row(fallback_reason="budget"),
    good_row(chooser="arm"),
])
def test_a_fallback_row_fails(row):
    assert "fallback" in types_of(smoke.validate_receipt(bot_info(), [row], expected()))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -0.01, None, True])
@pytest.mark.parametrize("field", ["bury_wall_seconds", "bury_compute_seconds", "bury_elapsed_seconds",
                                   "declare_max_call_seconds", "vd", "play"])
def test_nonfinite_or_negative_timing_fails(field, bad):
    if field == "vd":
        row = good_row(value_declare_search_seconds=[0.1, bad])
    elif field == "play":
        row = good_row()
        row["plays"][2]["seconds"] = bad
    else:
        row = good_row(**{field: bad})
    assert "timing" in types_of(smoke.validate_receipt(bot_info(), [row], expected()))


def test_missing_requested_play_turns_fails():
    short = good_row(plays=4)
    short["plays"] = short["plays"][:3]
    assert "plays" in types_of(smoke.validate_receipt(bot_info(), [short], expected()))
    stopped = good_row(play_stop={"reason": "phase", "phase": "done"})
    assert "plays" in types_of(smoke.validate_receipt(bot_info(), [stopped], expected()))
    uncommitted = good_row()
    uncommitted["plays"][0]["committed"] = False
    assert "plays" in types_of(smoke.validate_receipt(bot_info(), [uncommitted], expected()))


@pytest.mark.parametrize("change", [{"committed": False}, {"recommit_refused": False}, {"bury_events": 2},
                                    {"bury_events": 0}, {"phase_after_bury": "bury"}, {"kitty_size": 7}])
def test_not_committed_exactly_once_fails(change):
    assert "commit" in types_of(smoke.validate_receipt(bot_info(), [good_row(**change)], expected()))


def test_bury_over_budget_fails():
    assert "budget" in types_of(smoke.validate_receipt(bot_info(), [good_row(bury_wall_seconds=2.0)],
                                                      expected()))


@pytest.mark.parametrize("change", [{"declare_calls": -1}, {"declare_calls": 0},
                                    {"value_declare_decisions": -1}, {"value_declare_decisions": 1.5}])
def test_bad_counts_fail(change):
    assert "count" in types_of(smoke.validate_receipt(bot_info(), [good_row(**change)], expected()))


@pytest.mark.parametrize("change", [{"rounds": 0}, {"plays": -1}, {"plays": smoke.MAX_PLAYS + 1},
                                    {"k": 1}, {"budget_seconds": math.nan}, {"budget_seconds": 0.0}])
def test_invalid_expectations_fail(change):
    assert types_of(smoke.validate_receipt(bot_info(), [good_row()], expected(**change))) == {"expected_invalid"}


def test_round_coverage_is_bound():
    assert "coverage" in types_of(smoke.validate_receipt(bot_info(), [good_row()], expected(rounds=2)))
    assert "coverage" in types_of(smoke.validate_receipt(bot_info(), [good_row(seed=FIRST + 1)], expected()))
    assert "coverage" in types_of(smoke.validate_receipt(bot_info(), [], expected()))


# ---- the run: mocked build_production_bot and _one_round only ----

def fake_bot():
    return SimpleNamespace(bury_wide_value=True, bury_wide_k=64, bury_wide_swaps=1)


@pytest.fixture
def mocked(monkeypatch):
    def install(rows_or_errors):
        monkeypatch.setattr(cwv_serving_smoke, "build_production_bot", lambda env: (env["SHENGJI_BOT"], fake_bot()))
        queue = list(rows_or_errors)

        async def one_round(srv, bot, deal_seed, plays, log_dir, *, full_round=False):
            (log_dir / f"S{deal_seed}.jsonl").write_text(json.dumps({"e": "bury", "seed": deal_seed}) + "\n")
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        monkeypatch.setattr(smoke, "_one_round", one_round)
    return install


def write_fly(tmp_path):
    fly = tmp_path / "fly.toml"
    fly.write_text("[env]\n" + "".join(f"  {k} = '{v}'\n" for k, v in ENV.items()))
    return fly


def test_the_hold_reproduction_now_fails(mocked, tmp_path):
    """#983 HOLD: candidates 32 and plays [] with plays=4 returned passed=true."""
    row = good_row(candidates=32, bury_wall_seconds=0.1, plays=4)
    row["plays"] = []
    mocked([row])
    receipt = tmp_path / "r.jsonl"
    rc = smoke.main(["--fly-toml", str(write_fly(tmp_path)), "--rounds", "1", "--plays", "4",
                     "--first-seed", str(FIRST), "--receipt", str(receipt)])
    assert rc == 1
    terminal = smoke.read_receipt(receipt)[-1]
    assert terminal["kind"] == "terminal" and terminal["passed"] is False
    assert {"candidates", "plays"} <= types_of(terminal["failures"])


def test_a_complete_mocked_run_passes(mocked, tmp_path):
    mocked([good_row(FIRST), good_row(FIRST + 1)])
    receipt = tmp_path / "r.jsonl"
    rc = smoke.main(["--fly-toml", str(write_fly(tmp_path)), "--rounds", "2", "--plays", "4",
                     "--first-seed", str(FIRST), "--receipt", str(receipt)])
    assert rc == 0
    lines = smoke.read_receipt(receipt)
    assert [line["kind"] for line in lines] == ["header", "bot", "round", "round", "terminal"]
    assert lines[-1]["passed"] is True and lines[-1]["failures"] == []
    assert lines[-1]["summary"]["candidates"] == [64] and lines[-1]["summary"]["play_turns"] == 8


def test_a_failure_after_one_round_keeps_the_round_logs_and_a_terminal_row(mocked, tmp_path):
    mocked([good_row(FIRST), RuntimeError("deal 4501: server produced no bury turn")])
    receipt = tmp_path / "r.jsonl"
    rc = smoke.main(["--fly-toml", str(write_fly(tmp_path)), "--rounds", "3", "--plays", "4",
                     "--first-seed", str(FIRST), "--receipt", str(receipt)])
    assert rc == 1
    lines = smoke.read_receipt(receipt)
    assert [line["kind"] for line in lines] == ["header", "bot", "round", "terminal"]
    assert lines[2]["deal_seed"] == FIRST
    terminal = lines[-1]
    assert terminal["passed"] is False and terminal["rounds_completed"] == 1
    assert terminal["error"]["type"] == "RuntimeError"
    assert "no bury turn" in terminal["error"]["message"]
    assert any("RuntimeError" in line for line in terminal["error"]["traceback"])
    assert {"exception", "coverage"} <= types_of(terminal["failures"])
    logs = tmp_path / "r.jsonl.logs"
    assert (logs / f"S{FIRST}.jsonl").exists() and (logs / f"S{FIRST + 1}.jsonl").exists()


def test_a_build_failure_is_a_terminal_row(monkeypatch, tmp_path):
    def refuse(env):
        raise SystemExit("SHENGJI_BOT is not registered by this env")
    monkeypatch.setattr(cwv_serving_smoke, "build_production_bot", refuse)
    receipt = tmp_path / "r.jsonl"
    rc = smoke.main(["--fly-toml", str(write_fly(tmp_path)), "--rounds", "1", "--receipt", str(receipt)])
    assert rc == 1
    terminal = smoke.read_receipt(receipt)[-1]
    assert terminal["error"]["type"] == "SystemExit" and terminal["passed"] is False


def test_an_existing_receipt_or_log_dir_is_refused(mocked, tmp_path):
    mocked([good_row(FIRST)])
    receipt = tmp_path / "r.jsonl"
    receipt.write_text("prior evidence\n")
    with pytest.raises(FileExistsError):
        smoke.run(ENV, rounds=1, plays=4, first_seed=FIRST, receipt_path=receipt)
    assert receipt.read_text() == "prior evidence\n"
    other = tmp_path / "s.jsonl"
    (tmp_path / "s.jsonl.logs").mkdir()
    with pytest.raises(FileExistsError):
        smoke.run(ENV, rounds=1, plays=4, first_seed=FIRST, receipt_path=other)
    assert not other.exists()


@pytest.mark.parametrize("args", [["--plays", "101"], ["--plays", "-1"], ["--rounds", "0"]])
def test_out_of_range_arguments_are_refused(tmp_path, args):
    with pytest.raises(SystemExit):
        smoke.main(["--fly-toml", str(write_fly(tmp_path)), "--receipt", str(tmp_path / "r.jsonl"), *args])
    assert not (tmp_path / "r.jsonl").exists()


def test_the_recorded_pool_is_the_uncapped_widened_set():
    """`wide_pool_size` counts exactly what `wide_bury_candidates` would enumerate uncapped,
    so ``candidates == min(K, pool)`` is the chooser's own cap rule, on real deals."""
    import random

    from shengji.engine.game import Game
    from shengji.train.bury_wide_value import wide_bury_candidates

    for seed in range(4500, 4506):
        rnd = Game(random.Random(seed)).start_round()
        while rnd.phase == "deal":
            rnd.deal_next()
        rnd.finalize_declare()
        banker = rnd.banker
        hand = list(rnd.hands[banker])
        assert len(hand) == 33
        ballot = [hand[:8], hand[8:16], hand[1:9]]
        full, _ = wide_bury_candidates(rnd, banker, ballot, k=10 ** 6)
        for k in (2, 3, 64, 10 ** 6):
            capped, counts = wide_bury_candidates(rnd, banker, ballot, k=k)
            record = {"candidates": capped, "wide_value": {"ballot_count": counts["ballot_count"]}}
            size, exact = smoke.wide_pool_size(hand, record, rnd.ordering)
            if k < len(ballot):
                assert (size, exact) == (len(ballot), False)
            else:
                assert (size, exact) == (len(full), True)
                assert len(capped) == min(k, size)
