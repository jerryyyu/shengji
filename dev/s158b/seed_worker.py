"""One reserved S158 Stage B seed. The supervisor owns admission and concurrency."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
from unittest.mock import patch

from paired import play_deal
from shengji import releases
from shengji.ai.env import prepare_round
from shengji.engine.cards import RANKS
from shengji.engine.game import Game
from shengji.eval.served_config import process_env, registry_name
from scripts.expert_labels.validity import completion_shape


FIRST_SEED = 1011410000
DEALS = 2400


def arm_environment(directories):
    manifest = releases.load(55)
    paths = {}
    for directory in directories:
        paths.update(releases.package_paths(manifest, directory))
    if set(paths) != set(manifest["packages"]):
        raise ValueError("missing release 55 packages")
    env = releases.local_env(manifest, paths)
    if registry_name(env) != manifest["bot_name"]:
        raise ValueError("base recipe differs from release 55")
    env["SHENGJI_PV_EXACT_FOLLOW_ANYTIME_EIGHT"] = "1"
    env["SHENGJI_BOT"] = registry_name(env)
    if "-xf8any-" not in env["SHENGJI_BOT"]:
        raise ValueError("arm recipe lacks the eight-card rule")
    return env


def _declare_observer(bot, records):
    decide = bot.decide_declare

    def observe(rnd, seat, final=False):
        cards = decide(rnd, seat, final=final)
        rec = bot.last_declare_record
        if rec is not None:
            records.append(dict(seat=seat, arm="shared", evaluated=rec["evaluated"],
                                completed=rec["worlds_completed"], worlds=rec["worlds"],
                                fallback_reason=rec["fallback_reason"]))
        return cards

    return observe


def play_seed(seed, env):
    rank = RANKS[(seed - FIRST_SEED) % 12]
    game = Game(rng=random.Random(seed), start_level=rank)
    records = []
    with process_env(env):
        bots = [releases._build(env, False, seed * 10 + seat)[1] for seat in range(4)]
        with ExitStack() as stack:
            for bot in bots:
                stack.enter_context(patch.object(bot, "decide_declare", _declare_observer(bot, records)))
            rnd = prepare_round(game, bots)
        banker = rnd.banker
        bury = bots[banker].last_bury_record
        check = completion_shape(records, expected_worlds_by_arm={"shared": bots[0].value_declare_worlds})
        if check["verdict"] != "VALID":
            raise ValueError(check["reasons"])
        result = play_deal(rnd, bots)
        outcome = game.finish_round()
    return dict(rank=rank, banker=banker, declares=records, bury_fallback=bury["fallback_reason"],
                kitty_bonus=rnd.kitty_bonus, winner_team=outcome.winner_team,
                level_change=outcome.level_change, **result)


def write_seed(seed, root, env):
    if type(seed) is not int or not FIRST_SEED <= seed < FIRST_SEED + DEALS:
        raise ValueError("seed outside Stage B reservation")
    directory = Path(root) / str(seed)
    directory.mkdir()
    identity = dict(schema="s158b-seed-v1", seed=seed, release=55, arm_name=env["SHENGJI_BOT"])
    try:
        record = dict(identity, status="complete", **play_seed(seed, env))
        payload = json.dumps(record, allow_nan=False)
    except Exception as exc:
        payload = json.dumps(dict(identity, status="fault", error=type(exc).__name__, detail=str(exc)))
        _publish(directory, payload)
        raise
    return seed, _publish(directory, payload)


def _publish(directory, payload):
    temporary = directory / "result.tmp"
    raw = (payload + "\n").encode("utf-8")
    temporary.write_bytes(raw)
    temporary.rename(directory / "result.json")
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package-dir", action="append", required=True)
    args = parser.parse_args()
    write_seed(args.seed, args.root, arm_environment(args.package_dir))
