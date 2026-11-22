"""DEV diagnostic only (never a gate): release 54's flag-off decisions at two fixed self-play positions.

It replays deal 2669920000 with release 54 as served (the repo's ``fly.toml``, bot seed 54, clocks
lifted, all four seats) and prints each probed decision's admitted ballot, policy log-odds (``repr``),
pick and base-world digest as one ``S157_LINUX_PROBE`` JSON line, also written under
``$SHENGJI_CI_DURATIONS_OUT`` when set. It always passes.
"""
import hashlib
import json
import os
import platform
import random
import subprocess
import sys

from test_release46_fly_config import fly_env
from test_release50_fly_config import release50_packages  # noqa: F401
from test_release53_fly_config import release53_pair, served_bot  # noqa: F401
from test_unified_serving import served_functions  # noqa: F401

SEED = 2669920000
PROBES = {(1, 0), (1, 3)}


def _lift(bot):
    bot.serving_budget_seconds = 600.0
    bot.exact_lead_max_seconds = 300.0
    if bot.leaf_greedy_deadline_ms:
        bot.leaf_greedy_deadline_ms = 600_000
    return bot


def test_print_release54_flag_off_decisions(release50_packages, release53_pair, monkeypatch,
                                            served_functions, capsys):
    from shengji.ai.env import observe_committed_play, prepare_round
    from shengji.engine.cards import RANKS
    from shengji.engine.game import Game

    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=fly_env(), seed=54)
    _lift(bot)
    game = Game(rng=random.Random(SEED), start_level=RANKS[SEED % len(RANKS)])
    rnd = prepare_round(game, [bot] * 4)
    out = {"bot": name, "platform": f"{sys.platform}-{platform.machine()}",
           "fast": os.environ.get("SHENGJI_FAST"), "head": None, "decisions": {}}
    try:
        out["head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        pass
    trick, pos = 1, 0
    while rnd.phase == "play" and (trick, pos) <= max(PROBES):
        drawn = []
        original = bot._worlds

        def capture(*args, **kwargs):
            got = original(*args, **kwargs)
            drawn.append(got[0])
            return got

        bot._worlds = capture
        try:
            cards = sorted(bot.decide_play(rnd, rnd.turn))
        finally:
            del bot._worlds
        rec = bot.last_decision_record or {}
        if (trick, pos) in PROBES:
            worlds = hashlib.sha256(json.dumps([[sorted(map(sorted, h)), sorted(b)] for h, b in drawn[0]],
                                               sort_keys=True, default=list).encode()).hexdigest() if drawn else None
            out["decisions"][f"{SEED}:{trick}:{pos}"] = {
                "cards": cards, "admitted": rec.get("admitted"),
                "admitted_indices": rec.get("admitted_indices"), "selected_index": rec.get("selected_index"),
                "policy_log_odds_admitted": [repr(v) for v in rec.get("policy_log_odds_admitted") or []],
                "value_means": [repr(v) for v in rec.get("value_means") or []],
                "worlds_digest": worlds}
        before = len(rnd.history)
        rnd.play(rnd.turn, list(cards))
        observe_committed_play(rnd, [bot] * 4)
        pos += 1
        if len(rnd.history) != before:
            trick, pos = trick + 1, 0
    line = "S157_LINUX_PROBE " + json.dumps(out, sort_keys=True)
    with capsys.disabled():
        print("\n" + line, flush=True)
    target = os.environ.get("SHENGJI_CI_DURATIONS_OUT")
    if target:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, f"s157_linux_probe_{out['head'] or 'unknown'}.json"), "w") as fh:
            fh.write(line + "\n")
