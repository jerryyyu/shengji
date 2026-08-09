#!/usr/bin/env python3
"""Freeze the score-free S3c small-endgame curriculum.

S3b showed that entering the sampled perfect-information solver at four cards
can exceed a 250k-node world-session cap.  S3c does not relax that failed
recipe.  It first inventories naturally reached one-, two- and three-card
prefixes, then freezes a progressive information-set-legal contract.  This
module never evaluates an action value, publishes a game outcome, launches a
strength screen, trains a model or changes production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shengji.ai.endgame import exhaustive_legal_actions  # noqa: E402
from shengji.ai.heuristic import HeuristicBot             # noqa: E402
from shengji.engine.game import Game                      # noqa: E402


CENSUS_SCHEMA = "s3c-natural-prefix-census-v1"
PACKET_SCHEMA = "s3c-exact-root-curriculum-design-v1"
CENSUS_ID = "s3c-natural-prefix-census-173m-v1"
PACKET_ID = "s3c-exact-root-curriculum-v1"
HUMAN_MANIFEST_SHA256 = (
    "b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553"
)
BAND_SEED_STARTS = {1: 173_000_000, 2: 174_000_000, 3: 175_000_000}
SCAN_DEALS_PER_BAND = 4_096
ROWS_PER_OFFSET = 64
OFFSETS = (0, 1, 2, 3)
SAMPLER = "production-MCBot-information-set-sampler"
SOURCE_PATHS = {
    "script": "server/scripts/s3c_exact_root_design.py",
    "exact_solver": "server/shengji/ai/endgame.py",
    "heuristic": "server/shengji/ai/heuristic.py",
    "game": "server/shengji/engine/game.py",
    "round": "server/shengji/engine/round.py",
    "legal": "server/shengji/engine/legal.py",
    "combos": "server/shengji/engine/combos.py",
}


class S3CDesignError(RuntimeError):
    """The census or curriculum differs from its score-free contract."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise S3CDesignError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise S3CDesignError(f"JSON root is not an object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict]:
    try:
        rows = [json.loads(line) for line in path.read_text().splitlines()
                if line.strip()]
    except (OSError, ValueError) as exc:
        raise S3CDesignError(f"cannot read JSONL {path}: {exc}") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise S3CDesignError(f"non-object row in {path}")
    return rows


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    if dirty and not smoke:
        raise S3CDesignError("real S3c publication refuses a dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "promotable": not smoke,
        "script_sha256": sha256_file(SCRIPT),
    }


def source_identity() -> dict:
    result = {}
    for name, logical_path in SOURCE_PATHS.items():
        path = REPO / logical_path
        if not _regular_unlinked(path):
            raise S3CDesignError(f"source is not regular/unlinked: {logical_path}")
        result[name] = {
            "logical_path": logical_path,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return result


def _trick_snapshot(trick) -> dict | None:
    if trick is None:
        return None
    return {
        "leader": trick.leader,
        "plays": [{"seat": play.seat, "cards": sorted(play.cards)}
                  for play in trick.plays],
        "winner": trick.winner,
        "points": trick.points,
    }


def _round_digest(rnd) -> str:
    declaration = None
    if rnd.declaration is not None:
        declaration = {
            "seat": rnd.declaration.get("seat"),
            "cards": sorted(rnd.declaration.get("cards", [])),
            "strength": rnd.declaration.get("strength"),
        }
    payload = {
        "phase": rnd.phase,
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": bool(rnd.trump_is_nt),
        "turn": rnd.turn,
        "attacker_points_so_far": int(rnd.attacker_points),
        "kitty_bonus": int(rnd.kitty_bonus),
        "buried": sorted(rnd.buried),
        "hands": [sorted(hand) for hand in rnd.hands],
        "declaration": declaration,
        "history": [_trick_snapshot(trick) for trick in rnd.history],
        "trick": _trick_snapshot(rnd.trick),
        "last_trick_winner": rnd.last_trick_winner,
        "deck": sorted(rnd.deck),
    }
    return sha256_bytes(canonical_json(payload))


def _new_round(seed: int):
    game = Game(random.Random(seed))
    bots = [HeuristicBot() for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise S3CDesignError(f"deal {seed} has no banker")
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    return rnd, bots


def replay_prefix(seed: int, band: int, offset: int):
    """Return the natural decision at an exact trick-start hand-size band."""
    if band not in BAND_SEED_STARTS or offset not in OFFSETS:
        raise ValueError("band/offset outside S3c contract")
    rnd, bots = _new_round(seed)
    while rnd.phase == "play" and rnd.turn is not None:
        if (rnd.trick is not None and not rnd.trick.plays
                and len(set(len(hand) for hand in rnd.hands)) == 1
                and len(rnd.hands[0]) == band):
            for _ in range(offset):
                if rnd.phase != "play" or rnd.turn is None:
                    return None
                seat = rnd.turn
                rnd.play(seat, bots[seat].decide_play(rnd, seat))
            if rnd.phase != "play" or rnd.turn is None:
                return None
            if max(len(hand) for hand in rnd.hands) > band:
                raise S3CDesignError("natural prefix exceeded requested band")
            return rnd
        seat = rnd.turn
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return None


def prefix_row(seed: int, band: int, offset: int) -> dict | None:
    rnd = replay_prefix(seed, band, offset)
    if rnd is None or rnd.turn is None or rnd.trick is None:
        return None
    actions = exhaustive_legal_actions(rnd, rnd.turn, max_hand_cards=band)
    sizes = Counter(len(action) for action in actions)
    return {
        "state_id": f"s3c-b{band}-s{seed}-o{offset}",
        "deal_seed": seed,
        "max_hand_cards": band,
        "within_trick_offset": offset,
        "actor_seat": rnd.turn,
        "actor_role": "attacker" if rnd.is_attacker(rnd.turn) else "defender",
        "surface": "lead" if not rnd.trick.plays else "follow",
        "trick_index": len(rnd.history),
        "trick_play_count": len(rnd.trick.plays),
        "lead_size": (None if not rnd.trick.plays
                      else len(rnd.trick.plays[0].cards)),
        "hand_sizes": [len(hand) for hand in rnd.hands],
        "cards_remaining": sum(len(hand) for hand in rnd.hands),
        "legal_action_count": len(actions),
        "legal_action_size_counts": {
            str(size): count for size, count in sorted(sizes.items())
        },
        "state_sha256": _round_digest(rnd),
    }


def _band_summary(rows: list[dict]) -> dict:
    counts = sorted(row["legal_action_count"] for row in rows)
    return {
        "rows": len(rows),
        "by_offset": dict(sorted(Counter(
            str(row["within_trick_offset"]) for row in rows).items())),
        "by_surface": dict(sorted(Counter(
            row["surface"] for row in rows).items())),
        "by_role": dict(sorted(Counter(
            row["actor_role"] for row in rows).items())),
        "legal_action_count": {
            "min": counts[0],
            "max": counts[-1],
            "sum": sum(counts),
            "denominator": len(counts),
            "median_order_statistic": counts[(len(counts) - 1) // 2],
            "p95_order_statistic": counts[((len(counts) - 1) * 95) // 100],
        },
    }


def human_witness_appendix(corpus: Path, expected_manifest_sha256: str) -> dict:
    manifest_path = corpus / "manifest.json"
    if (expected_manifest_sha256 != HUMAN_MANIFEST_SHA256
            or not _regular_unlinked(manifest_path)
            or sha256_file(manifest_path) != HUMAN_MANIFEST_SHA256):
        raise S3CDesignError("human corpus manifest identity drift")
    manifest = _load_json(manifest_path)
    artifacts = {item.get("name"): item for item in manifest.get("artifacts", [])
                 if isinstance(item, dict)}
    play_info = artifacts.get("play_decisions.jsonl")
    play_path = corpus / "play_decisions.jsonl"
    if (not isinstance(play_info, dict) or not _regular_unlinked(play_path)
            or sha256_file(play_path) != play_info.get("sha256")):
        raise S3CDesignError("human play artifact identity drift")
    plays = _load_jsonl(play_path)
    selected = []
    counts: dict[int, Counter] = {band: Counter() for band in BAND_SEED_STARTS}
    deal_keys: dict[int, set[tuple]] = {band: set() for band in BAND_SEED_STARTS}
    for row in plays:
        remaining = row.get("cards_remaining")
        if (isinstance(remaining, bool) or not isinstance(remaining, int)
                or not 1 <= remaining <= 12):
            continue
        band = (remaining + 3) // 4
        key = (row.get("source"), row.get("round"), row.get("event_index"))
        selected.append((band, *key))
        counts[band][f"surface:{row.get('surface')}"] += 1
        counts[band][f"role:{row.get('role')}"] += 1
        counts[band]["rows"] += 1
        deal_keys[band].add((row.get("source"), row.get("round")))
    return {
        "manifest_sha256": HUMAN_MANIFEST_SHA256,
        "play_artifact_sha256": play_info["sha256"],
        "classification": (
            "ceil(total-cards-remaining/4); witness geometry only, not a "
            "proof of exact per-seat hand size after multi-card tricks"
        ),
        "by_equivalent_band": {
            str(band): {
                **dict(sorted(counts[band].items())),
                "source_rounds": len(deal_keys[band]),
            } for band in sorted(BAND_SEED_STARTS)
        },
        "witness_key_sha256": sha256_bytes(canonical_json(sorted(selected))),
        "raw_identifiers_published": False,
        "formal_selection_source": False,
        "use": "DESIGN witnesses and error analysis only",
    }


def build_census(corpus: Path, expected_manifest_sha256: str, *,
                 smoke: bool = False) -> dict:
    per_offset = 1 if smoke else ROWS_PER_OFFSET
    scan_limit = 256 if smoke else SCAN_DEALS_PER_BAND
    rows = []
    scan = {}
    for band, seed_start in sorted(BAND_SEED_STARTS.items()):
        needed = {offset: per_offset for offset in OFFSETS}
        skipped = 0
        seeds_scanned = 0
        band_rows = []
        for seed in range(seed_start, seed_start + scan_limit):
            seeds_scanned += 1
            offset = int.from_bytes(hashlib.sha256(
                f"{CENSUS_ID}:{band}:{seed}".encode()).digest()[:8], "big") % 4
            if needed[offset] == 0:
                continue
            row = prefix_row(seed, band, offset)
            if row is None:
                skipped += 1
                continue
            band_rows.append(row)
            needed[offset] -= 1
            if not any(needed.values()):
                break
        if any(needed.values()):
            raise S3CDesignError(
                f"band {band} underfilled after {seeds_scanned} deals: {needed}")
        rows.extend(band_rows)
        scan[str(band)] = {
            "seed_start": seed_start,
            "scan_cap": scan_limit,
            "seeds_scanned": seeds_scanned,
            "skipped_no_exact_band": skipped,
            "selection": (
                "hash-assigned offset, first qualifying seeds until exact "
                f"{per_offset}-per-offset quota"
            ),
            "summary": _band_summary(band_rows),
        }
    rows.sort(key=lambda row: row["state_id"])
    seeds = [row["deal_seed"] for row in rows]
    if len(seeds) != len(set(seeds)):
        raise S3CDesignError("census deals are not globally disjoint")
    census = {
        "schema": CENSUS_SCHEMA,
        "census_id": CENSUS_ID,
        "producer": producer_identity(smoke=smoke),
        "sources": source_identity(),
        "claim": (
            "natural-prefix supply and root-action geometry only; no action "
            "value, game outcome, strength, training or production evidence"
        ),
        "scan_contract": scan,
        "rows": rows,
        "human_witness_appendix": human_witness_appendix(
            corpus, expected_manifest_sha256),
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "action_values_computed": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "curriculum_packet_review_authorized": True,
            "solver_or_screen_launch_authorized": False,
        },
    }
    census["census_sha256"] = sha256_bytes(canonical_json(census))
    return census


def census_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("census full recomputation drift")
    authority = actual.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("outcomes_computed") is not False
            or authority.get("action_values_computed") is not False
            or authority.get("strength_claim") is not False
            or authority.get("training_authorized") is not False
            or authority.get("production_promotion") is not False
            or authority.get("solver_or_screen_launch_authorized") is not False):
        problems.append("census authority widened")
    return sorted(set(problems))


def validate_census(path: Path, expected_sha256: str) -> dict:
    if not _regular_unlinked(path) or sha256_file(path) != expected_sha256:
        raise S3CDesignError("census file identity drift")
    census = _load_json(path)
    authority = census.get("authority", {})
    rows = census.get("rows")
    producer = census.get("producer", {})
    expected_per_offset = (ROWS_PER_OFFSET
                           if producer.get("promotable") is True else 1)
    if (census.get("schema") != CENSUS_SCHEMA
            or census.get("census_id") != CENSUS_ID
            or not isinstance(rows, list)
            or len(rows) != 3 * 4 * expected_per_offset
            or len({row.get("deal_seed") for row in rows}) != len(rows)
            or authority.get("score_free") is not True
            or authority.get("outcomes_computed") is not False
            or authority.get("action_values_computed") is not False
            or authority.get("solver_or_screen_launch_authorized") is not False):
        raise S3CDesignError("census structure/authority drift")
    for band in BAND_SEED_STARTS:
        band_rows = [row for row in rows if row.get("max_hand_cards") == band]
        if (len(band_rows) != 4 * expected_per_offset
                or Counter(row.get("within_trick_offset") for row in band_rows)
                != Counter({offset: expected_per_offset
                            for offset in OFFSETS})):
            raise S3CDesignError(f"band {band} quota drift")
    return census


def build_packet(census_path: Path, expected_census_sha256: str, *,
                 smoke: bool = False) -> dict:
    census = validate_census(census_path, expected_census_sha256)
    if census.get("producer", {}).get("promotable") is not (not smoke):
        raise S3CDesignError("smoke/real census authority differs from packet")
    packet = {
        "schema": PACKET_SCHEMA,
        "packet_id": PACKET_ID,
        "producer": producer_identity(smoke=smoke),
        "parent": {
            "census_sha256": expected_census_sha256,
            "embedded_census_sha256": census["census_sha256"],
            "census_git": census["producer"]["git"],
            "human_manifest_sha256": HUMAN_MANIFEST_SHA256,
        },
        "objective": (
            "Establish sampled exact-root search on the smallest natural "
            "Shengji endgames before expanding its information-set and node "
            "budget, then use passing roots as privileged diagnostics and a "
            "possible bounded production continuation."
        ),
        "information_boundary": {
            "public_policy_observes_hidden_hands": False,
            "belief_sampler": SAMPLER,
            "exact_solver_runs_inside_each_accepted_determinized_world": True,
            "world_values_are_averaged_before_root_choice": True,
            "perfect_information_result_is_public_game_solution": False,
            "human_rows_are_design_witnesses_only": True,
            "formal_selection_uses_fresh_bot_generated_deals": True,
        },
        "curriculum": {
            "one_card": {
                "purpose": "mechanics_replay_and_capacity_only",
                "census_roots": 256,
                "reviewed_feasibility_roots": 64,
                "root_selection": (
                    "16 domain-hash-smallest census rows per within-trick "
                    "offset, frozen before solver work"),
                "worlds_per_root": 4,
                "max_nodes_per_world_session": 256,
                "utility_or_strength_gate": False,
                "required_outputs": [
                    "exact replay/state digest",
                    "complete legal root-action count",
                    "accepted-world and sampler refusal counts",
                    "exact nodes/cache hits and overflow counts",
                ],
                "pass_next_authority": (
                    "AUTHORIZE_TWO_CARD_MECHANISM_PACKET_REVIEW"),
            },
            "two_card": {
                "purpose": "first_nontrivial_action_selection_mechanism",
                "max_nodes_per_world_session": 10_000,
                "selection_worlds": 30,
                "report_worlds": 300,
                "matched_random_diversifier_required": True,
                "fresh_state_screen_required": True,
                "screen_estimands": [
                    "sampled-exact-choice minus live-champion-choice paired "
                    "acting-team signed level utility",
                    "sampled-exact-choice minus same-budget-random-choice "
                    "paired acting-team signed level utility",
                ],
                "screen_gate": (
                    "both state-clustered one-sided 95% lower bounds >0; "
                    "zero sampler refusal, exact refusal and node overflow"),
                "pass_next_authority": (
                    "AUTHORIZE_THREE_CARD_MECHANISM_PACKET_REVIEW"),
            },
            "three_card": {
                "purpose": "bounded_exact_root_candidate_and_teacher_target",
                "max_nodes_per_world_session": 100_000,
                "selection_worlds": 30,
                "report_worlds": 300,
                "matched_random_diversifier_required": True,
                "fresh_state_and_complete_round_screens_required": True,
                "state_screen_gate": (
                    "same two paired positive-LCB contrasts as two-card"),
                "complete_round_gate": (
                    "fresh 2,048-cluster paired screen versus exact live "
                    "champion and matched null; PASS opens a separately "
                    "reviewed 8,192-cluster confirmation packet only"),
                "pass_next_authority": (
                    "AUTHORIZE_FOUR_CARD_DESIGN_REVIEW_ONLY"),
            },
            "four_card": {
                "status": "CLOSED_BY_S3B_V2_CAPACITY_FAILURE",
                "old_max_nodes_per_world_session": 250_000,
                "retry_or_relaxed_cap_authorized": False,
                "reopen_condition": (
                    "three-card terminal strength PASS plus reviewed measured "
                    "complexity envelope and a new design"
                ),
            },
        },
        "shared_execution_contract": {
            "complete_legal_root_action_enumeration": True,
            "same_sampled_worlds_for_all_root_actions": True,
            "selection_and_report_worlds_disjoint": True,
            "production_champion": "mc-s0-report-lcb",
            "same_budget_null_required": True,
            "zero_sampler_refusal_and_zero_exact_overflow_required": True,
            "per_root_nodes_cache_hits_actions_and_worlds_required": True,
            "partial_root_or_world_dose_cannot_publish_a_metric": True,
            "state_clustered_acting_team_signed_level_utility": True,
            "complete_round_strength_required_before_policy_use": True,
            "exact_solver_source": census["sources"]["exact_solver"],
        },
        "human_witness_appendix": census["human_witness_appendix"],
        "execution_order": [
            "external review of this score-free contract",
            "implement and externally review one-card feasibility controller",
            "run one-card mechanics/capacity once without utility",
            "freeze/review two-card mechanism packet",
            "only a two-card PASS may freeze/review three-card work",
            "only a three-card state and full-game PASS may redesign four-card",
        ],
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "design_review_authorized": True,
            "one_card_controller_implementation_authorized": False,
            "solver_or_screen_launch_authorized": False,
            "two_or_three_card_work_authorized": False,
            "four_card_work_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("packet full recomputation drift")
    authority = actual.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("outcomes_computed") is not False
            or authority.get("one_card_controller_implementation_authorized")
            is not False
            or authority.get("solver_or_screen_launch_authorized") is not False
            or authority.get("two_or_three_card_work_authorized") is not False
            or authority.get("four_card_work_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False):
        problems.append("packet authority widened")
    return sorted(set(problems))


def publish_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise S3CDesignError("refusing existing final or partial")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    if not _regular_unlinked(path):
        raise S3CDesignError("published artifact is not regular/unlinked")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("census", "verify-census"):
        child = sub.add_parser(command)
        child.add_argument("--human-corpus", required=True)
        child.add_argument("--expected-human-manifest-sha256", required=True)
        child.add_argument("--out", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
    for command in ("freeze-packet", "verify-packet"):
        child = sub.add_parser(command)
        child.add_argument("--census", required=True)
        child.add_argument("--expected-census-sha256", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise S3CDesignError("Git differs from expected identity")
    if args.command in ("census", "verify-census"):
        expected = build_census(
            Path(args.human_corpus), args.expected_human_manifest_sha256,
            smoke=args.smoke)
        path = Path(args.out)
        if args.command == "census":
            publish_exclusive(path, expected)
        else:
            problems = census_problems(_load_json(path), expected)
            if problems:
                raise S3CDesignError("; ".join(problems))
        print(json.dumps({
            "status": ("FROZEN_FOR_DESIGN" if args.command == "census"
                       else "VERIFIED_SCORE_FREE"),
            "path": str(path),
            "sha256": sha256_file(path),
            "rows": len(expected["rows"]),
            "outcomes_computed": False,
        }, sort_keys=True))
        return
    packet = build_packet(
        Path(args.census), args.expected_census_sha256, smoke=args.smoke)
    path = Path(args.packet)
    if args.command == "freeze-packet":
        publish_exclusive(path, packet)
    else:
        problems = packet_problems(_load_json(path), packet)
        if problems:
            raise S3CDesignError("; ".join(problems))
    print(json.dumps({
        "status": ("FROZEN_FOR_DESIGN_REVIEW"
                   if args.command == "freeze-packet"
                   else "VERIFIED_FOR_DESIGN_REVIEW"),
        "path": str(path),
        "sha256": sha256_file(path),
        "solver_or_screen_launch_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError,
            S3CDesignError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
