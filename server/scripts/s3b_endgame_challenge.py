"""Frozen mechanics gate for the sampled exact-endgame (S3b) core.

This is deliberately *not* a strength runner.  It replays a small tracked set
of real late-round states, draws named information-set-legal determinizations,
and scores every submitted legal root action with one shared exact session per
world.  A terminal PASS proves only that the bounded mechanism completed under
its frozen work contract:

    exact perfect-information oracle inside a sampled determinization;
    not exact imperfect-information Shengji.

No full-game opponent/reference is accepted or named here.  A strength duel is
a later child of terminal S0 and must use a separate protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.endgame import (ExactEndgameBudgetExceeded,             # noqa: E402
                                ExactEndgameRefusal,
                                exhaustive_legal_actions)
from shengji.ai.heuristic import HeuristicBot                           # noqa: E402
from shengji.ai.mcbot import (DeterminizationContractError, MCBot)      # noqa: E402
from shengji.ai.memory import Memory                                    # noqa: E402
from shengji.engine.game import Game                                    # noqa: E402
from shengji.engine.combos import decompose                             # noqa: E402


RUN_SCHEMA = "s3b-exact-endgame-challenge-shard-v2"
AGGREGATE_SCHEMA = "s3b-exact-endgame-challenge-aggregate-v2"
STATE_SCHEMA = "s3b-exact-endgame-challenge-states-v2"
CLAIM = ("exact perfect-information oracle inside a sampled "
         "determinization; not exact imperfect-information Shengji")
MAX_HAND_CARDS = 4
MAX_NODES_PER_WORLD = 250_000
SHARD_COUNT = 4
WORLDS_PER_STATE = 4
ASSIGNMENT = "sorted_state_id_then_interleaved_position"
DEFAULT_STATE_ASSET = str(
    Path(__file__).parents[1] / "tests" / "data" /
    "s3b_endgame_challenge.v2.json")
# Byte identity of the tracked v2 asset, including the independently frozen
# candidate-value oracle for every named world.
EXPECTED_STATE_ASSET_SHA256 = (
    "02beac0534f84b3b4a43e7dfca83398c7073659cf0cda419ad9974af80153301")
SAMPLER_FLAGS = ("SHENGJI_WEIGHTED_SPLITS", "SHENGJI_UNIFORM_DEAL",
                 "SHENGJI_PHYSICAL_FILLS")
EXACT_FIELDS = ("attempts", "successes", "refusals", "budget_overflows",
                "sessions", "nodes", "cache_hits")


class ChallengeProtocolError(RuntimeError):
    """The mechanics artifact cannot support the claim it was asked to make."""


class ChallengeExactBot(MCBot):
    """Feature-on only inside this mechanics runner; never registry-visible."""

    EXACT_ENDGAME = True
    EXACT_ENDGAME_MAX_CARDS = MAX_HAND_CARDS
    EXACT_ENDGAME_MAX_NODES = MAX_NODES_PER_WORLD


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     default=list).encode()
    return hashlib.sha256(raw).hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def protocol_contract() -> dict:
    """The immutable claim/work boundary copied into every artifact."""
    return {
        "claim": CLAIM,
        "purpose": "bounded_mechanics_challenge",
        "strength_evidence": False,
        "promotion": False,
        "full_game_reference": None,
        "max_hand_cards": MAX_HAND_CARDS,
        "node_cap_kind": "cumulative_uncached_nonterminal_expansions_per_world_session",
        "max_nodes_per_world_session": MAX_NODES_PER_WORLD,
        "required_exact_refusals": 0,
        "required_budget_overflows": 0,
        "worlds_per_state": WORLDS_PER_STATE,
        "shard_count": SHARD_COUNT,
        "assignment": ASSIGNMENT,
        "sampler": "production_MCBot_information_set_sampler",
        "candidate_source": "exhaustive_submitted_legal_actions_inside_bound",
        "candidate_value_oracle": (
            "byte_pinned_final_attacker_points_per_candidate_and_world"),
    }


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


def round_snapshot(rnd) -> dict:
    """Canonical exact state used by the frozen state digest."""
    declaration = None
    if rnd.declaration is not None:
        declaration = {
            "seat": rnd.declaration.get("seat"),
            "cards": sorted(rnd.declaration.get("cards", [])),
            "strength": rnd.declaration.get("strength"),
        }
    return {
        "phase": rnd.phase,
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": bool(rnd.trump_is_nt),
        "turn": rnd.turn,
        "attacker_points": int(rnd.attacker_points),
        "kitty_bonus": int(rnd.kitty_bonus),
        "buried": sorted(rnd.buried),
        "hands": [sorted(hand) for hand in rnd.hands],
        "declaration": declaration,
        "history": [_trick_snapshot(trick) for trick in rnd.history],
        "trick": _trick_snapshot(rnd.trick),
        "last_trick_winner": rnd.last_trick_winner,
        "deck": sorted(rnd.deck),
    }


def replay_state(spec: dict):
    """Replay one real round to its named <=4-card decision."""
    game = Game(random.Random(spec["deal_seed"]))
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
        raise ChallengeProtocolError(f"{spec['state_id']}: replay has no banker")
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    while rnd.phase == "play" and max(len(hand) for hand in rnd.hands) > \
            MAX_HAND_CARDS:
        seat = rnd.turn
        if seat is None:
            raise ChallengeProtocolError(f"{spec['state_id']}: replay lost turn")
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    for _ in range(spec["late_offset"]):
        if rnd.phase != "play" or rnd.turn is None:
            raise ChallengeProtocolError(
                f"{spec['state_id']}: late offset crossed round end")
        rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    largest = max((len(hand) for hand in rnd.hands), default=0)
    if rnd.phase != "play" or rnd.turn is None or not 1 <= largest <= \
            MAX_HAND_CARDS:
        raise ChallengeProtocolError(
            f"{spec['state_id']}: replay outside exact scope, "
            f"phase={rnd.phase}, turn={rnd.turn}, largest={largest}")
    return rnd


def world_snapshot(state_id: str, world_seed: int, sampled: dict,
                   buried: list[str]) -> dict:
    return {
        "state_id": state_id,
        "world_seed": world_seed,
        "sampled_hands": {str(seat): sorted(cards)
                          for seat, cards in sorted(sampled.items())},
        "buried": sorted(buried),
    }


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def load_state_asset(path: str, expected_sha256: str) -> tuple[dict, str]:
    """Load only the one byte-pinned challenge population."""
    if expected_sha256 != EXPECTED_STATE_ASSET_SHA256:
        raise ChallengeProtocolError(
            "expected state asset SHA-256 differs from the frozen protocol")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ChallengeProtocolError(
            f"state asset byte hash mismatch: expected {expected_sha256}, "
            f"actual {actual}")
    try:
        with open(path) as fh:
            asset = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ChallengeProtocolError(f"cannot load state asset: {exc}") from exc
    problems = asset_problems(asset)
    if problems:
        raise ChallengeProtocolError(
            "state asset contract drift:\n  - " + "\n  - ".join(problems))
    return asset, actual


def asset_problems(asset: dict) -> list[str]:
    problems = []
    if asset.get("asset_id") != "s3b-exact-endgame-mechanics-v2":
        problems.append("state asset id")
    if asset.get("schema") != STATE_SCHEMA:
        problems.append("state schema")
    if asset.get("protocol") != protocol_contract():
        problems.append("embedded protocol contract")
    states = asset.get("states")
    if not isinstance(states, list) or len(states) != SHARD_COUNT:
        problems.append("state count must equal frozen shard count")
        return problems
    ids = [state.get("state_id") for state in states]
    if (any(not isinstance(value, str) or not value for value in ids)
            or ids != sorted(ids) or len(set(ids)) != len(ids)):
        problems.append("state ids must be unique and sorted")
    all_world_seeds = []
    for state in states:
        sid = state.get("state_id", "<missing>")
        if not isinstance(state.get("deal_seed"), int):
            problems.append(f"{sid}: deal seed")
        if state.get("late_offset") not in range(4):
            problems.append(f"{sid}: late offset")
        if not _is_sha256(state.get("expected_state_sha256")):
            problems.append(f"{sid}: expected state digest")
        if not _is_sha256(state.get("expected_candidates_sha256")):
            problems.append(f"{sid}: expected candidate digest")
        if not isinstance(state.get("expected_candidate_count"), int) \
                or state.get("expected_candidate_count", 0) < 1:
            problems.append(f"{sid}: expected candidate count")
        worlds = state.get("worlds")
        if not isinstance(worlds, list) or len(worlds) != WORLDS_PER_STATE:
            problems.append(f"{sid}: world count")
            continue
        seeds = [world.get("world_seed") for world in worlds]
        if any(not isinstance(seed, int) for seed in seeds) \
                or len(set(seeds)) != len(seeds):
            problems.append(f"{sid}: world seeds")
        all_world_seeds.extend(seeds)
        for world in worlds:
            if not _is_sha256(world.get("expected_world_sha256")):
                problems.append(f"{sid}: expected world digest")
            points = world.get("expected_attacker_points")
            if (not isinstance(points, list)
                    or len(points) != state.get("expected_candidate_count")
                    or any(isinstance(value, bool) or not isinstance(value, int)
                           or value < 0 for value in points)):
                problems.append(f"{sid}: expected candidate values")
            elif (not _is_sha256(
                    world.get("expected_attacker_points_sha256"))
                  or stable_digest(points) !=
                    world.get("expected_attacker_points_sha256")):
                problems.append(f"{sid}: expected candidate-value digest")
    if len(set(all_world_seeds)) != len(all_world_seeds):
        problems.append("world seeds must be globally unique")
    return sorted(set(problems))


def assigned_states(asset: dict, shard_index: int,
                    shard_count: int) -> list[dict]:
    if shard_count != SHARD_COUNT:
        raise ChallengeProtocolError(
            f"shard count {shard_count} differs from frozen {SHARD_COUNT}")
    if not 0 <= shard_index < shard_count:
        raise ChallengeProtocolError("shard index must satisfy 0 <= i < count")
    states = sorted(asset["states"], key=lambda state: state["state_id"])
    assigned = states[shard_index::shard_count]
    if len(assigned) != 1:
        raise ChallengeProtocolError(
            f"shard {shard_index} must own exactly one state, got {len(assigned)}")
    return assigned


def source_digests(asset_path: str) -> dict[str, str]:
    from shengji.engine import fast

    root = Path(__file__).parents[1]
    paths = {
        "runner": Path(__file__),
        "state_asset": Path(asset_path),
        "exact_solver": root / "shengji" / "ai" / "endgame.py",
        "mcbot": root / "shengji" / "ai" / "mcbot.py",
        "memory": root / "shengji" / "ai" / "memory.py",
        "heuristic": root / "shengji" / "ai" / "heuristic.py",
        "game": root / "shengji" / "engine" / "game.py",
        "round": root / "shengji" / "engine" / "round.py",
        "legal": root / "shengji" / "engine" / "legal.py",
        "combos": root / "shengji" / "engine" / "combos.py",
        "cards": root / "shengji" / "engine" / "cards.py",
        "fast_router": Path(fast.__file__),
        "compiled_engine": Path(fast._fast.__file__),
    }
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def runtime_contract(asset_path: str) -> dict:
    """Refuse anything except the clean compiled strict mechanics runtime."""
    if os.environ.get("SHENGJI_FAST") != "1":
        raise ChallengeProtocolError("set SHENGJI_FAST=1")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ChallengeProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ChallengeProtocolError(
            f"experimental sampler flags are forbidden: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ChallengeProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty:
        raise ChallengeProtocolError("S3b challenge refuses a dirty tree")
    return {
        "git_sha": git_output("rev-parse", "HEAD"),
        "tree_clean": True,
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "source_sha256": source_digests(asset_path),
    }


def ensure_output_available(path: str) -> None:
    if not path:
        raise ChallengeProtocolError("--out is required")
    if os.path.exists(path) or os.path.exists(path + ".partial"):
        raise ChallengeProtocolError(f"refusing to overwrite {path}")


def write_exclusive_atomic(path: str, payload: dict) -> None:
    """Publish complete bytes atomically without ever replacing a final file."""
    ensure_output_available(path)
    partial = path + ".partial"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    linked = False
    try:
        with open(partial, "x") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        # link(2), unlike os.replace, is atomic AND refuses an existing target.
        os.link(partial, path)
        linked = True
        os.unlink(partial)
    except Exception:
        if not linked and os.path.exists(partial):
            os.unlink(partial)
        raise


def exact_snapshot(bot: MCBot) -> dict[str, int]:
    return {
        "attempts": int(bot.exact_endgame_attempts),
        "successes": int(bot.exact_endgame_calls),
        "refusals": int(bot.exact_endgame_refusals),
        "budget_overflows": int(bot.exact_endgame_budget_exceeded),
        "sessions": int(bot.exact_endgame_sessions),
        "nodes": int(bot.exact_endgame_nodes),
        "cache_hits": int(bot.exact_endgame_cache_hits),
    }


def sampler_snapshot(bot: MCBot) -> dict[str, int]:
    return {name: int(getattr(bot, name)) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds")}


def world_problems(record: dict) -> list[str]:
    problems = list(record.get("problems", []))
    candidate_count = record.get("candidate_count", 0)
    expected_points = record.get("expected_attacker_points")
    expected_points_sha = record.get("expected_attacker_points_sha256")
    values = record.get("candidate_values", [])
    exact = record.get("exact", {})
    sampler = record.get("sampler", {})
    session = record.get("session", {})
    if sampler != {"sample_attempts": 1, "accepted_worlds": 1,
                   "failed_worlds": 0, "rejected_worlds": 0,
                   "impossible_worlds": 0}:
        problems.append("sampler did not produce one strict accepted world")
    if len(values) != candidate_count:
        problems.append("candidate-world work incomplete")
    actual_points = [value.get("attacker_points") for value in values
                     if isinstance(value, dict)]
    if (not isinstance(expected_points, list)
            or len(expected_points) != candidate_count
            or any(isinstance(value, bool) or not isinstance(value, int)
                   for value in expected_points)
            or not _is_sha256(expected_points_sha)
            or stable_digest(expected_points) != expected_points_sha):
        problems.append("frozen candidate-value expectation malformed")
    elif actual_points != expected_points:
        problems.append("candidate attacker-points differ from frozen oracle")
    if exact.get("attempts") != candidate_count:
        problems.append("exact attempts differ from candidate-world work")
    if exact.get("successes") != candidate_count:
        problems.append("exact successes differ from candidate-world work")
    if exact.get("refusals") != 0:
        problems.append("exact refusal")
    if exact.get("budget_overflows") != 0:
        problems.append("exact budget overflow")
    if exact.get("sessions") != 1:
        problems.append("world did not own exactly one exact session")
    if session.get("frontiers") != candidate_count:
        problems.append("session frontier count differs from candidate work")
    if session.get("max_hand_cards") != MAX_HAND_CARDS:
        problems.append("session hand-card scope drift")
    if session.get("max_nodes") != MAX_NODES_PER_WORLD:
        problems.append("session cumulative node cap drift")
    if session.get("nodes", MAX_NODES_PER_WORLD + 1) > MAX_NODES_PER_WORLD:
        problems.append("session exceeded cumulative node cap")
    if exact.get("nodes") != session.get("nodes"):
        problems.append("exact/session node counters disagree")
    if exact.get("cache_hits") != session.get("cache_hits"):
        problems.append("exact/session cache-hit counters disagree")
    return sorted(set(problems))


def run_world(rnd, state: dict, world: dict,
              candidates: list[list[str]]) -> dict:
    bot = ChallengeExactBot(seed=world["world_seed"])
    seat = rnd.turn
    assert seat is not None
    memory = Memory(rnd, seat, own_kitty=True)
    sampled_result = bot._sample_hands(rnd, seat, memory)
    record = {
        "world_seed": world["world_seed"],
        "expected_world_sha256": world["expected_world_sha256"],
        "expected_attacker_points": list(world["expected_attacker_points"]),
        "expected_attacker_points_sha256":
            world["expected_attacker_points_sha256"],
        "candidate_count": len(candidates),
        "candidate_values": [],
        "problems": [],
    }
    if sampled_result is None:
        record["sampler"] = sampler_snapshot(bot)
        record["exact"] = exact_snapshot(bot)
        record["session"] = {
            "frontiers": 0, "nodes": 0, "cache_hits": 0,
            "max_hand_cards": MAX_HAND_CARDS,
            "max_nodes": MAX_NODES_PER_WORLD}
        record["problems"].append("determinization sampler refused world")
        record["problems"] = world_problems(record)
        return record
    sampled, buried = sampled_result
    snapshot = world_snapshot(
        state["state_id"], world["world_seed"], sampled, buried)
    record["world_sha256"] = stable_digest(snapshot)
    if record["world_sha256"] != world["expected_world_sha256"]:
        record["sampler"] = sampler_snapshot(bot)
        record["exact"] = exact_snapshot(bot)
        record["session"] = {
            "frontiers": 0, "nodes": 0, "cache_hits": 0,
            "max_hand_cards": MAX_HAND_CARDS,
            "max_nodes": MAX_NODES_PER_WORLD}
        record["problems"].append("determinized world digest drift")
        record["problems"] = world_problems(record)
        return record

    session = bot._new_exact_world_session(rnd, buried)
    assert session is not None
    for candidate in candidates:
        try:
            value = bot._rollout(
                rnd, seat, sampled, buried, candidate,
                exact_session=session)
        except ExactEndgameBudgetExceeded as exc:
            record["problems"].append(
                f"exact budget overflow: nodes={exc.nodes}, "
                f"cache_hits={exc.cache_hits}")
            break
        except (ExactEndgameRefusal, DeterminizationContractError) as exc:
            record["problems"].append(
                f"exact/determinization refusal: {type(exc).__name__}: {exc}")
            break
        record["candidate_values"].append({
            "cards": list(candidate),
            "attacker_points": int(value),
        })
    record["sampler"] = sampler_snapshot(bot)
    record["exact"] = exact_snapshot(bot)
    record["session"] = {
        "frontiers": int(session.frontiers),
        "nodes": int(session.nodes),
        "cache_hits": int(session.cache_hits),
        "max_hand_cards": int(session.solver.max_hand_cards),
        "max_nodes": int(session.solver.max_nodes),
    }
    record["candidate_values_sha256"] = stable_digest(
        record["candidate_values"])
    record["problems"] = world_problems(record)
    return record


def run_state(state: dict) -> dict:
    rnd = replay_state(state)
    snapshot = round_snapshot(rnd)
    state_sha = stable_digest(snapshot)
    candidates = exhaustive_legal_actions(
        rnd, rnd.turn, max_hand_cards=MAX_HAND_CARDS)
    candidate_sha = stable_digest(candidates)
    problems = []
    tags = set(state.get("tags", []))
    observed_tags = {
        "attacker" if rnd.is_attacker(rnd.turn) else "defender",
        "lead" if not rnd.trick.plays else "follow",
    }
    hand = rnd.hands[rnd.turn]
    if any(count >= 2 for count in Counter(hand).values()):
        observed_tags.update({"duplicate-cards", "pair"})
    if any(len(candidate) > 1 for candidate in candidates):
        observed_tags.add("multi-card-submissions")
    if any(rnd.ordering.is_trump(card) for card in hand):
        observed_tags.add("trump")
    if rnd.trick.plays and len(rnd.trick.plays[0].cards) == 2:
        observed_tags.add("pair-lead")
    if not rnd.trick.plays and any(
            len(decompose(candidate, rnd.ordering).components) > 1
            for candidate in candidates):
        observed_tags.add("attempted-throws")
    checked_tags = {"attacker", "defender", "lead", "follow",
                    "duplicate-cards", "pair", "multi-card-submissions",
                    "trump", "pair-lead", "attempted-throws"}
    missing_tags = (tags & checked_tags) - observed_tags
    if missing_tags:
        problems.append(f"mechanics tag drift: {sorted(missing_tags)}")
    if state_sha != state["expected_state_sha256"]:
        problems.append("resolved state digest drift")
    if candidate_sha != state["expected_candidates_sha256"]:
        problems.append("candidate digest drift")
    if len(candidates) != state["expected_candidate_count"]:
        problems.append("candidate count drift")
    if problems:
        return {
            "state_id": state["state_id"], "deal_seed": state["deal_seed"],
            "late_offset": state["late_offset"],
            "state_sha256": state_sha,
            "candidate_sha256": candidate_sha,
            "candidate_count": len(candidates), "worlds": [],
            "problems": problems,
        }
    worlds = [run_world(rnd, state, world, candidates)
              for world in state["worlds"]]
    for world in worlds:
        problems.extend(f"world {world['world_seed']}: {problem}"
                        for problem in world["problems"])
    return {
        "state_id": state["state_id"],
        "deal_seed": state["deal_seed"],
        "late_offset": state["late_offset"],
        "tags": list(state.get("tags", [])),
        "state_sha256": state_sha,
        "candidate_sha256": candidate_sha,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "worlds": worlds,
        "problems": sorted(set(problems)),
    }


def summarize_records(records: list[dict]) -> dict:
    exact = {field: 0 for field in EXACT_FIELDS}
    worlds = candidate_planned = candidate_completed = 0
    nodes_by_session = []
    problems = []
    for state in records:
        problems.extend(f"{state.get('state_id')}: {problem}"
                        for problem in state.get("problems", []))
        for world in state.get("worlds", []):
            worlds += 1
            candidate_planned += int(world.get("candidate_count", 0))
            candidate_completed += len(world.get("candidate_values", []))
            for field in EXACT_FIELDS:
                exact[field] += int(world.get("exact", {}).get(field, 0))
            nodes_by_session.append(int(world.get("session", {}).get("nodes", 0)))
    work = {
        "states": len(records),
        "worlds": worlds,
        "candidate_world_work_planned": candidate_planned,
        "candidate_world_work_completed": candidate_completed,
        "max_session_nodes": max(nodes_by_session, default=0),
    }
    if exact["refusals"]:
        problems.append("aggregate exact refusals are nonzero")
    if exact["budget_overflows"]:
        problems.append("aggregate exact budget overflows are nonzero")
    if exact["sessions"] != worlds:
        problems.append("aggregate exact sessions differ from worlds")
    if exact["attempts"] != candidate_planned:
        problems.append("aggregate exact attempts differ from candidate-world work")
    if exact["successes"] != candidate_planned:
        problems.append("aggregate exact successes differ from candidate-world work")
    if candidate_completed != candidate_planned:
        problems.append("aggregate candidate-world work incomplete")
    if work["max_session_nodes"] > MAX_NODES_PER_WORLD:
        problems.append("aggregate includes an over-cap session")
    return {"exact": exact, "work": work,
            "problems": sorted(set(problems))}


def build_shard_payload(asset: dict, asset_sha: str, runtime: dict,
                        shard_index: int, records: list[dict]) -> dict:
    summary = summarize_records(records)
    assigned = assigned_states(asset, shard_index, SHARD_COUNT)
    expected_ids = [state["state_id"] for state in assigned]
    problems = list(summary["problems"])
    if [record.get("state_id") for record in records] != expected_ids:
        problems.append("shard state coverage differs from assignment")
    shard_pass = not problems
    return {
        "schema": RUN_SCHEMA,
        "status": "SHARD_PASS" if shard_pass else "HOLD",
        "shard_pass": shard_pass,
        "challenge_pass": False,
        "protocol": protocol_contract(),
        "state_asset": {"schema": STATE_SCHEMA, "sha256": asset_sha},
        "runtime": runtime,
        "shard": {
            "index": shard_index,
            "count": SHARD_COUNT,
            "assignment": ASSIGNMENT,
            "state_ids": expected_ids,
            "state_seeds": [state["deal_seed"] for state in assigned],
            "world_seeds": [world["world_seed"] for state in assigned
                            for world in state["worlds"]],
        },
        "records": records,
        "records_sha256": stable_digest(records),
        "exact": summary["exact"],
        "work": summary["work"],
        "problems": sorted(set(problems)),
    }


def runtime_compatibility(runtime: dict) -> dict:
    """Hosts may differ; executable bytes and strict semantics may not."""
    return {key: value for key, value in runtime.items() if key != "host"}


def state_record_problems(record: dict, spec: dict) -> list[str]:
    """Re-derive every frozen state/world binding from a shard record."""
    problems = []
    fixed = {
        "state_id": spec["state_id"],
        "deal_seed": spec["deal_seed"],
        "late_offset": spec["late_offset"],
        "tags": spec.get("tags", []),
        "state_sha256": spec["expected_state_sha256"],
        "candidate_sha256": spec["expected_candidates_sha256"],
        "candidate_count": spec["expected_candidate_count"],
    }
    for key, value in fixed.items():
        if record.get(key) != value:
            problems.append(f"state record {key}")
    candidates = record.get("candidates", [])
    if (not isinstance(candidates, list)
            or len(candidates) != spec["expected_candidate_count"]
            or stable_digest(candidates) != spec["expected_candidates_sha256"]):
        problems.append("state record candidate bytes")
    worlds = record.get("worlds", [])
    if not isinstance(worlds, list) or len(worlds) != WORLDS_PER_STATE:
        problems.append("state record world count")
        return problems
    expected_worlds = spec["worlds"]
    for index, (world, expected) in enumerate(zip(worlds, expected_worlds)):
        prefix = f"world {index}"
        if world.get("world_seed") != expected["world_seed"]:
            problems.append(f"{prefix} seed")
        if world.get("expected_world_sha256") != \
                expected["expected_world_sha256"]:
            problems.append(f"{prefix} expected digest")
        if world.get("expected_attacker_points") != \
                expected["expected_attacker_points"]:
            problems.append(f"{prefix} expected candidate values")
        if world.get("expected_attacker_points_sha256") != \
                expected["expected_attacker_points_sha256"]:
            problems.append(f"{prefix} expected candidate-value digest")
        if world.get("world_sha256") != expected["expected_world_sha256"]:
            problems.append(f"{prefix} resolved digest")
        if world.get("candidate_count") != spec["expected_candidate_count"]:
            problems.append(f"{prefix} candidate count")
        values = world.get("candidate_values", [])
        if not isinstance(values, list):
            problems.append(f"{prefix} candidate values")
            values = []
        else:
            cards = [value.get("cards") for value in values
                     if isinstance(value, dict)]
            if len(cards) != len(values) or cards != candidates[:len(values)]:
                problems.append(f"{prefix} candidate order")
            if any(not isinstance(value.get("attacker_points"), int)
                   for value in values if isinstance(value, dict)):
                problems.append(f"{prefix} candidate value type")
            actual_points = [value.get("attacker_points") for value in values
                             if isinstance(value, dict)]
            if actual_points != expected["expected_attacker_points"]:
                problems.append(f"{prefix} candidate oracle values")
        if world.get("candidate_values_sha256") != stable_digest(values):
            problems.append(f"{prefix} candidate value digest")
        exact = world.get("exact", {})
        if (set(exact) != set(EXACT_FIELDS)
                or any(not isinstance(exact.get(field), int)
                       or exact.get(field, -1) < 0 for field in EXACT_FIELDS)):
            problems.append(f"{prefix} exact counter shape")
        sampler = world.get("sampler", {})
        sampler_fields = {"sample_attempts", "accepted_worlds",
                          "failed_worlds", "rejected_worlds",
                          "impossible_worlds"}
        if (set(sampler) != sampler_fields
                or any(not isinstance(value, int) or value < 0
                       for value in sampler.values())):
            problems.append(f"{prefix} sampler counter shape")
        session = world.get("session", {})
        session_fields = {"frontiers", "nodes", "cache_hits",
                          "max_hand_cards", "max_nodes"}
        if (set(session) != session_fields
                or any(not isinstance(value, int) or value < 0
                       for value in session.values())):
            problems.append(f"{prefix} session counter shape")
        if world.get("problems") != world_problems(world):
            problems.append(f"{prefix} problem derivation")
    expected_state_problems = sorted(set(
        f"world {world['world_seed']}: {problem}"
        for world in worlds for problem in world.get("problems", [])))
    if record.get("problems") != expected_state_problems:
        problems.append("state record problem derivation")
    return sorted(set(problems))


def validate_shard_payload(payload: dict, asset: dict, asset_sha: str,
                           runtime: dict) -> list[str]:
    problems = []
    if payload.get("schema") != RUN_SCHEMA:
        problems.append("shard schema")
    if payload.get("protocol") != protocol_contract():
        problems.append("shard protocol")
    if payload.get("state_asset") != {"schema": STATE_SCHEMA,
                                      "sha256": asset_sha}:
        problems.append("shard state asset")
    if runtime_compatibility(payload.get("runtime", {})) != \
            runtime_compatibility(runtime):
        problems.append("shard runtime/source identity")
    shard = payload.get("shard", {})
    index = shard.get("index")
    if not isinstance(index, int) or not 0 <= index < SHARD_COUNT:
        problems.append("shard index")
        return problems
    expected = assigned_states(asset, index, SHARD_COUNT)
    expected_shard = {
        "index": index, "count": SHARD_COUNT, "assignment": ASSIGNMENT,
        "state_ids": [state["state_id"] for state in expected],
        "state_seeds": [state["deal_seed"] for state in expected],
        "world_seeds": [world["world_seed"] for state in expected
                        for world in state["worlds"]],
    }
    if shard != expected_shard:
        problems.append("shard assignment/seed coverage")
    records = payload.get("records", [])
    if [record.get("state_id") for record in records] != \
            expected_shard["state_ids"]:
        problems.append("shard record coverage/assignment")
    spec_by_id = {state["state_id"]: state for state in expected}
    for record in records:
        spec = spec_by_id.get(record.get("state_id"))
        if spec is not None:
            problems.extend(state_record_problems(record, spec))
    if payload.get("records_sha256") != stable_digest(records):
        problems.append("shard records digest")
    summary = summarize_records(records)
    if payload.get("exact") != summary["exact"]:
        problems.append("shard exact totals")
    if payload.get("work") != summary["work"]:
        problems.append("shard work totals")
    expected_problems = summary["problems"]
    if payload.get("problems") != expected_problems:
        problems.append("shard problem list")
    should_pass = not expected_problems
    if payload.get("shard_pass") is not should_pass \
            or payload.get("status") != ("SHARD_PASS" if should_pass else "HOLD"):
        problems.append("shard status")
    if payload.get("challenge_pass") is not False:
        problems.append("a shard may not claim terminal challenge PASS")
    return sorted(set(problems))


def build_aggregate_payload(shards: list[dict], input_hashes: list[str],
                            asset: dict, asset_sha: str,
                            runtime: dict) -> dict:
    problems = []
    indices = []
    all_records = []
    for pos, shard in enumerate(shards):
        shard_problems = validate_shard_payload(shard, asset, asset_sha, runtime)
        problems.extend(f"input {pos}: {problem}" for problem in shard_problems)
        index = shard.get("shard", {}).get("index")
        if isinstance(index, int):
            indices.append(index)
        all_records.extend(shard.get("records", []))
    if sorted(indices) != list(range(SHARD_COUNT)):
        problems.append("inputs do not cover each shard index exactly once")
    expected_ids = [state["state_id"] for state in asset["states"]]
    record_ids = [record.get("state_id") for record in all_records]
    if sorted(record_ids) != expected_ids or len(record_ids) != len(set(record_ids)):
        problems.append("aggregate state coverage")
    expected_world_seeds = sorted(
        world["world_seed"] for state in asset["states"]
        for world in state["worlds"])
    actual_world_seeds = sorted(
        world.get("world_seed") for record in all_records
        for world in record.get("worlds", []))
    if actual_world_seeds != expected_world_seeds:
        problems.append("aggregate world-seed coverage")
    summary = summarize_records(all_records)
    problems.extend(summary["problems"])
    challenge_pass = not problems
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": "PASS" if challenge_pass else "HOLD",
        "challenge_pass": challenge_pass,
        "protocol": protocol_contract(),
        "state_asset": {"schema": STATE_SCHEMA, "sha256": asset_sha},
        "runtime": runtime,
        "input_shards": [
            {"shard_index": shard.get("shard", {}).get("index"),
             "sha256": digest}
            for shard, digest in sorted(
                zip(shards, input_hashes),
                key=lambda item: item[0].get("shard", {}).get("index", -1))
        ],
        "coverage": {
            "shard_indices": sorted(indices),
            "state_ids": sorted(record_ids),
            "state_seeds": sorted(record.get("deal_seed")
                                  for record in all_records),
            "world_seeds": actual_world_seeds,
        },
        "records_sha256": stable_digest(
            sorted(all_records, key=lambda record: record.get("state_id", ""))),
        "exact": summary["exact"],
        "work": summary["work"],
        "problems": sorted(set(problems)),
        "strength_evidence": False,
        "promotion": False,
        "full_game_reference": None,
    }


def run_command(args) -> dict:
    ensure_output_available(args.out)
    asset, asset_sha = load_state_asset(
        args.states, args.expected_state_asset_sha256)
    assigned = assigned_states(asset, args.shard_index, args.shard_count)
    runtime = runtime_contract(args.states)
    records = [run_state(state) for state in assigned]
    payload = build_shard_payload(
        asset, asset_sha, runtime, args.shard_index, records)
    write_exclusive_atomic(args.out, payload)
    return payload


def aggregate_command(args) -> dict:
    ensure_output_available(args.out)
    asset, asset_sha = load_state_asset(
        args.states, args.expected_state_asset_sha256)
    runtime = runtime_contract(args.states)
    if len(args.inputs) != SHARD_COUNT or len(set(args.inputs)) != SHARD_COUNT:
        raise ChallengeProtocolError(
            f"aggregate requires {SHARD_COUNT} distinct shard inputs")
    shards = []
    hashes = []
    for path in args.inputs:
        try:
            with open(path) as fh:
                shards.append(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChallengeProtocolError(f"cannot read shard {path}: {exc}") from exc
        hashes.append(sha256_file(path))
    payload = build_aggregate_payload(
        shards, hashes, asset, asset_sha, runtime)
    write_exclusive_atomic(args.out, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("run", "aggregate"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--states", default=DEFAULT_STATE_ASSET)
        cmd.add_argument("--expected-state-asset-sha256", required=True)
        cmd.add_argument("--out", required=True)
    run = sub.choices["run"]
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--shard-count", type=int, default=SHARD_COUNT)
    aggregate = sub.choices["aggregate"]
    aggregate.add_argument("--inputs", nargs="+", required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        payload = run_command(args) if args.command == "run" \
            else aggregate_command(args)
    except (ChallengeProtocolError, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps({"status": payload["status"], "out": args.out},
                     sort_keys=True), flush=True)
    if payload["status"] not in {"SHARD_PASS", "PASS"}:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
