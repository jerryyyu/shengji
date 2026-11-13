"""Offline last-seat point-leak counters on logged production rounds.

Replays every complete round in the given room logs and, at each bot play that
carries a ``pv-search-decision-v1`` record, re-selects among the LOGGED admitted
candidates and value means under four arms: the served selection (R52: argmax,
then ``tb``, then the exact follow stage when it ran), ``xfpt`` (the exact follow
stage's points tie-break), ``lsp<milli>`` (`pv_search_policy.last_seat_points_pick`)
and both.  Each re-selected last-seat play is then flagged:

* P3: an opponent holds the trick, a legal play wins it, points are at stake,
  and the play does not win;
* P2: an opponent holds the trick, no legal play wins it, the play carries
  points and a zero-point legal play exists;
* P4: the partner holds the trick, the play does not win it, and it carries
  fewer points than the most-points legal play, which would not win either.

Limits: the arms re-use the logged search (worlds, admission, value means, exact
scores), so a rule's effect on later decisions is not modelled.  The ``xfpt``
arm ranks exact-tied candidates by the trick's certain points, not by the exact
stage's own rest-of-hand points, so it approximates that stage; on earlier seats
its effect is not estimable from the logs and only the count of tied exact
follows is reported.  P1 (refused throws) is counted for the served play only.

Usage::

    python scripts/point_leak_counters.py --logs ~/Projects/shengji/logs \\
        --rooms IPQQ YXKI ... --t0 1794459600 --out counters.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from shengji.engine.cards import total_points
from shengji.engine.combos import decompose
from shengji.harvest.legal import enumerate_legal
from shengji.rl.replay_log import rebuild_round
from shengji.train.pv_search_policy import (last_seat_points_pick, last_seat_signed_points,
                                            last_seat_trick_outcome)

#: the served points tie-break window (`policy_value_search.TIEBREAK_DEFAULTS`)
TB_EPSILON = 0.02
DECISION_SCHEMA = "pv-search-decision-v1"


def arm_pick(means, signed, exact_scores, *, xfpt, margin):
    """The admitted position an arm plays, from the logged ballot.  ``margin``
    None is the served selection without the last-seat rule."""
    argmax = max(range(len(means)), key=lambda i: (means[i], -i))
    pick, _ = last_seat_points_pick(means, signed, argmax, TB_EPSILON)
    if margin is not None:
        pick, _ = last_seat_points_pick(means, signed, pick, margin)
    if exact_scores is None:
        return pick
    # `pv_exact_follow.rerank_follow`: the best exact score, the baseline on a tie
    best = max(range(len(exact_scores)), key=lambda i: (exact_scores[i], -i))
    if exact_scores[best] <= exact_scores[pick]:
        best = pick
    top = max(exact_scores)
    tied = [i for i, v in enumerate(exact_scores) if v == top]
    if xfpt and len(tied) >= 2:
        best = max(tied, key=lambda i: (signed[i], i == best, -i))
    return best


def leak_flags(rnd, seat, legal, action):
    """The P2/P3/P4 flags of ``seat`` completing the trick with ``action``."""
    outcome = {tuple(sorted(a)): last_seat_trick_outcome(rnd, seat, a) for a in legal}
    team = rnd.is_attacker(seat)
    incumbent = _incumbent(rnd)
    partner_holds = rnd.is_attacker(incumbent) == team
    before = total_points(c for p in rnd.trick.plays for c in p.cards)

    def wins(a):
        return outcome[tuple(sorted(a))][0] == seat

    mine = total_points(action)
    winners = [a for a in legal if wins(a)]
    out = set()
    if not partner_holds:
        if not wins(action) and winners and before + mine > 0:
            out.add("P3")
        elif not wins(action) and not winners and mine > 0 \
                and any(total_points(a) == 0 for a in legal):
            out.add("P2")
    else:
        most = max(legal, key=total_points)
        if not wins(action) and mine < total_points(most) and not wins(most):
            out.add("P4")
    return out


def _incumbent(rnd):
    """The seat holding the trick before the fourth play."""
    from shengji.engine.legal import beats, uniform_suit
    order = rnd.ordering
    lead = rnd.trick.plays[0].cards
    suit, top = uniform_suit(lead, order), decompose(lead, order).top_level()
    winner = rnd.trick.plays[0].seat
    for play in rnd.trick.plays[1:]:
        won, new_top = beats(play.cards, lead, suit, top, order)
        if won:
            winner, top, suit = play.seat, new_top, order.eff_suit(play.cards[0])
    return winner


def round_events(path: Path, t0: float):
    by_round = defaultdict(list)
    for raw in path.read_text().splitlines():
        if raw.strip():
            event = json.loads(raw)
            if event.get("t", 0) >= t0:
                by_round[int(event["round"])].append(event)
    return by_round


def exact_scores_of(decision):
    if not decision.get("exact_follow_attempted") or decision.get("exact_follow_abandoned"):
        return None
    return decision.get("exact_follow_scores")


def collect(logs: Path, rooms, t0):
    """Per complete round, every bot decision; last-seat PV follows in detail."""
    rows, totals = [], Counter()
    for room in rooms:
        for number, events in sorted(round_events(logs / f"{room}.jsonl", t0).items()):
            if not any(e["e"] == "round_end" for e in events):
                continue
            rnd = rebuild_round(events)
            if rnd is None:
                continue
            for event in events:
                if event.get("e") != "play" or rnd.phase != "play":
                    continue
                seat, cards = int(event["seat"]), list(event["cards"])
                decision = event.get("decision") if isinstance(event.get("decision"), dict) else None
                position = len(rnd.trick.plays)
                if event.get("bot"):
                    totals["bot_decisions"] += 1
                    if position == 0 and len(event.get("attempted_cards") or cards) > 1 \
                            and len(decompose(list(event.get("attempted_cards") or cards),
                                              rnd.ordering).components) > 1:
                        totals["throws_attempted"] += 1
                        totals["throws_refused"] += bool(event.get("attempted_cards"))
                    if decision and decision.get("schema") == DECISION_SCHEMA \
                            and position in (1, 2) and exact_scores_of(decision):
                        scores = exact_scores_of(decision)
                        totals["earlier_exact_follows"] += 1
                        totals["earlier_exact_follows_tied"] += \
                            sum(v == max(scores) for v in scores) >= 2
                if event.get("bot") and position == 3 and decision \
                        and decision.get("schema") == DECISION_SCHEMA \
                        and None not in decision.get("value_means", [None]):
                    legal = enumerate_legal(rnd, seat, cap=4000, must_include=[cards]).actions
                    admitted = [list(a) for a in decision["admitted"]]
                    played = next(i for i, a in enumerate(admitted) if sorted(a) == sorted(cards))
                    rows.append(dict(
                        key=f"{room}/r{number}/t{len(rnd.history) + 1}/s{seat}",
                        rnd=_snapshot(rnd), seat=seat, legal=legal, admitted=admitted,
                        means=list(decision["value_means"]), played=played,
                        exact=exact_scores_of(decision),
                        signed=[last_seat_signed_points(rnd, seat, a) for a in admitted]))
                rnd.play(seat, cards)
    return rows, totals


def _snapshot(rnd):
    import copy
    return copy.deepcopy(rnd)


def run(rows, totals, arms):
    n_last = len(rows)
    result = {"bot_decisions": totals["bot_decisions"], "last_seat_pv_follows": n_last,
              "last_seat_with_exact": sum(r["exact"] is not None for r in rows),
              "earlier_exact_follows": totals["earlier_exact_follows"],
              "earlier_exact_follows_tied": totals["earlier_exact_follows_tied"],
              "p1": {"throws_attempted": totals["throws_attempted"],
                     "throws_refused": totals["throws_refused"]},
              "arms": {}}
    for name, (xfpt, margin) in arms.items():
        counts, changed, served_mismatch, events = Counter(), 0, 0, defaultdict(list)
        for r in rows:
            pick = arm_pick(r["means"], r["signed"], r["exact"], xfpt=xfpt, margin=margin)
            served = arm_pick(r["means"], r["signed"], r["exact"], xfpt=False, margin=None)
            served_mismatch += served != r["played"]
            changed += pick != r["played"]
            for flag in leak_flags(r["rnd"], r["seat"], r["legal"], r["admitted"][pick]):
                counts[flag] += 1
                events[flag].append(r["key"])
        result["arms"][name] = {
            "per_1000_last_seat": {f: round(1000 * counts[f] / n_last, 2) for f in ("P2", "P3", "P4")},
            "events": {f: counts[f] for f in ("P2", "P3", "P4")},
            "event_keys": dict(events),
            "changed_vs_played": changed,
            "changed_share_last_seat": round(changed / n_last, 4),
            "changed_share_all_bot_decisions": round(changed / totals["bot_decisions"], 4),
            "served_reconstruction_mismatches": served_mismatch,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--rooms", nargs="+", required=True)
    parser.add_argument("--t0", type=float, default=0.0)
    parser.add_argument("--margin", type=float, default=0.15)
    parser.add_argument("--sweep", type=float, nargs="*", default=())
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rows, totals = collect(args.logs.expanduser(), args.rooms, args.t0)
    tag = f"lsp{round(args.margin * 1000)}"
    arms = {"R52": (False, None), "xfpt": (True, None), tag: (False, args.margin),
            f"xfpt+{tag}": (True, args.margin)}
    for margin in args.sweep:
        arms[f"lsp{round(margin * 1000)}"] = (False, margin)
    result = run(rows, totals, arms)
    print(json.dumps({k: v for k, v in result.items() if k != "arms"}))
    for name, arm in result["arms"].items():
        rates = arm["per_1000_last_seat"]
        print(f"{name:14} P3 {rates['P3']:6.2f}  P2 {rates['P2']:6.2f}  P4 {rates['P4']:6.2f} /1k  "
              f"changed {arm['changed_vs_played']:3d} = {100 * arm['changed_share_last_seat']:.1f}% "
              f"last-seat, {100 * arm['changed_share_all_bot_decisions']:.2f}% all  "
              f"served-mismatch {arm['served_reconstruction_mismatches']}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
