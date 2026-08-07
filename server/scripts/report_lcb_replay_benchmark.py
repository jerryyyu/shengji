#!/usr/bin/env python3
"""Sanitize, exactly replay, and benchmark live report-LCB decisions.

The committed asset contains no room code, timestamps, connection tokens, or
player identities.  It retains only the public/engine setup needed to rebuild
three rounds, logged plays, and the exact pre-decision RNG state plus semantic
decision receipt for a deterministic stratified sample of 100 searched turns.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import lzma
import math
import os
import platform
import statistics
import struct
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.mcbot import restore_random_state  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.rl.replay_log import group_rounds, rebuild_round  # noqa: E402


ASSET_SCHEMA = "report-lcb-live-replay-v1"
RESULT_SCHEMA = "report-lcb-live-replay-result-v1"
ENCODED_HEADER = "report-lcb-live-replay-v1+lzmabase85"
POLICY = "mc-s0-report-lcb"
TARGET_DECISIONS = 100
BOT_MIN_TURN_SECONDS = 0.7
EXPECTED_MCBOT_SHA256 = (
    "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957"
)
SEMANTIC_FIELDS = (
    "schema", "policy", "policy_class", "seed", "n_determinizations",
    "margin", "confidence_override", "z", "adaptive_allocation",
    "random_allocation", "report_worlds_requested", "report_rule",
    "report_min_gain", "report_alpha", "candidates", "means",
    "n_by_candidate", "paired_se", "eligible_indices", "worlds", "alloc",
    "work", "rng_state", "report_seed", "allocation_seed",
    "raw_winner_index", "report_candidate_index", "report_fold",
    "played", "played_index", "reason", "sampler_counters", "ballot",
)
BANNED_ASSET_KEYS = {
    "players", "room", "claim_token", "token", "t",
}


class ReplayRefused(RuntimeError):
    """The input cannot establish the frozen live replay claim."""


def sha256(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()).hexdigest()


def fast_active() -> bool:
    """Whether execution is actually routed through the compiled kernels."""
    return bool(fast.HAVE_FAST and combos.decompose is fast.decompose)


def runtime_receipt() -> dict:
    extension = getattr(getattr(fast, "_fast", None), "__file__", None)
    repo = SERVER.parent
    try:
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        git_dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo, check=True, capture_output=True, text=True,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        git_head, git_dirty = None, None
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "git_head": git_head,
        "git_dirty": git_dirty,
        "benchmark_source_sha256": sha256(SCRIPT),
        "scheduler_source_sha256": sha256(
            SERVER / "shengji" / "api" / "server.py"),
        "mcbot_source_sha256": sha256(
            SERVER / "shengji" / "ai" / "mcbot.py"),
        "fast_active": fast_active(),
        "fast_extension_sha256": (
            sha256(extension) if extension and Path(extension).is_file()
            else None
        ),
    }


def encode_rng_state(state) -> str:
    """Compact the JSON form of ``random.Random.getstate()`` losslessly."""
    if (not isinstance(state, (list, tuple)) or len(state) != 3
            or not isinstance(state[1], (list, tuple))
            or state[2] is not None):
        raise ReplayRefused("unsupported random state shape")
    version = int(state[0])
    internal = [int(value) for value in state[1]]
    if not internal or any(not 0 <= value <= 0xFFFFFFFF for value in internal):
        raise ReplayRefused("random state contains an invalid word")
    raw = struct.pack(f"!{len(internal) + 2}I", version, len(internal), *internal)
    return base64.b85encode(raw).decode("ascii")


def decode_rng_state(encoded: str):
    try:
        raw = base64.b85decode(encoded.encode("ascii"))
        if len(raw) < 8 or len(raw) % 4:
            raise ValueError("invalid byte length")
        words = struct.unpack(f"!{len(raw) // 4}I", raw)
    except (AttributeError, UnicodeEncodeError, ValueError, struct.error) as exc:
        raise ReplayRefused(f"invalid encoded RNG state: {exc}") from exc
    version, length, *internal = words
    if length != len(internal):
        raise ReplayRefused("encoded RNG state word count drifted")
    return [version, internal, None]


def rng_state_ref(encoded: str) -> str:
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _phase(trick: int) -> str:
    return "early" if trick < 5 else ("mid" if trick < 12 else "late")


def _candidate_bin(count: int) -> str:
    if count <= 4:
        return "02-04"
    if count <= 8:
        return "05-08"
    return "09-plus"


def _stratum(decision: dict) -> str:
    return "/".join((
        decision["phase"], decision["decision"],
        _candidate_bin(decision["candidate_count"]),
    ))


def semantic_record(record: dict) -> dict:
    missing = sorted(set(SEMANTIC_FIELDS) - set(record))
    if missing:
        raise ReplayRefused(f"decision record missing semantic fields {missing}")
    extra = sorted(
        set(record) - set(SEMANTIC_FIELDS)
        - {"search_secs", "code", "mcbot_sha256"}
    )
    if extra:
        raise ReplayRefused(f"unclassified decision fields {extra}")
    code = record.get("code")
    source_digest = (
        record.get("mcbot_sha256")
        if code is None else code.get("mcbot_sha256")
        if isinstance(code, dict) else None
    )
    if source_digest != EXPECTED_MCBOT_SHA256:
        raise ReplayRefused("live decision MCBot source identity drifted")
    projected = {
        **{field: record[field] for field in SEMANTIC_FIELDS},
        "mcbot_sha256": source_digest,
    }
    ballot = projected["ballot"]
    if not isinstance(ballot, dict):
        raise ReplayRefused("decision ballot is not a mapping")
    # The historical digest included compiled-binary bytes and therefore moves
    # across reproducible source builds.  The executable semantic boundary is
    # the generator/config plus the exact ordered candidate list and MCBot
    # source hash, all of which remain in this projection.
    projected["ballot"] = {
        key: ballot[key] for key in ("name", "version", "source", "config")
    }
    counters = projected["sampler_counters"]
    if not isinstance(counters, dict):
        raise ReplayRefused("decision sampler counters are not a mapping")
    # A production room reuses one bot, so before/after totals are cumulative;
    # an isolated replay intentionally does not.  The per-decision delta is the
    # exact work/correctness invariant.
    if isinstance(counters.get("delta"), dict):
        projected["sampler_counters"] = counters["delta"]
    elif set(counters) != {
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    }:
        raise ReplayRefused("decision sampler counters lack an exact delta")
    return json.loads(json.dumps(projected))


def semantic_differences(expected, actual, path: str = "$") -> list[str]:
    """Return semantic drift paths, allowing only cross-platform float ULPs.

    The production log was generated on x86 while the replay fleet is ARM.
    IEEE operations can differ in the final bit (observed in one report-fold
    standard error) without changing the represented statistic or decision.
    Everything except finite floats remains exact; floats receive at most
    eight ULPs at their numerical scale, never a policy-level tolerance.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if type(expected) is type(actual) and expected == actual \
            else [path]
    if isinstance(expected, float) and isinstance(actual, float):
        if not math.isfinite(expected) or not math.isfinite(actual):
            return [] if expected == actual else [path]
        scale = max(1.0, abs(expected), abs(actual))
        return [] if abs(expected - actual) <= 8 * math.ulp(scale) else [path]
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            return [f"{path}.__keys__"]
        out = []
        for key in sorted(expected):
            out += semantic_differences(
                expected[key], actual[key], f"{path}.{key}")
        return out
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}.__len__"]
        out = []
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            out += semantic_differences(left, right, f"{path}[{index}]")
        return out
    return [] if expected == actual else [path]


def _safe_setup(events: list[dict]) -> list[dict]:
    keep = []
    for event in events:
        kind = event.get("e")
        if kind == "round_start":
            keep.append({
                "e": kind,
                "deck": list(event["deck"]),
                "banker": event["banker"],
                "trump_rank": event["trump_rank"],
            })
        elif kind == "declare":
            keep.append({
                "e": kind, "seat": event["seat"],
                "cards": list(event["cards"]),
            })
        elif kind == "trump":
            keep.append({
                "e": kind, "banker": event["banker"],
                "suit": event["suit"], "rank": event["rank"],
                "declared": event["declared"],
            })
        elif kind == "bury":
            keep.append({
                "e": kind, "seat": event["seat"],
                "cards": list(event["cards"]), "bot": bool(event["bot"]),
            })
    return keep


def _decision_inventory(rounds: dict[int, list[dict]]) -> list[dict]:
    inventory = []
    ordinal = 0
    for round_no, events in sorted(rounds.items()):
        rnd = rebuild_round(events)
        if rnd is None:
            continue
        ply = 0
        for event in events:
            if event.get("e") != "play":
                continue
            if rnd.phase != "play" or rnd.turn != event.get("seat"):
                raise ReplayRefused(
                    f"round {round_no} ply {ply} does not replay in order")
            record = event.get("decision")
            if record is not None:
                if event.get("bot") is not True:
                    raise ReplayRefused("a human play carries a bot decision")
                projected = semantic_record(record)
                if projected["policy"] != POLICY:
                    raise ReplayRefused(
                        f"unexpected live policy {projected['policy']!r}")
                if sorted(projected["played"]) != sorted(event["cards"]):
                    raise ReplayRefused("logged decision/play mismatch")
                decision = {
                    "ordinal": ordinal,
                    "round": round_no,
                    "ply": ply,
                    "seat": event["seat"],
                    "trick": len(rnd.history),
                    "phase": _phase(len(rnd.history)),
                    "decision": "lead" if not rnd.trick.plays else "follow",
                    "candidate_count": len(projected["candidates"]),
                    "source_search_secs": float(record["search_secs"]),
                    "record": projected,
                }
                decision["stratum"] = _stratum(decision)
                inventory.append(decision)
                ordinal += 1
            rnd.play(event["seat"], list(event["cards"]))
            ply += 1
    for index, decision in enumerate(inventory[:-1]):
        decision["expected_post_rng_state"] = inventory[index + 1][
            "record"]["rng_state"]
    if inventory:
        inventory[-1]["expected_post_rng_state"] = None
    return inventory


def _sample_ordinals(inventory: list[dict]) -> set[int]:
    eligible = list(inventory)
    if len(eligible) < TARGET_DECISIONS:
        raise ReplayRefused(f"only {len(eligible)} searched decisions exist")
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for item in eligible:
        by_stratum[item["stratum"]].append(item)
    total = len(eligible)
    quotas = {
        name: TARGET_DECISIONS * len(rows) // total
        for name, rows in by_stratum.items()
    }
    remaining = TARGET_DECISIONS - sum(quotas.values())
    remainder_order = sorted(
        by_stratum,
        key=lambda name: (
            -(TARGET_DECISIONS * len(by_stratum[name]) % total), name),
    )
    for name in remainder_order[:remaining]:
        quotas[name] += 1

    selected = set()
    for name, rows in by_stratum.items():
        ranked = sorted(
            rows,
            key=lambda item: hashlib.sha256(
                f"{ASSET_SCHEMA}|{item['round']}|{item['ply']}|"
                f"{item['seat']}".encode()
            ).hexdigest(),
        )
        selected.update(item["ordinal"] for item in ranked[:quotas[name]])
    if len(selected) != TARGET_DECISIONS:
        raise ReplayRefused(
            f"stratified selector chose {len(selected)}, expected 100")
    return selected


def _counts(items: Iterable[dict]) -> dict:
    items = list(items)
    return {
        "decisions": len(items),
        "phase": dict(sorted(Counter(item["phase"] for item in items).items())),
        "decision": dict(sorted(
            Counter(item["decision"] for item in items).items())),
        "candidate_bin": dict(sorted(Counter(
            _candidate_bin(item["candidate_count"]) for item in items).items())),
        "stratum": dict(sorted(Counter(item["stratum"] for item in items).items())),
    }


def _derive_post_rng_witnesses(safe_rounds: list[dict], rng_states: dict[str, str],
                               intern_rng) -> Counter:
    """Freeze post-RNG states from the exact logged pre-state and source.

    Live v2 receipts retained the pre-state but not the post-state.  The next
    searched receipt is an independent post witness only when no intervening
    bot action consumes the shared room RNG.  We retain that comparison, then
    derive the authoritative post-state by exact replay under the source hash
    already embedded in every receipt.  This is an explicit golden-master
    derivation, not falsely presented as a live-logged field.
    """
    methods = Counter()
    for round_asset in safe_rounds:
        rnd = rebuild_round(round_asset["setup"])
        if rnd is None:
            raise ReplayRefused("cannot derive RNG witness from incomplete round")
        for play in round_asset["plays"]:
            benchmark = play.get("benchmark")
            if benchmark is not None:
                expected = benchmark["record"]
                bot = make_bot(POLICY)
                restore_random_state(
                    bot.rng, decode_rng_state(rng_states[expected["rng_state"]]))
                played = bot.decide_play(rnd, play["seat"])
                actual = semantic_record(bot.last_decision_record)
                actual["rng_state"] = rng_state_ref(
                    encode_rng_state(actual["rng_state"]))
                drift = semantic_differences(expected, actual)
                if sorted(played) != sorted(play["cards"]) or drift:
                    raise ReplayRefused(
                        "cannot derive post-RNG witness for "
                        f"{benchmark['round']}:{benchmark['ply']}: "
                        f"cards={sorted(played) != sorted(play['cards'])}, "
                        f"semantic={drift[:8]}"
                    )
                post_ref = intern_rng(bot.rng.getstate())
                next_ref = benchmark.pop("next_logged_pre_rng_state")
                method = (
                    "logged-next-pre" if next_ref == post_ref
                    else "source-replay-derived"
                )
                benchmark["expected_post_rng_state"] = post_ref
                benchmark["post_rng_witness"] = {
                    "method": method,
                    "source_mcbot_sha256": EXPECTED_MCBOT_SHA256,
                    "next_logged_pre_rng_state": next_ref,
                }
                methods[method] += 1
            rnd.play(play["seat"], list(play["cards"]))
    return methods


def capture_asset(log_path: str | os.PathLike) -> dict:
    log_path = Path(log_path).resolve()
    rounds = group_rounds(str(log_path))
    inventory = _decision_inventory(rounds)
    selected = _sample_ordinals(inventory)
    selected_by_location = {
        (item["round"], item["ply"]): item
        for item in inventory if item["ordinal"] in selected
    }
    rng_states: dict[str, str] = {}

    def intern_rng(state) -> str:
        encoded = encode_rng_state(state)
        identity = rng_state_ref(encoded)
        previous = rng_states.setdefault(identity, encoded)
        if previous != encoded:
            raise ReplayRefused("RNG state digest collision")
        return identity

    safe_rounds = []
    for round_no, events in sorted(rounds.items()):
        if not any(item["round"] == round_no and item["ordinal"] in selected
                   for item in inventory):
            continue
        if rebuild_round(events) is None:
            raise ReplayRefused(f"selected round {round_no} lacks setup")
        plays = []
        ply = 0
        for event in events:
            if event.get("e") != "play":
                continue
            play = {
                "seat": event["seat"], "cards": list(event["cards"]),
                "bot": bool(event.get("bot")),
            }
            decision = selected_by_location.get((round_no, ply))
            if decision is not None:
                stored_record = dict(decision["record"])
                stored_record["rng_state"] = intern_rng(
                    stored_record["rng_state"])
                play["benchmark"] = {
                    **{key: decision[key] for key in (
                        "ordinal", "round", "ply", "seat", "trick", "phase",
                        "decision", "candidate_count", "stratum",
                        "source_search_secs",
                    )},
                    "record": stored_record,
                    "next_logged_pre_rng_state": (
                        None if decision["expected_post_rng_state"] is None
                        else intern_rng(decision["expected_post_rng_state"])
                    ),
                }
            plays.append(play)
            ply += 1
        safe_rounds.append({
            "round": round_no,
            "setup": _safe_setup(events),
            "plays": plays,
        })
    witness_counts = _derive_post_rng_witnesses(
        safe_rounds, rng_states, intern_rng)
    chosen = [item for item in inventory if item["ordinal"] in selected]
    asset = {
        "schema": ASSET_SCHEMA,
        "source": {
            "sha256": sha256(log_path),
            "searched_decisions": len(inventory),
            "mcbot_sha256": EXPECTED_MCBOT_SHA256,
        },
        "selection": {
            "method": (
                "proportional largest-remainder allocation over phase/lead-"
                "follow/candidate-bin, then stable SHA-256 rank"
            ),
            "target": TARGET_DECISIONS,
            "population": _counts(inventory),
            "eligible": _counts(inventory),
            "selected": _counts(chosen),
            "selected_ordinals": sorted(selected),
        },
        "policy": POLICY,
        "bot_min_turn_seconds": BOT_MIN_TURN_SECONDS,
        "semantic_fields": list(SEMANTIC_FIELDS),
        "rng_state_encoding": (
            "sha256-reference to base85(network-order uint32 version,length,"
            "internal words); gaussian cache must be null"
        ),
        "post_rng_witness_counts": dict(sorted(witness_counts.items())),
        "rng_states": dict(sorted(rng_states.items())),
        "rounds": safe_rounds,
    }
    asset["payload_sha256"] = stable_digest({
        key: value for key, value in asset.items() if key != "payload_sha256"
    })
    problems = asset_problems(asset)
    if problems:
        raise ReplayRefused("captured asset invalid: " + "; ".join(problems))
    return asset


def _walk_keys(value) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def asset_problems(asset: object) -> list[str]:
    if not isinstance(asset, dict):
        return ["asset is not a mapping"]
    problems = []
    if asset.get("schema") != ASSET_SCHEMA:
        problems.append("asset schema drift")
    if asset.get("policy") != POLICY:
        problems.append("asset policy drift")
    if (asset.get("source") or {}).get("mcbot_sha256") != \
            EXPECTED_MCBOT_SHA256:
        problems.append("asset MCBot source drift")
    if asset.get("semantic_fields") != list(SEMANTIC_FIELDS):
        problems.append("asset semantic field inventory drift")
    if asset.get("bot_min_turn_seconds") != BOT_MIN_TURN_SECONDS:
        problems.append("asset minimum turn pacing drift")
    source = asset.get("source") or {}
    if source.get("searched_decisions") != 109:
        problems.append("asset source decision inventory drift")
    selection = asset.get("selection") or {}
    if selection.get("target") != TARGET_DECISIONS:
        problems.append("asset selection target drift")
    rng_states = asset.get("rng_states")
    if not isinstance(rng_states, dict) or not rng_states:
        problems.append("asset RNG state pool is missing")
        rng_states = {}
    for identity, encoded in rng_states.items():
        try:
            if rng_state_ref(encoded) != identity:
                problems.append("asset RNG state reference drift")
            decode_rng_state(encoded)
        except Exception as exc:
            problems.append(
                f"asset RNG state refuses: {type(exc).__name__}: {exc}")
    selected = selection.get("selected_ordinals")
    if (not isinstance(selected, list) or len(selected) != TARGET_DECISIONS
            or len(set(selected)) != TARGET_DECISIONS):
        problems.append("asset does not contain 100 unique selections")
    benchmarks = []
    witness_methods = Counter()
    rounds = asset.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        problems.append("asset rounds are missing")
        rounds = []
    for round_asset in rounds:
        if not isinstance(round_asset, dict):
            problems.append("asset round is not a mapping")
            continue
        try:
            rnd = rebuild_round(round_asset["setup"])
        except Exception as exc:
            problems.append(
                f"round setup refuses: {type(exc).__name__}: {exc}")
            continue
        if rnd is None:
            problems.append("round setup is incomplete")
            continue
        for ply, play in enumerate(round_asset.get("plays", [])):
            if rnd.phase != "play" or rnd.turn != play.get("seat"):
                problems.append(
                    f"round {round_asset.get('round')} ply {ply} order drift")
                break
            bench = play.get("benchmark")
            if bench is not None:
                benchmarks.append(bench)
                if (bench.get("round") != round_asset.get("round")
                        or bench.get("ply") != ply
                        or bench.get("seat") != play.get("seat")
                        or bench.get("trick") != len(rnd.history)
                        or bench.get("phase") != _phase(len(rnd.history))
                        or bench.get("decision") != (
                            "lead" if not rnd.trick.plays else "follow")
                        or bench.get("candidate_count") != len(
                            (bench.get("record") or {}).get("candidates", []))
                        or bench.get("stratum") != _stratum(bench)):
                    problems.append(
                        f"round {round_asset.get('round')} ply {ply} "
                        "benchmark identity drift")
                try:
                    projected = semantic_record({
                        **bench["record"],
                        "search_secs": bench["source_search_secs"],
                        "code": {"mcbot_sha256": EXPECTED_MCBOT_SHA256},
                    })
                    if projected != bench["record"]:
                        problems.append("stored semantic record is not canonical")
                    if projected.get("policy") != POLICY:
                        problems.append("stored decision policy drift")
                    if sorted(projected.get("played", [])) != sorted(
                            play.get("cards", [])):
                        problems.append("stored decision/play mismatch")
                except Exception as exc:
                    problems.append(
                        f"stored record refuses: {type(exc).__name__}: {exc}")
                if (bench.get("record", {}).get("rng_state") not in rng_states
                        or bench.get("expected_post_rng_state") not in rng_states):
                    problems.append(
                        "selected decision lacks a pooled pre/post RNG witness")
                witness = bench.get("post_rng_witness")
                if not isinstance(witness, dict) or set(witness) != {
                    "method", "source_mcbot_sha256",
                    "next_logged_pre_rng_state",
                }:
                    problems.append("selected decision RNG witness contract drift")
                else:
                    method = witness.get("method")
                    next_ref = witness.get("next_logged_pre_rng_state")
                    post_ref = bench.get("expected_post_rng_state")
                    if method not in {
                            "logged-next-pre", "source-replay-derived"}:
                        problems.append("selected decision RNG witness method drift")
                    else:
                        witness_methods[method] += 1
                    if witness.get("source_mcbot_sha256") != \
                            EXPECTED_MCBOT_SHA256:
                        problems.append("selected decision RNG witness source drift")
                    if next_ref is not None and next_ref not in rng_states:
                        problems.append("next logged RNG witness is not pooled")
                    if method == "logged-next-pre" and (
                            next_ref is None or next_ref != post_ref):
                        problems.append("logged next-pre RNG witness is not exact")
                    if method == "source-replay-derived" and next_ref == post_ref:
                        problems.append("derived RNG witness mislabels a logged match")
            try:
                rnd.play(play["seat"], list(play["cards"]))
            except Exception as exc:
                problems.append(
                    f"round {round_asset.get('round')} ply {ply} play refuses: "
                    f"{type(exc).__name__}: {exc}")
                break
    if len(benchmarks) != TARGET_DECISIONS:
        problems.append(
            f"asset has {len(benchmarks)} benchmark decisions, expected 100")
    if isinstance(selected, list) and \
            sorted(item.get("ordinal") for item in benchmarks) != sorted(selected):
        problems.append("selected ordinal inventory differs from embedded rows")
    if selection.get("selected") != _counts(benchmarks):
        problems.append("selected stratum counts differ from embedded rows")
    if asset.get("post_rng_witness_counts") != dict(sorted(
            witness_methods.items())):
        problems.append("post-RNG witness counts differ from embedded rows")
    banned = sorted(BANNED_ASSET_KEYS & set(_walk_keys(asset)))
    if banned:
        problems.append(f"asset contains identity/sensitive keys {banned}")
    expected_payload = stable_digest({
        key: value for key, value in asset.items() if key != "payload_sha256"
    })
    if asset.get("payload_sha256") != expected_payload:
        problems.append("asset payload digest drift")
    return sorted(set(problems))


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def replay_asset(asset: dict, *, limit: int | None = None,
                 emit_progress: bool = True) -> dict:
    if limit is not None and limit < 1:
        raise ReplayRefused("benchmark limit must be positive")
    problems = asset_problems(asset)
    if problems:
        raise ReplayRefused("asset validation: " + "; ".join(problems))
    timings = []
    verified = 0
    mismatch = []
    for round_asset in asset["rounds"]:
        rnd = rebuild_round(round_asset["setup"])
        assert rnd is not None
        for ply, play in enumerate(round_asset["plays"]):
            benchmark = play.get("benchmark")
            if benchmark is not None and (limit is None or verified < limit):
                record = benchmark["record"]
                bot = make_bot(POLICY)
                restore_random_state(
                    bot.rng, decode_rng_state(
                        asset["rng_states"][record["rng_state"]]))
                started = time.perf_counter()
                played = bot.decide_play(rnd, play["seat"])
                elapsed = time.perf_counter() - started
                try:
                    actual = semantic_record(bot.last_decision_record)
                    actual["rng_state"] = rng_state_ref(
                        encode_rng_state(actual["rng_state"]))
                except Exception as exc:
                    mismatch.append({
                        "round": round_asset["round"], "ply": ply,
                        "error": f"record: {type(exc).__name__}: {exc}",
                    })
                    actual = None
                differences = []
                if sorted(played) != sorted(play["cards"]):
                    differences.append("played_cards")
                record_drift = (
                    [] if actual is None
                    else semantic_differences(record, actual)
                )
                if record_drift:
                    differences.append("semantic_record")
                if rng_state_ref(encode_rng_state(bot.rng.getstate())) != \
                        benchmark["expected_post_rng_state"]:
                    differences.append("rng_advance")
                if differences:
                    mismatch.append({
                        "round": round_asset["round"], "ply": ply,
                        "ordinal": benchmark["ordinal"],
                        "differences": differences,
                        **({"semantic_paths": record_drift[:16]}
                           if record_drift else {}),
                    })
                timings.append({
                    "ordinal": benchmark["ordinal"],
                    "round": round_asset["round"], "ply": ply,
                    "phase": benchmark["phase"],
                    "decision": benchmark["decision"],
                    "candidate_count": benchmark["candidate_count"],
                    "search_seconds": elapsed,
                    "reported_search_seconds": (
                        None if actual is None else
                        float(bot.last_decision_record["search_secs"])
                    ),
                    "source_search_seconds": benchmark["source_search_secs"],
                    "projected_turn_seconds": max(
                        BOT_MIN_TURN_SECONDS, elapsed),
                })
                verified += 1
                if emit_progress and verified % 10 == 0:
                    print(
                        f"REPLAY_PROGRESS verified={verified} "
                        f"target={limit or TARGET_DECISIONS}", flush=True)
            rnd.play(play["seat"], list(play["cards"]))
    target = min(TARGET_DECISIONS, limit) if limit is not None \
        else TARGET_DECISIONS
    if verified != target:
        mismatch.append({"error": f"verified {verified}, expected {target}"})
    search = [item["search_seconds"] for item in timings]
    turns = [item["projected_turn_seconds"] for item in timings]
    result = {
        "schema": RESULT_SCHEMA,
        "asset_payload_sha256": asset["payload_sha256"],
        "asset_source_sha256": asset["source"]["sha256"],
        "policy": POLICY,
        "runtime": runtime_receipt(),
        "decisions": verified,
        "semantic_mismatches": mismatch,
        "exact_semantic_replay": not mismatch,
        "bot_min_turn_seconds": BOT_MIN_TURN_SECONDS,
        "timing": {
            "search": {
                "mean": statistics.fmean(search) if search else None,
                "p50": _percentile(search, 0.50),
                "p95": _percentile(search, 0.95),
                "max": max(search, default=None),
            },
            "projected_end_to_end": {
                "mean": statistics.fmean(turns) if turns else None,
                "p50": _percentile(turns, 0.50),
                "p95": _percentile(turns, 0.95),
                "max": max(turns, default=None),
            },
        },
        "gate": {
            "decisions_at_least_100": verified >= 100,
            "identical_replay": not mismatch,
            "compiled_fast_active": fast_active(),
            "p50_le_1_5": bool(turns) and _percentile(turns, 0.50) <= 1.5,
            "p95_le_4_0": bool(turns) and _percentile(turns, 0.95) <= 4.0,
            "max_le_8_0": bool(turns) and max(turns) <= 8.0,
        },
        "strata": {
            "phase": dict(sorted(Counter(
                item["phase"] for item in timings).items())),
            "decision": dict(sorted(Counter(
                item["decision"] for item in timings).items())),
            "candidate_count": dict(sorted(Counter(
                str(item["candidate_count"]) for item in timings).items())),
        },
        "decisions_detail": timings,
    }
    result["gate"]["all"] = all(result["gate"].values())
    return result


def _load(path: str | os.PathLike) -> dict:
    try:
        text = Path(path).read_text()
        if text.startswith(ENCODED_HEADER + "\n"):
            encoded = "".join(text.splitlines()[1:])
            raw = lzma.decompress(base64.b85decode(encoded.encode("ascii")))
            value = json.loads(raw)
        else:
            value = json.loads(text)
    except (OSError, UnicodeDecodeError, UnicodeEncodeError,
            json.JSONDecodeError, lzma.LZMAError, ValueError) as exc:
        raise ReplayRefused(f"JSON unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReplayRefused(f"JSON root is not a mapping: {path}")
    return value


def _write_exclusive(path: str | os.PathLike, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _write_asset_exclusive(path: str | os.PathLike, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode()
    encoded = base64.b85encode(lzma.compress(raw, preset=9)).decode("ascii")
    with path.open("x", encoding="ascii") as fh:
        fh.write(ENCODED_HEADER + "\n")
        for offset in range(0, len(encoded), 100):
            fh.write(encoded[offset:offset + 100] + "\n")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--log", required=True)
    capture.add_argument("--out", required=True)
    verify = sub.add_parser("verify-asset")
    verify.add_argument("--asset", required=True)
    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("--asset", required=True)
    benchmark.add_argument("--out")
    benchmark.add_argument("--limit", type=int)
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "capture":
            asset = capture_asset(args.log)
            if str(args.out).endswith(".b85"):
                _write_asset_exclusive(args.out, asset)
            else:
                _write_exclusive(args.out, asset)
            print(json.dumps({
                "asset": str(Path(args.out).resolve()),
                "payload_sha256": asset["payload_sha256"],
                "decisions": asset["selection"]["selected"]["decisions"],
            }, sort_keys=True))
        elif args.command == "verify-asset":
            asset = _load(args.asset)
            problems = asset_problems(asset)
            if problems:
                raise ReplayRefused("; ".join(problems))
            print(json.dumps({
                "verified": True,
                "payload_sha256": asset["payload_sha256"],
                "decisions": asset["selection"]["selected"]["decisions"],
            }, sort_keys=True))
        else:
            result = replay_asset(
                _load(args.asset), limit=args.limit, emit_progress=True)
            if args.out:
                _write_exclusive(args.out, result)
            print(json.dumps({
                "exact_semantic_replay": result["exact_semantic_replay"],
                "decisions": result["decisions"],
                "timing": result["timing"],
                "gate": result["gate"],
            }, sort_keys=True))
            if not result["exact_semantic_replay"]:
                return 3
    except Exception as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
