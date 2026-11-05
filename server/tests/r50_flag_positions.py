"""Release-50 decisions at fixed production positions: the flag-off parity
witness of the opt-in serving rules.

Three production rounds, reduced to the events the engine replays (deck,
declarations, trump, bury, plays; the refused throw keeps its attempted cards)
in ``fixtures/r50_flag_rounds.json``.  ``POSITIONS`` are ten decisions in
them: leads and follows, above and within the exact stages' seven-card bound,
after accepted throws (ADKY round 3 trick 11, SDUS round 2 tricks 4 and 7) and
after a refused one (WJLB round 2 trick 16).

The bot is release 50 as the server builds it (`test_release50_fly_config.served_bot`:
fly.toml's env, the registry's import-time registration, ``make_bot``), with
its three clocks lifted (``lift``) so a slow engine never cuts a stage and the
decision is a function of the code alone.  ``decision`` returns the played
cards and digests of the base worlds and of the decision record without the
fields that measure the run (durations, solver effort).  ``fixtures/r50_flag_off_decisions.json`` holds the same
projection computed on the main tree the rules were added to; a rule that is
off must reproduce it exactly, on the pure and the compiled engine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
ROUNDS = json.loads((FIXTURES / "r50_flag_rounds.json").read_text())
PINNED = FIXTURES / "r50_flag_off_decisions.json"
SEED = 13046117975
POSITIONS = (("ADKY3", 9, 0), ("ADKY3", 11, 1), ("ADKY3", 12, 0), ("ADKY3", 13, 0),
             ("SDUS2", 8, 0), ("SDUS2", 14, 0), ("SDUS2", 14, 1), ("WJLB2", 16, 1),
             ("WJLB2", 17, 0), ("WJLB2", 18, 1))


def replay(key: str, trick: int, pos: int):
    """The live Round of round ``key`` at (trick, 1-based; position in trick)."""
    from shengji.rl.replay_log import rebuild_round

    events = ROUNDS[key]
    rnd = rebuild_round(events)
    t, p = 1, 0
    for event in events:
        if event["e"] != "play":
            continue
        if (t, p) == (trick, pos):
            assert rnd.turn == event["seat"]
            return rnd
        before = len(rnd.history)
        rnd.play(event["seat"], list(event.get("attempted", event["cards"])))
        trick_plays = (rnd.history[-1] if len(rnd.history) != before else rnd.trick).plays
        assert sorted(trick_plays[-1].cards) == sorted(event["cards"])
        p += 1
        if len(rnd.history) != before:
            t, p = t + 1, 0
    raise KeyError((key, trick, pos))


def lift(bot):
    """The serving budget, the exact lead's deadline and the greedy finish's
    deadline set far beyond any decision here, the same for every arm."""
    bot.serving_budget_seconds = 600.0
    bot.exact_lead_max_seconds = 300.0
    if bot.leaf_greedy_deadline_ms:
        bot.leaf_greedy_deadline_ms = 600_000
    return bot


def _engine_dependent(key: str) -> bool:
    """A record field that measures the run, not the decision: a duration, or
    a solver's effort (the pure and compiled solvers visit different nodes on
    the way to the same values)."""
    return key == "seconds" or key.endswith(("_seconds", "_ms", "_nodes", "_cache_hits"))


def decision(bot, rnd) -> dict:
    """``{cards, worlds, record}``: the played cards, and sha256 digests of the
    decision's base worlds and of its record without the fields that measure
    the run (`_engine_dependent`)."""
    drawn = []
    original = bot._worlds

    def capture(*args, **kwargs):
        out = original(*args, **kwargs)
        drawn.append(out[0])
        return out

    bot._worlds = capture
    try:
        cards = sorted(bot.decide_play(rnd, rnd.turn))
    finally:
        del bot._worlds
    record = {k: v for k, v in (bot.last_decision_record or {}).items() if not _engine_dependent(k)}

    def digest(value) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=list).encode()).hexdigest()
    return {"cards": cards,
            "worlds": digest([[sorted(map(sorted, hands)), sorted(buried)]
                              for hands, buried in drawn[0]]) if drawn else None,
            "record": digest(record)}


def label(key: str, trick: int, pos: int) -> str:
    return f"{key}:{trick}:{pos}"
