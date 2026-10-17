"""Small, paired DEV duel for the hybrid multi-trick policy.

This is intentionally a library-first runner.  It writes a header followed by
completed mirrored rounds and emits a terminal summary only when every deal in
the requested prefix has both mirrors.  A killed process therefore leaves
useful rounds on disk, but never a misleading score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Callable, Mapping

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

from shengji.ai.env import play_round  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

SCHEMA = "shengji-hybrid-duel-v1"
SEAT_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)
PLAY_COUNTERS = ('play_decisions', 'pv_fallback_budget', 'pv_fallback_search_error',
                 'pv_fallback_other', 'pv_record_missing')
COUNTERS = (*PLAY_COUNTERS, 'hybrid_attempted', 'hybrid_applied', 'hybrid_changed',
            'hybrid_expired', 'hybrid_invalid')


class DuelRefusal(ValueError):
    """The output cannot support a paired strength readout."""


class DuelWallExpired(RuntimeError):
    """Cooperative wall cap reached between gameplay calls."""


class DuelFailure(RuntimeError):
    """A gameplay or factory failure; never convert this into a win."""


def _utility(log, candidate_team: int) -> int:
    level = max(1, int(getattr(log, "level_change", 0)))
    return (1 if int(log.winner_team) == candidate_team else -1) * level


def _telemetry(bot) -> dict:
    """Capture policy telemetry without requiring the policy to know this runner."""
    fields = getattr(bot, "hybrid_last_fields", None)
    if not isinstance(fields, Mapping):
        fields = {}
    names = ("attempted", "applied", "changed", "expired", "invalid")
    out = {f"hybrid_{name}": int(bool(fields.get(f"hybrid_{name}", False)))
           for name in names}
    cumulative = getattr(bot, "_hybrid_duel_counts", None)
    if isinstance(cumulative, Mapping):
        out.update({f"hybrid_{name}": int(cumulative.get(name, 0))
                    for name in names})
        out.update({name: int(cumulative.get(name, 0)) for name in PLAY_COUNTERS})
    # An adapter may expose cumulative counters; prefer those when present.
    for name in names:
        key = f"hybrid_{name}_count"
        if hasattr(bot, key):
            out[f"hybrid_{name}"] = int(getattr(bot, key))
    return out


def _instrument(bot, check_wall=None):
    """Count per-decision hybrid fields, without changing bot semantics."""
    counts = {name: 0 for name in ("attempted", "applied", "changed", "expired", "invalid")}
    counts.update({name: 0 for name in PLAY_COUNTERS})
    original = getattr(bot, "decide_play", None)
    if original is None or not callable(original):
        return counts

    def decide(self, *args, **kwargs):
        if check_wall:
            check_wall()
        self.hybrid_last_fields = None
        self.last_decision_record = None
        result = original(*args, **kwargs)
        counts['play_decisions'] += 1
        record = getattr(self, 'last_decision_record', None)
        if not isinstance(record, Mapping):
            counts['pv_record_missing'] += 1
        elif record.get('schema') == 'pv-search-fallback-v1':
            key = {'budget': 'pv_fallback_budget',
                   'search-error': 'pv_fallback_search_error'}.get(
                       record.get('reason'), 'pv_fallback_other')
            counts[key] += 1
        fields = getattr(self, "hybrid_last_fields", None)
        if isinstance(fields, Mapping):
            for name in ('attempted', 'applied', 'changed', 'expired', 'invalid'):
                if name in ('expired', 'invalid'):
                    reason = fields.get('hybrid_fallback', '')
                    value = reason == 'budget' if name == 'expired' else reason not in ('', 'budget', 'disabled', 'exact_endgame')
                else:
                    value = bool(fields.get(f"hybrid_{name}", False))
                counts[name] += int(value)
        return result

    try:
        bot.decide_play = types.MethodType(decide, bot)
    except (AttributeError, TypeError):
        # A non-extensible production bot remains playable; its telemetry is
        # still captured from the final fields below.
        pass
    bot._hybrid_duel_counts = counts
    for name in ('decide_declare', 'decide_bury'):
        method = getattr(bot, name, None)
        if method is not None and check_wall is not None:
            def bounded(*args, _method=method, **kwargs):
                check_wall()
                return _method(*args, **kwargs)
            setattr(bot, name, bounded)
    return counts


def _round(factory_candidate, factory_baseline, seed: int, flip: int,
           check_wall: Callable[[], None] | None = None) -> dict:
    # Exactly the same four per-seat seeds as evaluation.run_arm: two bots per
    # arm, with the arm order changing between mirrors.
    if check_wall: check_wall()
    a1 = factory_candidate(seed)
    if check_wall: check_wall()
    a2 = factory_candidate(seed + SEAT_OFFSETS[1])
    if check_wall: check_wall()
    b1 = factory_baseline(seed + SEAT_OFFSETS[2])
    if check_wall: check_wall()
    b2 = factory_baseline(seed + SEAT_OFFSETS[3])
    candidate = [a1, a2]
    baseline = [b1, b2]
    for bot in (*candidate, *baseline):
        _instrument(bot, check_wall)
    if flip == 0:
        bots = [a1, b1, a2, b2]
        candidate_team = 0
    else:
        bots = [b1, a1, b2, a2]
        candidate_team = 1
    if check_wall: check_wall()
    log = play_round(Game(random.Random(seed)), bots)
    return {
        "kind": "round", "seed": int(seed), "flip": int(flip),
        "candidate_team": candidate_team,
        "level_utility": _utility(log, candidate_team),
        "winner_team": int(log.winner_team),
        "level_change": int(log.level_change),
        "telemetry": {"candidate": [_telemetry(bot) for bot in candidate],
                       "baseline": [_telemetry(bot) for bot in baseline]},
    }


def _bootstrap(values, replicates=2000, seed=0):
    values = [float(v) for v in values]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    samples = sorted(statistics.fmean(rng.choices(values, k=n))
                    for _ in range(replicates))
    return [samples[max(0, int(.025 * replicates) - 1)],
            samples[min(replicates - 1, int(.975 * replicates))]]


def _read_jsonl(path: Path):
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_duel(path: str | Path) -> dict:
    """Validate a completed paired output and return its deal-cluster readout."""
    rows = _read_jsonl(Path(path))
    if not rows or rows[0].get("kind") != "header":
        raise DuelRefusal("header is missing")
    header = rows[0]
    if header.get("schema") != SCHEMA:
        raise DuelRefusal("wrong duel schema")
    hybrid = header.get("hybrid")
    if isinstance(hybrid, dict) and 'total_seconds' in hybrid:
        total = hybrid['total_seconds']
        if total is not None and (isinstance(total, bool)
                or not isinstance(total, (int, float))
                or not math.isfinite(total) or total <= 0):
            raise DuelRefusal("invalid hybrid total deadline")
        if hybrid.get('stop_fraction') != (0.8 if total is None else 1.0):
            raise DuelRefusal("hybrid deadline mode disagrees with stop fraction")
    terminal = [r for r in rows if r.get("kind") == "terminal"]
    rounds = [r for r in rows if r.get("kind") == "round"]
    if len(terminal) != 1:
        raise DuelRefusal("exactly one terminal record is required")
    if rows[-1].get("kind") != "terminal":
        raise DuelRefusal("terminal must be the final record")
    if sum(r.get("kind") == "header" for r in rows) != 1:
        raise DuelRefusal("duplicate header")
    if any(r.get("kind") not in {"header", "round", "terminal"} for r in rows):
        raise DuelRefusal("unknown record kind")
    keys = [(int(r["seed"]), int(r["flip"])) for r in rounds]
    if len(keys) != len(set(keys)):
        raise DuelRefusal("duplicate deal/mirror")
    term = terminal[0]
    status = term.get("status")
    if status not in {"COMPLETE", "PARTIAL", "FAILED"}:
        raise DuelRefusal("invalid terminal status")
    expected = int(term.get("completed_deals", -1))
    by_seed = {}
    for row in rounds:
        if int(row["flip"]) not in (0, 1):
            raise DuelRefusal("invalid mirror")
        by_seed.setdefault(int(row["seed"]), []).append(row)
    complete_seeds = [s for s, values in by_seed.items() if len(values) == 2]
    dangling = [s for s, values in by_seed.items() if len(values) == 1]
    if len(complete_seeds) != expected or len(dangling) > 1:
        raise DuelRefusal("unpaired or incomplete final data")
    seed0 = int(header.get("seed0", 0))
    if expected < 0 or expected > header['deals']:
        raise DuelRefusal('invalid completed population')
    if status == 'COMPLETE' and expected != header['deals']:
        raise DuelRefusal('complete terminal lacks requested deals')
    wanted = [(seed0 + i, flip) for i in range(expected) for flip in (0, 1)]
    if dangling:
        wanted.append((seed0 + expected, 0))
    if keys != wanted:
        raise DuelRefusal('rounds are not the ordered frozen mirror prefix')
    if sorted(complete_seeds) != list(range(seed0, seed0 + expected)):
        raise DuelRefusal("completed deals are not a frozen seed prefix")
    if status == "COMPLETE" and dangling:
        raise DuelRefusal("complete terminal has dangling mirror")
    for row in rounds:
        if row['candidate_team'] != row['flip'] or row['winner_team'] not in (0, 1) or type(row['level_change']) is not int or row['level_change'] < 0:
            raise DuelRefusal('invalid round result or candidate team')
        utility = _utility_fields(row)
        if utility != row.get("level_utility"):
            raise DuelRefusal("level utility disagrees with terminal fields")
        if not math.isfinite(float(row["level_utility"])):
            raise DuelRefusal("non-finite utility")
    if status == "FAILED":
        return {"schema": SCHEMA, "status": status, "deals": expected,
                "header": header, "rows": rounds}
    per_deal = [statistics.fmean(r["level_utility"] for r in by_seed[s])
                for s in sorted(complete_seeds)]
    mean = statistics.fmean(per_deal) if per_deal else None
    ci = _bootstrap(per_deal)
    if term.get("paired_utility_mean") != mean:
        raise DuelRefusal("terminal score does not match rounds")
    if term.get("paired_utility_ci") != ci:
        raise DuelRefusal("terminal interval does not match rounds")
    return {"schema": SCHEMA, "status": status, "deals": len(per_deal),
            "paired_utility_mean": mean, "paired_utility_ci": ci,
            "rows": rounds, "header": header}


def read_duel_shards(paths) -> dict:
    """Pool complete deal pairs, never worker means, from one fixed recipe.

    The caller must first verify the complete reserved shard list and seals.
    Partial mirrors stay in their source files and do not enter the estimate.
    This reader does not grant promotion or replace per-shard quality checks.
    """
    paths = list(paths)
    if not paths:
        raise DuelRefusal('no duel shards')
    shards = [read_duel(path) for path in paths]
    identity = None
    intervals = []
    values = []
    partial_mirrors = 0
    for shard in shards:
        if shard['status'] == 'FAILED':
            raise DuelRefusal('failed duel shard')
        header = shard['header']
        current = {k: v for k, v in header.items() if k not in ('seed0', 'deals')}
        if identity is None:
            identity = current
        elif identity != current:
            raise DuelRefusal('duel shard recipe mismatch')
        start, count = header['seed0'], header['deals']
        if type(start) is not int or type(count) is not int or count < 1:
            raise DuelRefusal('invalid shard seed interval')
        end = start + count
        if any(start < old_end and old_start < end for old_start, old_end in intervals):
            raise DuelRefusal('overlapping planned shard seeds')
        intervals.append((start, end))
        pairs = {}
        for row in shard['rows']:
            pairs.setdefault(row['seed'], []).append(row['level_utility'])
        for seed, pair in pairs.items():
            if len(pair) == 2:
                values.append((seed, statistics.fmean(pair)))
            else:
                partial_mirrors += len(pair)
    paired = [value for _, value in sorted(values)]
    return {'schema': SCHEMA, 'shards': len(shards),
            'status': 'COMPLETE' if all(s['status'] == 'COMPLETE' for s in shards) else 'PARTIAL',
            'requested_deals': sum(end - start for start, end in intervals),
            'deals': len(paired), 'unscored_mirrors': partial_mirrors,
            'paired_utility_mean': statistics.fmean(paired) if paired else None,
            'paired_utility_ci': _bootstrap(paired),
            'header_common': identity,
            'seed_intervals': sorted(intervals)}


def _utility_fields(row):
    return _utility(type("Log", (), {"winner_team": row["winner_team"],
                                      "level_change": row["level_change"]}),
                    int(row["candidate_team"]))


def rehearsal_counters(path: str | Path) -> dict:
    """Validate the terminal and expose only non-outcome capacity evidence.

    Counters cover written completed mirrors, including an unpaired final
    mirror; an interrupted mirror has no result and is not in this denominator.
    """
    result = read_duel(path)
    terminal = _read_jsonl(Path(path))[-1]
    totals = {arm: {key: 0 for key in COUNTERS} for arm in ('candidate', 'baseline')}
    for row in result['rows']:
        for arm in totals:
            bots = row.get('telemetry', {}).get(arm)
            if not isinstance(bots, list) or len(bots) != 2:
                raise DuelRefusal('missing per-arm capacity counters')
            for bot in bots:
                for key in COUNTERS:
                    value = bot.get(key)
                    if type(value) is not int or value < 0:
                        raise DuelRefusal('missing or invalid capacity counter')
                    totals[arm][key] += value
    return dict(status=result['status'], deals=result['header']['deals'],
                completed_deals=result['deals'], mirrors_written=len(result['rows']),
                elapsed_seconds=terminal['elapsed_seconds'], error=terminal.get('error'),
                counters=totals)


def run_duel(factory_candidate: Callable[[int], object],
             factory_baseline: Callable[[int], object], output: str | Path,
             *, deals: int, seed0: int, wall_seconds: float,
             header: Mapping[str, object], clock=time.monotonic, blind=False) -> dict:
    """Run one worker, preserving completed rounds under a wall cap."""
    if type(deals) is not int or deals < 1 or type(seed0) is not int or not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise ValueError("deals and wall_seconds must be positive")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    started = clock()
    rows = [{**dict(header), "kind": "header", "schema": SCHEMA, "deals": int(deals),
             "seed0": int(seed0), "wall_seconds": float(wall_seconds),
             }]
    with path.open("x") as fh:
        fh.write(json.dumps(rows[0], sort_keys=True) + "\n")
        fh.flush(); os.fsync(fh.fileno())
        saw_partial = False
        failure = None
        for index in range(deals):
            if clock() - started >= wall_seconds:
                saw_partial = True
                break
            seed = seed0 + index
            pair = []
            try:
                for flip in (0, 1):
                    if clock() - started >= wall_seconds:
                        break
                    def check_wall():
                        if clock() - started >= wall_seconds:
                            raise DuelWallExpired("wall cap reached")
                    row = _round(factory_candidate, factory_baseline, seed,
                                 flip, check_wall)
                    pair.append(row)
                    # A hard stop during the next mirror must retain this one.
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                    fh.flush(); os.fsync(fh.fileno())
            except DuelWallExpired as exc:
                saw_partial = True
            except Exception as exc:
                # Keep any completed mirror in ``pair`` for forensic use;
                # the incomplete deal remains unscorable.
                failure = f"{type(exc).__name__}: {exc}"
            if len(pair) != 2:
                # A partial pair is deliberately not scored, but already
                # completed rounds are retained for forensic inspection.
                saw_partial = True
                break
            rows.extend(pair)
        completed = {}
        for row in rows[1:]:
            completed.setdefault(row["seed"], []).append(row)
        complete = [v for v in completed.values() if len(v) == 2]
        status = "FAILED" if failure is not None else (
            "PARTIAL" if saw_partial or len(complete) != len(completed) else "COMPLETE")
        values = [statistics.fmean(r["level_utility"] for r in pair)
                  for pair in complete]
        mean = statistics.fmean(values) if values else None
        ci = _bootstrap(values)
        terminal = {"kind": "terminal", "schema": SCHEMA, "status": status,
                    "completed_deals": len(values),
                    "paired_utility_mean": mean if status != "FAILED" else None,
                    "paired_utility_ci": ci if status != "FAILED" else None,
                    "partial": len(values) < deals,
                    "elapsed_seconds": clock() - started}
        if failure is not None:
            terminal["error"] = failure
        fh.write(json.dumps(terminal, sort_keys=True) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    return rehearsal_counters(path) if blind else read_duel(path)


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deals", type=int, default=8)
    parser.add_argument("--seed0", type=int, default=70_260_904)
    parser.add_argument("--wall-seconds", type=float, default=900)
    parser.add_argument("--rehearsal", action="store_true",
                        help="mark the input recipe as rehearsal; does not alter scoring")
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--hybrid-total-seconds", type=float, default=None,
                        help="DEV total play deadline, activated only after baseline selection")
    args = parser.parse_args(argv)
    from scripts.cwv_serving_smoke import build_production_bot, env_from_fly_toml
    recipe = json.loads(args.recipe.read_text())
    env = env_from_fly_toml(recipe["fly_toml"], dict(recipe.get("map", [])))
    name, _ = build_production_bot(env)
    from shengji.ai.registry import make_bot
    from scripts.hybrid_duel_policy import attach_hybrid
    baseline = lambda seed: make_bot(name, seed=seed)
    candidate = lambda seed: attach_hybrid(make_bot(name, seed=seed), enabled=True,
                                           total_seconds=args.hybrid_total_seconds)
    candidate(args.seed0)
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SERVER,
                                     text=True).strip()
    package_paths = {key: value for key, value in env.items() if key.endswith('_CKPT')}
    packages = {key: {'path': value, 'sha256': hashlib.sha256(Path(value).read_bytes()).hexdigest()}
                for key, value in package_paths.items()}
    result = run_duel(candidate, baseline, args.output, deals=args.deals,
                      seed0=args.seed0, wall_seconds=args.wall_seconds,
                      blind=args.rehearsal,
                      header={"recipe": recipe, "policy": name,
                              "candidate": name + '-dev-two-completed-tricks',
                              "source_head": source, "env": env, "packages": packages,
                              "fly_toml_sha256": hashlib.sha256(Path(recipe['fly_toml']).read_bytes()).hexdigest(),
                              "hybrid": {"completed_tricks": 2, "exact_tail": 0,
                                         "skip_max_hand_le": 7,
                                         "stop_fraction": 0.8 if args.hybrid_total_seconds is None else 1.0,
                                         "total_seconds": args.hybrid_total_seconds},
                              "rehearsal": bool(args.rehearsal)})
    printed = result if args.rehearsal else {k: result.get(k) for k in (
        'status', 'deals', 'paired_utility_mean', 'paired_utility_ci')}
    print(json.dumps(printed, sort_keys=True))


if __name__ == "__main__":
    _main()
