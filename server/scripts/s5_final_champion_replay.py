#!/usr/bin/env python3
"""Replay the live champion on the reviewed late-seat S5 witnesses.

The reviewed S5 census established a historical mechanism, but it did not run
the complete ``mc-s0-report-lcb`` decision rule.  Candidate zero and the
rollout policy both matched the historical point-bearing discard on sixteen
states; that is not proof that the report fold's *final* action still does so.

This exploration-tier diagnostic closes only that gap.  It reconstructs the
ten reviewed third/fourth-seat witnesses (the actor's partner has already
played), runs the literal live champion on 32 deterministic RNG seeds per
state, and publishes action-shape/work counters only.  It never publishes
cards, hands, source names, players, rooms, round scores, winners, utilities,
or belief worlds.  A positive result may motivate an actor-visible treatment
design.  It is not a strength result and grants no training, promotion, or
deployment authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT  # noqa: E402
import s5_point_protection_census as CENSUS  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import total_points  # noqa: E402
from shengji.engine.legal import beats  # noqa: E402
from shengji.rl.replay_log import EXCLUDE_PLAYERS, group_rounds, rebuild_round  # noqa: E402


DESIGN_SCHEMA = "s5-final-champion-replay-design-v1"
RESULT_SCHEMA = "s5-final-champion-replay-result-v1"
RUN_ID = "human-v8-s5-final-champion-replay-v1"
CHAMPION = "mc-s0-report-lcb"
REVIEW_PREFIX = "S5_FINAL_CHAMPION_REPLAY_V1_REVIEW "
CENSUS_REVIEW_PREFIX = "S5_POINT_PROTECTION_CENSUS_V1_REVIEW "
CENSUS_PATH = (
    SERVER / "runs/logs/human-v8-s5-point-protection-census-v1/census.json"
)
CENSUS_SHA256 = (
    "efc82b8c22eef30a3f926d51db3d0922ba355406fe9da5dd5cf9b2468c6dbac3"
)
CENSUS_REVIEW_MARKER_SHA256 = (
    "05256414756f9946fbef5638db27951061956f021692167448dfa1c12969c504"
)
SOURCE_MANIFEST_SHA256 = CENSUS.SOURCE_MANIFEST_SHA256
SEEDS_PER_TARGET = 32
SEED_DOMAIN = b"shengji-s5-final-champion-replay-v1\0"
TARGET_WITNESSES = (
    "0e36ec3ca113f498ce90e95e0538a7b5efedef5b79b5f242af8408ae8ede9309",
    "28f0661ff01285c03d2c91e9d2b2c5ffefc87d45b25249f014c9085a446804eb",
    "2e095275caef93fbf403406e47d3d91e81638a3e088d31cbf06b9bb97f4bc192",
    "759be9d5e44e79d6274fd030d3defbdc9ef5f40287abff6494f9fc9d1560b31c",
    "7a279f41237aee01d14202a432e20514d98d9c21d6a64dcb904654be8a25f83d",
    "7b4c7e286b26f9d74bac23da14b8f5d071f97f52a462e82a4360b03defb2e2e3",
    "866fbd79569766a192ac4f6a08f2b3394832a1d9c6e3a03d37d8858395a29278",
    "aa68b8a4177374a5b500abcdf13b1438e23dac7a606e096630b85b268f7d0df5",
    "aec274f33a2d6e800796820152562bd2f19e7b99c70d2413543398c9e5c7343c",
    "d3502bce6f421d291d29f825f8f5d7732d409118f6ed24cafae421f18a4c4343",
)

DESIGN_FIELDS = frozenset({
    "schema", "run_id", "champion", "source_census", "selection",
    "rng", "estimand", "decision_rule", "authority", "design_sha256",
})
SOURCE_CENSUS_FIELDS = frozenset({
    "path", "file_sha256", "packet_sha256", "witness_set_sha256",
    "review_marker_sha256",
})
SELECTION_FIELDS = frozenset({
    "rule", "target_count", "target_witnesses", "target_witnesses_sha256",
    "required_follow_positions", "partner_already_acted_only",
})
TARGET_FIELDS = frozenset({
    "witness_sha256", "role", "follow_position", "lead_size",
    "cards_remaining_total", "lower_point_on_current_ballot",
})
RNG_FIELDS = frozenset({
    "domain_sha256", "seeds_per_target", "total_decisions",
    "derivation",
})
DECISION_RULE_FIELDS = frozenset({
    "ranking_treatment_design_eligible", "ballot_diagnosis_only",
    "no_current_reproduction", "continuous_counts_retained",
    "automatic_strength_claim",
})
AUTHORITY_FIELDS = frozenset({
    "exploration_only", "private_source_required", "raw_cards_published",
    "room_or_player_identifiers_published", "round_outcomes_read",
    "utilities_published", "strength_execution", "strength_claim",
    "labels_authorized", "training_authorized", "production_promotion",
    "production_deployment",
})
RESULT_FIELDS = frozenset({
    "schema", "run_id", "design", "producer", "runtime", "source",
    "stats", "witnesses", "decisions", "decision", "authority",
    "result_sha256",
})
PRODUCER_FIELDS = frozenset({"git", "script_sha256", "tree_dirty"})
RUNTIME_FIELDS = frozenset({
    "python", "implementation", "machine", "fast_engine",
    "fast_binary_sha256", "live_parent_sha256",
})
SOURCE_FIELDS = frozenset({
    "manifest_sha256", "member_count", "total_bytes",
    "members_commitment_sha256", "source_names_published",
})
DECISION_FIELDS = frozenset({
    "witness_sha256", "replicate", "seed", "role", "follow_position",
    "candidate_count", "candidate0_card_points", "chosen_card_points",
    "minimum_legal_card_points", "minimum_ballot_card_points",
    "avoidable_legal_point_delta", "avoidable_ballot_point_delta",
    "played_index", "raw_winner_index", "reason", "donated_points",
    "lower_point_action_on_ballot", "selection_rollouts",
    "report_rollouts", "total_rollouts", "work_complete", "sampler_counters",
})
SAMPLER_FIELDS = frozenset({
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
})
WITNESS_RESULT_FIELDS = frozenset({
    "witness_sha256", "role", "follow_position", "decisions",
    "donation_decisions", "avoidable_on_ballot_decisions",
    "override_decisions", "candidate0_decisions", "reason_counts",
    "chosen_point_histogram", "total_rollouts",
})
STATS_FIELDS = frozenset({
    "target_count", "seeds_per_target", "decisions",
    "donation_decisions", "donation_witnesses",
    "avoidable_on_ballot_decisions", "avoidable_on_ballot_witnesses",
    "override_decisions", "candidate0_decisions", "total_rollouts",
    "complete_work_decisions", "incomplete_work_decisions",
})
REASONS = frozenset({
    "candidate0_best", "search_override", "below_fixed_margin",
    "lcb_below_margin", "selection_underfilled", "no_report_challenger",
    "report_underfilled", "report_mean_below_min_gain",
    "report_mean_override", "report_lcb_below_min_gain",
    "report_lcb_override",
})


class ReplayRefused(RuntimeError):
    """The diagnostic input, execution, or publication boundary drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReplayRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReplayRefused(f"JSON root is not an object: {path}")
    return value


def _exact_fields(value: object, expected: frozenset[str], name: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{name} is not an object"]
    actual = set(value)
    if actual == expected:
        return []
    return [f"{name} fields differ: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"]


def seed_for(witness_sha256: str, replicate: int) -> int:
    if witness_sha256 not in TARGET_WITNESSES:
        raise ReplayRefused("seed requested for a non-target witness")
    if isinstance(replicate, bool) or not 0 <= replicate < SEEDS_PER_TARGET:
        raise ReplayRefused("replicate outside the frozen schedule")
    payload = canonical_json([witness_sha256, replicate])
    return int.from_bytes(hashlib.sha256(SEED_DOMAIN + payload).digest()[:8],
                          "big")


def _load_reviewed_census(path: Path = CENSUS_PATH) -> dict:
    if sha256_file(path) != CENSUS_SHA256:
        raise ReplayRefused("reviewed S5 census file SHA-256 drift")
    packet = _load_object(path)
    if packet.get("schema") != CENSUS.SCHEMA:
        raise ReplayRefused("reviewed S5 census schema drift")
    packet_copy = dict(packet)
    claimed_packet_sha = packet_copy.pop("packet_sha256", None)
    if (claimed_packet_sha != CENSUS.sha256_bytes(
            CENSUS.canonical_json(packet_copy))):
        raise ReplayRefused("reviewed S5 census packet self-hash drift")
    witnesses = packet.get("witnesses")
    if (not isinstance(witnesses, list)
            or packet.get("witness_set_sha256") != CENSUS.sha256_bytes(
                CENSUS.canonical_json(witnesses))):
        raise ReplayRefused("reviewed S5 witness-set self-hash drift")
    authority = packet.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("full_champion_mc_replays") != 0
            or authority.get("strength_run_authorized") is not False
            or authority.get("strength_claim") is not False):
        raise ReplayRefused("reviewed S5 census authority drift")
    return packet


def _target_rows(packet: Mapping[str, object]) -> dict[str, dict]:
    witnesses = packet.get("witnesses")
    if not isinstance(witnesses, list):
        raise ReplayRefused("S5 census witnesses are not a list")
    selected = {
        str(row.get("witness_sha256")): dict(row)
        for row in witnesses
        if isinstance(row, Mapping)
        and row.get("reproduced_by_current_policy_surface") is True
        and row.get("follow_position") in (3, 4)
    }
    if tuple(sorted(selected)) != TARGET_WITNESSES:
        raise ReplayRefused("late current-surface witness selection drift")
    for witness, row in selected.items():
        required = {
            "structural_trigger": True,
            "incumbent_is_opponent": True,
            "historical_wins_immediately": False,
            "legal_winner_count": 0,
            "current_candidate0_matches_historical": True,
            "rollout_policy_matches_historical": True,
            "final_winner_is_opponent": True,
        }
        if any(row.get(key) != value for key, value in required.items()):
            raise ReplayRefused(f"target witness contract drift: {witness}")
        if (row.get("historical_points", 0) <= 0
                or row.get("avoidable_point_delta", 0) <= 0):
            raise ReplayRefused(f"target lacks avoidable points: {witness}")
    return selected


def build_design(census_path: Path = CENSUS_PATH) -> dict:
    packet = _load_reviewed_census(census_path)
    selected = _target_rows(packet)
    targets = [{
        "witness_sha256": witness,
        "role": selected[witness]["role"],
        "follow_position": selected[witness]["follow_position"],
        "lead_size": selected[witness]["lead_size"],
        "cards_remaining_total": selected[witness]["cards_remaining_total"],
        "lower_point_on_current_ballot":
            selected[witness]["lower_point_on_current_ballot"],
    } for witness in TARGET_WITNESSES]
    design = {
        "schema": DESIGN_SCHEMA,
        "run_id": RUN_ID,
        "champion": CHAMPION,
        "source_census": {
            "path": str(CENSUS_PATH.relative_to(REPO)),
            "file_sha256": CENSUS_SHA256,
            "packet_sha256": packet["packet_sha256"],
            "witness_set_sha256": packet["witness_set_sha256"],
            "review_marker_sha256": CENSUS_REVIEW_MARKER_SHA256,
        },
        "selection": {
            "rule": (
                "all reviewed current-surface S5 triggers at follow position "
                "3 or 4; no utility/outcome selection"
            ),
            "target_count": len(targets),
            "target_witnesses": targets,
            "target_witnesses_sha256": sha256_bytes(canonical_json(targets)),
            "required_follow_positions": [3, 4],
            "partner_already_acted_only": True,
        },
        "rng": {
            "domain_sha256": sha256_bytes(SEED_DOMAIN),
            "seeds_per_target": SEEDS_PER_TARGET,
            "total_decisions": len(targets) * SEEDS_PER_TARGET,
            "derivation": (
                "uint64_be(sha256(domain || canonical_json([witness,rep]))[:8])"
            ),
        },
        "estimand": (
            "frequency with which literal mc-s0-report-lcb's final returned "
            "action carries more card points than a legal action, on frozen "
            "late-seat DEV witnesses where an opponent owns the trick, the "
            "partner has already acted, and no legal action can win"
        ),
        "decision_rule": {
            "ranking_treatment_design_eligible": (
                "at least one final champion decision donates points while a "
                "strictly lower-point action is on the same root ballot"
            ),
            "ballot_diagnosis_only": (
                "donation occurs only where no lower-point ballot action exists"
            ),
            "no_current_reproduction": (
                "zero final champion donations across all frozen decisions"
            ),
            "continuous_counts_retained": True,
            "automatic_strength_claim": False,
        },
        "authority": {
            "exploration_only": True,
            "private_source_required": True,
            "raw_cards_published": False,
            "room_or_player_identifiers_published": False,
            "round_outcomes_read": False,
            "utilities_published": False,
            "strength_execution": False,
            "strength_claim": False,
            "labels_authorized": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    design["design_sha256"] = sha256_bytes(canonical_json(design))
    problems = design_problems(design)
    if problems:
        raise ReplayRefused("; ".join(problems))
    return design


def design_problems(design: object) -> list[str]:
    problems = _exact_fields(design, DESIGN_FIELDS, "design")
    if problems or not isinstance(design, Mapping):
        return problems
    problems += _exact_fields(
        design.get("source_census"), SOURCE_CENSUS_FIELDS, "source_census")
    problems += _exact_fields(
        design.get("selection"), SELECTION_FIELDS, "selection")
    problems += _exact_fields(design.get("rng"), RNG_FIELDS, "rng")
    problems += _exact_fields(
        design.get("authority"), AUTHORITY_FIELDS, "authority")
    selection = design.get("selection")
    if isinstance(selection, Mapping):
        targets = selection.get("target_witnesses")
        if not isinstance(targets, list):
            problems.append("target_witnesses is not a list")
        else:
            for index, target in enumerate(targets):
                problems += _exact_fields(
                    target, TARGET_FIELDS, f"target_witnesses[{index}]")
    decision_rule = design.get("decision_rule")
    problems += _exact_fields(
        decision_rule, DECISION_RULE_FIELDS, "decision_rule")
    copy_design = dict(design)
    claimed = copy_design.pop("design_sha256", None)
    if claimed != sha256_bytes(canonical_json(copy_design)):
        problems.append("design self-hash drift")
    authority = design.get("authority", {})
    if (not isinstance(authority, Mapping)
            or authority.get("exploration_only") is not True
            or authority.get("round_outcomes_read") is not False
            or authority.get("strength_execution") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_deployment") is not False):
        problems.append("design authority drift")
    return sorted(set(problems))


def _review_marker(path: Path, *, expected_git: str,
                   design: Mapping[str, object]) -> dict:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ReplayRefused("review record is unreadable") from exc
    matches = [line for line in lines if line.startswith(REVIEW_PREFIX)]
    if len(matches) != 1:
        raise ReplayRefused("exactly one raw S5 replay review marker is required")
    try:
        marker = json.loads(matches[0][len(REVIEW_PREFIX):])
    except (TypeError, ValueError) as exc:
        raise ReplayRefused("S5 replay review marker is invalid JSON") from exc
    expected = {
        "schema": "s5-final-champion-replay-review-v1",
        "git": expected_git,
        "script_sha256": sha256_file(SCRIPT),
        "census_artifact_sha256": CENSUS_SHA256,
        "design_sha256": design["design_sha256"],
        "target_count": len(TARGET_WITNESSES),
        "seeds_per_target": SEEDS_PER_TARGET,
        "total_decisions": len(TARGET_WITNESSES) * SEEDS_PER_TARGET,
        "final_champion_action_replayed": True,
        "partner_already_acted_only": True,
        "closed_public_schema": True,
        "one_diagnostic_execution_authorized": True,
        "strength_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }
    if marker != expected:
        raise ReplayRefused("S5 replay review marker differs from exact contract")
    return marker


def _census_review_marker(path: Path) -> dict:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ReplayRefused("review record is unreadable") from exc
    matches = [line for line in lines if line.startswith(CENSUS_REVIEW_PREFIX)]
    if len(matches) != 1:
        raise ReplayRefused("exactly one raw reviewed-census marker is required")
    if sha256_bytes((matches[0] + "\n").encode()) != CENSUS_REVIEW_MARKER_SHA256:
        raise ReplayRefused("reviewed-census marker byte identity drift")
    try:
        marker = json.loads(matches[0][len(CENSUS_REVIEW_PREFIX):])
    except (TypeError, ValueError) as exc:
        raise ReplayRefused("reviewed-census marker is invalid JSON") from exc
    expected = {
        "artifact_sha256": CENSUS_SHA256,
        "bot_follow_rows": 4363,
        "design_authorized": True,
        "lower_point_on_current_ballot": 57,
        "producer_git": "2351b3643a5c0231ad829b9d1cff6f96e50d035f",
        "production_deployment": False,
        "production_promotion": False,
        "reproduced_by_current_surface": 16,
        "rounds_replayed": 122,
        "schema": "s5-point-protection-census-review-v1",
        "score_free": True,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "strength_execution_authorized": False,
        "structural_triggers": 58,
        "training_authorized": False,
        "verdict": "PASS",
    }
    if marker != expected:
        raise ReplayRefused("reviewed-census marker semantic identity drift")
    return marker


def _partner_already_acted(rnd, seat: int) -> bool:
    if rnd.trick is None or len(rnd.trick.plays) not in (2, 3):
        return False
    teammate_plays = [play for play in rnd.trick.plays
                      if play.seat % 2 == seat % 2]
    return len(teammate_plays) == 1


def _actor_visible_trigger(rnd, seat: int,
                           legal_actions: Sequence[tuple[str, ...]], bot) -> bool:
    if not _partner_already_acted(rnd, seat):
        return False
    winner, incumbent_suit, incumbent_top = bot._current_winner(rnd)
    if winner % 2 == seat % 2:
        return False
    lead = list(rnd.trick.plays[0].cards)
    return not any(beats(
        list(action), lead, incumbent_suit, incumbent_top, rnd.ordering)[0]
        for action in legal_actions)


def collect_target_states(members, production_bot,
                          expected_rows: Mapping[str, Mapping[str, object]]):
    """Reconstruct targets privately; return no source/card data."""
    found: dict[str, tuple[object, int]] = {}
    for source_path, source_sha, source_size in members:
        CENSUS.require_source_exact(
            source_path, source_sha, source_size, "before target replay")
        try:
            rounds = group_rounds(str(source_path))
        except Exception as exc:
            raise ReplayRefused(
                f"private source cannot be grouped: {type(exc).__name__}") from exc
        for round_no, events in sorted(rounds.items()):
            if CENSUS._evaluation_tagged(events):
                raise ReplayRefused("evaluation-only round entered target replay")
            start = next((event for event in events
                          if event.get("e") == "round_start"), None)
            end = next((event for event in events
                        if event.get("e") == "round_end"), None)
            if start is None or end is None:
                continue
            players = start.get("players")
            if (not isinstance(players, list) or len(players) != 4
                    or any(not isinstance(player, Mapping) for player in players)):
                continue
            if any(str(player.get("name")) in EXCLUDE_PLAYERS
                   for player in players):
                continue
            try:
                rnd = rebuild_round(events)
            except Exception:
                continue
            if rnd is None:
                continue
            pending: list[tuple[str, int, dict, object]] = []
            completed: dict[str, tuple[object, int, dict]] = {}
            replay_error: BaseException | None = None
            for event_index, event in enumerate(events):
                if event.get("e") != "play":
                    continue
                seat, cards = event.get("seat"), event.get("cards")
                if (rnd.phase != "play" or isinstance(seat, bool)
                        or not isinstance(seat, int) or seat != rnd.turn
                        or not isinstance(cards, list)):
                    replay_error = ReplayRefused("private replay turn drift")
                    break
                witness = CENSUS.witness_digest(
                    source_sha, round_no, event_index, seat)
                if witness in expected_rows:
                    if event.get("bot") is not True or not rnd.trick.plays:
                        replay_error = ReplayRefused("target is not a bot follow")
                        break
                    try:
                        row = CENSUS.analyze_bot_follow(
                            rnd, seat, cards, event,
                            source_sha256=source_sha,
                            round_no=round_no,
                            event_index=event_index,
                            production_bot=production_bot,
                        )
                    except Exception as exc:
                        replay_error = exc
                        break
                    pending.append((witness, seat, row, copy.deepcopy(rnd)))
                previous_last = rnd.last_trick
                try:
                    rnd.play(seat, cards)
                except Exception as exc:
                    replay_error = exc
                    break
                if rnd.last_trick is not previous_last:
                    if rnd.last_trick is None or rnd.last_trick.winner is None:
                        replay_error = ReplayRefused("closed trick lacks winner")
                        break
                    for witness, pending_seat, row, state in pending:
                        final = CENSUS._finalize_row(
                            row, rnd.last_trick.winner, pending_seat)
                        if final != expected_rows[witness]:
                            replay_error = ReplayRefused(
                                "target row differs from reviewed census")
                            break
                        completed[witness] = (state, pending_seat, final)
                    pending.clear()
                    if replay_error is not None:
                        break
            if replay_error is not None or rnd.phase != "round_end" or pending:
                if completed:
                    raise ReplayRefused("target occurred in a failed round replay")
                continue
            for witness, (state, seat, _row) in completed.items():
                if witness in found:
                    raise ReplayRefused("target witness reconstructed twice")
                found[witness] = (state, seat)
        CENSUS.require_source_exact(
            source_path, source_sha, source_size, "after target replay")
    if tuple(sorted(found)) != TARGET_WITNESSES:
        raise ReplayRefused("not all target states were reconstructed")
    return found


def _decision_row(rnd, seat: int, witness: str, replicate: int,
                  bot_factory=make_bot) -> dict:
    seed = seed_for(witness, replicate)
    legal_actions, _ = CENSUS.legal_follow_actions(rnd, seat)
    bot = bot_factory(CHAMPION, seed=seed)
    if not _actor_visible_trigger(rnd, seat, legal_actions, bot):
        raise ReplayRefused("target no longer satisfies actor-visible trigger")
    candidates = [CENSUS.action_key(action) for action in bot._candidates(
        copy.deepcopy(rnd), seat)]
    if len(candidates) <= 1 or len(candidates) != len(set(candidates)):
        raise ReplayRefused("final-champion target ballot is uncontested/duplicated")
    legal = set(legal_actions)
    if any(candidate not in legal for candidate in candidates):
        raise ReplayRefused("final-champion ballot contains an illegal action")
    played = CENSUS.action_key(bot.decide_play(copy.deepcopy(rnd), seat))
    record = bot.last_decision_record
    if not isinstance(record, Mapping):
        raise ReplayRefused("contested champion decision lacks a final record")
    record_candidates = [CENSUS.action_key(action)
                         for action in record.get("candidates", [])]
    work = record.get("work")
    counters = record.get("sampler_counters", {}).get("delta", {})
    if (record.get("policy") != CHAMPION
            or record_candidates != candidates
            or CENSUS.action_key(record.get("played", [])) != played
            or not isinstance(work, Mapping)
            or not isinstance(counters, Mapping)
            or set(counters) != SAMPLER_FIELDS):
        raise ReplayRefused("final champion decision/work record drift")
    played_index = record.get("played_index")
    raw_winner = record.get("raw_winner_index")
    if (isinstance(played_index, bool) or not isinstance(played_index, int)
            or not 0 <= played_index < len(candidates)
            or candidates[played_index] != played
            or isinstance(raw_winner, bool) or not isinstance(raw_winner, int)
            or not 0 <= raw_winner < len(candidates)):
        raise ReplayRefused("final champion selected-index binding drift")
    selection_rollouts = work.get("selection_rollouts")
    report_rollouts = work.get("report_rollouts")
    total_rollouts = work.get("total_rollouts")
    work_complete = work.get("complete")
    expected_total = len(candidates) * 30 + 600
    if (isinstance(selection_rollouts, bool)
            or not isinstance(selection_rollouts, int)
            or isinstance(report_rollouts, bool)
            or not isinstance(report_rollouts, int)
            or isinstance(total_rollouts, bool)
            or not isinstance(total_rollouts, int)
            or selection_rollouts < 0 or report_rollouts < 0
            or total_rollouts != selection_rollouts + report_rollouts
            or total_rollouts > expected_total
            or not isinstance(work_complete, bool)
            or work_complete != (total_rollouts == expected_total)):
        raise ReplayRefused("live report-LCB exact work drift")
    legal_points = {action: total_points(action) for action in legal_actions}
    ballot_points = {action: legal_points[action] for action in candidates}
    played_points = legal_points[played]
    minimum_legal = min(legal_points.values())
    minimum_ballot = min(ballot_points.values())
    row = {
        "witness_sha256": witness,
        "replicate": replicate,
        "seed": seed,
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "follow_position": len(rnd.trick.plays) + 1,
        "candidate_count": len(candidates),
        "candidate0_card_points": ballot_points[candidates[0]],
        "chosen_card_points": played_points,
        "minimum_legal_card_points": minimum_legal,
        "minimum_ballot_card_points": minimum_ballot,
        "avoidable_legal_point_delta": played_points - minimum_legal,
        "avoidable_ballot_point_delta": played_points - minimum_ballot,
        "played_index": played_index,
        "raw_winner_index": raw_winner,
        "reason": record.get("reason"),
        "donated_points": played_points > minimum_legal,
        "lower_point_action_on_ballot": minimum_ballot < played_points,
        "selection_rollouts": selection_rollouts,
        "report_rollouts": report_rollouts,
        "total_rollouts": total_rollouts,
        "work_complete": work_complete,
        "sampler_counters": {key: int(counters[key])
                             for key in sorted(SAMPLER_FIELDS)},
    }
    problems = _exact_fields(row, DECISION_FIELDS, "decision")
    if problems or row["reason"] not in REASONS:
        raise ReplayRefused("; ".join(problems or ["decision reason drift"]))
    return row


def _witness_summary(witness: str, rows: Sequence[Mapping[str, object]]) -> dict:
    if len(rows) != SEEDS_PER_TARGET:
        raise ReplayRefused("witness does not have the full seed schedule")
    reasons = Counter(str(row["reason"]) for row in rows)
    chosen_points = Counter(str(row["chosen_card_points"]) for row in rows)
    return {
        "witness_sha256": witness,
        "role": rows[0]["role"],
        "follow_position": rows[0]["follow_position"],
        "decisions": len(rows),
        "donation_decisions": sum(bool(row["donated_points"]) for row in rows),
        "avoidable_on_ballot_decisions": sum(
            bool(row["lower_point_action_on_ballot"]) for row in rows),
        "override_decisions": sum(int(row["played_index"]) != 0 for row in rows),
        "candidate0_decisions": sum(int(row["played_index"]) == 0 for row in rows),
        "reason_counts": dict(sorted(reasons.items())),
        "chosen_point_histogram": dict(sorted(chosen_points.items())),
        "total_rollouts": sum(int(row["total_rollouts"]) for row in rows),
    }


def _summaries_and_stats(
        decisions: Sequence[Mapping[str, object]],
        design: Mapping[str, object]) -> tuple[list[dict], dict]:
    ordered = sorted(decisions,
                     key=lambda row: (row.get("witness_sha256", ""),
                                      row.get("replicate", -1)))
    if list(decisions) != ordered:
        raise ReplayRefused("diagnostic decisions are not canonically ordered")
    targets = {
        row["witness_sha256"]: row
        for row in design["selection"]["target_witnesses"]
    }
    if tuple(sorted(targets)) != TARGET_WITNESSES:
        raise ReplayRefused("design target population drift")
    summaries = []
    for witness in TARGET_WITNESSES:
        rows = [row for row in decisions
                if row.get("witness_sha256") == witness]
        if [row.get("replicate") for row in rows] != \
                list(range(SEEDS_PER_TARGET)):
            raise ReplayRefused("diagnostic seed schedule drift")
        target = targets[witness]
        for row in rows:
            problems = _exact_fields(row, DECISION_FIELDS, "decision")
            if problems:
                raise ReplayRefused("; ".join(problems))
            replicate = row["replicate"]
            if row["seed"] != seed_for(witness, replicate):
                raise ReplayRefused("diagnostic seed derivation drift")
            if (row["role"] != target["role"]
                    or row["follow_position"] != target["follow_position"]):
                raise ReplayRefused("diagnostic target stratum drift")
            if row["reason"] not in REASONS:
                raise ReplayRefused("diagnostic reason drift")
            integer_fields = (
                "candidate_count", "candidate0_card_points",
                "chosen_card_points", "minimum_legal_card_points",
                "minimum_ballot_card_points", "avoidable_legal_point_delta",
                "avoidable_ballot_point_delta", "played_index",
                "raw_winner_index", "selection_rollouts", "report_rollouts",
                "total_rollouts",
            )
            if any(isinstance(row[name], bool)
                   or not isinstance(row[name], int) for name in integer_fields):
                raise ReplayRefused("diagnostic integer field drift")
            if (not 2 <= row["candidate_count"] <= 14
                    or not 0 <= row["played_index"] < row["candidate_count"]
                    or not 0 <= row["raw_winner_index"] < row["candidate_count"]
                    or any(row[name] < 0 for name in (
                        "candidate0_card_points", "chosen_card_points",
                        "minimum_legal_card_points",
                        "minimum_ballot_card_points", "selection_rollouts",
                        "report_rollouts", "total_rollouts"))):
                raise ReplayRefused("diagnostic value range drift")
            if (row["avoidable_legal_point_delta"] !=
                    row["chosen_card_points"] -
                    row["minimum_legal_card_points"]
                    or row["avoidable_ballot_point_delta"] !=
                    row["chosen_card_points"] -
                    row["minimum_ballot_card_points"]
                    or row["donated_points"] is not
                    (row["avoidable_legal_point_delta"] > 0)
                    or row["lower_point_action_on_ballot"] is not
                    (row["avoidable_ballot_point_delta"] > 0)):
                raise ReplayRefused("diagnostic point classification drift")
            expected_total = row["candidate_count"] * 30 + 600
            if (row["total_rollouts"] != row["selection_rollouts"]
                    + row["report_rollouts"]
                    or row["selection_rollouts"] >
                    row["candidate_count"] * 30
                    or row["report_rollouts"] > 600
                    or not isinstance(row["work_complete"], bool)
                    or row["work_complete"] !=
                    (row["total_rollouts"] == expected_total)):
                raise ReplayRefused("diagnostic work accounting drift")
            counters = row["sampler_counters"]
            counter_problems = _exact_fields(
                counters, SAMPLER_FIELDS, "sampler_counters")
            if counter_problems or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    or value < 0 for value in counters.values()):
                raise ReplayRefused("diagnostic sampler counter drift")
        summaries.append(_witness_summary(witness, rows))
    stats = {
        "target_count": len(summaries),
        "seeds_per_target": SEEDS_PER_TARGET,
        "decisions": len(decisions),
        "donation_decisions": sum(row["donation_decisions"] for row in summaries),
        "donation_witnesses": sum(
            row["donation_decisions"] > 0 for row in summaries),
        "avoidable_on_ballot_decisions": sum(
            row["avoidable_on_ballot_decisions"] for row in summaries),
        "avoidable_on_ballot_witnesses": sum(
            row["avoidable_on_ballot_decisions"] > 0 for row in summaries),
        "override_decisions": sum(row["override_decisions"] for row in summaries),
        "candidate0_decisions": sum(row["candidate0_decisions"] for row in summaries),
        "total_rollouts": sum(row["total_rollouts"] for row in summaries),
        "complete_work_decisions": sum(
            bool(row["work_complete"]) for row in decisions),
        "incomplete_work_decisions": sum(
            not bool(row["work_complete"]) for row in decisions),
    }
    return summaries, stats


def build_result(design: dict, producer: dict, runtime: dict, source: dict,
                 decisions: list[dict]) -> dict:
    decisions = sorted(decisions,
                       key=lambda row: (row["witness_sha256"], row["replicate"]))
    if len(decisions) != len(TARGET_WITNESSES) * SEEDS_PER_TARGET:
        raise ReplayRefused("diagnostic decision count drift")
    summaries, stats = _summaries_and_stats(decisions, design)
    if stats["avoidable_on_ballot_decisions"]:
        decision = "S5_RANKING_TREATMENT_DESIGN_ELIGIBLE"
    elif stats["donation_decisions"]:
        decision = "S5_BALLOT_DIAGNOSIS_ONLY"
    else:
        decision = "S5_CURRENT_CHAMPION_NOT_REPRODUCED_ON_FROZEN_DEV"
    authority = dict(design["authority"])
    result = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "design": design,
        "producer": producer,
        "runtime": runtime,
        "source": source,
        "stats": stats,
        "witnesses": summaries,
        "decisions": decisions,
        "decision": decision,
        "authority": authority,
    }
    result["result_sha256"] = sha256_bytes(canonical_json(result))
    problems = result_problems(result, design)
    if problems:
        raise ReplayRefused("; ".join(problems))
    return result


def result_problems(result: object, design: Mapping[str, object]) -> list[str]:
    problems = _exact_fields(result, RESULT_FIELDS, "result")
    if problems or not isinstance(result, Mapping):
        return problems
    problems += _exact_fields(result.get("producer"), PRODUCER_FIELDS, "producer")
    problems += _exact_fields(result.get("runtime"), RUNTIME_FIELDS, "runtime")
    problems += _exact_fields(result.get("source"), SOURCE_FIELDS, "source")
    problems += _exact_fields(result.get("stats"), STATS_FIELDS, "stats")
    problems += _exact_fields(result.get("authority"), AUTHORITY_FIELDS, "authority")
    decisions = result.get("decisions")
    witnesses = result.get("witnesses")
    if not isinstance(decisions, list):
        problems.append("decisions are not a list")
        decisions = []
    if not isinstance(witnesses, list):
        problems.append("witness summaries are not a list")
        witnesses = []
    for index, row in enumerate(decisions):
        problems += _exact_fields(row, DECISION_FIELDS, f"decisions[{index}]")
        if isinstance(row, Mapping):
            problems += _exact_fields(
                row.get("sampler_counters"), SAMPLER_FIELDS,
                f"decisions[{index}].sampler_counters")
    for index, row in enumerate(witnesses):
        problems += _exact_fields(
            row, WITNESS_RESULT_FIELDS, f"witnesses[{index}]")
    if result.get("design") != design:
        problems.append("result design differs from frozen design")
    if result.get("authority") != design.get("authority"):
        problems.append("result authority differs from frozen design")
    try:
        expected_witnesses, expected_stats = _summaries_and_stats(
            decisions, design)
    except (KeyError, ReplayRefused, TypeError, ValueError) as exc:
        problems.append(f"result decision schedule invalid: {exc}")
    else:
        if witnesses != expected_witnesses:
            problems.append("witness summaries differ from decisions")
        if result.get("stats") != expected_stats:
            problems.append("result statistics differ from decisions")
        expected_decision = (
            "S5_RANKING_TREATMENT_DESIGN_ELIGIBLE"
            if expected_stats["avoidable_on_ballot_decisions"] else
            "S5_BALLOT_DIAGNOSIS_ONLY"
            if expected_stats["donation_decisions"] else
            "S5_CURRENT_CHAMPION_NOT_REPRODUCED_ON_FROZEN_DEV"
        )
        if result.get("decision") != expected_decision:
            problems.append("result decision differs from frozen rule")
    copy_result = dict(result)
    claimed = copy_result.pop("result_sha256", None)
    if claimed != sha256_bytes(canonical_json(copy_result)):
        problems.append("result self-hash drift")
    return sorted(set(problems))


def _runtime_payload(parent: Mapping[str, object]) -> dict:
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ReplayRefused("compiled engine is not active")
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "fast_engine": True,
        "fast_binary_sha256": sha256_file(fast._fast.__file__),
        "live_parent_sha256": sha256_bytes(canonical_json(parent)),
    }


def run(args) -> dict:
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise ReplayRefused("producer Git differs from expected Git")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise ReplayRefused("real diagnostic refuses a dirty tracked tree")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ReplayRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    design = build_design(Path(args.census))
    review_record = Path(args.review_record)
    _census_review_marker(review_record)
    _review_marker(review_record,
                   expected_git=args.expected_git, design=design)
    parent = LIVE_PARENT.require_portable_live_champion_parent()
    runtime = _runtime_payload(parent)
    producer = {
        "git": args.expected_git,
        "script_sha256": sha256_file(SCRIPT),
        "tree_dirty": False,
    }
    packet = _load_reviewed_census(Path(args.census))
    expected_rows = _target_rows(packet)
    members, source = CENSUS.source_population(
        Path(args.source_manifest).resolve(),
        Path(args.source_root).resolve(),
        SOURCE_MANIFEST_SHA256,
        smoke=False,
    )
    # Recompute the complete reviewed witness population first. This prevents
    # target-only reconstruction from silently changing the source semantics.
    _runtime_record, geometry_bot = CENSUS._runtime(smoke=False)
    totals, rejections, witnesses = CENSUS.census_sources(members, geometry_bot)
    if (dict(sorted(totals.items())) != packet.get("stats")
            or rejections != packet.get("rejection_examples")
            or witnesses != packet.get("witnesses")):
        raise ReplayRefused("full reviewed census does not reproduce")
    states = collect_target_states(members, geometry_bot, expected_rows)
    rows = []
    for witness in TARGET_WITNESSES:
        rnd, seat = states[witness]
        for replicate in range(SEEDS_PER_TARGET):
            rows.append(_decision_row(rnd, seat, witness, replicate))
    result = build_result(design, producer, runtime, source, rows)
    CENSUS.publish_exclusive(Path(args.out).resolve(), result)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    design = commands.add_parser("design")
    design.add_argument("--census", default=str(CENSUS_PATH))
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--census", default=str(CENSUS_PATH))
    run_parser.add_argument("--source-manifest", required=True)
    run_parser.add_argument("--source-root", required=True)
    run_parser.add_argument("--review-record", required=True)
    run_parser.add_argument("--expected-git", required=True)
    run_parser.add_argument("--out", required=True)
    verify = commands.add_parser("verify-result")
    verify.add_argument("--census", default=str(CENSUS_PATH))
    verify.add_argument("--result", required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "design":
        print(canonical_json(build_design(Path(args.census))).decode(), end="")
        return
    if args.command == "run":
        result = run(args)
        print(json.dumps({
            "status": result["decision"],
            "run_id": result["run_id"],
            "result_sha256": sha256_file(Path(args.out).resolve()),
            "decisions": result["stats"]["decisions"],
            "strength_claim": False,
        }, sort_keys=True))
        return
    design = build_design(Path(args.census))
    result = _load_object(Path(args.result).resolve())
    problems = result_problems(result, design)
    if problems:
        raise ReplayRefused("; ".join(problems))
    print(json.dumps({
        "status": "S5_FINAL_CHAMPION_REPLAY_RESULT_STRUCTURALLY_VERIFIED",
        "result_sha256": sha256_file(Path(args.result).resolve()),
        "strength_claim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ReplayRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
