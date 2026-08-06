"""Executable contracts shared by the teacher-v1 producer and gates.

Teacher-v1 is intentionally separate from the historical high-N and
DEV/CALIB/REPORT assets.  This module contains the small, testable pieces of
the contract: exact state replay, domain-separated random streams, terminal
targets, dense-tensor validation and the Stage-B clustered regret gate.

Nothing in here selects a state after seeing its 512-world labels.  The state
freezer owns selection; the labeller and gate only accept its immutable rows.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections import Counter

from .engine.game import Game

EXPERIMENT = "teacher-v1"
STATE_SCHEMA = "teacher-v1-state-v1"
STATE_SET_SCHEMA = "teacher-v1-state-set-v1"
CHEAP_SHARD_SCHEMA = "teacher-v1-cheap-shard-v1"
GOLD_SHARD_SCHEMA = "teacher-v1-gold-shard-v1"
GATE_SCHEMA = "teacher-v1-gate-v1"
PRODUCER_RECEIPT_SCHEMA = "teacher-v1-producer-receipt-v1"
TARGET_SCHEMA = "teacher-v1-uncapped-possession-utility-v1"

SEED_START = 120_000_000
CAPTURE_PACKET_ID = "teacher-v1-entry-120m-v1"
CAPTURE_MAX_DEALS = 1_024
CAPTURE_SEED_END = SEED_START + CAPTURE_MAX_DEALS - 1
CAPTURE_SHARDS = 8
CAPTURE_DEALS_PER_SHARD = CAPTURE_MAX_DEALS // CAPTURE_SHARDS
PHASES = ("early", "mid", "late")
ROLES = ("attacker", "defender")
DECISIONS = ("lead", "follow")
REPRESENTATIVE_CELLS = tuple(
    (phase, role, decision)
    for phase in PHASES
    for role in ROLES
    for decision in DECISIONS
)

STAGE_A_STATES = 64
STAGE_A_REPRESENTATIVE_PER_CELL = 4
STAGE_A_OTHER_STATES = 16
CHEAP_FOLDS = {"selection": 256, "report": 256}
STAGE_B_STATES = 128
STAGE_B_REPRESENTATIVE_PER_CELL = 8
STAGE_B_BOUNDARY_STATES = 16
STAGE_B_UNCERTAINTY_STATES = 16
GOLD_FOLDS = {"gold_selection": 64, "gold_report": 64}
STAGE_B_REGRET_LIMIT = 0.10
# One-sided Student-t critical at df=127 is about 1.657.  Use the named,
# slightly conservative constant rather than silently substituting a two-sided
# 1.96 interval or requiring scipy on generation hosts.
STAGE_B_T_CRITICAL = 1.66

SAMPLER_COUNTERS = (
    "sample_attempts",
    "accepted_worlds",
    "failed_worlds",
    "rejected_worlds",
    "impossible_worlds",
    "short_search_decisions",
    "zero_world_decisions",
)


class TeacherProtocolError(RuntimeError):
    """A condition that makes a teacher artifact unusable."""


def capture_packet() -> dict:
    """Literal identity of the first frozen teacher entry population."""
    return {
        "packet_id": CAPTURE_PACKET_ID,
        "seed0": SEED_START,
        "seed_end_inclusive": CAPTURE_SEED_END,
        "max_deals": CAPTURE_MAX_DEALS,
        "shard_count": CAPTURE_SHARDS,
        "sharding": "interleaved_seed_offset_mod_8",
        "deals_per_shard": CAPTURE_DEALS_PER_SHARD,
    }


def capture_shard_seeds(shard_index: int) -> list[int]:
    if not 0 <= shard_index < CAPTURE_SHARDS:
        raise ValueError(f"capture shard must be 0..{CAPTURE_SHARDS - 1}")
    return list(range(
        SEED_START + shard_index,
        SEED_START + CAPTURE_MAX_DEALS,
        CAPTURE_SHARDS,
    ))


def capture_coverage() -> dict:
    seeds = list(range(SEED_START, CAPTURE_SEED_END + 1))
    return {
        **capture_packet(),
        "seed_count": len(seeds),
        "seeds_sha256": stable_digest(seeds),
        "shard_seed_sha256": {
            str(index): stable_digest(capture_shard_seeds(index))
            for index in range(CAPTURE_SHARDS)
        },
    }


def stable_json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list
    ).encode()


def stable_digest(value) -> str:
    return hashlib.sha256(stable_json(value)).hexdigest()


def is_sha256(value) -> bool:
    """Return whether ``value`` is a canonical lowercase SHA-256 digest."""
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def is_run_id(value) -> bool:
    """Bounded, shell-safe identity shared by one eight-shard producer run."""
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:"
    return (isinstance(value, str) and 8 <= len(value) <= 128
            and all(char in allowed for char in value))


def canonical_state_partition(records: list[dict], shard_index: int,
                              shard_count: int) -> list[dict]:
    """Return the registered order-independent state partition.

    A manifest's claimed shard number must determine which state identities it
    contains.  Sorting globally by ``state_id`` and then interleaving makes that
    relation independently reconstructable from the state set and prevents a
    shard-index field swap from remaining plausible.
    """
    if not 0 <= shard_index < shard_count:
        raise ValueError("invalid state partition shard index/count")
    if any(not isinstance(record.get("state_id"), str) for record in records):
        raise ValueError("state partition requires string state_id values")
    ordered = sorted(records, key=lambda record: record["state_id"])
    return ordered[shard_index::shard_count]


def derive_stream(**identity) -> dict:
    """Return the recorded derivation inputs and deterministic stream seed.

    A stream is identified by names, not by a mutable RNG-state digest.  The
    caller must include experiment/state/fold/purpose and, for continuation
    streams, candidate and world.  Belief-world streams deliberately omit the
    candidate so every action sees the same worlds.
    """
    required = {"experiment_id", "deal_seed", "state_id", "purpose", "fold"}
    missing = sorted(required - set(identity))
    if missing:
        raise ValueError(f"stream identity missing {missing}")
    if identity["purpose"] == "belief" and identity.get("candidate") is not None:
        raise ValueError("belief stream must be common across candidates")
    payload = {k: identity[k] for k in sorted(identity)}
    seed = int.from_bytes(hashlib.sha256(stable_json(payload)).digest()[:16],
                          "big")
    return {"derivation": payload, "seed": seed}


def split_for_deal(experiment_id: str, deal_seed: int) -> str:
    """Deal-disjoint deterministic 70/15/15 TRAIN/TUNE/HOLDOUT assignment."""
    raw = hashlib.sha256(
        f"{experiment_id}|split|{int(deal_seed)}".encode()
    ).digest()
    bucket = int.from_bytes(raw[:8], "big") % 20
    return "train" if bucket < 14 else ("tune" if bucket < 17 else "holdout")


def phase_for_trick(trick: int) -> str:
    if trick < 0:
        raise ValueError("trick index must be non-negative")
    return "early" if trick < 5 else ("mid" if trick < 12 else "late")


def state_id(row: dict) -> str:
    return f'{row["seed"]}:{row["ply"]}:{row["seat"]}'


def action_key(action) -> tuple[str, ...]:
    return tuple(sorted(action))


def replay_state(row: dict):
    """Rebuild an arbitrary lead or follow teacher state exactly.

    Declarations are replayed at their original deal position.  Regenerating
    them with today's actor would not be replay and would silently move the
    banker/trump boundary whenever the actor changes.
    """
    if row.get("schema") != STATE_SCHEMA:
        raise ValueError(f"unsupported teacher state schema {row.get('schema')!r}")
    setup = row["setup"]
    seed = int(row["seed"])
    rnd = Game(random.Random(seed)).start_round()
    if list(rnd.deck) != list(setup["deck"]):
        raise ValueError("teacher deck does not reproduce from its seed")
    if rnd.banker != setup.get("initial_banker"):
        raise ValueError("teacher initial banker mismatch")
    if rnd.trump_rank != setup["trump_rank"]:
        raise ValueError("teacher initial trump rank mismatch")

    events = list(setup["declarations"])
    event_i = 0
    while rnd.phase == "deal":
        rnd.deal_next()
        while event_i < len(events) and events[event_i]["stage"] == "deal":
            event = events[event_i]
            if event["deal_pos"] < rnd._deal_pos:
                raise ValueError("teacher declaration was not replayed in order")
            if event["deal_pos"] != rnd._deal_pos:
                break
            rnd.declare(event["seat"], list(event["cards"]))
            event_i += 1
    if event_i < len(events) and events[event_i]["stage"] == "deal":
        raise ValueError("teacher declaration lies beyond the deal")
    while event_i < len(events):
        event = events[event_i]
        if event["stage"] != "final" or event["deal_pos"] != rnd._deal_pos:
            raise ValueError("invalid teacher final declaration event")
        rnd.declare(event["seat"], list(event["cards"]))
        event_i += 1

    rnd.finalize_declare()
    if rnd.banker != setup["banker"]:
        raise ValueError("teacher banker mismatch")
    if rnd.trump_suit != setup["trump_suit"]:
        raise ValueError("teacher trump suit mismatch")
    if rnd.trump_is_nt != setup["trump_is_nt"]:
        raise ValueError("teacher no-trump mismatch")
    live_decl = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"],
        "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    if live_decl != setup.get("final_declaration"):
        raise ValueError("teacher final declaration mismatch")

    rnd.bury(rnd.banker, list(setup["buried"]))
    for play in row["plays"]:
        if rnd.turn != play["seat"]:
            raise ValueError("teacher play order mismatch")
        rnd.play(play["seat"], list(play["cards"]))

    if len(row["plays"]) != row["ply"]:
        raise ValueError("teacher ply count mismatch")
    if len(rnd.history) != row["trick"]:
        raise ValueError("teacher trick index mismatch")
    if rnd.phase != "play" or rnd.trick is None:
        raise ValueError("teacher replay did not land at a play decision")
    if rnd.turn != row["seat"]:
        raise ValueError("teacher replay landed on the wrong seat")
    decision = "lead" if not rnd.trick.plays else "follow"
    role = "attacker" if rnd.is_attacker(rnd.turn) else "defender"
    phase = phase_for_trick(len(rnd.history))
    if (decision, role, phase) != (
        row["decision"], row["role"], row["phase"]
    ):
        raise ValueError("teacher replay stratum mismatch")
    if row.get("split") != split_for_deal(row["experiment_id"], seed):
        raise ValueError("teacher split is not the registered deal hash")
    if row.get("state_id") != state_id(row):
        raise ValueError("teacher state_id mismatch")
    return rnd


def ballot_problems(rnd, seat: int, candidates) -> list[str]:
    """Check complete, unique, held and engine-legal action candidates."""
    bad: list[str] = []
    if not isinstance(candidates, list) or not candidates:
        return ["empty or non-list ballot"]
    held = Counter(rnd.hands[seat])
    keys = [action_key(action) for action in candidates]
    if len(keys) != len(set(keys)):
        bad.append("duplicate candidate action")
    for index, action in enumerate(candidates):
        need = Counter(action)
        if not action or any(n > held.get(card, 0) for card, n in need.items()):
            bad.append(f"candidate {index} is empty or not held")
            continue
        clone = copy.deepcopy(rnd)
        try:
            clone.play(seat, list(action))
        except Exception as exc:
            bad.append(f"candidate {index} is illegal: {type(exc).__name__}: {exc}")
    return bad


def scoring_bracket(attacker_points: int | float) -> int:
    """Uncapped house-rule bracket before the possession term."""
    p = attacker_points
    if p >= 80:
        return int(p - 80) // 40
    if p == 0:
        return -3
    return -(1 + int(79 - p) // 40)


def attacker_level_utility(attacker_points: int | float) -> float:
    p = attacker_points
    if p >= 80:
        return float(int(p - 80) // 40 + 0.5)
    if p == 0:
        return -3.5
    return float(-(1 + int(79 - p) // 40) - 0.5)


def targets(attacker_points: int | float, acting_is_attacker: bool) -> dict:
    """All four teacher targets, with acting-team signs made explicit."""
    sign = 1 if acting_is_attacker else -1
    return {
        "attacker_points": attacker_points,
        "signed_points": sign * attacker_points,
        "bracket": scoring_bracket(attacker_points),
        "signed_level_utility": sign * attacker_level_utility(attacker_points),
    }


def sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in SAMPLER_COUNTERS}


def sampler_delta(before: dict[str, int], bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) - before[name]
            for name in SAMPLER_COUNTERS}


def counter_problems(counters: dict, expected_worlds: int) -> list[str]:
    bad = []
    if set(counters) != set(SAMPLER_COUNTERS):
        return ["sampler counter schema mismatch"]
    if counters["sample_attempts"] != (
        counters["accepted_worlds"] + counters["failed_worlds"]
    ):
        bad.append("sample attempts do not reconcile")
    if counters["accepted_worlds"] != expected_worlds:
        bad.append(
            f"accepted {counters['accepted_worlds']} worlds, expected {expected_worlds}"
        )
    forbidden = {
        key: counters[key]
        for key in (
            "failed_worlds", "rejected_worlds", "impossible_worlds",
            "short_search_decisions", "zero_world_decisions",
        )
        if counters[key]
    }
    if forbidden:
        bad.append(f"forbidden sampler/search counters {forbidden}")
    return bad


def matrix_shape(matrix) -> tuple[int, int] | None:
    if not isinstance(matrix, list):
        return None
    if not matrix:
        return (0, 0)
    if not all(isinstance(row, list) for row in matrix):
        return None
    widths = {len(row) for row in matrix}
    return (len(matrix), widths.pop()) if len(widths) == 1 else None


def tensor_problems(fold: dict, worlds: int, candidates: int) -> list[str]:
    bad = []
    if fold.get("requested_worlds") != worlds:
        bad.append("requested world count drift")
    if len(fold.get("draw_ids", [])) != worlds:
        bad.append("draw-id count mismatch")
    if len(set(fold.get("draw_ids", []))) != worlds:
        bad.append("draw IDs are not unique")
    if len(fold.get("world_digests", [])) != worlds:
        bad.append("world-digest count mismatch")
    tensor = fold.get("tensor", {})
    for target in (
        "attacker_points", "signed_points", "bracket", "signed_level_utility"
    ):
        shape = matrix_shape(tensor.get(target))
        if shape != (worlds, candidates):
            bad.append(f"{target} tensor shape {shape}, expected {(worlds, candidates)}")
    return bad


def paired_moments(values: list[float]) -> dict:
    if not values:
        raise ValueError("paired moments require at least one value")
    n = len(values)
    mean = sum(values) / n
    variance = (sum((x - mean) ** 2 for x in values) / (n - 1)
                if n > 1 else 0.0)
    return {
        "n": n,
        "sum": sum(values),
        "sum_sq": sum(x * x for x in values),
        "mean": mean,
        "se": math.sqrt(variance / n) if n > 1 else float("inf"),
    }


def stage_b_regret(records: list[dict]) -> dict:
    """Recompute the registered Stage-B gate from raw gold-report tensors."""
    problems = []
    if len(records) != STAGE_B_STATES:
        problems.append(f"records {len(records)}, required {STAGE_B_STATES}")
    deals = [record.get("deal_seed") for record in records]
    if len(deals) != len(set(deals)):
        problems.append("Stage B is not one-state-per-deal")
    state_regrets = []
    for record in records:
        candidates = record.get("candidates", [])
        cheap_i = record.get("cheap_selected_index")
        gold_i = record.get("gold_reference_index")
        if not (isinstance(cheap_i, int) and isinstance(gold_i, int)
                and 0 <= cheap_i < len(candidates)
                and 0 <= gold_i < len(candidates)):
            problems.append(f"{record.get('state_id')}: frozen action index")
            continue
        fold = record.get("folds", {}).get("gold_report", {})
        problems += [f"{record.get('state_id')}: {p}"
                     for p in tensor_problems(
                         fold, GOLD_FOLDS["gold_report"], len(candidates)
                     )]
        matrix = fold.get("tensor", {}).get("signed_level_utility")
        if matrix_shape(matrix) != (GOLD_FOLDS["gold_report"], len(candidates)):
            continue
        diffs = [row[gold_i] - row[cheap_i] for row in matrix]
        recomputed = sum(diffs) / len(diffs)
        if not math.isclose(
            recomputed, record.get("gold_report_regret", float("nan")),
            rel_tol=0.0, abs_tol=1e-12,
        ):
            problems.append(f"{record.get('state_id')}: stored regret drift")
        state_regrets.append(recomputed)
    if problems or len(state_regrets) != STAGE_B_STATES:
        return {
            "passed": False, "inconclusive": True, "problems": problems,
            "n_states": len(state_regrets), "mean_regret": None,
            "se": None, "upper_95": None,
            "limit": STAGE_B_REGRET_LIMIT,
        }
    moments = paired_moments(state_regrets)
    upper = moments["mean"] + STAGE_B_T_CRITICAL * moments["se"]
    return {
        "passed": upper <= STAGE_B_REGRET_LIMIT,
        "inconclusive": False,
        "problems": [],
        "n_states": len(state_regrets),
        "mean_regret": moments["mean"],
        "se": moments["se"],
        "upper_95": upper,
        "critical": STAGE_B_T_CRITICAL,
        "limit": STAGE_B_REGRET_LIMIT,
    }
