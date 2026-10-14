"""Two fixed-root serving calls, not a gameplay comparison or host admission.

Run only on an admitted, otherwise idle host. From server/ with PYTHONPATH=.:
python scripts/qualify_exact_lead.py --checkpoint PATH --out NEW.jsonl
Use ``--first-trick`` only for the bounded mechanism screen; it does not assert
that the new first-trick evaluator is a better action.
No retries or overwrite; each completed call is flushed before the next.
"""
import argparse
import asyncio
import copy
import json
import platform
import random
import time
from pathlib import Path
from contextlib import nullcontext

from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.train.lead_root_capture import restore_with_ledger
from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries
from scripts.exact_lead_cost_probe import exact_lead_cost_probe

PACKAGE_SHA = '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670'
BASELINE = 'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6'
R45_NAMES = (
    'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8',
    'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-la-dtr-vd-r2ac93e3d-bury-hybrid-bwv-02f0041fee6a',
)
# The first-trick arm has its own recipe digest and must not be conflated with
# the whole-endgame arm.  These names are derived from ``pv_registry_entries``
# using the pinned release-45 recipe (the factory is the source of identity).
R45_FIRST_TRICK_NAMES = (
    R45_NAMES[0],
    'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-elf-la-dtr-vd-r128e803c-bury-hybrid-bwv-510d61d26e9d',
)
BASELINE45 = R45_NAMES[0]


def qualification_env(checkpoint, release=44):
    if release not in (44, 45):
        raise ValueError('unsupported qualification release')
    env = dict(SHENGJI_PV_CKPT=str(checkpoint), SHENGJI_PV_SHA256=PACKAGE_SHA,
        SHENGJI_PV_WORLDS='64', SHENGJI_PV_CANDIDATES='8', SHENGJI_PV_CAP='4000',
        SHENGJI_PV_BATCH_SIZE='128', SHENGJI_PV_ADMISSION_DIVERSITY='1',
        SHENGJI_PV_REFUSAL_CONSTRAINTS='1', SHENGJI_PV_TIEBREAK_POINTS='1',
        SHENGJI_PV_LEAD_ANCHOR='1', SHENGJI_PV_DOOMED_THROW_RESELECT='1',
        SHENGJI_PV_VALUE_DECLARE='1', SHENGJI_PV_SERVING_BUDGET_SECONDS='3',
        SHENGJI_PV_BURY_ARM='hybrid', SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS='2')
    if release == 45:
        env.update(SHENGJI_PV_BURY_WIDE_VALUE='1', SHENGJI_PV_BURY_WIDE_K='64')
    return env


async def qualify(checkpoint, dest, release=44, *, first_trick=False, release45=False,
                  cost_out=None):
    if cost_out is not None and not first_trick:
        raise ValueError('cost_out requires first_trick')
    if release45:
        if release != 44:
            raise ValueError('release45 is incompatible with --release other than 44')
        release = 45
    if release not in (44, 45):
        raise ValueError('unsupported qualification release')
    packet = json.loads((Path(__file__).resolve().parents[1] /
                         'tests/fixtures/r44_joker_lead.json').read_text())
    env = qualification_env(checkpoint, release)
    probe = exact_lead_cost_probe(cost_out) if cost_out is not None else nullcontext()
    with probe:
        for enabled in (False, True):
            entries = pv_registry_entries(**pv_env_recipe({**env,
                'SHENGJI_PV_EXACT_LEAD_ENDGAME': str(int(enabled)),
                'SHENGJI_PV_EXACT_LEAD_FIRST_TRICK': str(int(enabled and first_trick)),
            }))
            name, = entries
            if release == 45:
                expected_names = R45_FIRST_TRICK_NAMES if first_trick else R45_NAMES
                if name != expected_names[int(enabled)]:
                    raise ValueError('release45 qualification arm drift')
            if release == 44 and not enabled and name != BASELINE:
                raise ValueError('release44 recipe drift')
            rnd, ledger = restore_with_ledger(packet)
            bot = entries[name](seed=941210121)
            bot._refusals = ledger
            game = Game(random.Random(7))
            game.round = rnd
            room = srv.Room(code='QUALIFY', game=game, bot=bot,
                            seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
            room.ids = [dict(enumerate(h)) for h in rnd.hands]
            room._kitty_given = True
            room.log_event = lambda *a, **kw: None
            before = copy.deepcopy(rnd.hands)
            started = time.perf_counter()
            prepared = await srv._paced_bot_step(room, 3, minimum_turn_seconds=0)
            seconds = time.perf_counter()-started
            if prepared is None or rnd.hands != before:
                raise RuntimeError('snapshot did not preserve live root')
            rec = prepared.decision.snapshot.bot_copy.last_decision_record
            cards = list(prepared.decision.cards)
            committed = srv._commit_bot_turn(room, prepared)
            if not committed or srv._commit_bot_turn(room, prepared):
                raise RuntimeError('decision did not commit exactly once')
            if first_trick:
                # This is a mechanism read, not a strength claim: action identity is
                # deliberately recorded but never compared to a BJ expectation.
                passed = (rec.get('work_complete') is True and seconds < 3
                          and (not enabled or (rec.get('exact_lead_mode') == 'first_trick'
                               and rec.get('exact_lead_status') == 'complete'
                               and rec.get('exact_lead_worlds_completed') == 64)))
            else:
                expected = ['BJ'] if enabled else ['BJ', 'S5', 'S8', 'SQ']
                passed = (rec.get('work_complete') is True and cards == expected and seconds < 3
                          and (not enabled or (rec.get('exact_lead_status') == 'complete'
                               and rec.get('exact_lead_worlds_completed') == 64)))
            action_record = {'cards': cards, 'selected_index': rec.get('selected_index'),
                             'played': rec.get('played')}
            value_record = {key: rec.get(key) for key in (
                'value_means', 'exact_lead_selected_level_mean',
                'exact_lead_base_level_mean', 'exact_lead_selected_level_delta')}
            cost_record = {key: rec.get(key) for key in (
                'seconds', 'exact_lead_seconds', 'exact_lead_worlds_completed',
                'exact_lead_nodes', 'exact_lead_cache_hits')}
            row = dict(release=release, first_trick=first_trick, enabled=enabled,
                       policy=name, seconds=seconds, cards=cards,
                       passed=passed, committed=committed, record=rec,
                       action_record=action_record, value_record=value_record,
                       cost_record=cost_record,
                       machine=platform.machine(), system=platform.system())
            if release == 45:
                row.update(recipe_release=45, root_provenance='historical release44 fixed root; not a release45 trajectory')
            dest.write(json.dumps(row)+'\n')
            dest.flush()
            print(json.dumps({k:v for k,v in row.items() if k != 'record'}), flush=True)
            if not passed:
                return 1  # Preserve typed record; never retry a deadline/abandon.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--release', type=int, choices=(44, 45), default=None,
                        help='explicit recipe; default preserves the historical release44 qualifier')
    parser.add_argument('--first-trick', action='store_true',
                        help='screen exact first-trick mechanism; no action-strength claim')
    parser.add_argument('--cost-out', type=Path,
                        help='optional score-free exact-stage cost journal (new file)')
    parser.add_argument('--release45', action='store_true',
                        help='use release45 serving recipe on the historical fixed root')
    args = parser.parse_args(argv)
    if args.release45 and args.release is not None:
        parser.error('--release45 cannot be combined with --release; use one spelling')
    if args.cost_out is not None and not args.first_trick:
        parser.error('--cost-out requires --first-trick')
    if args.cost_out is not None and args.cost_out.resolve() == args.out.resolve():
        parser.error('--cost-out and --out must be different new files')
    if args.cost_out is not None and args.cost_out.exists():
        parser.error('cost output exists; preserve it and use a new path')
    release = 44 if args.release is None else args.release
    with args.out.open('x') as dest:
        if args.cost_out is not None:
            with args.cost_out.open('x') as cost_dest:
                if args.release45:
                    return asyncio.run(qualify(args.checkpoint, dest,
                                              first_trick=args.first_trick, release45=True,
                                              cost_out=cost_dest))
                return asyncio.run(qualify(args.checkpoint, dest, release,
                                           first_trick=args.first_trick, cost_out=cost_dest))
        if args.release45:
            return asyncio.run(qualify(args.checkpoint, dest,
                                      first_trick=args.first_trick, release45=True))
        return asyncio.run(qualify(args.checkpoint, dest, release,
                                   first_trick=args.first_trick))


if __name__ == '__main__':
    raise SystemExit(main())
