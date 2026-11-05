"""D7+X7 and belief-combo late-game latency worker; no launch authorization.

Derived from the qualified S18 server-path worker. Harvest uses the release-45
recipe on the selected source and captures BOTH leads and follows when all
hands hold at most seven cards. Measure restores the engine and refusal ledger,
then uses the real server snapshot/admission/off-loop compute/commit path.
This is not exact bot-RNG replay. Files are exclusive-create and flushed;
round outcomes are not exported. Host admission, source/package pins, a bounded
supervisor, sealing and review belong to the external launch packet.

The dx arm requires the integrated D7+X7 source; an older tree must refuse.
Screen-host timings are not Fly qualification without an explicit host model.
The combo arm measures belief only on these late-game roots, not all hand sizes.
"""
import argparse, asyncio, json, os, platform, random, resource, sys, time
from pathlib import Path

PACKAGE_SHA = '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670'
NAMES = {'r45': 'pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8',
         'dx': 'pv-search-491ee4bf-w64-k8-div-rc-tb-ele-la-dtr-vd-ed7-xf7-xfcompactlevel-r8250a8cc-bury-hybrid-bwv-1cca424ae14c',
         'combo': 'pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0'}
BELIEF_SHA = '763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343'
BELIEF_PATH = '/data/models/s17long-e2-763b5e05.npz'
MAPS = {'/data/models/smv3out-491ee4bf.npz': '/root/models/smv3out-491ee4bf.npz',
        '/data/models/js-m1-0d17fd03.npz': '/root/models/js-m1-0d17fd03.npz',
        BELIEF_PATH: '/root/models/s17long-e2-763b5e05.npz'}
EXACT_FIELDS = ('exact_lead_status', 'exact_lead_seconds', 'exact_lead_worlds_completed', 'exact_lead_nodes',
                'exact_lead_cache_hits', 'exact_lead_changed', 'exact_lead_change_kind', 'exact_lead_abandon_reason',
                'exact_lead_abandon_error', 'exact_deep_cards',
                'exact_follow_attempted', 'exact_follow_applied', 'exact_follow_abandoned',
                'exact_follow_error', 'exact_follow_worlds', 'exact_follow_nodes')
BELIEF_FIELDS = ('belief_fallback', 'belief_proposed', 'belief_ms', 'belief_error',
                 'history_rejections', 'history_fallback_worlds')


def memory():
    hwm = None
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmHWM:'):
                hwm = int(line.split()[1]) * 1024
    except OSError:
        pass
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return dict(ru_maxrss_bytes=ru * 1024 if sys.platform.startswith('linux') else ru, vm_hwm_bytes=hwm)


def build(arm, fly_toml, maps):
    from scripts.cwv_serving_smoke import build_production_bot, env_from_fly_toml
    env = env_from_fly_toml(fly_toml, maps)
    assert env['SHENGJI_BOT'] == NAMES['r45'], ('fly.toml is not release 45', env['SHENGJI_BOT'])
    assert env['SHENGJI_PV_SHA256'] == PACKAGE_SHA and 'SHENGJI_PV_EXACT_LEAD_ENDGAME' not in env
    assert not [k for k in os.environ if k.startswith('SHENGJI_') and k not in ('SHENGJI_FAST', 'SHENGJI_REQUIRE_VOIDS')], \
        'deploy SHENGJI_* keys in the process environment'
    assert arm in NAMES, 'unknown latency arm'
    exact = arm in ('dx', 'combo')
    if exact:
        env.update(SHENGJI_PV_EXACT_LEAD_ENDGAME='1', SHENGJI_PV_EXACT_DEEP_CARDS='7',
                   SHENGJI_PV_EXACT_FOLLOW='1', SHENGJI_PV_EXACT_FOLLOW_SOLVER='compact-level',
                   SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS='7', SHENGJI_PV_EXACT_FOLLOW_MAX_NODES='50000000')
        env['SHENGJI_BOT'] = NAMES[arm]
    if arm == 'combo':
        env.update(SHENGJI_PV_WORLD_HISTORY_LEGAL='1', SHENGJI_PV_WORLD_HISTORY_DRAW='1',
                   SHENGJI_PV_BELIEF_WORLDS='1', SHENGJI_PV_BELIEF_CKPT=maps[BELIEF_PATH],
                   SHENGJI_PV_BELIEF_SHA256=BELIEF_SHA, SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST='1')
    name, bot = build_production_bot(env)
    assert name == NAMES[arm] and type(bot).__name__ == 'PVSearchBuryBot'
    assert bot.exact_lead_endgame is exact and bot.config.exact_lead_endgame is exact
    if exact:
        assert bot.exact_deep_cards == bot.config.exact_deep_cards == 7
        assert bot.exact_follow is True and bot.config.exact_follow is True
        assert (bot.exact_follow_solver, bot.exact_follow_max_cards, bot.exact_follow_max_nodes) == ('compact-level', 7, 50000000)
        from shengji.ai.endgame_compact import default_backend
        assert default_backend() == 'compiled', 'compiled exact solver required'
    assert bot.config.belief_worlds is (arm == 'combo')
    if arm == 'combo':
        assert bot.config.world_history_legal and bot.config.world_history_draw
        assert bot.config.belief_sha256 == BELIEF_SHA and bot.belief_model is not None
        assert bot.config.value_declare_every_first and bot.value_declare_every_first
    assert bot.serving_budget_seconds == 3.0 and bot.worlds == 64 and bot.candidates == 8
    assert getattr(bot.evaluator, 'backend', None) == 'numpy', 'not the model-serving (numpy) path'
    from shengji.engine import combos, fast
    assert fast.HAVE_FAST and combos.decompose is fast.decompose, 'compiled engine not active'
    return name, bot, env


class Sink:
    def __init__(self, path):
        self.fh = open(path, 'x')

    def write(self, row):
        self.fh.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
        self.fh.flush()
        os.fsync(self.fh.fileno())


def room_for(srv, code, bot, events):
    room = srv.Room(code=code, bot=bot)
    room.log_event = lambda kind, **data: events.append(dict(kind=kind, **{k: v for k, v in data.items()
                                                                            if k in ('event', 'stage', 'phase', 'elapsed_seconds')}))
    return room


async def timed_turn(srv, room, seat):
    """One bot turn through the server path; returns (prepared, wall_step, wall_commit, committed_once).

    Recommit once to prove stale-result refusal, including a fourth-seat winner
    becoming the next leader. The witness is outside the timed commit interval:
    production commits once, so the check must not inflate its measured cost.
    Requires the immutable snapshot play-cursor guard integrated from #1050.
    """
    before = len(room.round.hands[seat])
    t0 = time.perf_counter()
    prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
    t1 = time.perf_counter()
    if prepared is None:
        raise RuntimeError('server produced no turn')
    async with room.lock:
        ok = srv._commit_bot_turn(room, prepared)
        t2 = time.perf_counter()
        again = srv._commit_bot_turn(room, prepared)
    shrank = len(room.round.hands[seat]) < before
    return prepared, t1 - t0, t2 - t1, bool(ok) and not again and shrank


def record_fields(rec):
    rec = rec or {}
    out = dict(schema=rec.get('schema'), reason=rec.get('reason'), work_complete=rec.get('work_complete'),
               record_seconds=rec.get('seconds', rec.get('elapsed_seconds')))
    out.update({k: rec.get(k) for k in EXACT_FIELDS + BELIEF_FIELDS if k in rec})
    return out


async def harvest(args, srv, bot, out):
    from shengji.engine.game import Game
    from shengji.train.lead_root_capture import LeadCapture
    from shengji.train.policy_value_search import leading
    if not callable(getattr(LeadCapture, 'capture_turn', None)):
        raise RuntimeError('integrated follow-root capture source required before harvest')
    turns, roots = Sink(out / 'harvest_turns.jsonl'), Sink(out / 'roots.jsonl')
    n_roots = 0
    for i in range(args.rounds):
        deal_seed = args.seed0 + i
        events = []
        room = room_for(srv, f'H{deal_seed}', bot, events)
        room.game = Game(random.Random(deal_seed))
        rnd = room.game.start_round()
        assert rnd.first_round
        room.index_round()
        room.seats = [srv.Seat(name=f'Bot {s}', is_bot=True) for s in range(4)]
        while rnd.phase == 'deal':
            async with room.lock:
                seat, idx, card = rnd.deal_next()
                room.ids[seat][idx] = card
            await srv._bot_declares(room, [seat])
        await srv._bot_declares(room, list(range(4)), final=True)
        async with room.lock:
            rnd.finalize_declare()
        prepared, step, commit, once = await timed_turn(srv, room, rnd.banker)
        if not once or rnd.phase != 'play':
            raise RuntimeError(f'deal {deal_seed}: bury not committed exactly once')
        capture = LeadCapture(rnd)
        while rnd.phase == 'play':
            trick_no = len(rnd.history)
            seat = rnd.turn
            lead = leading(rnd)
            max_hand = max(map(len, rnd.hands))
            eligible = max_hand <= getattr(args, 'max_hand', 7)
            if eligible:
                packet = capture.capture_turn(rnd, ledger=room.bot._refusals, decision={})
                roots.write(dict(root_index=n_roots, deal_seed=deal_seed, trick=trick_no, seat=seat,
                                 hand_size=len(rnd.hands[seat]), lead=lead, max_hand=max_hand, packet=packet))
                n_roots += 1
            del events[:]
            prepared, step, commit, once = await timed_turn(srv, room, seat)
            if not once:
                raise RuntimeError(f'deal {deal_seed}: play not committed exactly once')
            async with room.lock:
                capture.committed(rnd, seat, list(prepared.decision.cards))
            rec = prepared.decision.snapshot.bot_copy.last_decision_record
            turns.write(dict(deal_seed=deal_seed, trick=trick_no, seat=seat, lead=lead, max_hand=max_hand,
                             small_endgame=max_hand <= 7, wall_step_seconds=step, wall_commit_seconds=commit,
                             compute_seconds=prepared.compute_seconds, **record_fields(rec),
                             model_search=[e for e in events if e['kind'] == 'model_search']))
        print(json.dumps(dict(round=i, deal_seed=deal_seed, roots=n_roots, mem=memory())), flush=True)
    return dict(rounds=args.rounds, roots=n_roots)


async def measure(args, srv, bot, out):
    from shengji.engine.game import Game
    from shengji.train.lead_root_capture import restore_with_ledger
    rows = Sink(out / f'measure_{args.pass_label}.jsonl')
    n = 0
    for line in (Path(args.roots)).read_text().splitlines():
        item = json.loads(line)
        rnd, ledger = restore_with_ledger(item['packet'])
        seat = rnd.turn
        assert seat == item['seat']
        assert len(rnd.hands[seat]) == item['hand_size']
        assert len(rnd.history) == item['trick']
        bot._refusals = ledger
        events = []
        game = Game(random.Random(7))
        game.round = rnd
        room = room_for(srv, f'M{item["root_index"]}', bot, events)
        room.game = game
        room.seats = [srv.Seat(str(s), is_bot=True) for s in range(4)]
        room.ids = [dict(enumerate(h)) for h in rnd.hands]
        room._kitty_given = True
        leading_before = not bool(rnd.trick.plays)
        assert leading_before == item['lead'] and max(map(len, rnd.hands)) == item['max_hand'] <= getattr(args, 'max_hand', 7)
        prepared, step, commit, once = await timed_turn(srv, room, seat)
        if not once:
            raise RuntimeError(f'root {item["root_index"]}: play not committed exactly once')
        rec = prepared.decision.snapshot.bot_copy.last_decision_record
        rows.write(dict(root_index=item['root_index'], deal_seed=item['deal_seed'], trick=item['trick'],
                        hand_size=item['hand_size'], lead=leading_before,
                        captured_lead=item['lead'], max_hand=item['max_hand'], arm=args.arm, pass_label=args.pass_label,
                        wall_step_seconds=step, wall_commit_seconds=commit, wall_total_seconds=step + commit,
                        compute_seconds=prepared.compute_seconds, committed_once=once, **record_fields(rec),
                        model_search=[e for e in events if e['kind'] == 'model_search']))
        n += 1
    return dict(roots_measured=n)


async def preplay(args, srv, bot, out):
    """Measure all declaration opportunities and bury without playing a round.

    Each arm generates its own declarations and resulting bury hand. These
    timings cover a recipe, not matched-state action-quality comparisons.
    """
    from shengji.engine.game import Game
    rows = Sink(out / f'preplay_{args.pass_label}.jsonl')
    declarations = buries = 0
    for i in range(args.rounds):
        deal_seed = args.seed0 + i
        events = []
        room = room_for(srv, f'P{deal_seed}', bot, events)
        room.game = Game(random.Random(deal_seed))
        rnd = room.game.start_round()
        room.index_round()
        room.seats = [srv.Seat(name=f'Bot {s}', is_bot=True) for s in range(4)]

        async def declare(seat, final=False):
            nonlocal declarations
            events.clear()
            started = time.perf_counter()
            complete = await srv._bot_declares(room, [seat], final=final)
            elapsed = time.perf_counter() - started
            if not complete:
                raise RuntimeError('declaration transaction invalidated')
            rows.write(dict(phase='declare', deal_seed=deal_seed, seat=seat,
                            final=final, arm=args.arm, pass_label=args.pass_label,
                            wall_total_seconds=elapsed,
                            model_search=[e for e in events if e['kind'] == 'model_search']))
            declarations += 1

        while rnd.phase == 'deal':
            async with room.lock:
                seat, idx, card = rnd.deal_next()
                room.ids[seat][idx] = card
            await declare(seat)
        for seat in range(4):
            await declare(seat, final=True)
        async with room.lock:
            rnd.finalize_declare()
        events.clear()
        prepared, step, commit, once = await timed_turn(srv, room, rnd.banker)
        if not once or rnd.phase != 'play':
            raise RuntimeError('bury transaction did not commit exactly once')
        rows.write(dict(phase='bury', deal_seed=deal_seed, seat=rnd.banker,
                        arm=args.arm, pass_label=args.pass_label,
                        wall_total_seconds=step + commit, wall_step_seconds=step,
                        wall_commit_seconds=commit, compute_seconds=prepared.compute_seconds,
                        committed_once=once,
                        model_search=[e for e in events if e['kind'] == 'model_search']))
        buries += 1
    return dict(rounds=args.rounds, declarations=declarations, buries=buries)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('harvest', 'measure', 'preplay'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--fly-toml', type=Path, required=True)
    p.add_argument('--arm', choices=tuple(NAMES), default='r45')
    p.add_argument('--rounds', type=int, default=0)
    p.add_argument('--seed0', type=int, default=0)
    p.add_argument('--roots', type=Path)
    p.add_argument('--max-hand', type=int, choices=range(1, 26), default=7,
                   help='Capture/replay hand-size ceiling; 25 includes early play, not declaration or bury.')
    p.add_argument('--pass-label', default='')
    p.add_argument('--map', action='append', default=[])
    args = p.parse_args(argv)
    maps = dict(MAPS, **dict(m.split('=', 1) for m in args.map))
    if args.mode == 'harvest':
        assert args.arm == 'r45' and args.rounds > 0, 'harvest uses release 45 and needs --rounds'
    elif args.mode == 'measure':
        assert args.roots and args.pass_label, 'measure needs --roots and --pass-label'
    else:
        assert args.rounds > 0 and args.pass_label, 'preplay needs --rounds and --pass-label'
    terminal = Sink(args.out / f'terminal_{args.mode}{"_" + args.pass_label if args.pass_label else ""}.json')
    started = time.perf_counter()
    mem0 = memory()
    name, mem_built = None, None
    result, error = None, None
    try:
        name, bot, _ = build(args.arm, args.fly_toml, maps)
        mem_built = memory()
        from shengji.api import server as srv
        run = {'harvest': harvest, 'measure': measure, 'preplay': preplay}[args.mode]
        result = asyncio.run(run(args, srv, bot, args.out))
    except Exception as exc:   # typed terminal witness; never retried
        error = dict(type=type(exc).__name__, message=str(exc)[:500])
    terminal.write(dict(mode=args.mode, arm=args.arm, policy=name, pass_label=args.pass_label, result=result, error=error, max_hand=args.max_hand,
                        seconds=time.perf_counter() - started, memory_start=mem0, memory_after_build=mem_built,
                        memory_end=memory(), python=platform.python_version(), machine=platform.machine(),
                        argv=sys.argv))
    return 0 if error is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
