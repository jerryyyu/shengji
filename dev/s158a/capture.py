"""S158 stage A capture: release 54 as served plays whole deals; at every follow with max hand 8 and more
than one admitted candidate, record the served pick plus a full exact solve of every admitted candidate in
every one of the decision's own sampled worlds (the worlds the served value pass used), with per-cell level,
marginal nodes and CPU time, and the true-deal perfect-information points of every admitted candidate.

Record only: the capture runs after ``decide_play`` returns and before the play is committed; it touches no
bot attribute and draws from no RNG. ``--plain`` runs the same games with no wrapper and no capture (the
identity check compares the two play sequences).

usage: capture.py SEED0 N OUTDIR [--plain] [--stride K --offset J] [--selftest M]
cwd = <worktree>/server, PYTHONPATH=.
"""
import copy, json, os, random, sys, time
os.environ.setdefault("OMP_NUM_THREADS", "1"); os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ["SHENGJI_FAST"] = "1"   # the engine is chosen when `shengji` is first imported: set before it
from shengji import releases
MAN = releases.load(54)
PKG_DIRS = ("/Users/jerryyu/Projects/shengji-wt/pkg", "/Users/jerryyu/Projects/shengji-wt/pkg-r54")
paths = {}
for name, pk in MAN["packages"].items():
    for d in PKG_DIRS:
        f = os.path.join(d, pk["basename"])
        if os.path.isfile(f): paths[name] = f
assert set(paths) == set(MAN["packages"]), paths
ENV = releases.local_env(MAN, paths)          # sha256-checks every local package against the manifest
os.environ.update(ENV)
from shengji.ai import registry  # noqa: F401  (import order: registry first, as the server)
from shengji.engine.game import Game
from shengji.engine.cards import RANKS
from shengji.engine import fast as _fast
from shengji.ai.env import prepare_round, observe_committed_play
from shengji.ai.endgame import ExactEndgameRefusal, ExactEndgameBudgetExceeded, _clone_for_play
from shengji.ai.endgame_compact import CompactWorldSession
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train.cwv_prior_admission import root_clone
import shengji.train.pv_exact_follow as PEF
from shengji.ai.endgame_compact import default_backend
assert _fast.HAVE_FAST and _fast._saved and default_backend() == "compiled", "compiled engine required"

SEED_BASE = 1011400000
STAGE_CAP_S = 20.0            # CPU seconds for the full 64-world exact stage
MAX_NODES = int(MAN["env"]["SHENGJI_PV_EXACT_FOLLOW_MAX_NODES"])   # served per-world session cap (50M)
PI_CAP_S = 60.0
PI_MAX_NODES = 2_000_000_000


class StageCap(Exception):
    pass


def make_bots(seed):
    return [releases._build(ENV, False, seed * 10 + s)[1] for s in range(4)]


def instrument(bot, box):
    """Stash (actions, worlds) of the value pass at 8-card follows. Deep copies only; returns the original's
    result unchanged."""
    orig = bot._value_means
    def wrapped(rnd, seat, actions, worlds, check_budget=None):
        if rnd.trick is not None and rnd.trick.plays and max(map(len, rnd.hands)) == 8:
            box.append(([list(a) for a in actions], [([list(h) for h in hs], list(b)) for hs, b in worlds]))
        return orig(rnd, seat, actions, worlds, check_budget)
    bot._value_means = wrapped


def level_of(points, attacker):
    return float(category_signed_level(signed_level_category(points, attacker)))


def exact_capture(rnd, seat, admitted, worlds):
    """Mirror of `pv_exact_follow._world_scores` (compact-level, max 8 cards), world-major, timed per cell."""
    att = bool(rnd.is_attacker(seat))
    t0 = time.process_time()
    def guard():
        if time.process_time() - t0 > STAGE_CAP_S:
            raise StageCap()
    L, N, T, D = [], [], [], []
    censored = False; nodecap = []
    for wi, (hands, buried) in enumerate(worlds):
        lv, nd, tm, dup = [None] * len(admitted), [0] * len(admitted), [0] * len(admitted), [-1] * len(admitted)
        world_root = root_clone(rnd, hands, buried)
        try:
            c0 = time.process_time()
            session = CompactWorldSession(world_root, max_hand_cards=8, max_nodes=MAX_NODES, check_budget=guard,
                                          alpha_beta=True, level=True)
            keys = {}
            for i, action in enumerate(admitted):
                c = time.process_time()
                child = root_clone(rnd, hands, buried); child._trusted_rollout = False
                child.play(seat, list(action))
                if child.phase == "round_end":
                    lv[i] = level_of(child.attacker_points, att)
                else:
                    key = session.play_key(world_root, action)
                    if key is not None and key in keys:
                        lv[i] = lv[keys[key]]; dup[i] = keys[key]
                    else:
                        if key is not None: keys[key] = i
                        b = session.nodes
                        try:
                            pts = session.solve_level(child)
                        except ExactEndgameBudgetExceeded as exc:
                            if isinstance(exc.__cause__, StageCap) or time.process_time() - t0 > STAGE_CAP_S:
                                raise StageCap()
                            nodecap.append([wi, i]); nd[i] = session.nodes - b
                            tm[i] = round((time.process_time() - c) * 1e6); lv[i] = None
                            continue
                        lv[i] = level_of(pts, att); nd[i] = session.nodes - b
                if i == 0:
                    tm[i] = round((time.process_time() - c0) * 1e6)   # session construction charged to cell 0
                else:
                    tm[i] = round((time.process_time() - c) * 1e6)
        except StageCap:
            censored = True
            break
        L.append(lv); N.append(nd); T.append(tm); D.append(dup)
    return dict(L=L, N=N, T=T, D=D, censored=censored, nodecap=nodecap, worlds_done=len(L),
                stage_cpu=round(time.process_time() - t0, 4))


def pi_points(rnd, seat, admitted):
    """True-deal perfect-information final attacker points after each admitted play (exact minimax points)."""
    t0 = time.process_time()
    def guard():
        if time.process_time() - t0 > PI_CAP_S:
            raise StageCap()
    sess = CompactWorldSession(rnd, max_hand_cards=8, max_nodes=PI_MAX_NODES, check_budget=guard,
                               alpha_beta=True, level=True)
    out = []
    try:
        for a in admitted:
            c = _clone_for_play(rnd); c.play(seat, list(a))
            out.append(int(c.attacker_points) if c.phase == "round_end" else int(sess.solve_points(c)))
    except (StageCap, ExactEndgameBudgetExceeded):
        return out, True, round(time.process_time() - t0, 4)
    return out, False, round(time.process_time() - t0, 4)


def play_deal(seed, plain, selftest_left):
    g = Game(rng=random.Random(seed), start_level=RANKS[(seed - SEED_BASE) % 12])
    bots = make_bots(seed)
    boxes = [[] for _ in range(4)]
    if not plain:
        for b, box in zip(bots, boxes): instrument(b, box)
    rnd = prepare_round(g, bots)
    plays, decisions, selftests = [], [], 0
    trick, pos = 1, 0
    while rnd.phase == "play":
        seat = rnd.turn
        snap = None if plain else copy.deepcopy(rnd)
        boxes[seat].clear()
        w0 = time.perf_counter()
        cards = list(bots[seat].decide_play(rnd, seat))
        dec_sec = time.perf_counter() - w0
        plays.append([seat, sorted(cards)])
        rec = bots[seat].last_decision_record or {}
        if not plain and pos > 0 and max(map(len, snap.hands)) == 8:
            adm = rec.get("admitted") or []
            row = dict(seed=seed, trick=trick, pos=pos, seat=seat, attacker=bool(snap.is_attacker(seat)),
                       n_adm=len(adm), dec_sec=round(dec_sec, 4), schema=rec.get("schema"),
                       fallback=rec.get("fallback"), fallback_reason=rec.get("fallback_reason"))
            if len(adm) > 1:
                sel = rec["admitted_indices"].index(rec["selected_index"])
                match = [x for x in boxes[seat] if x[0] == adm]
                row.update(admitted=adm, served_idx=sel, played=sorted(cards),
                           played_is_admitted=sorted(cards) == sorted(adm[sel]),
                           value_means=rec.get("value_means"), prior=rec.get("policy_log_odds_admitted"),
                           n_worlds=rec.get("worlds"), stash_calls=len(boxes[seat]))
                if not match or len(match[0][1]) != rec.get("worlds"):
                    row["capture_error"] = "no value-pass stash matching the admitted ballot"
                else:
                    worlds = match[0][1]
                    x = exact_capture(snap, seat, adm, worlds)
                    row.update(x)
                    pts, pcens, psec = pi_points(snap, seat, adm)
                    row.update(pi=pts, pi_censored=pcens, pi_cpu=psec)
                    if selftest_left > 0 and not x["censored"] and not x["nodecap"] and x["stage_cpu"] < 3.0:
                        ref = PEF.rerank_follow(snap, seat, adm, worlds, baseline_index=sel, max_hand_cards=8,
                                                max_nodes=MAX_NODES, solver="compact-level",
                                                retain_world_scores=True)
                        ok = ([list(r) for r in ref.world_scores] == x["L"]
                              and ref.nodes == sum(map(sum, x["N"])))
                        row["selftest_ok"] = ok
                        assert ok, ("capture differs from rerank_follow", seed, trick, pos)
                        selftest_left -= 1; selftests += 1
            decisions.append(row)
        before = len(rnd.history)
        rnd.play(seat, cards); pos += 1
        observe_committed_play(rnd, bots)
        if len(rnd.history) != before: trick += 1; pos = 0
    return dict(seed=seed, plain=plain, plays=plays, attacker_points=int(rnd.attacker_points),
                decisions=decisions, selftests=selftests), selftest_left


def main():
    a = sys.argv[1:]
    seed0, n, out = int(a[0]), int(a[1]), a[2]
    plain = "--plain" in a
    stride = int(a[a.index("--stride") + 1]) if "--stride" in a else 1
    offset = int(a[a.index("--offset") + 1]) if "--offset" in a else 0
    selftest = int(a[a.index("--selftest") + 1]) if "--selftest" in a else 0
    os.makedirs(out, exist_ok=True)
    for k, seed in enumerate(range(seed0, seed0 + n)):
        if k % stride != offset: continue
        final = os.path.join(out, f"{seed}.json")
        if os.path.exists(final): continue
        t = time.time(); c = time.process_time()
        res, selftest = play_deal(seed, plain, selftest)
        res.update(wall=round(time.time() - t, 2), cpu=round(time.process_time() - c, 2), pid=os.getpid())
        tmp = final + f".tmp{os.getpid()}"
        with open(tmp, "w") as f: json.dump(res, f, separators=(",", ":"))
        os.replace(tmp, final)
        print("seed", seed, "decisions", len(res["decisions"]), "wall", res["wall"], flush=True)
    print("WORKER DONE", flush=True)


if __name__ == "__main__":
    main()
