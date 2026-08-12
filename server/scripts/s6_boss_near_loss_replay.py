#!/usr/bin/env python3
"""Replay the sole utility-changing S6 boss/near DEV witness.

This is an outcome-bearing exploration diagnostic, never a promotion test.  It
replays the treatment and literal champion on the same frozen deal and records
only actor-available state plus compact search records around policy-team
leads.  The first trajectory divergence therefore explains the causal S6
override without exposing any sealed population or opponent hand.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_boss_near_dev_pilot as PILOT  # noqa: E402
import s6_throw_duel as BASE  # noqa: E402
from shengji.ai import throw_sourcing as SOURCE  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.round import actual_play_after  # noqa: E402


SCHEMA = "s6-boss-near-loss-replay-v1"
WITNESS_SEED = 449_000_000_024
WITNESS_FLIP = 1
LABELS = ("treatment", "champion")
OVERRIDE_WITNESSES = (
    (449_000_000_004, 1), (449_000_000_008, 1),
    (449_000_000_010, 1), (449_000_000_011, 1),
    (449_000_000_014, 0), (449_000_000_016, 1),
    (449_000_000_020, 1), (449_000_000_022, 0),
    (449_000_000_024, 1), (449_000_000_025, 0),
    (449_000_000_027, 1), (449_000_000_028, 1),
)
EXPECTED_UTILITY_DELTAS = {
    witness: (-2 if witness == (WITNESS_SEED, WITNESS_FLIP) else 0)
    for witness in OVERRIDE_WITNESSES
}


class ReplayRefused(RuntimeError):
    """The frozen DEV witness cannot support a causal diagnostic."""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def compact_search(record: object) -> dict | None:
    """Retain decision evidence while dropping bulky RNG/replay internals."""
    if not isinstance(record, dict):
        return None
    report = record.get("report_fold")
    if isinstance(report, dict):
        report = {
            key: deepcopy(report.get(key)) for key in (
                "complete", "worlds", "gap", "se", "critical", "statistic",
                "min_gain", "rule", "candidate", "candidate0")
            if key in report
        }
    return {
        "candidates": deepcopy(record.get("candidates")),
        "means": deepcopy(record.get("means")),
        "n_by_candidate": deepcopy(record.get("n_by_candidate")),
        "eligible_indices": deepcopy(record.get("eligible_indices")),
        "raw_winner_index": record.get("raw_winner_index"),
        "report_candidate_index": record.get("report_candidate_index"),
        "played_index": record.get("played_index"),
        "played": deepcopy(record.get("played")),
        "reason": record.get("reason"),
        "report_fold": report,
        "work": deepcopy(record.get("work")),
    }


def component_proof(rnd, seat: int, cards: list[str]) -> dict:
    """Classify a proposed bundle using only information available to actor."""
    if rnd.ordering is None or not cards:
        raise ReplayRefused("component proof requires an ordered nonempty play")
    ordering = rnd.ordering
    suits = {ordering.eff_suit(card) for card in cards}
    if len(suits) != 1:
        raise ReplayRefused("S6 throw candidate spans effective suits")
    suit = next(iter(suits))
    memory = Memory(rnd, seat, own_kitty=True)
    components = []
    for component in combos.decompose(cards, ordering).components:
        top = max(component.cards, key=ordering.level)
        if component.pair_len:
            boss = memory.pair_is_boss(top)
            near = SOURCE._pair_near_boss(top, suit, memory)
        else:
            boss = memory.is_boss(top)
            near = False
        components.append({
            "cards": list(component.cards),
            "top": top,
            "pair_len": component.pair_len,
            "publicly_proven_boss": boss,
            "publicly_near_boss": near,
        })
    return {
        "effective_suit": suit,
        "components": components,
        "all_components_publicly_proven_boss": all(
            row["publicly_proven_boss"] for row in components),
        "near_boss_components": sum(
            row["publicly_near_boss"] and not row["publicly_proven_boss"]
            for row in components),
    }


def _policies(label: str, seed: int, flip: int) -> list:
    a1 = PILOT.make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[0])
    a2 = PILOT.make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[1])
    b1 = PILOT.make_arm("champion", seed + BASE.OPPONENT_ROLE_OFFSETS[0])
    b2 = PILOT.make_arm("champion", seed + BASE.OPPONENT_ROLE_OFFSETS[1])
    return ([a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2])


def trace_round(label: str, seed: int, flip: int) -> dict:
    policies = _policies(label, seed, flip)
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise ReplayRefused("witness has no banker")
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(rnd, rnd.banker))

    policy_team = flip
    history = []
    tricks = []
    lead_events = []
    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            raise ReplayRefused("play phase has no actor")
        bot = policies[seat]
        action_index = len(history)
        is_lead = bool(rnd.trick is not None and not rnd.trick.plays)
        hand_before = rnd.sorted_hand(seat)
        trick_before = ([{"seat": play.seat, "cards": list(play.cards)}
                         for play in rnd.trick.plays]
                        if rnd.trick is not None else [])
        attempted = bot.decide_play(rnd, seat)
        decision = deepcopy(getattr(bot, "last_decision_record", None))
        s6 = deepcopy(getattr(bot, "last_s6_throw_record", None))
        proof = (component_proof(rnd, seat, list(attempted))
                 if isinstance(s6, dict)
                 and s6.get("treatment_override") is True else None)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, previous_last)
        history.append({"seat": seat, "cards": actual})
        if rnd.last_trick is not previous_last:
            trick = rnd.last_trick
            if trick is None or trick.winner is None:
                raise ReplayRefused("resolved trick is incomplete")
            tricks.append({
                "trick_index": len(tricks),
                "leader": trick.leader,
                "plays": [{"seat": play.seat, "cards": list(play.cards)}
                          for play in trick.plays],
                "winner": trick.winner,
                "points": trick.points,
                "attackers_captured": rnd.is_attacker(trick.winner),
                "attacker_points_after": rnd.attacker_points,
            })
        if is_lead and seat % 2 == policy_team:
            incumbent = (decision.get("s6_incumbent_decision")
                         if isinstance(decision, dict) else None)
            lead_events.append({
                "action_index": action_index,
                "trick_index": len(rnd.history) - (
                    1 if rnd.last_trick is not previous_last else 0),
                "seat": seat,
                "role": "attacker" if rnd.is_attacker(seat) else "defender",
                "attacker_points_before": (
                    rnd.attacker_points - (
                        rnd.last_trick.points
                        if rnd.last_trick is not previous_last
                        and rnd.is_attacker(rnd.last_trick.winner) else 0)),
                "hand_before": hand_before,
                "trick_before": trick_before,
                "attempted": list(attempted),
                "actual": list(actual),
                "s6": s6,
                "component_proof": proof,
                "search": compact_search(decision),
                "incumbent_search": compact_search(incumbent),
            })

    result = game.finish_round()
    return {
        "label": label,
        "seed": seed,
        "flip": flip,
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "attacker_points": result.attacker_points,
        "winner_team": result.winner_team,
        "level_change": result.level_change,
        "kitty_points": result.kitty_points,
        "kitty_cards": result.kitty_cards,
        "history": history,
        "tricks": tricks,
        "lead_events": lead_events,
    }


def first_divergence(left: list[dict], right: list[dict]) -> int | None:
    mismatch = next((index for index, pair in enumerate(zip(left, right))
                     if pair[0] != pair[1]), None)
    if mismatch is not None:
        return mismatch
    return None if len(left) == len(right) else min(len(left), len(right))


def signed_utility(trace: dict, flip: int) -> int:
    return ((1 if trace["winner_team"] == flip else -1)
            * max(1, trace["level_change"]))


def summarize_witness(treatment: dict, champion: dict) -> dict:
    seed = treatment["seed"]
    flip = treatment["flip"]
    if (champion.get("seed"), champion.get("flip")) != (seed, flip):
        raise ReplayRefused("witness trace identity drift")
    divergence = first_divergence(treatment["history"], champion["history"])
    if divergence is None:
        raise ReplayRefused("override witness did not diverge")
    event = next((row for row in treatment["lead_events"]
                  if row["action_index"] == divergence), None)
    if (event is None or not isinstance(event.get("s6"), dict)
            or event["s6"].get("treatment_override") is not True):
        raise ReplayRefused("first divergence is not an S6 override")
    report = event["search"]["report_fold"]
    if not isinstance(report, dict) or report.get("complete") is not True:
        raise ReplayRefused("S6 override lacks complete report evidence")
    utility_delta = signed_utility(treatment, flip) - signed_utility(
        champion, flip)
    expected = EXPECTED_UTILITY_DELTAS.get((seed, flip))
    if expected is not None and utility_delta != expected:
        raise ReplayRefused("override utility no longer matches frozen pilot")
    attempted = event["attempted"]
    actual = event["actual"]
    return {
        "seed": seed,
        "flip": flip,
        "first_divergence_action_index": divergence,
        "trick_index": event["trick_index"],
        "seat": event["seat"],
        "role": event["role"],
        "attacker_points_before": event["attacker_points_before"],
        "hand_before": event["hand_before"],
        "incumbent": event["incumbent_search"]["played"],
        "attempted": attempted,
        "actual": actual,
        "throw_succeeded": Counter(attempted) == Counter(actual),
        "ballot": event["s6"]["ballot"],
        "component_proof": event["component_proof"],
        "report": report,
        "treatment_attacker_points": treatment["attacker_points"],
        "champion_attacker_points": champion["attacker_points"],
        "treatment_utility": signed_utility(treatment, flip),
        "champion_utility": signed_utility(champion, flip),
        "signed_level_utility_delta": utility_delta,
    }


def _trace_pair(witness: tuple[int, int]) -> tuple[tuple[int, int], dict, dict]:
    seed, flip = witness
    return witness, trace_round("treatment", seed, flip), trace_round(
        "champion", seed, flip)


def build_census_payload(expected_git: str, workers: int) -> dict:
    if not 0 < workers <= 8:
        raise ReplayRefused("worker count outside exploration bound")
    traces = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pending = {executor.submit(_trace_pair, witness): witness
                   for witness in OVERRIDE_WITNESSES}
        for future in as_completed(pending):
            witness, treatment, champion = future.result()
            traces[witness] = (treatment, champion)
            print(json.dumps({
                "event": "s6-boss-near-override-replay-progress-v1",
                "witnesses_complete": len(traces),
                "witnesses_total": len(OVERRIDE_WITNESSES),
            }, sort_keys=True), flush=True)
    rows = [summarize_witness(*traces[witness])
            for witness in OVERRIDE_WITNESSES]
    failed = [row for row in rows if not row["throw_succeeded"]]
    proven = [row for row in rows if row["component_proof"][
        "all_components_publicly_proven_boss"]]
    payload = {
        "schema": "s6-boss-near-override-census-v1",
        "git": expected_git,
        "population": "all 12 treatment overrides in frozen 32-cluster DEV pilot",
        "rows": rows,
        "summary": {
            "witnesses": len(rows),
            "successful_throws": len(rows) - len(failed),
            "failed_throws": len(failed),
            "positive_utility": sum(
                row["signed_level_utility_delta"] > 0 for row in rows),
            "neutral_utility": sum(
                row["signed_level_utility_delta"] == 0 for row in rows),
            "negative_utility": sum(
                row["signed_level_utility_delta"] < 0 for row in rows),
            "failed_throw_negative_utility": sum(
                row["signed_level_utility_delta"] < 0 for row in failed),
            "all_boss_public_proof": len(proven),
            "all_boss_positive_utility": sum(
                row["signed_level_utility_delta"] > 0 for row in proven),
            "all_boss_neutral_utility": sum(
                row["signed_level_utility_delta"] == 0 for row in proven),
            "all_boss_negative_utility": sum(
                row["signed_level_utility_delta"] < 0 for row in proven),
        },
        "exploration_only": True,
        "confirmatory_claim": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = PILOT.stable_digest(payload)
    return payload


def build_payload(expected_git: str) -> dict:
    traces = {label: trace_round(label, WITNESS_SEED, WITNESS_FLIP)
              for label in LABELS}
    treatment = traces["treatment"]
    champion = traces["champion"]
    divergence = first_divergence(
        treatment["history"], champion["history"])
    if divergence is None:
        raise ReplayRefused("frozen loss witness did not diverge")
    event = next((row for row in treatment["lead_events"]
                  if row["action_index"] == divergence), None)
    if (event is None or not isinstance(event.get("s6"), dict)
            or event["s6"].get("treatment_override") is not True):
        raise ReplayRefused("first divergence is not the S6 treatment override")
    delta = signed_utility(treatment, WITNESS_FLIP) - signed_utility(
        champion, WITNESS_FLIP)
    if delta != -2:
        raise ReplayRefused("witness no longer reproduces the two-level loss")
    payload = {
        "schema": SCHEMA,
        "git": expected_git,
        "seed": WITNESS_SEED,
        "flip": WITNESS_FLIP,
        "first_divergence_action_index": divergence,
        "signed_level_utility_delta": delta,
        "traces": traces,
        "exploration_only": True,
        "confirmatory_claim": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = PILOT.stable_digest(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--all-overrides", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if git("rev-parse", "HEAD") != args.expected_git:
        raise SystemExit("REFUSED: git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("REFUSED: dirty producer")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise SystemExit("REFUSED: strict compiled runtime required")
    payload = (build_census_payload(args.expected_git, args.workers)
               if args.all_overrides else build_payload(args.expected_git))
    PILOT.write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "COMPLETE",
        "result_sha256": PILOT.sha256(args.out),
        "result_internal_sha256": payload["internal_sha256"],
        "schema": payload["schema"],
        "first_divergence_action_index": payload.get(
            "first_divergence_action_index"),
        "signed_level_utility_delta": payload.get(
            "signed_level_utility_delta"),
        "summary": payload.get("summary"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
