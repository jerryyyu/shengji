#!/usr/bin/env python3
"""Freeze and adjudicate the bounded S4 point-banking state screen.

The two stages are intentionally separate:

``capture``
    Scan a fresh, fixed deal stream and freeze the first 32 attacker and 32
    defender late-game states where the rollout treatment actually changes the
    historical cheap winner.  This stage is score-free: it does not call the
    exact solver or expose any candidate outcome.

``screen``
    Only after an independent review admission, force the treatment and null
    actions in each frozen fully-known state and solve the remaining two-card
    endgame exactly.  The primary estimand is acting-team signed final attacker
    points; bracket/level utility is a predeclared secondary safety check.

PASS opens review of a full-game packet only.  It never authorizes a duel,
training, promotion, or production change.  SELECT_NONE closes this exact
recipe; there is no retry or threshold tuning after outcomes are visible.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.endgame import solve_exact_endgame                 # noqa: E402
from shengji.ai.heuristic import HeuristicBot                     # noqa: E402
from shengji.ai.point_banking import PointBankingRolloutPolicy     # noqa: E402
from shengji.engine.cards import Ordering, make_deck, total_points # noqa: E402
from shengji.engine.game import Game                               # noqa: E402
from shengji.engine.legal import beats, uniform_suit               # noqa: E402
from shengji.engine.combos import decompose                         # noqa: E402
from shengji.engine.round import Round, Trick, TrickPlay            # noqa: E402


CAPTURE_SCHEMA = "s4-point-banking-states-v1"
SCREEN_SCHEMA = "s4-point-banking-exact-screen-v1"
ADMISSION_SCHEMA = "s4-point-banking-screen-review-v1"
SEED0 = 160_000_000
MAX_DEALS = 200_000
ROLE_QUOTA = {"attacker": 32, "defender": 32}
HAND_CARDS_AT_DECISION = 3
EXACT_MAX_HAND_CARDS = 2
EXACT_MAX_NODES = 50_000
T_CRITICAL_OVERALL = 1.669       # one-sided 95%, df=63
T_CRITICAL_ROLE = 1.696          # one-sided 95%, df=31


class S4ProtocolError(RuntimeError):
    pass


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def runtime(*, smoke: bool) -> dict:
    from shengji.ai import endgame, mcbot, point_banking, registry
    from shengji.engine import combos, fast, legal, round as round_mod

    dirty = bool(git_output("status", "--porcelain"))
    if dirty and not smoke:
        raise S4ProtocolError("real S4 work refuses a dirty tree")
    if not smoke and os.environ.get("SHENGJI_FAST") != "1":
        raise S4ProtocolError("real S4 work requires SHENGJI_FAST=1")
    fast_routed = (fast.HAVE_FAST and combos.decompose is fast.decompose
                   and legal.beats is fast.beats)
    if not smoke and not fast_routed:
        raise S4ProtocolError(
            "real S4 work requires the compiled engine on the live route")
    paths = {
        "script": __file__,
        "point_banking": point_banking.__file__,
        "mcbot": mcbot.__file__,
        "registry": registry.__file__,
        "endgame": endgame.__file__,
        "engine_round": round_mod.__file__,
    }
    return {
        "git": git_output("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "promotable": not smoke,
        "python": sys.version.split()[0],
        "fast_engine": bool(fast.HAVE_FAST),
        "fast_routed": bool(fast_routed),
        "files": {name: sha256_file(path)
                  for name, path in sorted(paths.items())},
    }


def publish_exclusive(path: str | os.PathLike, payload: dict) -> None:
    """Publish through a sibling partial without overwrite/resume semantics."""
    final = Path(path)
    partial = Path(str(final) + ".partial")
    final.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(final) or os.path.lexists(partial):
        raise S4ProtocolError(
            f"refusing existing final/partial artifact at {final}")
    try:
        with partial.open("xb") as fh:
            fh.write(canonical_json(payload))
            fh.flush()
            os.fsync(fh.fileno())
        os.link(partial, final)
        partial.unlink()
    except Exception:
        if partial.exists() and not final.exists():
            partial.unlink()
        raise


def _play_record(trick: Trick) -> dict:
    return {
        "leader": trick.leader,
        "plays": [{"seat": play.seat, "cards": list(play.cards)}
                  for play in trick.plays],
        "winner": trick.winner,
        "points": trick.points,
    }


def _trick_from_record(record: dict) -> Trick:
    return Trick(
        leader=int(record["leader"]),
        plays=[TrickPlay(int(play["seat"]), list(play["cards"]))
               for play in record["plays"]],
        winner=record.get("winner"),
        points=int(record.get("points", 0)),
    )


def state_record(rnd: Round, seat: int, seed: int,
                 null_action: list[str], treatment_action: list[str],
                 telemetry: dict) -> dict:
    assert rnd.trick is not None and rnd.ordering is not None
    role = "attacker" if rnd.is_attacker(seat) else "defender"
    record = {
        "schema": "s4-point-banking-state-v1",
        "state_id": f"{seed}:late-last-follow",
        "deal_seed": seed,
        "seat": seat,
        "role": role,
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": bool(rnd.trump_is_nt),
        "attacker_points": int(rnd.attacker_points),
        "buried": list(rnd.buried),
        "hands": [list(hand) for hand in rnd.hands],
        "history": [_play_record(trick) for trick in rnd.history],
        "trick": _play_record(rnd.trick),
        "turn": rnd.turn,
        "null_action": list(null_action),
        "treatment_action": list(treatment_action),
        "trigger_delta": dict(telemetry["delta"]),
    }
    record["state_sha256"] = sha256_bytes(canonical_json(record))
    return record


def replay_state(record: dict) -> Round:
    if record.get("schema") != "s4-point-banking-state-v1":
        raise S4ProtocolError("wrong S4 state schema")
    body = dict(record)
    observed_digest = body.pop("state_sha256", None)
    if observed_digest != sha256_bytes(canonical_json(body)):
        raise S4ProtocolError("S4 state digest mismatch")
    rnd = Round(str(record["trump_rank"]), int(record["banker"]),
                random.Random(0))
    rnd.phase = "play"
    rnd.trump_suit = record["trump_suit"]
    rnd.trump_is_nt = bool(record["trump_is_nt"])
    rnd.ordering = Ordering(rnd.trump_suit, rnd.trump_rank)
    rnd.buried = list(record["buried"])
    rnd.kitty = list(rnd.buried)
    rnd.hands = [list(hand) for hand in record["hands"]]
    rnd.history = [_trick_from_record(t) for t in record["history"]]
    rnd.last_trick = rnd.history[-1] if rnd.history else None
    rnd.last_trick_winner = (rnd.last_trick.winner
                             if rnd.last_trick is not None else None)
    rnd.trick = _trick_from_record(record["trick"])
    rnd.turn = int(record["turn"])
    rnd.attacker_points = int(record["attacker_points"])
    rnd.kitty_bonus = 0
    validate_state(rnd, expected_seat=int(record["seat"]))
    return rnd


def _winner_and_points(trick: Trick, ordering: Ordering) -> tuple[int, int]:
    if len(trick.plays) != 4:
        raise S4ProtocolError("resolved history trick does not have four plays")
    lead = trick.plays[0].cards
    inc_suit = uniform_suit(lead, ordering)
    if inc_suit is None:
        raise S4ProtocolError("history contains a non-uniform resolved lead")
    inc_top = decompose(lead, ordering).top_level()
    winner = trick.plays[0].seat
    for play in trick.plays[1:]:
        won, top = beats(play.cards, lead, inc_suit, inc_top, ordering)
        if won:
            winner, inc_top = play.seat, top
            inc_suit = ordering.eff_suit(play.cards[0])
    return winner, total_points(
        card for play in trick.plays for card in play.cards)


def validate_state(rnd: Round, *, expected_seat: int) -> None:
    if rnd.phase != "play" or rnd.turn != expected_seat or rnd.trick is None:
        raise S4ProtocolError("S4 state is not the registered active decision")
    if len(rnd.hands[expected_seat]) != HAND_CARDS_AT_DECISION:
        raise S4ProtocolError("S4 acting hand is not the registered three cards")
    if len(rnd.trick.plays) != 3:
        raise S4ProtocolError("S4 state is not a last-seat follow")
    if any(len(hand) != 2 for seat, hand in enumerate(rnd.hands)
           if seat != expected_seat):
        raise S4ProtocolError("S4 nonacting hands do not have two cards")
    # Shengji tricks may contain pairs/tractors/throws, so hand depth does not
    # imply a fixed number of resolved tricks.  The exact boundary is the
    # remaining-card vector above, not an ordinary-card-game trick index.
    history_points = 0
    for trick in rnd.history:
        winner, points = _winner_and_points(trick, rnd.ordering)
        if trick.winner != winner or trick.points != points:
            raise S4ProtocolError("S4 history winner/points mismatch")
        if rnd.is_attacker(winner):
            history_points += points
    if history_points != rnd.attacker_points:
        raise S4ProtocolError("S4 accumulated attacker points mismatch")
    cards = list(rnd.buried)
    cards += [card for hand in rnd.hands for card in hand]
    cards += [card for trick in rnd.history for play in trick.plays
              for card in play.cards]
    cards += [card for play in rnd.trick.plays for card in play.cards]
    if Counter(cards) != Counter(make_deck()):
        raise S4ProtocolError("S4 state does not contain one physical deck")


def _drive_to_trigger(seed: int) -> tuple[Round, int, list[str], list[str], dict] | None:
    game = Game(random.Random(seed))
    rnd = game.start_round()
    actors = [HeuristicBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))

    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None and rnd.trick is not None
        if (len(rnd.hands[seat]) == HAND_CARDS_AT_DECISION
                and len(rnd.trick.plays) == 3):
            treatment = PointBankingRolloutPolicy(apply_treatment=True)
            null = PointBankingRolloutPolicy(apply_treatment=False)
            before = treatment.point_banking_snapshot()
            treatment_action = treatment.decide_play(rnd, seat)
            null_action = null.decide_play(rnd, seat)
            telemetry = treatment.point_banking_delta(before)
            if telemetry["delta"]["triggers"]:
                if treatment_action == null_action:
                    raise S4ProtocolError("triggered S4 state has identical arms")
                return rnd, seat, null_action, treatment_action, telemetry
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    return None


def capture_states(*, seed0: int, max_deals: int,
                   role_quota: dict[str, int], progress: bool = True) -> dict:
    if seed0 != SEED0 or max_deals != MAX_DEALS or role_quota != ROLE_QUOTA:
        raise S4ProtocolError("real S4 capture constants drifted")
    accepted = Counter()
    observed = Counter()
    rows = []
    scanned = 0
    for offset in range(max_deals):
        seed = seed0 + offset
        scanned += 1
        found = _drive_to_trigger(seed)
        if found is not None:
            rnd, seat, null_action, treatment_action, telemetry = found
            role = "attacker" if rnd.is_attacker(seat) else "defender"
            observed[role] += 1
            if accepted[role] < role_quota[role]:
                rows.append(state_record(
                    rnd, seat, seed, null_action, treatment_action, telemetry))
                accepted[role] += 1
        if progress and scanned % 5_000 == 0:
            print(f"CAPTURE_PROGRESS deals={scanned}/{max_deals} "
                  f"accepted={sum(accepted.values())}/{sum(role_quota.values())}",
                  flush=True)
        if all(accepted[role] == role_quota[role] for role in role_quota):
            break
    if dict(accepted) != role_quota:
        raise S4ProtocolError(
            f"S4 capture exhausted population: accepted={dict(accepted)}")
    seeds = [row["deal_seed"] for row in rows]
    if len(seeds) != len(set(seeds)):
        raise S4ProtocolError("S4 capture selected multiple states per deal")
    return {
        "schema": CAPTURE_SCHEMA,
        "score_free": True,
        "outcomes_computed": False,
        "evaluation_only": True,
        "training_authorized": False,
        "strength_claim": False,
        "source_policy": "heuristic",
        "selection": "first trigger per role in ascending fresh deal stream",
        "seed0": seed0,
        "seed_end_inclusive": seed0 + max_deals - 1,
        "deals_scanned": scanned,
        "role_quota": dict(role_quota),
        "accepted_by_role": dict(accepted),
        "observed_triggers_by_role": dict(observed),
        "states": rows,
    }


def _round_team_level_value(attacker_points: int, acting_is_attacker: bool) -> int:
    if attacker_points >= 80:
        attacker_value = max(1, (attacker_points - 80) // 40)
    else:
        defender_gain = (3 if attacker_points == 0 else
                         2 if attacker_points < 40 else 1)
        attacker_value = -defender_gain
    return attacker_value if acting_is_attacker else -attacker_value


def score_state(record: dict) -> dict:
    rnd = replay_state(record)
    seat = int(record["seat"])
    treatment = PointBankingRolloutPolicy(apply_treatment=True)
    null = PointBankingRolloutPolicy(apply_treatment=False)
    if treatment.decide_play(copy.deepcopy(rnd), seat) != record["treatment_action"]:
        raise S4ProtocolError("frozen S4 treatment action drifted")
    if null.decide_play(copy.deepcopy(rnd), seat) != record["null_action"]:
        raise S4ProtocolError("frozen S4 null action drifted")

    values = {}
    nodes = {}
    for label in ("null", "treatment"):
        clone = copy.deepcopy(rnd)
        clone.play(seat, list(record[f"{label}_action"]))
        if max(len(hand) for hand in clone.hands) != EXACT_MAX_HAND_CARDS:
            raise S4ProtocolError("S4 forced action did not reach exact boundary")
        result = solve_exact_endgame(
            clone, max_hand_cards=EXACT_MAX_HAND_CARDS,
            max_nodes=EXACT_MAX_NODES)
        values[label] = int(result.attacker_points)
        nodes[label] = int(result.nodes)
    acting_is_attacker = record["role"] == "attacker"
    point_delta = (values["treatment"] - values["null"]
                   if acting_is_attacker else
                   values["null"] - values["treatment"])
    level_delta = (
        _round_team_level_value(values["treatment"], acting_is_attacker)
        - _round_team_level_value(values["null"], acting_is_attacker)
    )
    return {
        "state_id": record["state_id"],
        "deal_seed": record["deal_seed"],
        "role": record["role"],
        "null_action": record["null_action"],
        "treatment_action": record["treatment_action"],
        "null_attacker_points": values["null"],
        "treatment_attacker_points": values["treatment"],
        "signed_point_delta": point_delta,
        "signed_level_utility_delta": level_delta,
        "exact_nodes": nodes,
    }


def _mean_se_lcb(values: list[int], critical: float) -> dict[str, float | int]:
    n = len(values)
    if n < 2:
        raise S4ProtocolError("S4 metric requires at least two independent deals")
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    se = math.sqrt(variance / n)
    return {"n": n, "mean": mean, "se": se,
            "lcb_one_sided_95": mean - critical * se}


def aggregate(rows: list[dict]) -> dict:
    if len(rows) != sum(ROLE_QUOTA.values()):
        raise S4ProtocolError("S4 result row count drift")
    if len({row["deal_seed"] for row in rows}) != len(rows):
        raise S4ProtocolError("S4 result deals are not independent")
    by_role = {}
    for role in ROLE_QUOTA:
        role_rows = [row for row in rows if row["role"] == role]
        if len(role_rows) != ROLE_QUOTA[role]:
            raise S4ProtocolError(f"S4 role count drift for {role}")
        by_role[role] = {
            "points": _mean_se_lcb(
                [row["signed_point_delta"] for row in role_rows],
                T_CRITICAL_ROLE),
            "level_utility_mean": sum(
                row["signed_level_utility_delta"] for row in role_rows
            ) / len(role_rows),
        }
    points = _mean_se_lcb(
        [row["signed_point_delta"] for row in rows], T_CRITICAL_OVERALL)
    level_mean = sum(row["signed_level_utility_delta"] for row in rows) / len(rows)
    wins = sum(row["signed_point_delta"] > 0 for row in rows)
    losses = sum(row["signed_point_delta"] < 0 for row in rows)
    criteria = {
        "overall_point_lcb_gt_0": points["lcb_one_sided_95"] > 0,
        "each_role_point_mean_gt_0": all(
            value["points"]["mean"] > 0 for value in by_role.values()),
        "overall_level_utility_mean_ge_0": level_mean >= 0,
        "point_wins_gt_losses": wins > losses,
    }
    passed = all(criteria.values())
    return {
        "primary": "acting-team signed exact final attacker-point delta",
        "points": points,
        "level_utility_mean": level_mean,
        "by_role": by_role,
        "point_wins": wins,
        "point_losses": losses,
        "point_ties": len(rows) - wins - losses,
        "criteria": criteria,
        "verdict": ("AUTHORIZE_FULL_GAME_PACKET_REVIEW"
                    if passed else "SELECT_NONE"),
        "strength_claim": False,
        "full_game_launch_authorized": False,
        "production_promotion": False,
    }


def verify_capture(payload: dict) -> None:
    if payload.get("schema") != CAPTURE_SCHEMA:
        raise S4ProtocolError("wrong S4 capture schema")
    if (payload.get("score_free") is not True
            or payload.get("outcomes_computed") is not False
            or payload.get("evaluation_only") is not True
            or payload.get("training_authorized") is not False
            or payload.get("strength_claim") is not False):
        raise S4ProtocolError("S4 capture is not score-free")
    if payload.get("seed0") != SEED0 or payload.get("role_quota") != ROLE_QUOTA:
        raise S4ProtocolError("S4 capture constants drifted")
    capture_runtime = payload.get("runtime", {})
    if (capture_runtime.get("tree_dirty") is not False
            or capture_runtime.get("promotable") is not True
            or capture_runtime.get("fast_engine") is not True
            or capture_runtime.get("fast_routed") is not True):
        raise S4ProtocolError("S4 capture runtime is not promotable")
    states = payload.get("states")
    if not isinstance(states, list) or len(states) != sum(ROLE_QUOTA.values()):
        raise S4ProtocolError("S4 capture state count drift")
    counts = Counter(row.get("role") for row in states)
    if dict(counts) != ROLE_QUOTA:
        raise S4ProtocolError("S4 capture role population drift")
    for row in states:
        replay_state(row)
        if row["trigger_delta"].get("triggers") != 1:
            raise S4ProtocolError("S4 capture includes a nontrigger state")


def verify_admission(path: str, *, git: str, states_sha256: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        admission = json.load(fh)
    required = {
        "schema": ADMISSION_SCHEMA,
        "git": git,
        "states_sha256": states_sha256,
        "independent_review": True,
        "screen_launch_authorized": True,
        "strength_claim": False,
        "production_promotion": False,
        "verdict": "PASS",
    }
    if any(admission.get(key) != value for key, value in required.items()):
        raise S4ProtocolError("S4 external review admission mismatch")
    return admission


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--out", required=True)
    capture.add_argument("--smoke", action="store_true")
    screen = sub.add_parser("screen")
    screen.add_argument("--states", required=True)
    screen.add_argument("--expected-states-sha256", required=True)
    screen.add_argument("--review-admission", required=True)
    screen.add_argument("--out", required=True)
    screen.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    rt = runtime(smoke=args.smoke)
    if args.command == "capture":
        payload = capture_states(
            seed0=SEED0, max_deals=MAX_DEALS,
            role_quota=dict(ROLE_QUOTA), progress=True)
        payload["runtime"] = rt
        payload["contract"] = {
            "hand_cards_at_decision": HAND_CARDS_AT_DECISION,
            "exact_max_hand_cards_after_action": EXACT_MAX_HAND_CARDS,
            "exact_max_nodes": EXACT_MAX_NODES,
            "primary": "acting-team signed exact final attacker-point delta",
            "gate": {
                "overall_point_lcb_gt_0": True,
                "each_role_point_mean_gt_0": True,
                "overall_level_utility_mean_ge_0": True,
                "point_wins_gt_losses": True,
            },
            "terminal_authority": [
                "AUTHORIZE_FULL_GAME_PACKET_REVIEW", "SELECT_NONE"],
        }
        publish_exclusive(args.out, payload)
        print(f"S4_CAPTURE_COMPLETE path={args.out} "
              f"sha256={sha256_file(args.out)} states={len(payload['states'])}")
        return

    observed_sha = sha256_file(args.states)
    if observed_sha != args.expected_states_sha256:
        raise S4ProtocolError("S4 states SHA does not match predeclared input")
    with open(args.states, encoding="utf-8") as fh:
        states = json.load(fh)
    verify_capture(states)
    if states.get("runtime", {}).get("git") != rt["git"]:
        raise S4ProtocolError("S4 screen git differs from capture git")
    admission = verify_admission(
        args.review_admission, git=rt["git"], states_sha256=observed_sha)
    rows = []
    for index, state in enumerate(states["states"], start=1):
        rows.append(score_state(state))
        if index % 8 == 0:
            print(f"SCREEN_PROGRESS states={index}/{len(states['states'])}",
                  flush=True)
    result = {
        "schema": SCREEN_SCHEMA,
        "complete": True,
        "git": rt["git"],
        "runtime": rt,
        "states_sha256": observed_sha,
        "review_admission_sha256": sha256_file(args.review_admission),
        "review_admission": admission,
        "rows": rows,
        "aggregate": aggregate(rows),
    }
    publish_exclusive(args.out, result)
    print(f"S4_SCREEN_COMPLETE path={args.out} sha256={sha256_file(args.out)} "
          f"verdict={result['aggregate']['verdict']}")


if __name__ == "__main__":
    main()
