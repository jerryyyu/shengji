"""Bounded fixed-fixture serving qualification, never a gameplay comparison.

Run only after host admission and launch authorization. The fixtures use
heuristic declaration/bury, cover all ranks and fixed banker seats, and are
not held-out gameplay evidence. A failure preserves the partial file and
stops without retry. Construction is outside decision wall timing.
"""
import argparse
import asyncio
import copy
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import time
import tomllib

from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.cards import RANKS
from shengji.engine.game import Game
from shengji.eval.singleton_challenger import candidate_from_env
from shengji.train import pv_search_policy as pv


def fixture(rank, banker, seed):
    game = Game(random.Random(seed), start_level=rank)
    game.banker = banker
    rnd = game.start_round()
    heuristic = HeuristicBot()
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        cards = heuristic.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = heuristic.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    return rnd


async def qualify_one(root, bot):
    """Measure one real server preparation/commit; do not retry failures."""
    if root.phase != 'play' or root.trick.plays or max(map(len, root.hands)) <= 7:
        raise ValueError('qualification requires a lead above exact coverage')
    rnd = copy.deepcopy(root)
    game = Game(random.Random(0))
    game.round = rnd
    room = srv.Room(code='SCQUAL', game=game, bot=bot,
                    seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
    room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
    room._kitty_given = True
    room.log_event = lambda *args, **kwargs: None
    seat = rnd.turn
    before = copy.deepcopy(rnd.hands)
    rng_before = bot.sampler.rng.getstate()
    started = time.perf_counter()
    prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
    seconds = time.perf_counter() - started
    if prepared is None or rnd.hands != before or bot.sampler.rng.getstate() != rng_before:
        raise RuntimeError('snapshot preparation changed live state or produced no decision')
    rec = prepared.decision.snapshot.bot_copy.last_decision_record or {}
    attempted = list(prepared.decision.cards)
    if not srv._commit_bot_turn(room, prepared) or srv._commit_bot_turn(room, prepared):
        raise RuntimeError('decision did not commit exactly once')
    accepted = sorted((Counter(before[seat]) - Counter(rnd.hands[seat])).elements())
    healthy = (rec.get('schema') == pv.RECORD_SCHEMA and rec.get('work_complete') is True
               and rec.get('worlds') == bot.worlds
               and (not bot.belief_worlds or rec.get('belief_fallback') == 0))
    return dict(policy=bot.policy_name, seconds=seconds, healthy=healthy,
                attempted=attempted, accepted=accepted,
                failed_throw=sorted(attempted) != accepted,
                schema=rec.get('schema'), worlds=rec.get('worlds'),
                belief_fallback=rec.get('belief_fallback'),
                probe_evaluations=rec.get('singleton_probe_evaluations', 0),
                challenger_applied=rec.get('singleton_challenger_applied', False))


async def qualify(env, dest):
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    if list(entries) != [env['SHENGJI_BOT']]:
        raise ValueError('baseline identity drift')
    baseline = entries[env['SHENGJI_BOT']]
    elapsed = {'baseline': [], 'candidate': []}
    for rank_index, rank in enumerate(RANKS):
        for banker in range(4):
            index = 4 * rank_index + banker
            seed = 625091990 + index
            root = fixture(rank, banker, seed)
            arms = ('baseline', 'candidate') if index % 2 == 0 else ('candidate', 'baseline')
            for arm in arms:
                bot = baseline(seed=seed) if arm == 'baseline' else candidate_from_env(env, seed=seed)
                for attr, enabled in pv.latency_switches(env).items():
                    setattr(bot, attr, enabled)
                bot.belief_log = pv.belief_log_enabled(env)
                if bot.worlds != 64 or bot.candidates != 8 or bot.serving_budget_seconds != 3:
                    raise ValueError('requires served W64/K8/3-second budget')
                row = await qualify_one(root, bot)
                row.update(kind='decision', arm=arm, seed=seed, rank=rank, banker=banker)
                dest.write(json.dumps(row) + '\n')
                dest.flush()
                os.fsync(dest.fileno())
                elapsed[arm].append(row['seconds'])
                if not row['healthy']:
                    return 1
    # A maximum bound is stricter than the proposed p99 bound on these fixtures.
    passed = all(max(times) <= 2.5 for times in elapsed.values())
    dest.write(json.dumps(dict(kind='terminal', passed=passed,
                              calls={arm: len(times) for arm, times in elapsed.items()},
                              max_seconds={arm: max(times) for arm, times in elapsed.items()},
                              claim='fixed-fixture functionality and host timing only')) + '\n')
    dest.flush()
    os.fsync(dest.fileno())
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--recipe-sha', required=True)
    parser.add_argument('--play-package', required=True)
    parser.add_argument('--belief-package', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not srv._fast_active():
        raise ValueError('qualification requires the activated compiled engine')
    raw = args.recipe.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.recipe_sha:
        raise ValueError('recipe bytes changed')
    env = tomllib.loads(raw.decode())['env']
    env.update(SHENGJI_PV_CKPT=args.play_package, SHENGJI_PV_BELIEF_CKPT=args.belief_package)
    with args.out.open('x') as dest:
        dest.write(json.dumps(dict(kind='start', recipe_sha=args.recipe_sha,
                                  baseline=env['SHENGJI_BOT'], fixtures=52,
                                  scope='heuristic-setup fixed first leads; no gameplay outcomes')) + '\n')
        dest.flush()
        os.fsync(dest.fileno())
        return asyncio.run(qualify(env, dest))


if __name__ == '__main__':
    raise SystemExit(main())
