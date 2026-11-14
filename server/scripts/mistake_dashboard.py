#!/usr/bin/env python3
"""One mistake-class table for any batch of game logs.

Runs the shengji.org pilot audit's mistake classes on production room logs
(``--source prod``: ``logs/<ROOM>.jsonl``, full deals) or on shengji.org pilot
game directories (``--source sjorg``: ``<game>/A`` and ``<game>/B`` with
``frames_live_stripped.jsonl`` and ``pilot.jsonl``), and prints one comparable
table, so every pilot, production week or self-play batch gets the same report.

Classes (each counted for both sides, by the seat that made the decision):

* risky throws: multi-component leads (attempted cards, so failed throws count);
  risky when some card unseen by the thrower could beat a component, failed
  when the engine forced a smaller play;
* leads into a hidden void: side-suit leads where an opponent is void and has
  not shown it, and the share of those the opponents won (with their points);
* last-seat overtakes of a winning partner, and last-seat no-feeds (a single
  card lead, partner winning, a higher point card was legal);
* kitty bonus against the banking side (rounds, points and the levels it moved);
* no-bid rounds, and the ones where a seat of the side held a legal bid;
* overcalls of the partner's standing bid (all, and into NT with a joker pair);
* bid refusals (shengji.org only: the adapter's own log);
* optional exact endgame regret at <= K cards on the true deal (hindsight double
  dummy, node-capped; off by default because it is slow).

Sides: shengji.org runs compare our seats (default 0 and 2) with the site's
bots; production compares bot-controlled seats with human-controlled seats, by
each seat's own play, declare and bury events (a round where a seat changes
hands or an event has no controller flag is excluded and counted), and the
level line uses rounds where exactly one team is bot-controlled throughout and
the other has a human-controlled seat.  Output names seats and teams only,
never players.

The engine is imported inside the run so the module imports with the standard
library alone.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]

PTS = {"5": 5, "10": 10, "K": 10}
# Two-sided 95% t quantiles, read at the largest tabulated df not above the
# sample's df; the pilot readers used this table, so their intervals reproduce.
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 10: 2.228, 20: 2.086,
        30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}
SJORG_HIDDEN_KEYS = ("_deck", "_cardMap", "kitty", "dealerKitty")


def pts(cards) -> int:
    return sum(PTS.get(c[1:], 0) for c in cards if c not in ("BJ", "LJ"))


def t975(df: int) -> float:
    if df >= 1000:
        return 1.96
    return T975[max([d for d in T975 if d <= df] or [1])]


def mean_ci(xs):
    """Mean and round-level t 95% interval (None bounds below two values)."""
    n = len(xs)
    if not n:
        return None, None, None, None
    m = statistics.mean(xs)
    if n < 2:
        return m, None, None, None
    sd = statistics.stdev(xs)
    h = t975(n - 1) * sd / math.sqrt(n)
    return m, sd, m - h, m + h


def sjorg_attacker_levels(p: int) -> int:
    """shengji.org attacker level change for attacker total ``p``."""
    if p == 0:
        return -3
    if p < 40:
        return -2
    if p < 80:
        return -1
    if p < 120:
        return 0
    return (p - 120) // 40 + 1


def prod_attacker_levels(p: int) -> int:
    """Our server's attacker level change for attacker total ``p`` (``Game.finish_round``)."""
    if p >= 80:
        return (p - 80) // 40
    return -(3 if p == 0 else (2 if p < 40 else 1))


def parse_time(text: str | None, now: float | None = None) -> float | None:
    """Epoch seconds from ``Nd``/``Nh`` (before now), an epoch number or ISO 8601 (UTC if naive)."""
    if text is None:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([dh])", text.strip())
    if m:
        span = float(m.group(1)) * (86400 if m.group(2) == "d" else 3600)
        return (now if now is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()) - span
    try:
        return float(text)
    except ValueError:
        pass
    value = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.timestamp()


def expand_inputs(patterns) -> list[str]:
    out: list[str] = []
    for pattern in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pattern))) or [os.path.expanduser(pattern)]
        for hit in hits:
            if hit not in out:
                out.append(hit)
    return out


# Round records.  Every loader yields dicts with these keys:
#   game, label, deal_key, t, level, trump ("NT" or a suit), banker,
#   tricks [{"plays": [[seat, cards]], "winner": seat}], kitty_bottom, kitty_in,
#   bids [[seat, cards]], failed {(trick no, seat): (sorted forced cards, sorted attempted)},
#   dealt {seat: cards or None}, side {seat: side name}, team_delta [t0, t1],
#   total_attack, kitty_bonus, bid_refusals (int or None), level_team (0/1/None).


def _played(tricks):
    played = {s: [] for s in range(4)}
    for t in tricks:
        for seat, cards in t["plays"]:
            played[seat] += list(cards)
    return played


def load_prod(paths, since=None, until=None):
    """Complete rounds from production room logs; duplicates across files are dropped."""
    rounds, seen = [], set()
    notes = collections.Counter({f"rounds excluded: {why}": 0 for why in (
        "seat map is not seats 0-3", "an event has no controller flag", "a seat changed controller mid-round")})
    for path in paths:
        cur = None
        recs = []
        with open(path) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    notes["unparsable lines"] += 1
                    continue
                e = o.get("e")
                if e == "round_start":
                    cur = {"start": o, "decl": [], "plays": [], "tricks": []}
                    recs.append(cur)
                elif cur is None:
                    continue
                elif e == "trump":
                    cur["trump"] = o
                elif e == "bury":
                    cur["bury"] = o
                elif e == "declare":
                    cur["decl"].append(o)
                elif e == "play":
                    cur["plays"].append(o)
                elif e == "trick":
                    cur["tricks"].append(o)
                elif e == "round_end":
                    cur["end"] = o
        for rec in recs:
            st = rec["start"]
            t = float(st["t"])
            if (since is not None and t < since) or (until is not None and t >= until):
                continue
            key = (st.get("room"), st.get("t"))
            if key in seen:
                notes["duplicate rounds"] += 1
                continue
            seen.add(key)
            if "end" not in rec or "trump" not in rec or "bury" not in rec:
                notes["incomplete rounds"] += 1
                continue
            tricks = [dict(plays=[[int(p["seat"]), list(p["cards"])] for p in tr["plays"]], winner=int(tr["winner"]))
                      for tr in rec["tricks"]]
            roster = st.get("players") or []
            seats = [p.get("seat") for p in roster]
            if (not all(_seat_ok(x) for x in seats) or sorted(seats) != [0, 1, 2, 3]
                    or not all(_seat_ok(x) for x in _tricks_seats(tricks))):
                notes["rounds excluded: seat map is not seats 0-3"] += 1
                continue
            played = _played(tricks)
            deck = list(st["deck"])
            if len(deck) != 108 or not all(len(v) == 25 for v in played.values()):
                notes["incomplete rounds"] += 1
                continue
            control, why = _controllers(rec)
            if control is None:
                notes[f"rounds excluded: {why}"] += 1
                continue
            if any(bool(p.get("is_bot")) != (control[int(p["seat"])] == "bot") for p in roster):
                notes["rounds where a seat's controller differs from its round-start roster entry"] += 1
            failed, nplay = {}, 0
            for p in rec["plays"]:
                if p.get("engine_resolution") == "failed_throw_forced" and p.get("attempted_cards"):
                    failed[(nplay // 4 + 1, int(p["seat"]))] = (sorted(p["cards"]), sorted(p["attempted_cards"]))
                nplay += 1
            tr = rec["trump"]
            end = rec["end"]
            banker = int(tr["banker"])
            win, gain = int(end["winner_team"]), int(end["level_change"])
            team_delta = [gain if win == 0 else -gain, gain if win == 1 else -gain]
            bot_teams = [tm for tm in (0, 1) if control[tm] == control[tm + 2] == "bot"]
            human_teams = [tm for tm in (0, 1) if "human" in (control[tm], control[tm + 2])]
            rounds.append(dict(
                game=str(st.get("room")), label=int(st.get("round") or 0), deal_key=f"{st.get('room')}:{st.get('t')}",
                t=t, level=str(tr.get("rank") or st.get("trump_rank")), trump=tr.get("suit") or "NT", banker=banker,
                tricks=tricks, kitty_bottom=list(rec["bury"]["cards"]), kitty_in=deck[100:],
                bids=[[int(d["seat"]), list(d["cards"])] for d in rec["decl"]], failed=failed,
                dealt={s: deck[s:100:4] for s in range(4)},
                side=control, team_delta=team_delta,
                total_attack=int(end["attacker_points"]), kitty_bonus=int(end.get("kitty_points") or 0),
                bid_refusals=None, level_team=(bot_teams[0] if len(bot_teams) == 1 and len(human_teams) == 1 else None)))
    return rounds, notes


def _seat_ok(seat):
    return type(seat) is int and 0 <= seat <= 3


def _tricks_seats(tricks):
    return [seat for t in tricks for seat, _ in t["plays"]]


def _controllers(rec):
    """Each seat's controller for the whole round from its own play, declare and bury events.

    A seat is "bot" or "human" only when every one of its events carries the same
    ``bot`` flag; the round-start roster is not evidence, because a bot covers a
    disconnected human's seat and a human can reclaim a bot's seat mid-game.
    Returns (None, reason) when a flag is missing or a seat changes hands."""
    flags = {s: set() for s in range(4)}
    for kind in ("plays", "decl"):
        for o in rec[kind]:
            flags.setdefault(o.get("seat"), set()).add(o.get("bot"))
    flags.setdefault(rec["bury"].get("seat"), set()).add(rec["bury"].get("bot"))
    if set(flags) != {0, 1, 2, 3}:
        return None, "seat map is not seats 0-3"
    if any(not f or not f <= {True, False} for f in flags.values()):
        return None, "an event has no controller flag"
    if any(len(f) > 1 for f in flags.values()):
        return None, "a seat changed controller mid-round"
    return {s: ("bot" if True in f else "human") for s, f in flags.items()}, None


def _sjorg_code(card):
    if card["kind"] == "J":
        return {"BJ": "LJ", "RJ": "BJ"}[card["joker"]]
    return card["suit"] + card["rank"]


def _sjorg_frames(path):
    with open(path) as fh:
        for line in fh:
            if '"state"' not in line:
                continue
            state = json.loads(line).get("state")
            if state:
                yield state


def _sjorg_build(path):
    """Per deal, in frame order: tricks, kitty, revealed bids and failed throws from public state."""
    by = collections.OrderedDict()
    hidden = 0
    for s in _sjorg_frames(path):
        hidden += any(k in s for k in SJORG_HIDDEN_KEYS)
        by.setdefault(s["dealStartedAt"], []).append(s)
    deals = []
    for key, ss in by.items():
        end = next((s for s in reversed(ss) if s.get("roundResult")), None)
        src = end or ss[-1]
        cm = src["cardMap"]
        tricks = [dict(plays=[[int(p["seat"]), [_sjorg_code(cm[i]) for i in p["cards"]]] for p in t["trick"]],
                       winner=int(t["winner"])) for t in src.get("trickHistory") or []]
        rr = src.get("roundResult")
        bids, seen = [], set()
        failed = {}
        for s in ss:
            for b in (s.get("bidding") or {}).get("revealed") or []:
                k = (b["seat"], tuple(b["cardIds"]))
                if k not in seen:
                    seen.add(k)
                    bids.append([int(b["seat"]), [_sjorg_code(s["cardMap"][i]) for i in b["cardIds"]]])
            sf = s.get("slamFailure")
            if sf:
                cms = s["cardMap"]
                failed[(len(s.get("trickHistory") or []) + 1, int(sf["seat"]))] = (
                    sorted(_sjorg_code(cms[i]) for i in sf["forcedCards"]),
                    sorted(_sjorg_code(cms[i]) for i in sf["attemptedCards"]))
        trump = src.get("trump") or {}
        deals.append(dict(deal_key=key, level=trump.get("levelRank"), trump=trump.get("trumpSuit") or "NT",
                          banker=trump.get("dealer"), tricks=tricks, bids=bids, failed=failed,
                          kitty_bottom=[_sjorg_code(cm[i]) for i in rr["kittyCards"]] if rr and rr.get("kittyCards") else None,
                          round_result={k: v for k, v in (rr or {}).items() if k != "kittyCards"} if rr else None))
    return deals, hidden


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_sjorg(game_dirs, our_seats=(0, 2), since=None, until=None):
    """Complete rounds from shengji.org team-game directories (seat A frames, checked against B)."""
    rounds, notes = [], collections.Counter()
    for gdir in game_dirs:
        game = os.path.basename(os.path.normpath(gdir))
        deals_a, hid_a = _sjorg_build(os.path.join(gdir, "A", "frames_live_stripped.jsonl"))
        b_path = os.path.join(gdir, "B", "frames_live_stripped.jsonl")
        deals_b, hid_b = _sjorg_build(b_path) if os.path.exists(b_path) else ([], 0)
        notes["frames with a hidden key"] += hid_a + hid_b
        by_b = {d["deal_key"]: d for d in deals_b}
        bury, refusals = {}, []
        for sub in ("A", "B"):
            for x in _read_jsonl(os.path.join(gdir, sub, "pilot.jsonl")):
                if x.get("kind") == "bury":
                    bury[x["deal"]] = x
                elif x.get("kind") == "bid_refused":
                    refusals.append((float(x["t"]), int(x.get("new", 1))))
        complete = [d for d in deals_a if d["round_result"] and d["kitty_bottom"]]
        starts = sorted(int(d["deal_key"]) / 1000.0 for d in deals_a if d["deal_key"] is not None)
        ref_by_deal = collections.Counter()
        for t, n in refusals:
            owner = max((s for s in starts if s <= t), default=None)
            if owner is not None:
                ref_by_deal[owner] += n
        label = 0
        for d in complete:
            label += 1
            b = by_b.get(d["deal_key"])
            if b is not None:
                if any(d[k] != b[k] for k in ("tricks", "kitty_bottom", "trump", "banker", "level")):
                    notes["rounds where seat logs disagree"] += 1
                if len(b["bids"]) > len(d["bids"]):
                    d["bids"] = b["bids"]
                for k, v in b["failed"].items():
                    d["failed"].setdefault(k, v)
            played = _played(d["tricks"])
            if not all(len(v) == 25 for v in played.values()):
                notes["incomplete rounds"] += 1
                continue
            t = int(d["deal_key"]) / 1000.0
            if (since is not None and t < since) or (until is not None and t >= until):
                continue
            rr = d["round_result"]
            banker = int(d["banker"])
            kitty_in = None
            bx = bury.get(d["deal_key"])
            if bx is not None and banker in our_seats:
                kitty_in = list(bx["kitty_in"])
            dealt = {}
            for s in range(4):
                if s != banker:
                    dealt[s] = list(played[s])
                elif kitty_in is not None:
                    hand = collections.Counter(played[s]) + collections.Counter(d["kitty_bottom"])
                    hand.subtract(collections.Counter(kitty_in))
                    dealt[s] = list(hand.elements())
                else:
                    dealt[s] = None
            lc = rr.get("levelChange") or {}
            ours_team = our_seats[0] % 2
            delta = 0
            if lc:
                delta = lc.get("delta", 0) if lc.get("team") == ours_team else -lc.get("delta", 0)
            team_delta = [delta, -delta] if ours_team == 0 else [-delta, delta]
            total = rr.get("totalAttackPoints", rr.get("attackPoints"))
            rounds.append(dict(
                game=game, label=label, deal_key=d["deal_key"], t=t, level=d["level"], trump=d["trump"], banker=banker,
                tricks=d["tricks"], kitty_bottom=d["kitty_bottom"], kitty_in=kitty_in, bids=d["bids"], failed=d["failed"],
                dealt=dealt, side={s: ("ours" if s in our_seats else "theirs") for s in range(4)}, team_delta=team_delta,
                total_attack=total, kitty_bonus=int(rr.get("kittyBonus") or 0),
                bid_refusals=ref_by_deal.get(t, 0), level_team=ours_team))
    return rounds, notes


def _start_round(r, engine):
    Round, Trick, Ordering = engine["Round"], engine["Trick"], engine["Ordering"]
    import random
    rnd = Round(r["level"], r["banker"], random.Random(0))
    played = _played(r["tricks"])
    rnd.hands = [list(played[s]) for s in range(4)]
    rnd.buried = list(r["kitty_bottom"])
    rnd.kitty = list(r.get("kitty_in") or r["kitty_bottom"])
    rnd._deal_pos = 100
    nt = r["trump"] in ("NT", None)
    rnd.trump_is_nt = nt
    rnd.trump_suit = None if nt else r["trump"]
    rnd.ordering = Ordering(rnd.trump_suit, r["level"])
    rnd.first_round = False
    if r["bids"]:
        seat, cards = r["bids"][-1]
        rnd.declaration = {"seat": seat, "cards": list(cards), "strength": rnd._declaration_strength(list(cards)) or 0}
    lead = r["tricks"][0]["plays"][0][0]
    rnd.trick = Trick(leader=lead, plays=[])
    rnd.phase, rnd.turn = "play", lead
    return rnd


def _plays(r):
    for i, t in enumerate(r["tricks"], 1):
        for pos, (seat, cards) in enumerate(t["plays"]):
            yield i, pos, seat, cards


def _engine():
    from shengji.engine.cards import Ordering, make_deck
    from shengji.engine.combos import decompose
    from shengji.engine.legal import beats, uniform_suit, validate_lead
    from shengji.engine.round import Round, Trick, TrickPlay
    return dict(Ordering=Ordering, make_deck=make_deck, decompose=decompose, beats=beats,
                uniform_suit=uniform_suit, validate_lead=validate_lead, Round=Round, Trick=Trick, TrickPlay=TrickPlay)


def _cur_winner(plays, o, eng):
    lead = plays[0].cards
    inc_suit = eng["uniform_suit"](lead, o)
    inc_top = eng["decompose"](lead, o).top_level()
    w = plays[0].seat
    for tp in plays[1:]:
        won, top = eng["beats"](tp.cards, lead, inc_suit, inc_top, o)
        if won:
            w, inc_top, inc_suit = tp.seat, top, o.eff_suit(tp.cards[0])
    return w


def replay_check(r, eng):
    """Mismatches between the engine replay and the log (legality, trick winners, attacker total)."""
    rnd = _start_round(r, eng)
    bad = []
    try:
        for tn, pos, seat, cards in _plays(r):
            if rnd.turn != seat:
                bad.append(("turn", tn, pos))
                break
            n = len(rnd.history)
            rnd.play(seat, list(cards))
            if len(rnd.history) > n and rnd.history[-1].winner != r["tricks"][tn - 1]["winner"]:
                bad.append(("winner", tn))
    except Exception as exc:  # an illegal recorded play: the round cannot be audited
        bad.append(("illegal", repr(exc)[:80]))
    if not bad and r["total_attack"] is not None and rnd.attacker_points != r["total_attack"]:
        bad.append(("attack_points", rnd.attacker_points, r["total_attack"]))
    if not bad and rnd.kitty_bonus != r["kitty_bonus"]:
        bad.append(("kitty_bonus", rnd.kitty_bonus, r["kitty_bonus"]))
    return bad


def analyse_round(r, eng):
    """Per-round class events, by acting seat."""
    from collections import Counter
    rnd = _start_round(r, eng)
    o = rnd.ordering
    deck = Counter(eng["make_deck"]())
    pub = {s: set() for s in range(4)}
    ls = None
    ev = dict(throws=[], leads=[], last_seat=[], nofeed_chances=[])
    matched_fails = set()
    for tn, pos, seat, cards in _plays(r):
        tr = rnd.trick
        if pos == 0:
            fk = (tn, seat)
            att = None
            if fk in r["failed"] and r["failed"][fk][0] == sorted(cards):
                att = r["failed"][fk][1]
                matched_fails.add(fk)
            tried = att or list(cards)
            ncomp = len(eng["decompose"](list(tried), o).components)
            if ncomp > 1:
                seen = Counter(rnd.hands[seat]) + Counter(c for t in rnd.history for p in t.plays for c in p.cards)
                if seat == rnd.banker:
                    seen += Counter(rnd.buried)
                unseen = deck - seen
                _, msg = eng["validate_lead"](list(tried), list(rnd.hands[seat]), [list(unseen.elements())], o)
                ev["throws"].append(dict(trick=tn, seat=seat, attempted=sorted(tried), failed=att is not None,
                                         risky=msg is not None))
            ls = o.eff_suit(cards[0])
            if ls != "T":
                opps = [(seat + 1) % 4, (seat + 3) % 4]
                void = [s for s in opps if not any(o.eff_suit(c) == ls for c in rnd.hands[s])]
                hid = [s for s in void if ls not in pub[s]]
                t = r["tricks"][tn - 1]
                ev["leads"].append(dict(trick=tn, seat=seat, hidden=bool(hid), opp_won=t["winner"] % 2 != seat % 2,
                                        pts=sum(pts(c) for _, c in t["plays"]), lead=list(cards)))
        else:
            if any(o.eff_suit(c) != ls for c in cards):
                pub[seat].add(ls)
            if pos == 3:
                partner = (seat + 2) % 4
                cw = _cur_winner(tr.plays, o, eng)
                if cw == partner:
                    nw = _cur_winner(list(tr.plays) + [eng["TrickPlay"](seat, list(cards))], o, eng)
                    row = dict(trick=tn, seat=seat, overtook=nw == seat, cards=list(cards))
                    lead = tr.plays[0].cards
                    if len(lead) == 1:
                        hand = list(rnd.hands[seat])
                        insuit = [c for c in hand if o.eff_suit(c) == o.eff_suit(lead[0])]
                        could = max(pts([c]) for c in (insuit or hand))
                        row["left_pts"] = max(0, could - pts(cards))
                    ev["last_seat"].append(row)
        rnd.play(seat, list(cards))
    ev["unmatched_fails"] = len(set(r["failed"]) - matched_fails)
    return ev


def _held_bid(hand, level):
    c = collections.Counter(hand)
    if any(code[1:] == level and code not in ("BJ", "LJ") for code in c):
        return True
    return c["LJ"] >= 2 or c["BJ"] >= 2


def _new_side():
    return collections.defaultdict(float)


def summarise(rounds, source, exact=None):
    """Class totals per side plus per-round rows."""
    eng = _engine()
    level_fn = sjorg_attacker_levels if source == "sjorg" else prod_attacker_levels
    sides = ("ours", "theirs") if source == "sjorg" else ("bot", "human")
    tot = {s: _new_side() for s in sides}
    per_round = []
    checks = collections.Counter({"rounds excluded: engine replay disagrees with the log": 0})
    level_rows = []
    kept = []
    for r in rounds:
        bad = replay_check(r, eng)
        if bad:
            checks["rounds excluded: engine replay disagrees with the log"] += 1
            continue
        kept.append(r)
        ev = analyse_round(r, eng)
        checks["failed throws not matched to a lead"] += ev["unmatched_fails"]
        side = r["side"]
        row = dict(game=r["game"], round=r["label"], deal_key=r["deal_key"], trump=r["trump"], banker=r["banker"],
                   banker_side=side[r["banker"]], total_attack=r["total_attack"], team_delta=r["team_delta"])
        rs = {s: collections.Counter() for s in sides}
        for th in ev["throws"]:
            c = rs[side[th["seat"]]]
            c["throws"] += 1
            c["throws_risky"] += th["risky"]
            c["throws_failed"] += th["failed"]
        for ld in ev["leads"]:
            c = rs[side[ld["seat"]]]
            c["side_leads"] += 1
            c["hidden_void_leads"] += ld["hidden"]
            if ld["hidden"] and ld["opp_won"]:
                c["hidden_void_lost"] += 1
                c["hidden_void_lost_pts"] += ld["pts"]
        for ls in ev["last_seat"]:
            c = rs[side[ls["seat"]]]
            c["last_seat_partner_winning"] += 1
            c["last_seat_overtakes"] += ls["overtook"]
            if "left_pts" in ls:
                c["single_lead_last_seat_partner_winning"] += 1
                if ls["left_pts"] > 0:
                    c["no_feeds"] += 1
                    c["no_feed_pts"] += ls["left_pts"]
        bs = side[r["banker"]]
        rs[bs]["banker_rounds"] += 1
        if r["kitty_bonus"]:
            rs[bs]["kitty_rounds"] += 1
            rs[bs]["kitty_pts"] += r["kitty_bonus"]
            rs[bs]["kitty_levels"] += level_fn(r["total_attack"]) - level_fn(r["total_attack"] - r["kitty_bonus"])
        for s in sides:
            rs[s]["rounds"] += 1
        no_bid = not r["bids"]
        row["no_bid"] = no_bid
        if no_bid:
            checks["no-bid rounds"] += 1
            for s in sides:
                teams = sorted({seat % 2 for seat in range(4) if side[seat] == s and r["dealt"].get(seat) is not None
                                and _held_bid(r["dealt"][seat], r["level"])})
                unknown = any(side[seat] == s and r["dealt"].get(seat) is None for seat in range(4))
                rs[s]["no_bid_rounds"] += 1
                if unknown:
                    rs[s]["no_bid_hand_unknown"] += 1
                if teams:
                    rs[s]["no_bid_held"] += 1
                    rs[s]["no_bid_held_levels"] += sum(r["team_delta"][tm] for tm in teams)
        for i in range(1, len(r["bids"])):
            seat, cards = r["bids"][i]
            if r["bids"][i - 1][0] == (seat + 2) % 4:
                c = rs[side[seat]]
                c["partner_overcalls"] += 1
                c["partner_overcall_levels"] += r["team_delta"][seat % 2]
                if cards[0] in ("BJ", "LJ"):
                    c["partner_overcalls_nt"] += 1
                    c["partner_overcall_nt_levels"] += r["team_delta"][seat % 2]
        if r["bid_refusals"] is not None:
            rs[sides[0]]["bid_refusals"] += r["bid_refusals"]
        if r["level_team"] is not None:
            d = r["team_delta"][r["level_team"]]
            level_rows.append((d, r["banker"] % 2 == r["level_team"]))
            row["level_delta"] = d
        if exact is not None:
            for d in exact_endgame_round(r, eng, source, **exact):
                s = side[d["seat"]]
                if "skipped" in d:
                    rs[s]["dd_skipped"] += 1
                    continue
                rs[s]["dd_decisions"] += 1
                rs[s]["dd_optimal"] += d["dd_best"]
                rs[s]["dd_regret_pts"] += d["dd_regret"]
                rs[s]["dd_regret_levels"] += d["lvl_regret"]
                rs[s]["dd_with_regret"] += d["dd_regret"] > 0
        for s in sides:
            for k, v in rs[s].items():
                tot[s][k] += v
        row["classes"] = {s: dict(rs[s]) for s in sides}
        per_round.append(row)
    deltas = [d for d, _ in level_rows]
    m, sd, lo, hi = mean_ci(deltas)
    bank = [d for d, b in level_rows if b]
    dfn = [d for d, b in level_rows if not b]
    levels = dict(team=("our team" if source == "sjorg" else "the all-bot team"), rounds=len(deltas),
                  mean=m, sd=sd, ci95=[lo, hi],
                  as_banker=dict(rounds=len(bank), mean=statistics.mean(bank) if bank else None),
                  as_defender=dict(rounds=len(dfn), mean=statistics.mean(dfn) if dfn else None))
    games = sorted({r["game"] for r in kept})
    return dict(source=source, sides=list(sides), rounds=len(kept), games=len(games),
                checks=dict(checks), levels=levels,
                totals={s: {k: (int(v) if float(v).is_integer() else v) for k, v in tot[s].items()} for s in sides},
                exact_endgame=exact, per_round=per_round)


def exact_endgame_round(r, eng, source, cap, k=7):
    """Hindsight double-dummy regret of every non-forced play once every hand is <= k cards."""
    from shengji.ai.endgame import (ExactEndgameBudgetExceeded, ExactEndgameRefusal, _clone_for_play,
                                    exhaustive_legal_actions)
    from shengji.ai.endgame_compact import CompactWorldSession
    level_fn = sjorg_attacker_levels if source == "sjorg" else prod_attacker_levels
    rnd = _start_round(r, eng)
    rows = []

    def value(sess, a, seat):
        c = _clone_for_play(rnd)
        c.play(seat, list(a))
        return c.attacker_points if c.phase == "round_end" else sess.solve(c).attacker_points

    for tn, pos, seat, cards in _plays(r):
        if max(len(h) for h in rnd.hands) <= k:
            try:
                sess = CompactWorldSession(rnd, max_hand_cards=k, max_nodes=cap, alpha_beta=True)
                acts = sorted({tuple(sorted(a)) for a in exhaustive_legal_actions(rnd, seat, max_hand_cards=k)})
                if len(acts) > 1:
                    dd = {a: value(sess, a, seat) for a in acts}
                    sg = 1 if rnd.is_attacker(seat) else -1
                    chosen = tuple(sorted(cards))
                    if pos == 0:
                        _, att = r["failed"].get((tn, seat), (None, None))
                        if att is not None and tuple(att) in dd:
                            chosen = tuple(att)
                    if chosen in dd:
                        signed = {a: sg * v for a, v in dd.items()}
                        best = max(signed.values())
                        tp = (lambda v: v) if sg > 0 else (lambda v: -v)
                        rows.append(dict(trick=tn, pos=pos, seat=seat, dd_best=signed[chosen] == best,
                                         dd_regret=best - signed[chosen],
                                         lvl_regret=sg * (level_fn(tp(best)) - level_fn(tp(signed[chosen])))))
            except (ExactEndgameBudgetExceeded, ExactEndgameRefusal) as exc:  # skipped and counted
                rows.append(dict(trick=tn, pos=pos, seat=seat, skipped=repr(exc)[:120]))
        rnd.play(seat, list(cards))
    return rows


def _rate(a, b):
    return f"{a / b:.1%}" if b else "n/a"


CLASS_ROWS = (
    # label, count key, denominator key, pts key, levels key, description
    ("Risky throws", "throws_risky", "throws", None, None, "multi-component leads where an unseen card could beat a component"),
    ("Failed throws", "throws_failed", "throws", None, None, "throws the engine forced smaller"),
    ("Leads into a hidden void", "hidden_void_leads", "side_leads", None, None, "side-suit leads; an opponent is void and has not shown it"),
    ("... and lost to the opponents", "hidden_void_lost", "hidden_void_leads", "hidden_void_lost_pts", None, "points are the trick's points"),
    ("Last-seat overtakes of partner", "last_seat_overtakes", "last_seat_partner_winning", None, None, "last to play, partner winning, we beat partner"),
    ("Last-seat no-feeds", "no_feeds", "single_lead_last_seat_partner_winning", "no_feed_pts", None, "single-card lead, partner winning, a higher point card was legal"),
    ("Kitty bonus against the banker", "kitty_rounds", "banker_rounds", "kitty_pts", "kitty_levels", "levels: attacker level change the bonus caused"),
    ("No-bid rounds, side held a bid", "no_bid_held", "rounds", None, "no_bid_held_levels", "levels: the holder team's level change"),
    ("Overcalls of partner's bid", "partner_overcalls", "rounds", None, "partner_overcall_levels", "levels: the overcaller team's level change"),
    ("... into NT (joker pair)", "partner_overcalls_nt", "rounds", None, "partner_overcall_nt_levels", ""),
    ("Bid refusals", "bid_refusals", "rounds", None, None, "shengji.org adapter log; our seats only"),
)
DD_ROWS = (
    ("Exact endgame: DD-suboptimal plays", "dd_with_regret", "dd_decisions", "dd_regret_pts", "dd_regret_levels", "hindsight double dummy on the true deal"),
)


def render_markdown(res) -> str:
    a, b = res["sides"]
    ta, tb = res["totals"][a], res["totals"][b]
    lv = res["levels"]
    out = [f"# Mistake dashboard ({res['source']})", ""]
    out.append(f"- rounds audited: {res['rounds']} in {res['games']} games or rooms")
    if lv["rounds"]:
        lo, hi = lv["ci95"]
        ci = f", 95% CI [{lo:+.3f}, {hi:+.3f}] (round-level t, sd {lv['sd']:.2f})" if lo is not None else ""
        bk, df = lv["as_banker"], lv["as_defender"]
        out.append(f"- levels/round for {lv['team']}: **{lv['mean']:+.3f}**{ci}, n = {lv['rounds']}; "
                   f"as banker {bk['rounds']} rds {bk['mean'] if bk['mean'] is None else format(bk['mean'], '+.3f')}, "
                   f"as defender {df['rounds']} rds {df['mean'] if df['mean'] is None else format(df['mean'], '+.3f')}")
    else:
        out.append("- levels/round: no round has exactly one all-bot team")
    for k, v in sorted(res["checks"].items()):
        out.append(f"- {k}: {v}")
    out.append("")
    out.append(f"| class | {a}: count / n | {a} rate | {a} pts | {a} levels | {b}: count / n | {b} rate | {b} pts | {b} levels | note |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    rows = CLASS_ROWS + (DD_ROWS if res.get("exact_endgame") else ())
    for label, ck, nk, pk, lk, note in rows:
        cells = []
        for t in (ta, tb):
            n = t.get(nk, 0)
            c = t.get(ck, 0)
            if ck == "bid_refusals" and (t is tb or res["source"] != "sjorg"):
                cells += ["n/a", "", "", ""]
                continue
            cells += [f"{c} / {n}", _rate(c, n), (str(t.get(pk, 0)) if pk else "·"),
                      (f"{t.get(lk, 0):+g}" if lk else "·")]
        out.append(f"| {label} | " + " | ".join(cells) + f" | {note} |")
    if res.get("exact_endgame"):
        for s in (a, b):
            t = res["totals"][s]
            n = t.get("dd_decisions", 0)
            if n:
                out.append("")
                out.append(f"- exact endgame {s}: n {n}, DD-optimal {t.get('dd_optimal', 0) / n:.3f}, "
                           f"regret {t.get('dd_regret_pts', 0) / n:.2f} pts/decision, total {t.get('dd_regret_pts', 0):g} pts, "
                           f"{t.get('dd_regret_levels', 0):g} levels, skipped at the node cap {t.get('dd_skipped', 0)}")
    out.append("")
    for s in (a, b):
        unknown = res["totals"][s].get("no_bid_hand_unknown", 0)
        if unknown:
            out.append(f"- {s}: {unknown} no-bid rounds where a {s} banker's dealt hand is not in the log "
                       "(its pre-bury kitty is private), so 'held a bid' checks only the other seat")
    out.append("- risky throws and hidden voids are judged on public play plus the acting seat's own hand")
    return "\n".join(out) + "\n"


def parse_exact(text):
    if text in (None, "off"):
        return None
    opts = dict(part.split("=", 1) for part in text.split(","))
    if "cap" not in opts:
        raise argparse.ArgumentTypeError("--exact-endgame takes off or cap=N[,k=K]")
    return dict(cap=int(opts["cap"]), k=int(opts.get("k", 7)))


def run(source, inputs, since=None, until=None, exact=None, our_seats=(0, 2)):
    paths = expand_inputs(inputs)
    if source == "prod":
        files = [p for p in paths if os.path.isfile(p) and p.endswith(".jsonl")]
        rounds, notes = load_prod(files, since, until)
    else:
        dirs = [p for p in paths if os.path.isdir(os.path.join(p, "A"))]
        rounds, notes = load_sjorg(dirs, our_seats, since, until)
    if source == "sjorg":
        from shengji.engine import rules_profile
        previous = rules_profile.active()
        rules_profile.install(rules_profile.SHENGJIORG)
        try:
            res = summarise(rounds, source, exact)
        finally:
            rules_profile.install(previous)
    else:
        res = summarise(rounds, source, exact)
    res["checks"].update(notes)
    res["inputs"] = len(paths)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("prod", "sjorg"), required=True)
    ap.add_argument("--input", nargs="+", required=True, help="room log files (prod) or game directories (sjorg); globs allowed")
    ap.add_argument("--since", help="round start at or after: ISO 8601 (UTC), epoch seconds, or Nd/Nh ago")
    ap.add_argument("--until", help="round start before (same forms)")
    ap.add_argument("--exact-endgame", default="off", type=parse_exact, help="off (default) or cap=N[,k=K]: node cap, hand size")
    ap.add_argument("--our-seats", default="0,2", help="sjorg: our seats")
    ap.add_argument("--out", help="markdown table path (default: stdout)")
    ap.add_argument("--json", help="JSON result path")
    args = ap.parse_args(argv)
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    res = run(args.source, args.input, parse_time(args.since), parse_time(args.until), args.exact_endgame,
              tuple(int(x) for x in args.our_seats.split(",")))
    md = render_markdown(res)
    if args.out:
        Path(args.out).write_text(md)
    else:
        sys.stdout.write(md)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1, default=str))
    return 0 if res["rounds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
