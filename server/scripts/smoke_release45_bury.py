"""Release-45 server-path smoke: the wide value-only bury (K=64) through the server.

The deploy gate for release 45. It builds the served bot
from a fly.toml ``[env]`` exactly as the server does (`cwv_serving_smoke.
build_production_bot`: registry registration from the env, ``make_bot(SHENGJI_BOT)``),
then for each of N first-round deals with four bot seats:

- streams the deal card by card and runs every declaration through the server's
  `_bot_declares` (the gated value declare goes off the loop through the shared
  model-search admission, as served), then the final declare call and
  ``finalize_declare``;
- runs the banker's bury through `_paced_bot_step` -> `_commit_bot_turn` (the
  snapshot path, never an in-process ``decide_bury``) and records its wall
  seconds, the bot's own elapsed seconds, ``wide_value.candidates``, the
  chooser, the fallback reason, the size of the legal widened pool, and that
  the turn committed exactly once (a second commit of the same prepared turn
  is refused and the room log holds one ``bury`` event);
- plays either the requested fixed number of turns or, with ``--full-round``,
  until the engine reaches ``round_end`` (bounded to 100 committed actions).

    SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \\
    python scripts/smoke_release45_bury.py --fly-toml ../fly.toml \\
        --map /data/models/smv3out-491ee4bf.npz=/local/smv3out-491ee4bf.npz \\
        --map /data/models/js-m1-0d17fd03.npz=/local/js-m1-0d17fd03.npz \\
        --receipt smoke.jsonl [--rounds 40] [--plays 4] [--expect-k 64]

The receipt is a JSON-lines file, created exclusively (an existing path is
refused, never overwritten) and fsynced line by line: a ``header`` line (the
expected recipe and arguments), a ``bot`` line (what was built), one ``round``
line per completed round, and one ``terminal`` line (``passed``, the typed
``failures`` of `validate_receipt`, a summary and, after an exception, the
typed error with a traceback tail).  The per-round room logs are kept in
``<receipt>.logs/`` beside it (also refused if it exists).  A crash after some
rounds therefore leaves the completed rows, the logs and a terminal failure row.

Exit status 0 only when `validate_receipt` finds nothing: see its docstring for
every rule.  Timings are this host's, not Fly's.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import time
import traceback
from pathlib import Path

SCHEMA = "release45-bury-smoke-v2"
#: the served recipe this gate binds
EXPECTED_CHOOSER = "wide-value"
EXPECTED_SWAPS = 1
EXPECTED_RECORD_SCHEMA = "cwv-bury-policy-v1"
EXPECTED_KITTY = 8
#: A first round has 100 engine play actions. Fixed-count runs may request
#: fewer; full-round mode stops on the engine's round_end transition.
MAX_PLAYS = 100


def _quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _events(log_path: Path, kind: str) -> list[dict]:
    if not log_path.exists():
        return []
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    return [row for row in rows if row["e"] == kind]


def wide_pool_size(hand, record: dict, ordering) -> tuple[int | None, bool]:
    """The number of distinct legal buries the K-capped widened set draws from:
    the record's ballot (its first ``ballot_count`` candidates, the literal
    incumbent at index 0) united by card multiset with the incumbent's
    single-card swaps over the banker's pre-bury 33-card ``hand``, exactly the
    stream `bury_wide_value.wide_bury_candidates` cuts at K.  Returns ``(size,
    exact)``; when the ballot alone exceeds the recorded candidates (only
    possible when the ballot is longer than K) the ballot length is a lower
    bound and ``exact`` is False.  ``(None, False)`` when the record lacks it."""
    from shengji.train.bury_wide_value import single_card_swaps

    wide = record.get("wide_value") or {}
    candidates = record.get("candidates")
    ballot_count = wide.get("ballot_count")
    if not isinstance(candidates, list) or not candidates or type(ballot_count) is not int:
        return None, False
    if ballot_count > len(candidates):
        return ballot_count, False
    ballot = candidates[:ballot_count]
    pool = {tuple(sorted(c)) for c in ballot}
    pool.update(tuple(sorted(s)) for s in single_card_swaps(list(hand), list(ballot[0]), ordering))
    return len(pool), True


async def _one_round(srv, bot, deal_seed: int, plays: int, log_dir: Path,
                     *, full_round: bool = False) -> dict:
    from shengji.engine.game import Game

    code = f"S{deal_seed}"
    room = srv.Room(code=code, log_dir=log_dir)
    room.game = Game(random.Random(deal_seed))
    rnd = room.game.start_round()
    assert rnd.first_round
    room.index_round()
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
    room.bot = bot
    declare_calls = []
    while rnd.phase == "deal":
        async with room.lock:
            seat, idx, card = rnd.deal_next()
            room.ids[seat][idx] = card
        started = time.perf_counter()
        await srv._bot_declares(room, [seat])
        declare_calls.append(time.perf_counter() - started)
    started = time.perf_counter()
    await srv._bot_declares(room, list(range(4)), final=True)
    declare_calls.append(time.perf_counter() - started)
    async with room.lock:
        rnd.finalize_declare()
    log = log_dir / f"{code}.jsonl"
    decisions = _events(log, "declare_decision")
    gated_seconds = [e["elapsed_seconds"] for e in _events(log, "model_search")
                     if e.get("phase") == "declare" and e.get("event") == "completed"]
    assert rnd.phase == "bury", rnd.phase
    banker = rnd.banker
    pre_bury_hand = list(rnd.hands[banker])
    started = time.perf_counter()
    prepared = await srv._paced_bot_step(room, banker, minimum_turn_seconds=0)
    if prepared is None:
        raise RuntimeError(f"deal {deal_seed}: server produced no bury turn")
    async with room.lock:
        committed = srv._commit_bot_turn(room, prepared)
        recommitted = srv._commit_bot_turn(room, prepared)
    wall = time.perf_counter() - started
    record = prepared.decision.snapshot.bot_copy.last_bury_record or {}
    wide = record.get("wide_value") or {}
    pool_size, pool_exact = wide_pool_size(pre_bury_hand, record, rnd.ordering)
    bury_events = _events(log, "bury")
    row = {
        "deal_seed": deal_seed, "banker": banker,
        "trump": rnd.trump_suit or "NT", "declared": rnd.declaration is not None,
        "bury_wall_seconds": round(wall, 4),
        "bury_compute_seconds": round(prepared.compute_seconds, 4),
        "bury_elapsed_seconds": (round(record["elapsed_seconds"], 4)
                                 if "elapsed_seconds" in record else None),
        "wide_seconds": round(wide["seconds"], 4) if "seconds" in wide else None,
        "schema": record.get("schema"),
        "arm": record.get("arm"),
        "chooser": "wide-value" if wide else ("fallback" if record.get("schema") == "cwv-bury-fallback-v1"
                                              else "arm"),
        "candidates": wide.get("candidates"),
        "wide_k": wide.get("k"),
        "wide_swaps": wide.get("swaps", 1) if wide else None,
        "ballot_count": wide.get("ballot_count"),
        "pre_bury_hand_size": len(pre_bury_hand),
        "pool_size": pool_size, "pool_size_exact": pool_exact,
        "chosen_is_incumbent": wide.get("chosen_is_incumbent"),
        "fallback_reason": record.get("fallback_reason", record.get("reason")),
        "committed": bool(committed), "recommit_refused": not recommitted,
        "bury_events": len(bury_events), "phase_after_bury": rnd.phase,
        "kitty_size": len(rnd.kitty),
        "declare_calls": len(declare_calls),
        "declare_max_call_seconds": round(max(declare_calls), 4),
        "value_declare_decisions": len(decisions),
        "value_declare_search_seconds": [round(s, 4) for s in gated_seconds],
        "plays_requested": MAX_PLAYS if full_round else plays,
        "full_round": full_round,
        "plays": [],
        "play_stop": None,
        "terminal_phase": None,
        "hands_empty": None,
        "trick_empty": None,
        "round_result": None,
    }
    for _ in range(MAX_PLAYS if full_round else plays):
        if rnd.phase != "play":
            row["play_stop"] = {"reason": "phase", "phase": rnd.phase}
            break
        seat = rnd.turn
        started = time.perf_counter()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        if prepared is None:
            raise RuntimeError(f"deal {deal_seed}: server produced no play turn")
        async with room.lock:
            ok = srv._commit_bot_turn(room, prepared)
        row["plays"].append({"seat": seat, "seconds": round(time.perf_counter() - started, 4),
                             "committed": bool(ok)})
        if full_round and rnd.phase == "round_end":
            result = room.game.result
            row.update({
                "play_stop": {"reason": "round_end", "phase": rnd.phase},
                "terminal_phase": rnd.phase,
                "hands_empty": not any(rnd.hands),
                "trick_empty": rnd.trick is None,
                "round_result": ({
                    "attacker_points": result.attacker_points,
                    "kitty_points": result.kitty_points,
                    "winner_team": result.winner_team,
                    "level_change": result.level_change,
                    "next_banker": result.next_banker,
                    "new_levels": list(result.new_levels),
                    "game_over": result.game_over,
                    "games_won": list(result.games_won),
                    "point_scored": result.point_scored,
                } if result is not None else None),
            })
            break
    return row


def _is_time(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _is_count(value) -> bool:
    return type(value) is int and value >= 0


def validate_receipt(bot_info: dict | None, rows: list[dict], expected: dict) -> list[dict]:
    """Every rule the release-45 bury smoke must satisfy; returns typed failures
    (``{"type", "deal_seed", "detail"}``), empty only on a pass.

    ``expected``: ``policy`` (the fly.toml SHENGJI_BOT), ``k`` (the served cap,
    64), ``rounds`` (>= 1), ``plays`` (0..MAX_PLAYS), ``full_round``,
    ``first_seed`` and ``budget_seconds`` (finite, > 0).

    Recipe: the built bot is ``policy``; the env and the bot both say wide value
    on with K = ``k`` and single-card swaps.  Coverage: exactly ``rounds`` rows,
    deal seeds ``first_seed`` + i in order.  Each bury: chooser ``wide-value``
    with record schema ``cwv-bury-policy-v1``, no fallback reason, the record's
    ``k`` and swaps the expected ones, ``candidates == min(k, pool_size)`` with
    ``pool_size`` the legal widened pool recorded for the row (the tiny-pool
    rule: a banker hand whose ballot plus distinct single swaps number fewer
    than K legitimately scores them all, and no fewer; a missing pool size
    fails); committed, the recommit refused, exactly one ``bury`` log event,
    phase ``play`` after it, an 8-card kitty; wall seconds under the budget.
    Each round: exactly ``plays`` fixed-count turns, each committed, or in
    full-round mode a genuine ``round_end`` witness with empty hands/trick,
    a complete engine result, and no uncommitted actions; at least one declare
    call.
    Every timing finite and >= 0; every count a nonnegative int."""
    failures: list[dict] = []

    def fail(kind, detail, seed=None):
        failures.append({"type": kind, "deal_seed": seed, "detail": detail})

    k, rounds, plays = expected.get("k"), expected.get("rounds"), expected.get("plays")
    full_round = expected.get("full_round") is True
    budget = expected.get("budget_seconds")
    if type(k) is not int or k < 2:
        fail("expected_invalid", f"k {k!r} is not an int >= 2")
    if type(rounds) is not int or rounds < 1:
        fail("expected_invalid", f"rounds {rounds!r} is not a positive int")
    if type(plays) is not int or not 0 <= plays <= MAX_PLAYS:
        fail("expected_invalid", f"plays {plays!r} is not an int in [0, {MAX_PLAYS}]")
    if not (_is_time(budget) and budget > 0):
        fail("expected_invalid", f"budget {budget!r} is not finite and positive")
    if failures:
        return failures

    if not bot_info:
        fail("recipe", "no bot was built")
    else:
        if bot_info.get("policy") != expected.get("policy"):
            fail("recipe", f"policy {bot_info.get('policy')!r} != expected {expected.get('policy')!r}")
        if bot_info.get("env_bury_wide_value") != "1" or bot_info.get("env_bury_wide_k") != str(k):
            fail("recipe", f"env wide value {bot_info.get('env_bury_wide_value')!r} / "
                           f"K {bot_info.get('env_bury_wide_k')!r}, expected '1' / '{k}'")
        if (bot_info.get("bot_bury_wide_value") is not True or bot_info.get("bot_bury_wide_k") != k
                or bot_info.get("bot_bury_wide_swaps") != EXPECTED_SWAPS):
            fail("recipe", f"bot wide value {bot_info.get('bot_bury_wide_value')!r} K "
                           f"{bot_info.get('bot_bury_wide_k')!r} swaps {bot_info.get('bot_bury_wide_swaps')!r}")

    if len(rows) != rounds:
        fail("coverage", f"{len(rows)} rounds completed of {rounds} requested")
    seeds = [r.get("deal_seed") for r in rows]
    if seeds != [expected.get("first_seed", 0) + i for i in range(len(rows))]:
        fail("coverage", f"deal seeds {seeds[:3]}... are not first_seed + i in order")

    for r in rows:
        seed = r.get("deal_seed")
        if r.get("chooser") != EXPECTED_CHOOSER or r.get("fallback_reason") is not None:
            fail("fallback", f"chooser {r.get('chooser')!r} fallback {r.get('fallback_reason')!r}", seed)
        if r.get("schema") != EXPECTED_RECORD_SCHEMA:
            fail("recipe", f"record schema {r.get('schema')!r}", seed)
        if r.get("wide_k") != k or r.get("wide_swaps") != EXPECTED_SWAPS:
            fail("recipe", f"record k {r.get('wide_k')!r} swaps {r.get('wide_swaps')!r}", seed)
        pool, candidates = r.get("pool_size"), r.get("candidates")
        if type(pool) is not int or pool < 1:
            fail("candidates", f"pool size {pool!r} not recorded", seed)
        elif type(candidates) is not int or candidates != min(k, pool):
            fail("candidates", f"candidates {candidates!r} != min(K={k}, pool={pool})", seed)
        if not (r.get("committed") is True and r.get("recommit_refused") is True
                and r.get("bury_events") == 1 and r.get("phase_after_bury") == "play"
                and r.get("kitty_size") == EXPECTED_KITTY):
            fail("commit", "bury not committed exactly once (committed "
                           f"{r.get('committed')!r}, recommit refused {r.get('recommit_refused')!r}, "
                           f"bury events {r.get('bury_events')!r}, phase {r.get('phase_after_bury')!r}, "
                           f"kitty {r.get('kitty_size')!r})", seed)
        timings = {name: r.get(name) for name in ("bury_wall_seconds", "bury_compute_seconds",
                                                  "bury_elapsed_seconds", "declare_max_call_seconds")}
        vd = r.get("value_declare_search_seconds")
        if not isinstance(vd, list):
            fail("timing", f"value_declare_search_seconds {vd!r} is not a list", seed)
            vd = []
        timings.update({f"value_declare_search_seconds[{i}]": s for i, s in enumerate(vd)})
        play_rows = r.get("plays")
        if not isinstance(play_rows, list):
            fail("plays", f"plays {play_rows!r} is not a list", seed)
            play_rows = []
        timings.update({f"plays[{i}].seconds": p.get("seconds") for i, p in enumerate(play_rows)})
        for name, value in timings.items():
            if not _is_time(value):
                fail("timing", f"{name} {value!r} is not finite and >= 0", seed)
        wall = r.get("bury_wall_seconds")
        if _is_time(wall) and wall >= budget:
            fail("budget", f"bury {wall} s >= budget {budget} s", seed)
        for name in ("declare_calls", "value_declare_decisions"):
            if not _is_count(r.get(name)):
                fail("count", f"{name} {r.get(name)!r} is not a nonnegative int", seed)
        if r.get("declare_calls") == 0:
            fail("count", "no declare call ran", seed)
        if full_round:
            if r.get("plays_requested") != MAX_PLAYS or r.get("full_round") is not True:
                fail("plays", "full-round row is not marked as a bounded full-round run", seed)
            if not 1 <= len(play_rows) <= MAX_PLAYS:
                fail("plays", f"full-round produced {len(play_rows)} actions, expected 1..{MAX_PLAYS}", seed)
            if r.get("play_stop") != {"reason": "round_end", "phase": "round_end"}:
                fail("terminal", f"full-round stop {r.get('play_stop')!r} is not round_end", seed)
            if (r.get("terminal_phase") != "round_end" or r.get("hands_empty") is not True
                    or r.get("trick_empty") is not True):
                fail("terminal", "full-round lacks empty-hand/empty-trick evidence", seed)
            result = r.get("round_result")
            if (not isinstance(result, dict) or type(result.get("winner_team")) is not int
                    or result.get("winner_team") not in (0, 1)
                    or type(result.get("attacker_points")) is not int
                    or result["attacker_points"] < 0
                    or type(result.get("kitty_points")) is not int
                    or type(result.get("level_change")) is not int
                    or type(result.get("next_banker")) is not int
                    or result.get("next_banker") not in range(4)
                    or type(result.get("game_over")) is not bool):
                fail("terminal", f"invalid full-round engine result {result!r}", seed)
        else:
            if r.get("plays_requested") != plays:
                fail("plays", f"row requested {r.get('plays_requested')!r} play turns, expected {plays}", seed)
            if len(play_rows) != plays or r.get("play_stop") is not None:
                fail("plays", f"{len(play_rows)} of {plays} play turns (stop {r.get('play_stop')!r})", seed)
        if not all(p.get("committed") is True for p in play_rows):
            fail("plays", "a play turn did not commit", seed)
    return failures


def summarize(rows: list[dict]) -> dict:
    """Timing and coverage summary over the finite values only (never raises)."""
    walls = [r.get("bury_wall_seconds") for r in rows]
    walls = [w for w in walls if _is_time(w)]
    plays_s = [p.get("seconds") for r in rows for p in (r.get("plays") or [])]
    plays_s = [s for s in plays_s if _is_time(s)]
    vd = [s for r in rows for s in (r.get("value_declare_search_seconds") or []) if _is_time(s)]
    declare = [r.get("declare_max_call_seconds") for r in rows]
    declare = [s for s in declare if _is_time(s)]
    return {
        "buries": len(rows),
        "bury_wall_p50": _quantile(walls, 0.5) if walls else None,
        "bury_wall_p90": _quantile(walls, 0.9) if walls else None,
        "bury_wall_max": max(walls) if walls else None,
        "bury_wall_mean": round(statistics.fmean(walls), 4) if walls else None,
        "fallbacks": sum(r.get("chooser") != EXPECTED_CHOOSER or r.get("fallback_reason") is not None
                         for r in rows),
        "candidates": sorted({r.get("candidates") for r in rows if type(r.get("candidates")) is int}),
        "pool_size_min": min((r["pool_size"] for r in rows if type(r.get("pool_size")) is int), default=None),
        "chosen_incumbent": sum(bool(r.get("chosen_is_incumbent")) for r in rows),
        "committed_exactly_once": sum(r.get("committed") is True and r.get("recommit_refused") is True
                                      and r.get("bury_events") == 1 for r in rows),
        "play_turns": sum(len(r.get("plays") or []) for r in rows),
        "play_p50": _quantile(plays_s, 0.5) if plays_s else None,
        "play_max": max(plays_s) if plays_s else None,
        "value_declare_decisions": sum(r.get("value_declare_decisions") or 0 for r in rows),
        "value_declare_search_max": max(vd) if vd else None,
        "declare_max_call_seconds": max(declare) if declare else None,
    }


def run(env: dict[str, str], *, rounds: int, plays: int, first_seed: int, receipt_path: Path,
        expect_k: int = 64, full_round: bool = False) -> dict:
    """Run the smoke, writing the receipt as it goes; returns the terminal row.

    Refuses (FileExistsError, before anything runs) an existing receipt path or
    log directory.  Any exception after the receipt opened becomes a terminal
    row with ``passed`` false and the typed error."""
    receipt_path = Path(receipt_path)
    logs_dir = receipt_path.with_name(receipt_path.name + ".logs")
    if logs_dir.exists():
        raise FileExistsError(f"log directory {logs_dir} exists: refusing to mix evidence")
    rows: list[dict] = []
    bot_info = None
    expected = {"policy": env.get("SHENGJI_BOT"), "k": expect_k, "rounds": rounds,
                "plays": MAX_PLAYS if full_round else plays, "full_round": full_round,
                "first_seed": first_seed, "budget_seconds": None}
    with open(receipt_path, "x") as fh:
        def write(obj):
            fh.write(json.dumps(obj, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

        try:
            logs_dir.mkdir()
            expected["budget_seconds"] = float(env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"])
            write({"kind": "header", "schema": SCHEMA, "expected": expected, "logs_dir": str(logs_dir),
                   "argv": sys.argv})
            from scripts.cwv_serving_smoke import build_production_bot, file_sha256
            from shengji.api import server as srv
            from shengji.engine import combos, fast

            name, bot = build_production_bot(env)
            bot_info = {"kind": "bot", "policy": name, "bot_class": type(bot).__name__,
                        "env_bury_wide_value": env.get("SHENGJI_PV_BURY_WIDE_VALUE"),
                        "env_bury_wide_k": env.get("SHENGJI_PV_BURY_WIDE_K"),
                        "bot_bury_wide_value": getattr(bot, "bury_wide_value", None),
                        "bot_bury_wide_k": getattr(bot, "bury_wide_k", None),
                        "bot_bury_wide_swaps": getattr(bot, "bury_wide_swaps", None),
                        "compiled_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
                        "files": {k: {"path": v, "sha256": file_sha256(v)} for k, v in env.items()
                                  if k.endswith("_CKPT")}}
            write(bot_info)

            async def scenario():
                for i in range(rounds):
                    if full_round:
                        row = await _one_round(srv, bot, first_seed + i, plays, logs_dir,
                                               full_round=True)
                    else:
                        row = await _one_round(srv, bot, first_seed + i, plays, logs_dir)
                    rows.append(row)
                    write({"kind": "round", **row})
            asyncio.run(scenario())
        except BaseException as exc:
            failures = validate_receipt(bot_info, rows, expected) if expected["budget_seconds"] else []
            failures.append({"type": "exception", "deal_seed": first_seed + len(rows),
                             "detail": f"{type(exc).__name__}: {exc}"})
            terminal = {"kind": "terminal", "passed": False, "rounds_completed": len(rows),
                        "error": {"type": type(exc).__name__, "message": str(exc),
                                  "traceback": traceback.format_exception(exc)[-8:]},
                        "failures": failures, "summary": summarize(rows)}
            write(terminal)
            if isinstance(exc, KeyboardInterrupt):
                raise
            return terminal
        failures = validate_receipt(bot_info, rows, expected)
        terminal = {"kind": "terminal", "passed": not failures, "rounds_completed": len(rows),
                    "error": None, "failures": failures, "summary": summarize(rows)}
        write(terminal)
    return terminal


def read_receipt(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def _plays_arg(text: str) -> int:
    value = int(text)
    if not 0 <= value <= MAX_PLAYS:
        raise argparse.ArgumentTypeError(f"--plays must be in [0, {MAX_PLAYS}]")
    return value


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive int")
    return value


def main(argv=None) -> int:
    from scripts.cwv_serving_smoke import env_from_fly_toml

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fly-toml", required=True)
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--rounds", type=_positive, default=40)
    parser.add_argument("--plays", type=_plays_arg, default=4)
    parser.add_argument("--full-round", action="store_true",
                        help="play until round_end, bounded to 100 committed actions")
    parser.add_argument("--first-seed", type=int, default=4500)
    parser.add_argument("--expect-k", type=_positive, default=64)
    parser.add_argument("--receipt", type=Path, required=True,
                        help="new JSON-lines receipt path (refused if it exists)")
    args = parser.parse_args(argv)
    env = env_from_fly_toml(args.fly_toml, dict(item.split("=", 1) for item in args.map))
    terminal = run(env, rounds=args.rounds, plays=args.plays, first_seed=args.first_seed,
                   receipt_path=args.receipt, expect_k=args.expect_k,
                   full_round=args.full_round)
    rows = [r for r in read_receipt(args.receipt) if r.get("kind") == "round"]
    print("deal  banker trump declared  bury_s  elapsed_s  cand  pool  chooser     fallback  "
          "committed_once  plays  vd_decisions")
    for r in rows:
        print(f"{r['deal_seed']:5d}  {r['banker']:6d} {r['trump']:5s} {str(r['declared']):8s}  "
              f"{r['bury_wall_seconds']!s:6s}  {r['bury_elapsed_seconds']!s:9s}  {r['candidates']!s:4s}  "
              f"{r['pool_size']!s:4s}  {r['chooser']:10s}  {r['fallback_reason']!s:8s}  "
              f"{str(r['committed'] and r['recommit_refused'] and r['bury_events'] == 1):14s}  "
              f"{len(r['plays'])}/{r['plays_requested']}    {r['value_declare_decisions']}")
    print(json.dumps({"summary": terminal["summary"], "error": terminal["error"]}, indent=1))
    for failure in terminal["failures"]:
        print("FAIL:", json.dumps(failure, sort_keys=True))
    print("PASS" if terminal["passed"] else "FAIL")
    return 0 if terminal["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
