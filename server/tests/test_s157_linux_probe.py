"""DEV diagnostic only (never a gate): release 54's flag-off decisions at two fixed self-play positions.

It replays deal 2669920000 with release 54 as served (the repo's ``fly.toml``, bot seed 54, clocks
lifted, all four seats) and prints each probed decision's admitted ballot, policy log-odds (``repr``),
pick and base-world digest as one ``S157_LINUX_PROBE`` JSON line, also written under
the uploaded ``ci-durations`` directory (`_artifact_dir`).  A second test replays the four deals of the vp2 identity
fixture and writes every play decision's full projection (`r50_flag_positions.decision`, digested
as the fixture digests it) to ``r54_flag_off_decisions.<platform>.json`` there,
the fixture's format.  Both always pass.
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


def _artifact_dir():
    """Where the files go: ``$S157_PROBE_OUT``, else on GitHub Actions the workspace's ``ci-durations``
    directory (the job uploads it; the CI session plugin hides its env variable from tests), else none."""
    if os.environ.get("S157_PROBE_OUT"):
        return os.environ["S157_PROBE_OUT"]
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_WORKSPACE"):
        return os.path.join(os.environ["GITHUB_WORKSPACE"], "ci-durations")
    return None
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
    target = _artifact_dir()
    if target:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, f"s157_linux_probe_{out['head'] or 'unknown'}.json"), "w") as fh:
            fh.write(line + "\n")


FIXTURE_SEEDS = (2669920000, 2669920001, 2669920002, 2669920003)


def test_write_the_platform_fixture(release50_packages, release53_pair, monkeypatch, served_functions,
                                    capsys):
    import r50_flag_positions as P
    from shengji.ai.env import observe_committed_play, prepare_round
    from shengji.engine.cards import RANKS
    from shengji.engine.game import Game

    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=fly_env(), seed=54)
    P.lift(bot)
    plat = f"{sys.platform}-{platform.machine()}"
    decisions = {}
    for seed in FIXTURE_SEEDS:
        game = Game(rng=random.Random(seed), start_level=RANKS[seed % len(RANKS)])
        rnd = prepare_round(game, [bot] * 4)
        trick, pos = 1, 0
        while rnd.phase == "play":
            seat = rnd.turn
            projection = P.decision(bot, rnd)
            digest = hashlib.sha256(json.dumps(projection, sort_keys=True, default=list).encode()).hexdigest()
            decisions[f"{seed}:{trick}:{pos}"] = {"digest": digest, "projection": projection}
            before = len(rnd.history)
            rnd.play(seat, list(projection["cards"]))
            observe_committed_play(rnd, [bot] * 4)
            pos += 1
            if len(rnd.history) != before:
                trick, pos = trick + 1, 0
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        head = None
    out = {"name": name, "main": head, "pinned_on": plat, "engine": "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure",
           "engines": {"compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure": decisions}}
    text = json.dumps(out, separators=(",", ":"))
    with capsys.disabled():
        print(f"\nS157_LINUX_FIXTURE platform {plat} decisions {len(decisions)} sha256 "
              f"{hashlib.sha256(text.encode()).hexdigest()}", flush=True)
    target = _artifact_dir()
    if target:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, f"r54_flag_off_decisions.{plat}.json"), "w") as fh:
            fh.write(text)
