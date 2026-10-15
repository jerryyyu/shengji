"""Where do the production bots lose levels to humans?  (production room logs)

Replays every complete bot-vs-human round in the production room-log cache,
re-derives the round facts (declaration, bury/kitty, per-trick points, level
outcome), and scores decisions against two PERFECT-INFORMATION YARDSTICKS on
the true deal.  Neither yardstick is a policy a player could follow: both see
all four hands.

* ``exact``   -- every play decision where all four hands hold <= 4 cards:
  partnership minimax (``shengji.ai.endgame``) over every legal action.
  Regret = minimax value of the best action minus that of the played action.
* ``hybrid``  -- earlier play decisions: candidate set = MCBot ballot +
  HeuristicBot pick + the played action; each candidate is continued on the
  true deal by HeuristicBot for all four seats until all hands are <= 4 cards,
  then solved exactly (continuation switches to exact at <= 3 cards).  Regret = best candidate minus played.  This is a
  max over a noisy deterministic continuation, so it is biased upward; the
  same metric is applied to human decisions as the reference.
* ``bury``    -- the logged bury vs four rule-based buries (Heuristic/Loose/
  Strict/NoVoid), each continued by the hybrid rollout from the first lead.
* ``declare`` -- when a team held a stronger declaration than the final one
  and did not use it: full heuristic round (heuristic bury + hybrid play)
  under the unused declaration vs under the actual declaration.

All values are final attacker points (kitty bonus included).  Levels use the
engine's scoring: attackers >= 80 gain (p-80)//40, else the banker team gains
3/2/1 (p == 0 / < 40 / else).  Per-decision regrets are not additive; sums are
"at stake" totals, not a decomposition of the realised level change.

Usage (cwd = server/):
  SHENGJI_FAST=1 .venv/bin/python scripts/find_gaps/human_loss_attribution.py \
      [--logs ../../shengji/logs] [--out DIR] [--shard K/N] [--report-only]
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shengji.ai.endgame import (  # noqa: E402
    ExactEndgameRefusal, ExactWorldSession, _clone_for_play,
    exhaustive_legal_actions)
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.mcbot import MCBot, _BuryLoose, _BuryNoVoid, _BuryStrict  # noqa: E402
from shengji.engine.cards import total_points  # noqa: E402
from shengji.engine.round import Round, Trick, TrickPlay  # noqa: E402
from shengji.rl.replay_log import group_rounds, pretty_cards, rebuild_round  # noqa: E402

DEFAULT_LOGS = "/Users/jerryyu/Projects/shengji/logs"
DEFAULT_OUT = "/Users/jerryyu/.claude/jobs/d0498cda/tmp/part1"
EXACT_CAP = 4          # scored endgame decisions: all hands <= 4 cards
HYBRID_CAP = 3         # rollout continuations switch to exact at <= 3 cards
EXACT_NODES = 400_000
HEUR = HeuristicBot()
BURY_ALTS = {"heuristic": HeuristicBot(), "loose": _BuryLoose(),
             "strict": _BuryStrict(), "novoid": _BuryNoVoid()}


# ------------------------------------------------------------------ scoring
def attacker_signed_levels(p: float) -> int:
    """Signed level change for the ATTACKING team at final attacker points p."""
    p = int(p)
    if p >= 80:
        return (p - 80) // 40
    return -(3 if p == 0 else (2 if p < 40 else 1))


def team_levels(p: float, attacker: bool) -> int:
    v = attacker_signed_levels(p)
    return v if attacker else -v


def family_of(policy: str | None) -> str:
    if not policy:
        return "unlogged-policy"
    for pre in ("pv-search-491ee4bf", "pv-search-ccade130", "mc-s0-report-lcb"):
        if policy.startswith(pre):
            return pre
    if policy.startswith("mc-shortlist"):
        return "mc-shortlist"
    return "other:" + policy[:24]


# ----------------------------------------------------------------- rollouts
def _frontier(clone: Round, cap: int = EXACT_CAP) -> bool:
    return max(len(h) for h in clone.hands) <= cap


def exact_value(clone: Round, session: ExactWorldSession) -> float | None:
    try:
        return float(session.solve(clone).attacker_points)
    except ExactEndgameRefusal:
        return None


def hybrid_continue(clone: Round, session: ExactWorldSession | None) -> float:
    """Heuristic for all seats until every hand <= 4 cards, then exact."""
    clone._trusted_rollout = True
    while clone.phase == "play":
        if session is not None and _frontier(clone, HYBRID_CAP):
            v = exact_value(clone, session)
            if v is not None:
                return v
            session = None  # budget refusal: finish heuristically
        s = clone.turn
        clone.play(s, HEUR.decide_play(clone, s))
    return float(clone.attacker_points)


def rollout_action(rnd: Round, seat: int, action: list[str],
                   session: ExactWorldSession | None) -> float:
    clone = _clone_for_play(rnd)
    clone.play(seat, list(action))
    return hybrid_continue(clone, session)


def new_session(rnd: Round, cap: int = HYBRID_CAP) -> ExactWorldSession:
    return ExactWorldSession(rnd, max_hand_cards=cap, max_nodes=EXACT_NODES)


def play_round_from_bury(rnd_after_declare: Round, bury_cards: list[str]) -> float:
    r = copy.deepcopy(rnd_after_declare)
    r.bury(r.banker, list(bury_cards))
    return hybrid_continue(r, new_session(r))


def full_heuristic_round(rnd_after_declare: Round) -> float:
    r = copy.deepcopy(rnd_after_declare)
    r.bury(r.banker, HEUR.decide_bury(r, r.banker))
    return hybrid_continue(r, new_session(r))


# -------------------------------------------------------------- the replay
def rebuild_to_declare(evs, extra_declare=None) -> Round:
    rs = next(e for e in evs if e["e"] == "round_start")
    rnd = Round(rs["trump_rank"], rs["banker"])
    rnd.deck = rs["deck"]
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = rs["deck"][100:]
    while rnd.phase == "deal":
        rnd.deal_next()
    return rnd


def declare_strength_options(rnd: Round, seat: int) -> list[tuple[int, list[str]]]:
    """Every declaration a seat could make with its full dealt hand (no prior)."""
    saved = rnd.declaration
    rnd.declaration = None
    try:
        return [(rnd._declaration_strength(o), o) for o in rnd.declare_options(seat)]
    finally:
        rnd.declaration = saved


def decl_label(cards) -> str:
    if not cards:
        return "none"
    c = cards[0]
    return ("NT" if c in ("BJ", "LJ") else c[0]) + ("x2" if len(cards) == 2 else "")


def analyse_round(room: str, rno: int, evs: list[dict], meta: dict,
                  do_rollouts: bool, max_cands: int):
    rs = next(e for e in evs if e["e"] == "round_start")
    tr = next(e for e in evs if e["e"] == "trump")
    end = next(e for e in evs if e["e"] == "round_end")
    is_bot = {p["seat"]: bool(p["is_bot"]) for p in rs["players"]}
    banker = tr["banker"]
    bot_team = meta["bot_team"]
    bot_is_attacker = (banker % 2) != bot_team
    rec = dict(room=room, round=rno, family=meta["family"], policy=meta["policy"],
               tier=meta["tier"], bot_team=bot_team, banker=banker,
               bot_role="attacker" if bot_is_attacker else "banker",
               trump_rank=rs["trump_rank"], trump=tr["suit"],
               levels_before=rs["levels"], first_round=rs["banker"] is None,
               human_seat_autoplay_frac=meta["autoplay_frac"])

    # ---------------------------------------------------------- declaration
    decls = [e for e in evs if e["e"] == "declare"]
    base = rebuild_to_declare(evs)
    final = decls[-1] if decls else None
    final_strength = base._declaration_strength(final["cards"]) if final else 0
    team_opts = {}
    for s in range(4):
        opts = declare_strength_options(base, s)
        team_opts[s] = opts
    rec["declares"] = [{"seat": d["seat"], "cards": d["cards"], "bot": d.get("bot")}
                       for d in decls]
    rec["final_declarer"] = final["seat"] if final else None
    rec["final_declarer_team"] = (final["seat"] % 2) if final else None
    rec["final_strength"] = final_strength
    unused = {}
    for team in (0, 1):
        own_final = final is not None and final["seat"] % 2 == team
        best = max((st for s in (team, team + 2) for st, _ in team_opts[s]), default=0)
        declared_any = any(d["seat"] % 2 == team for d in decls)
        unused[team] = dict(
            best_available=best, declared_any=declared_any, own_final=own_final,
            unused_overcall=(not own_final and best > final_strength))
    rec["decl_bot_team"] = unused[bot_team]
    rec["decl_human_team"] = unused[1 - bot_team]

    # ------------------------------------------------------------ the replay
    rnd = rebuild_round(evs)
    assert rnd is not None
    if rnd.banker != banker:
        raise RuntimeError(f"banker mismatch {rnd.banker} vs {banker}")
    after_declare = rebuild_to_declare(evs)
    for d in decls:
        after_declare.declare(d["seat"], d["cards"])
    after_declare.finalize_declare()

    bury = next(e for e in evs if e["e"] == "bury")
    rec["bury_seat"] = bury["seat"]
    rec["bury_by_bot"] = bool(bury.get("bot", is_bot[bury["seat"]]))
    rec["buried"] = bury["cards"]
    rec["buried_points"] = total_points(bury["cards"])

    plays = [e for e in evs if e["e"] == "play"]
    logged_tricks = [e for e in evs if e["e"] == "trick"]
    decisions = []
    failed = Counter()
    mismatch = []
    trick_no = 0
    mc = MCBot(seed=0)
    for e in plays:
        if rnd.phase != "play":
            mismatch.append("play after round end")
            break
        seat = e["seat"]
        if rnd.turn != seat:
            raise RuntimeError(f"turn mismatch at play {e}")
        if not rnd.trick.plays:
            trick_no += 1
        ply = len(rnd.trick.plays)
        attempted = e.get("attempted_cards")
        action = list(attempted) if attempted else list(e["cards"])
        d = None
        if do_rollouts:
            d = score_decision(rnd, seat, action, mc, max_cands)
            d.update(room=room, round=rno, trick=trick_no, ply=ply, seat=seat,
                     is_bot=is_bot[seat], bot_played=bool(e.get("bot")),
                     bot_team_seat=(seat % 2 == bot_team),
                     actor_role="attacker" if rnd.is_attacker(seat) else "banker",
                     kind="lead" if ply == 0 else "follow",
                     hand=pretty_cards(rnd.sorted_hand(seat)),
                     trick_so_far=[[p.seat, pretty_cards(p.cards)] for p in rnd.trick.plays],
                     played=pretty_cards(action),
                     failed_throw=bool(attempted),
                     forced=pretty_cards(e["cards"]) if attempted else None,
                     att_pts_before=rnd.attacker_points)
        rnd.play(seat, action)
        last = rnd.history[-1] if rnd.history else None
        if attempted:
            failed["bot" if e.get("bot") else "human"] += 1
        if d is not None:
            decisions.append(d)
    if rnd.phase != "round_end":
        raise RuntimeError("replay did not reach round end")
    n_tricks = len(rnd.history)
    for i, (t, lt) in enumerate(zip(rnd.history, logged_tricks)):
        if t.winner != lt["winner"] or t.points != lt["points"]:
            mismatch.append(f"trick {i+1}")
    if rnd.attacker_points != end["attacker_points"]:
        mismatch.append(f"attacker_points {rnd.attacker_points} vs {end['attacker_points']}")
    rec["replay_mismatch"] = mismatch
    rec["n_tricks"] = n_tricks

    def phase_of(t):  # 1-based
        if t > n_tricks - 4:
            return "end"
        return "early" if t <= 8 else "mid"

    att_by_phase = Counter()
    for i, t in enumerate(rnd.history, 1):
        if rnd.is_attacker(t.winner):
            att_by_phase[phase_of(i)] += t.points
    last_t = rnd.history[-1]
    rec.update(
        attacker_points=end["attacker_points"], kitty_bonus=rnd.kitty_bonus,
        last_trick_winner=rnd.last_trick_winner,
        last_trick_winner_team=rnd.last_trick_winner % 2,
        last_trick_mult=2 * len(last_t.plays[0].cards),
        att_pts_by_phase=dict(att_by_phase),
        winner_team=end["winner_team"], level_change=end["level_change"],
        bot_signed_levels=(end["level_change"] if end["winner_team"] == bot_team
                           else -end["level_change"]),
        bot_won=end["winner_team"] == bot_team,
        failed_throws=dict(failed),
        failed_throw_detectable_for_bots=meta["family"] in (
            "pv-search-491ee4bf", "pv-search-ccade130", "mc-shortlist"),
    )
    # level change attributable to the kitty bonus (accounting, not counterfactual)
    p = end["attacker_points"]
    rec["kitty_levels_for_bot"] = (team_levels(p, bot_is_attacker)
                                   - team_levels(p - rnd.kitty_bonus, bot_is_attacker))

    for d in decisions:
        d["phase"] = phase_of(d["trick"])
        d["family"] = meta["family"]
        d["tier"] = meta["tier"]

    # ------------------------------------------------- bury counterfactual
    if do_rollouts:
        rec["bury_cf"] = bury_counterfactual(after_declare, bury["cards"])
        rec["declare_cf"] = declare_counterfactual(evs, decls, team_opts,
                                                   final_strength, unused, after_declare)
    return rec, decisions


def score_decision(rnd: Round, seat: int, action: list[str], mc: MCBot,
                   max_cands: int) -> dict:
    attacker = rnd.is_attacker(seat)
    better = max if attacker else min
    if _frontier(rnd):
        session = new_session(rnd, EXACT_CAP)
        try:
            acts = exhaustive_legal_actions(rnd, seat, max_hand_cards=EXACT_CAP)
            vals = {}
            for a in acts:
                child = _clone_for_play(rnd)
                child.play(seat, a)
                vals[tuple(sorted(a))] = float(session.solver.value(child))
            key = tuple(sorted(action))
            if key not in vals:
                child = _clone_for_play(rnd)
                child.play(seat, action)
                vals[key] = float(session.solver.value(child))
            method = "exact"
        except ExactEndgameRefusal:
            vals = None
    else:
        vals = None
    if vals is None:
        method = "hybrid"
        cands = []
        try:
            cands = [list(c) for c in mc._candidates(rnd, seat)][:max_cands]
        except Exception:
            cands = []
        heur = HEUR.decide_play(rnd, seat)
        pool = {}
        for c in [action, heur] + cands:
            pool.setdefault(tuple(sorted(c)), c)
        session = new_session(rnd)
        vals = {k: rollout_action(rnd, seat, c, session) for k, c in pool.items()}
        heur_key = tuple(sorted(heur))
    else:
        heur = HEUR.decide_play(rnd, seat)
        heur_key = tuple(sorted(heur))
        if heur_key not in vals:
            heur_key = None
    key = tuple(sorted(action))
    best_key = better(vals, key=lambda k: vals[k])
    v_play, v_best = vals[key], vals[best_key]
    sign = 1 if attacker else -1
    out = dict(
        method=method, n_alternatives=len(vals),
        v_played=v_play, v_best=v_best, best=pretty_cards(best_key),
        regret_pts=sign * (v_best - v_play),
        regret_levels=(team_levels(v_best, attacker) - team_levels(v_play, attacker)),
    )
    if heur_key is not None and heur_key in vals:
        out["heur"] = pretty_cards(heur_key)
        out["heur_minus_played_pts"] = sign * (vals[heur_key] - v_play)
    return out


def bury_counterfactual(after_declare: Round, actual: list[str]) -> dict:
    banker = after_declare.banker
    attacker_view = False  # banker team minimises attacker points
    vals = {"actual": play_round_from_bury(after_declare, actual)}
    for name, bot in BURY_ALTS.items():
        r = copy.deepcopy(after_declare)
        try:
            cards = bot.decide_bury(r, banker)
        except Exception:
            continue
        vals[name] = play_round_from_bury(after_declare, cards)
    best = min(vals, key=lambda k: vals[k])
    return dict(values=vals, best=best,
                regret_pts=vals["actual"] - vals[best],
                regret_levels=(team_levels(vals[best], attacker_view)
                               - team_levels(vals["actual"], attacker_view)))


def declare_counterfactual(evs, decls, team_opts, final_strength, unused,
                           after_declare: Round) -> dict:
    out = {}
    base_val = full_heuristic_round(after_declare)
    for team in (0, 1):
        if not unused[team]["unused_overcall"]:
            continue
        alts = {}
        for s in (team, team + 2):
            for st, opt in team_opts[s]:
                if st <= final_strength:
                    continue
                r = rebuild_to_declare(evs)
                for d in decls:
                    r.declare(d["seat"], d["cards"])
                r.declare(s, opt)
                r.finalize_declare()
                v = full_heuristic_round(r)
                attacker = (r.banker % 2) != team
                alts[f"{s}:{decl_label(opt)}"] = dict(
                    v=v, team_levels=team_levels(v, attacker),
                    team_attacker=attacker)
        base_attacker = (after_declare.banker % 2) != team
        base_lv = team_levels(base_val, base_attacker)
        if alts:
            bk = max(alts, key=lambda k: alts[k]["team_levels"])
            out[str(team)] = dict(actual_v=base_val, actual_team_levels=base_lv,
                                  alts=alts, best=bk,
                                  gain_levels=alts[bk]["team_levels"] - base_lv)
    return out


# --------------------------------------------------------------- discovery
def discover(logs: str):
    rounds = []
    excluded = Counter()
    for path in sorted(glob.glob(os.path.join(logs, "*.jsonl"))):
        room = Path(path).stem
        for rno, evs in sorted(group_rounds(path).items()):
            rs = next((e for e in evs if e["e"] == "round_start"), None)
            if rs is None:
                excluded["no_round_start"] += 1
                continue
            bots = tuple(bool(p["is_bot"]) for p in
                         sorted(rs["players"], key=lambda p: p["seat"]))
            if all(bots) or not any(bots):
                excluded["all_bot_or_all_human"] += 1
                continue
            if not any(e["e"] == "round_end" for e in evs):
                excluded["incomplete"] += 1
                continue
            pols = {e.get("policy") for e in evs
                    if e["e"] in ("model_search", "bot_timing") and e.get("policy")}
            pols |= {e["decision"].get("policy") for e in evs
                     if e["e"] == "play" and "decision" in e}
            pols.discard(None)
            if len(pols) > 1:
                excluded["multi_policy"] += 1
                continue
            policy = next(iter(pols), None)
            bot_teams = [t for t in (0, 1) if bots[t] and bots[t + 2]]
            if len(bot_teams) != 1:
                excluded["no_all_bot_team"] += 1
                continue
            bt = bot_teams[0]
            hp = [e for e in evs if e["e"] == "play" and not bots[e["seat"]]]
            auto = (sum(bool(e.get("bot")) for e in hp) / len(hp)) if hp else 1.0
            if auto > 0.5:
                excluded[f"human_seat_autoplay>50%:{family_of(policy)}"] += 1
                continue
            humans_opp = sum(not bots[s] for s in (1 - bt, 3 - bt))
            tier = "H2-vs-B2" if humans_opp == 2 else "H1+B-vs-B2"
            rounds.append((room, rno, evs, dict(
                bot_team=bt, tier=tier, policy=policy, family=family_of(policy),
                autoplay_frac=auto, t=rs["t"])))
    return rounds, excluded


# ----------------------------------------------------------------- report
def mean(xs):
    xs = list(xs)
    return (sum(xs) / len(xs)) if xs else float("nan")


def report(out_dir: str):
    recs = []
    decs = []
    for f in sorted(glob.glob(os.path.join(out_dir, "rounds*.jsonl"))):
        recs += [json.loads(l) for l in open(f)]
    for f in sorted(glob.glob(os.path.join(out_dir, "decisions*.jsonl"))):
        decs += [json.loads(l) for l in open(f)]
    ok = [r for r in recs if not r.get("replay_mismatch") and not r.get("error")]
    print(f"\n=== rounds: {len(recs)} analysed, {len(ok)} replayed cleanly, "
          f"{len(recs) - len(ok)} mismatched/errored ===")
    families = ["pv-search-491ee4bf", "pv-search-ccade130", "mc-s0-report-lcb",
                "mc-shortlist", "unlogged-policy"]
    groups = {f: [r for r in ok if r["family"] == f] for f in families}
    groups["ALL"] = ok
    print("\n--- counts by family / tier (bot team signed levels per round) ---")
    print(f"{'family':22s} {'tier':12s} {'n':>4s} {'bank':>4s} {'att':>4s} "
          f"{'lv/rd':>6s} {'lv|bank':>8s} {'lv|att':>7s} {'win%':>5s} {'kitty_lv':>8s}")
    for f, rs in groups.items():
        for tier in ("H2-vs-B2", "H1+B-vs-B2", "*"):
            sub = [r for r in rs if tier == "*" or r["tier"] == tier]
            if not sub:
                continue
            b = [r for r in sub if r["bot_role"] == "banker"]
            a = [r for r in sub if r["bot_role"] == "attacker"]
            print(f"{f:22s} {tier:12s} {len(sub):4d} {len(b):4d} {len(a):4d} "
                  f"{mean(r['bot_signed_levels'] for r in sub):+6.2f} "
                  f"{mean(r['bot_signed_levels'] for r in b):+8.2f} "
                  f"{mean(r['bot_signed_levels'] for r in a):+7.2f} "
                  f"{100*mean(r['bot_won'] for r in sub):5.0f} "
                  f"{mean(r['kitty_levels_for_bot'] for r in sub):+8.2f}")

    print("\n--- round facts by family (bot team) ---")
    for f, rs in groups.items():
        if not rs:
            continue
        b = [r for r in rs if r["bot_role"] == "banker"]
        a = [r for r in rs if r["bot_role"] == "attacker"]
        print(f"[{f}] n={len(rs)}")
        print(f"  bot banker  n={len(b)}: att pts mean {mean(r['attacker_points'] for r in b):.1f}"
              f"  buried pts {mean(r['buried_points'] for r in b if r['bury_by_bot']):.1f}"
              f"  kitty bonus conceded {mean(r['kitty_bonus'] for r in b):.1f}"
              f"  att pts early/mid/end {mean(r['att_pts_by_phase'].get('early',0) for r in b):.1f}/"
              f"{mean(r['att_pts_by_phase'].get('mid',0) for r in b):.1f}/"
              f"{mean(r['att_pts_by_phase'].get('end',0) for r in b):.1f}")
        print(f"  bot attacker n={len(a)}: att pts mean {mean(r['attacker_points'] for r in a):.1f}"
              f"  kitty bonus won {mean(r['kitty_bonus'] for r in a):.1f}"
              f"  att pts early/mid/end {mean(r['att_pts_by_phase'].get('early',0) for r in a):.1f}/"
              f"{mean(r['att_pts_by_phase'].get('mid',0) for r in a):.1f}/"
              f"{mean(r['att_pts_by_phase'].get('end',0) for r in a):.1f}")
        dbt = Counter()
        for r in rs:
            u = r["decl_bot_team"]
            dbt["bot_team_final_declarer"] += r["final_declarer_team"] == r["bot_team"]
            dbt["human_team_final_declarer"] += (r["final_declarer_team"] is not None
                                                 and r["final_declarer_team"] != r["bot_team"])
            dbt["no_declaration"] += r["final_declarer"] is None
            dbt["bot_unused_overcall"] += u["unused_overcall"]
            dbt["human_unused_overcall"] += r["decl_human_team"]["unused_overcall"]
        ft = Counter()
        for r in rs:
            for k, v in r["failed_throws"].items():
                ft[k] += v
        print(f"  declaration: {dict(dbt)}")
        print(f"  failed throws logged: {dict(ft)} (bot throws detectable only for pv-search/"
              f"mc-shortlist; human failed throws are not logged)")

    if not decs:
        print("\n(no decision records: run without --no-rollouts)")
        return
    okset = {(r["room"], r["round"]) for r in ok}
    decs = [d for d in decs if (d["room"], d["round"]) in okset]
    rmeta = {(r["room"], r["round"]): r for r in ok}
    print("\n--- phase/role attribution: regret per ROUND (sum of per-decision regret / rounds) ---")
    print("    side = bot team seats (B) vs human seats (H); bot partner of a human (H1 tier) = P;"
          " autoplay at a human seat = A")

    def side(d):
        if d["bot_team_seat"]:
            return "B"
        if d["is_bot"]:
            return "P"
        return "A" if d["bot_played"] else "H"

    for f in ("pv-search-491ee4bf", "ALL"):
        rs = groups[f]
        keys = {(r["room"], r["round"]) for r in rs}
        ds = [d for d in decs if (d["room"], d["round"]) in keys]
        print(f"\n[{f}] rounds={len(rs)} decisions={len(ds)}")
        print(f"  {'side':4s} {'role':8s} {'phase':5s} {'kind':6s} {'n_dec':>6s} "
              f"{'pts/dec':>7s} {'pts/rd':>7s} {'lv/rd':>6s} {'heur-pl/dec':>11s}")
        tbl = defaultdict(list)
        for d in ds:
            tbl[(side(d), d["actor_role"], d["phase"], d["kind"])].append(d)
        for k in sorted(tbl):
            v = tbl[k]
            nr = len(rs)
            hp = [x["heur_minus_played_pts"] for x in v if "heur_minus_played_pts" in x]
            print(f"  {k[0]:4s} {k[1]:8s} {k[2]:5s} {k[3]:6s} {len(v):6d} "
                  f"{mean(x['regret_pts'] for x in v):7.2f} "
                  f"{sum(x['regret_pts'] for x in v)/nr:7.2f} "
                  f"{sum(x['regret_levels'] for x in v)/nr:6.2f} "
                  f"{mean(hp):11.2f}")
        # per-seat-normalised side summary (a side's decisions per round differ)
        print("  per-decision means by side x method:")
        for s in ("B", "H", "P", "A"):
            for m in ("exact", "hybrid"):
                v = [d for d in ds if side(d) == s and d["method"] == m]
                if v:
                    print(f"    {s} {m:6s} n={len(v):5d} regret pts/dec {mean(x['regret_pts'] for x in v):6.2f}"
                          f"  levels/dec {mean(x['regret_levels'] for x in v):.4f}"
                          f"  zero-regret {100*mean(x['regret_pts'] == 0 for x in v):.0f}%")
        # bury and declaration counterfactuals
        bury = [r for r in rs if "bury_cf" in r]
        for who, pred in (("bot-team banker", lambda r: r["bot_role"] == "banker"),
                          ("human-side banker", lambda r: r["bot_role"] == "attacker")):
            v = [r for r in bury if pred(r)]
            if v:
                print(f"  bury cf [{who}] n={len(v)}: regret pts/rd "
                      f"{mean(r['bury_cf']['regret_pts'] for r in v):.1f}  levels/rd "
                      f"{mean(r['bury_cf']['regret_levels'] for r in v):.3f}  "
                      f"actual-is-best {100*mean(r['bury_cf']['best']=='actual' for r in v):.0f}%")
        for who, tkey in (("bot team", "bot"), ("human team", "human")):
            v = []
            for r in rs:
                t = r["bot_team"] if tkey == "bot" else 1 - r["bot_team"]
                cf = (r.get("declare_cf") or {}).get(str(t))
                if cf:
                    v.append(cf["gain_levels"])
            print(f"  declare cf [{who}] rounds with unused overcall n={len(v)}: "
                  f"best-alt gain levels/that-round {mean(v):.2f}; per all rounds "
                  f"{sum(v)/max(1,len(rs)):.3f}")

    # top leaks for the bot team
    print("\n--- top leak categories, bot team (ALL families; pv-search-491ee4bf in brackets) ---")
    cats = defaultdict(list)
    hcats = defaultdict(list)  # same categories on genuine human decisions

    def cat_of(d):
        if d["failed_throw"]:
            return "failed throw (lead)"
        if d["method"] == "exact":
            return f"endgame-exact {d['kind']} ({d['actor_role']})"
        return f"{d['phase']} {d['kind']} ({d['actor_role']})"

    for d in decs:
        if d["bot_team_seat"]:
            cats[cat_of(d)].append(d)
        elif not d["is_bot"] and not d["bot_played"]:
            hcats[cat_of(d)].append(d)
    for r in ok:
        if "bury_cf" not in r:
            continue
        row = dict(room=r["room"], round=r["round"],
                   regret_pts=r["bury_cf"]["regret_pts"],
                   regret_levels=r["bury_cf"]["regret_levels"],
                   family=r["family"], _bury=r)
        if r["bot_role"] == "banker":
            cats["bury (banker)"].append(row)
        elif not r["bury_by_bot"]:
            hcats["bury (banker)"].append(row)
        for team, dest in ((r["bot_team"], cats), (1 - r["bot_team"], hcats)):
            cf = (r.get("declare_cf") or {}).get(str(team))
            if cf:
                dest["declaration (unused overcall)"].append(dict(
                    room=r["room"], round=r["round"], regret_pts=0.0,
                    regret_levels=cf["gain_levels"], family=r["family"], _decl=cf))
    n_all = len(ok)
    n_pv = len(groups["pv-search-491ee4bf"])
    rows = []
    for c, v in cats.items():
        lv = sum(x["regret_levels"] for x in v) / n_all
        pts = sum(x["regret_pts"] for x in v) / n_all
        h = hcats.get(c, [])
        hl = mean(x["regret_levels"] for x in h) if h else 0.0
        hp = mean(x["regret_pts"] for x in h) if h else 0.0
        ex_lv = (mean(x["regret_levels"] for x in v) - hl) * len(v) / n_all
        ex_pts = (mean(x["regret_pts"] for x in v) - hp) * len(v) / n_all
        pv = [x for x in v if x["family"] == "pv-search-491ee4bf"]
        rows.append((lv, pts, c, v, pv, h, ex_lv, ex_pts))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print("  raw = sum of bot regret / all rounds; excess = (bot per-decision mean - human"
          " per-decision mean in the same category) x bot decisions / rounds")
    for lv, pts, c, v, pv, h, ex_lv, ex_pts in rows:
        pvlv = sum(x["regret_levels"] for x in pv) / max(1, n_pv)
        pvpts = sum(x["regret_pts"] for x in pv) / max(1, n_pv)
        nz = sum(1 for x in v if x["regret_pts"] > 0 or x["regret_levels"] > 0)
        print(f"  {c:34s} n={len(v):5d} nz={nz:4d} raw lv/rd {lv:6.3f} pts/rd {pts:6.2f} | "
              f"bot/dec {mean(x['regret_pts'] for x in v):5.2f}pt {mean(x['regret_levels'] for x in v):.3f}lv"
              f" human/dec(n={len(h)}) {(mean(x['regret_pts'] for x in h) if h else float('nan')):5.2f}pt "
              f"{(mean(x['regret_levels'] for x in h) if h else float('nan')):.3f}lv | excess lv/rd {ex_lv:+.3f}"
              f" pts/rd {ex_pts:+.2f} | [pv491 n={len(pv)} lv/rd {pvlv:.3f} pts/rd {pvpts:.2f}]")
    print("\n--- examples (largest regrets, levels then points) ---")
    for lv, pts, c, v, pv, *_ in rows[:8]:
        print(f"\n# {c}")
        key = lambda x: (-x["regret_levels"], -x["regret_pts"])  # noqa: E731
        top = sorted(v, key=key)[:3]
        top += [x for x in sorted(pv, key=key)[:2] if x not in top]
        for x in top:
            if "_bury" in x:
                r = x["_bury"]
                print(f"  {x['room']} r{x['round']} [{r['family']}] buried "
                      f"{pretty_cards(r['buried'])} ({r['buried_points']} pts); "
                      f"values {r['bury_cf']['values']} best={r['bury_cf']['best']}; "
                      f"actual att pts {r['attacker_points']} kitty bonus {r['kitty_bonus']}")
            elif "_decl" in x:
                cf = x["_decl"]
                print(f"  {x['room']} r{x['round']} [{x['family']}] actual lv "
                      f"{cf['actual_team_levels']} best alt {cf['best']} "
                      f"-> {cf['alts'][cf['best']]['team_levels']} (+{cf['gain_levels']})")
            else:
                print(f"  {x['room']} r{x['round']} trick {x['trick']} ply {x['ply']} seat {x['seat']} "
                      f"[{x['family']}, {x['method']}] hand: {x['hand']} | trick: {x['trick_so_far']} | "
                      f"played {x['played']}{' (failed->'+x['forced']+')' if x['failed_throw'] else ''} "
                      f"v={x['v_played']:.0f} vs best {x['best']} v={x['v_best']:.0f} "
                      f"(regret {x['regret_pts']:.0f} pts, {x['regret_levels']} lv)")


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", default=DEFAULT_LOGS,
                    help="production log dir (*.jsonl; local/ is not read)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--shard", default="0/1", help="K/N: analyse rounds i with i%%N==K")
    ap.add_argument("--no-rollouts", action="store_true",
                    help="facts only (no yardstick evaluation)")
    ap.add_argument("--max-cands", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if not a.report_only:
        rounds, excluded = discover(a.logs)
        k, n = map(int, a.shard.split("/"))
        fam = Counter((m["family"], m["tier"]) for *_, m in rounds)
        print(f"discovered {len(rounds)} complete human-vs-bot rounds; excluded {dict(excluded)}")
        for (f, t), c in sorted(fam.items()):
            print(f"  {f:22s} {t:12s} {c}")
        mine = [r for i, r in enumerate(rounds) if i % n == k]
        if a.limit:
            mine = mine[:a.limit]
        suf = "" if n == 1 else f".{k}of{n}"
        with open(os.path.join(a.out, f"rounds{suf}.jsonl"), "w") as fr, \
                open(os.path.join(a.out, f"decisions{suf}.jsonl"), "w") as fd:
            t0 = time.time()
            for i, (room, rno, evs, meta) in enumerate(mine):
                t1 = time.time()
                try:
                    rec, decs = analyse_round(room, rno, evs, meta,
                                              not a.no_rollouts, a.max_cands)
                except Exception as exc:  # recorded, never silently dropped
                    rec, decs = dict(room=room, round=rno, family=meta["family"],
                                     tier=meta["tier"],
                                     error=f"{type(exc).__name__}: {exc}"), []
                fr.write(json.dumps(rec) + "\n")
                for d in decs:
                    fd.write(json.dumps(d) + "\n")
                fr.flush()
                fd.flush()
                print(f"[{i+1}/{len(mine)}] {room} r{rno} {meta['family']} "
                      f"{len(decs)} dec {time.time()-t1:.1f}s (total {time.time()-t0:.0f}s)"
                      + (f" ERROR {rec['error']}" if "error" in rec else
                         (f" MISMATCH {rec['replay_mismatch']}" if rec.get("replay_mismatch") else "")),
                      flush=True)
    if not a.no_report:
        report(a.out)


if __name__ == "__main__":
    main()
