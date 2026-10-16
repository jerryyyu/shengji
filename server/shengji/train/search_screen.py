"""Cheap resumable DEV duel of learned root search vs production MC-LCB.

No deployment, freeze, one-shot gate, or fresh training. Completed mirrored
deal shards survive errors. Outcome summaries are descriptive; CPU work and
coverage are separate measured facts, never inferred from equal N settings.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from functools import lru_cache
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import random
import tempfile
import time

from ..ai.registry import make_bot
from ..engine.cards import RANKS
from ..engine.game import Game
from ..engine.round import Round
from ..oracle import screen as duel


_SCALARS = (str, int, float, bool, type(None))
TRACE_LIST_MAX = 16     # a numeric list up to this long is persisted whole


def trace_fields(rec, skip=()):
    """The persisted form of a served bot's decision record (#679 B6).

    Scalars are kept exactly as before (same keys, same order, same values),
    so an existing reader parses a new shard unchanged.  Everything else is
    ADDED after them, never silently dropped:

    * every list/tuple field gets ``<field>__len``; a numeric list of at most
      ``TRACE_LIST_MAX`` entries is also kept whole under its own name (e.g.
      ``diversity_skipped``, ``tiebreak_near_set``, ``admitted_indices``);
      the bounded ``exact_lead_base_played`` string list is also retained so
      the reader can verify the final-action change instead of trusting a flag;
    * ``trace_dropped_fields`` counts the fields whose full value is NOT in the
      trace (long or non-numeric lists, kept as their length only; dicts and
      other objects).  It is always present, so 0 means "nothing lost", and a
      missing list field in a new shard means the bot did not record it.

    A summary key never overwrites a key the record itself carries."""
    out = {k: v for k, v in rec.items() if k not in skip and isinstance(v, _SCALARS)}
    dropped = 0
    for k, v in rec.items():
        if k in skip or isinstance(v, _SCALARS):
            continue
        whole = False
        if isinstance(v, (list, tuple)):
            if f"{k}__len" not in rec:
                out[f"{k}__len"] = len(v)
            if (len(v) <= TRACE_LIST_MAX and k not in out
                    and (all(isinstance(x, (int, float)) for x in v)
                         or (k == 'exact_lead_base_played'
                             and all(isinstance(x, str) for x in v)))):
                out[k] = list(v)
                whole = True
        dropped += not whole
    if "trace_dropped_fields" not in rec:
        out["trace_dropped_fields"] = dropped
    return out


class TimedPolicy:
    def __init__(self, bot):
        self.bot = bot
        self.decision_cpu_seconds = self.decision_wall_seconds = 0.0
        self.decisions = []
        self.bury_decisions = []        # bury receipts, apart from the play traces

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def decide_declare(self, rnd, seat, final=False):
        """Declare through the wrapped bot; a bot that publishes a declare record
        (pv-search's ``value_declare`` rule: ``pv-value-declare-decision-v1``, set
        only on the calls its gate admits) leaves its scalar receipt in
        ``declare_decisions``, created on the first one, so a screen without
        the rule carries no new key."""
        try:
            return self.bot.decide_declare(rnd, seat, final=final)
        finally:
            rec = getattr(self.bot, "last_declare_record", None)
            if rec:
                self.__dict__.setdefault("declare_decisions", []).append({
                    "seat": seat, "phase": "declare", **trace_fields(rec),
                })

    def decide_bury(self, rnd, seat):
        """Bury through the wrapped bot; a bot that publishes a bury record (the served
        CWV bury arms: ``cwv-bury-policy-v1`` / ``cwv-bury-fallback-v1``) leaves its
        scalar receipt in ``decisions`` so internal bury fallbacks are countable."""
        try:
            return self.bot.decide_bury(rnd, seat)
        finally:
            rec = getattr(self.bot, "last_bury_record", None)
            if rec:
                self.bury_decisions.append({
                    "seat": seat, "phase": "bury", **trace_fields(rec),
                })

    def decide_play(self, rnd, seat):
        cpu, wall = time.process_time(), time.perf_counter()
        try:
            return self.bot.decide_play(rnd, seat)
        finally:
            self.decision_cpu_seconds += time.process_time() - cpu
            self.decision_wall_seconds += time.perf_counter() - wall
            # A policy without a decision record (SmartBot, the heuristic) is a
            # legal opponent since #647 and leaves NO trace, on purpose: its
            # time is still counted above, and the summary reports its world
            # budget as None rather than inventing one. Reading the attribute
            # bare aborted the first any-policy lane at its first decision
            # (x36c, 2026-09-26): the smoke went through play_round, never
            # through this wrapper.
            rec = getattr(self.bot, "last_decision_record", None)
            if rec and "candidates" not in rec:
                # A served policy with its own record (release 29's pv-search
                # `pv-search-decision-v1` / `pv-search-fallback-v1`): keep the
                # scalar receipt plus bounded list summaries (`trace_fields`),
                # not the MC shortlist shape.
                self.decisions.append({
                    "seat": seat, "trick": len(rnd.history), "played": rec.get("played"),
                    **trace_fields(rec, skip=("played",)),
                })
            elif rec:
                challenger = rec.get("report_candidate_index")
                learned = rec.get("learned_search", {})
                self.decisions.append({
                    "seat": seat, "trick": len(rnd.history),
                    "incumbent": rec["candidates"][0], "played": rec["played"],
                    "challenger": (rec["candidates"][challenger]
                                   if challenger is not None else None),
                    "reason": rec["reason"], "report": rec.get("report_fold"),
                    "selection_N": rec["n_determinizations"],
                    "report_worlds": rec["report_worlds_requested"],
                    "legal_size": learned.get("legal_size"),
                    "production_size": learned.get("production_size"),
                    "ranking_basis": learned.get("ranking_basis"),
                    "leaf_tricks": learned.get("config", {}).get("leaf_tricks"),
                    "counts": learned.get("counts"),
                })


@lru_cache(maxsize=1)
def loaded_heads(path, allow_legacy, batch_size):
    import torch
    from .search_inference import SearchHeads
    torch.set_num_threads(1)
    return SearchHeads.from_checkpoint(path, allow_legacy=allow_legacy, batch_size=batch_size)


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, val in getattr(bot, "learned_counts", {}).items():
            out[f"learned_{key}"] = out.get(f"learned_{key}", 0) + val
    for name in ("decision_cpu_seconds", "decision_wall_seconds", "enumeration_secs",
                 "learned_inference_secs"):
        out[name] = sum(getattr(bot, name, 0.0) for bot in bots)
    # Legacy counter rollouts includes replaced leaf evaluations. Do not label
    # those as full continuations in the new report.
    out["continuation_rollouts"] = out["rollouts"] - out.get("learned_value_evaluations", 0)
    out["total_rollouts"] = out["continuation_rollouts"]
    return out


def run_cluster(config, cluster):
    """Both mirrors are one atomic, independently replayable work unit."""
    created = []
    def factory(_config, side, seed):
        if side == "baseline" or config["arm"] == "none":
            bot = make_bot("mc-s0-report-lcb", seed=seed)
        else:
            from .search_policy import LearnedSearchBot, SearchConfig
            heads = loaded_heads(config["checkpoint"], config["allow_legacy"], config["batch_size"])
            expected = config.get("checkpoint_sha256")
            if expected and heads.metadata["checkpoint_sha256"] != expected:
                raise ValueError("checkpoint changed between parent and worker")
            bot = LearnedSearchBot(heads, seed=seed, config=SearchConfig(
                arm=config["arm"], leaf_tricks=config["leaf_tricks"],
                paired_advantage=config.get("paired_advantage", False)))
        # Small overrides are ONLY for source-wiring tests, not labelled as
        # production-work evidence by summarize().
        bot.N_DETERMINIZATIONS = config["select_worlds"]
        if side == "arm" and config["arm"] != "none":
            bot.N_DETERMINIZATIONS = config.get("candidate_select_worlds") or config["select_worlds"]
        bot.REPORT_FOLD_WORLDS = config["report_worlds"]
        wrapped = TimedPolicy(bot)
        created.append((side, wrapped))
        return wrapped

    rank = RANKS[cluster % len(RANKS)]

    def game_factory(rng):
        game = Game(rng)
        game.level_idx = [RANKS.index(rank), RANKS.index(rank)]
        # Game.start_round uses rank 2 when banker is not yet known. Keep the
        # first-round declaration rule but explicitly construct this rank.
        def start():
            game.round = Round(rank, None, game.rng)
            game.round_no += 1
            return game.round
        game.start_round = start
        return game

    base = duel.build_config(arm="none", select_worlds=config["select_worlds"],
                             report_worlds=config["report_worlds"])
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(base, cluster, seed, mirror,
                bot_factory=factory, counter_fn=work_counters, game_factory=game_factory)
            for mirror in (0, 1)]
    for record, _ in rows:
        record["arm"] = config["arm"]
    return {"cluster": cluster, "seed": seed, "rank": rank,
            "records": [r for r, _ in rows], "timings": [t for _, t in rows],
            "decision_traces": [{"mirror": i // 4, "side": side,
                                 "decisions": bot.decisions}
                                for i, (side, bot) in enumerate(created)]}


def exact_lead_summary(shards):
    """Descriptive coverage of persisted traces, never a gameplay gain estimate.

    Missing telemetry includes flag-off policies and early fallbacks; it cannot
    be counted as ineligible. Override values price ballot entries, not the
    final played actions, so no value-delta average is reported here.
    """
    import math

    statuses = ('ineligible', 'skipped_budget', 'abandoned', 'complete')
    kinds = ('unchanged', 'higher', 'tie', 'lower', 'post_selection_override')
    out = {side: dict(total_traces=0, missing=0, invalid=0,
                     statuses=dict.fromkeys(statuses, 0),
                     change_kinds=dict.fromkeys(kinds, 0), changed=0)
           for side in ('arm', 'baseline')}
    # Keep abandoned work: successful calls alone understate optional-stage cost.
    costs = {side: {status: dict(samples=[], missing=0, invalid=0)
                    for status in ('complete', 'abandoned')}
             for side in out}
    for shard in shards:
        for group in shard.get('decision_traces', []):
            side = group['side']
            if side not in out:
                raise ValueError('unknown exact-lead trace side')
            counts = out[side]
            for row in group['decisions']:
                counts['total_traces'] += 1
                status = row.get('exact_lead_status')
                if status is None:
                    counts['missing'] += 1
                    continue
                if status not in statuses:
                    counts['invalid'] += 1
                    continue
                if status in costs[side]:
                    cost = costs[side][status]
                    seconds = row.get('exact_lead_seconds')
                    if seconds is None:
                        cost['missing'] += 1
                    elif type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                        cost['invalid'] += 1
                    else:
                        cost['samples'].append(seconds)
                if status == 'complete':
                    kind = row.get('exact_lead_change_kind')
                    changed = row.get('exact_lead_changed')
                    delta = row.get('exact_lead_selected_level_delta')
                    worlds = row.get('exact_lead_worlds_completed')
                    played = row.get('played')
                    base_played = row.get('exact_lead_base_played')
                    selected = row.get('exact_lead_selected_level_mean')
                    base_value = row.get('exact_lead_base_level_mean')
                    cards_valid = all(isinstance(cards, list) and bool(cards)
                                      and all(isinstance(c, str) for c in cards)
                                      for cards in (played, base_played))
                    valid = (kind in kinds and type(changed) is bool
                             and changed == (kind != 'unchanged')
                             and type(worlds) is int and worlds > 0
                             and all(type(v) in (int, float) and math.isfinite(v)
                                     for v in (delta, selected, base_value))
                             and cards_valid)
                    if valid:
                        valid = (changed == (sorted(played) != sorted(base_played))
                                 and math.isclose(delta, selected - base_value,
                                                  rel_tol=1e-12, abs_tol=1e-12))
                    if valid and kind in ('higher', 'tie', 'lower'):
                        valid = ((delta > 0) if kind == 'higher' else
                                 (delta < 0) if kind == 'lower' else delta == 0)
                    if not valid:
                        counts['invalid'] += 1
                        continue
                    counts['change_kinds'][kind] += 1
                    counts['changed'] += int(changed)
                counts['statuses'][status] += 1
    for side, groups in costs.items():
        for status, cost in groups.items():
            samples = sorted(cost.pop('samples'))
            n = len(samples)
            cost.update(count=n, total_seconds=sum(samples),
                        p50_seconds=samples[math.ceil(.5 * n) - 1] if n else None,
                        p90_seconds=samples[math.ceil(.9 * n) - 1] if n else None,
                        max_seconds=samples[-1] if n else None)
        out[side]['stage_cost'] = groups
    return {'schema': 'exact-lead-trace-summary-v1', 'sides': out,
            'claim': 'descriptive sampled-world mechanism counts, not playing strength',
            'cost_claim': 'optional-stage wall time, nearest-rank quantiles; not whole-decision latency',
            'cost_valid': all(c['invalid'] == 0 for groups in costs.values() for c in groups.values()),
            'cost_complete': all(c['missing'] == 0 and c['invalid'] == 0
                                 for groups in costs.values() for c in groups.values()),
            'valid': all(c['invalid'] == 0 for c in out.values())}


def exact_follow_summary(shards):
    """Count and validate persisted exact-follow stage receipts.

    A decision without exact-follow telemetry is an ordinary missing receipt,
    not an ineligible attempt.  A complete receipt may retain only the length
    of a long score list; that is counted explicitly rather than treated as a
    successful score publication.
    """
    sides = {
        side: dict(total_traces=0, missing=0, invalid=0, attempted=0,
                   complete=0, soft_budget=0, hard_budget=0, refusal=0,
                   other_error=0, applied=0, score_unavailable=0)
        for side in ('arm', 'baseline')
    }
    reasons = {None, 'soft_budget', 'hard_budget', 'error'}

    def finite_score_list(value):
        return (isinstance(value, list) and bool(value)
                and all(type(score) in (int, float) and math.isfinite(score)
                        for score in value))

    for shard in shards:
        for group in shard.get('decision_traces', []):
            side = group.get('side')
            if side not in sides:
                raise ValueError('unknown exact-follow trace side')
            counts = sides[side]
            for row in group.get('decisions', []):
                counts['total_traces'] += 1
                if not isinstance(row, dict):
                    counts['invalid'] += 1
                    continue
                present = {key for key in row if key.startswith('exact_follow_')}
                if not present:
                    counts['missing'] += 1
                    continue

                attempted = row.get('exact_follow_attempted')
                if attempted is True:
                    counts['attempted'] += 1
                valid = type(attempted) is bool and attempted is True
                applied = row.get('exact_follow_applied')
                abandoned = row.get('exact_follow_abandoned')
                valid = valid and type(applied) is bool
                valid = valid and 'exact_follow_abandoned' in row
                valid = valid and (
                    abandoned is None
                    or (type(abandoned) is str and abandoned in reasons)
                )
                if not valid:
                    counts['invalid'] += 1
                    continue

                if abandoned is not None:
                    # An abandoned optional stage never publishes partial result
                    # data, including a bounded score-list marker.
                    valid = (applied is False
                             and type(row.get('exact_follow_error')) is str
                             and bool(row.get('exact_follow_error'))
                             and 'exact_follow_worlds' not in row
                             and 'exact_follow_nodes' not in row
                             and 'exact_follow_scores' not in row
                             and 'exact_follow_scores__len' not in row)
                    if not valid:
                        counts['invalid'] += 1
                        continue
                    if abandoned in ('soft_budget', 'hard_budget'):
                        counts[abandoned] += 1
                    else:
                        if row.get('exact_follow_error') == 'ExactFollowRefusal':
                            counts['refusal'] += 1
                        else:
                            counts['other_error'] += 1
                    continue

                worlds = row.get('exact_follow_worlds')
                nodes = row.get('exact_follow_nodes')
                scores_present = 'exact_follow_scores' in row
                scores = row.get('exact_follow_scores')
                score_len_present = 'exact_follow_scores__len' in row
                score_len = row.get('exact_follow_scores__len')
                valid = (type(worlds) is int and worlds > 0
                         and type(nodes) is int and nodes >= 0
                         and row.get('exact_follow_error') is None)
                if scores_present:
                    valid = valid and finite_score_list(scores) and len(scores) > 1
                    if score_len_present:
                        valid = valid and type(score_len) is int and score_len == len(scores)
                else:
                    # A missing list is valid only when trace_fields recorded
                    # the source list's bounded length.
                    valid = (valid and score_len_present and type(score_len) is int
                             and score_len > TRACE_LIST_MAX)
                if not valid:
                    counts['invalid'] += 1
                    continue
                counts['complete'] += 1
                counts['applied'] += int(applied)
                if not scores_present:
                    counts['score_unavailable'] += 1

    return {'schema': 'exact-follow-trace-summary-v1', 'sides': sides,
            'claim': 'descriptive exact-follow receipt counts; no latency or playing-strength inference',
            'valid': all(counts['invalid'] == 0 for counts in sides.values())}


def summary_for(shards, config):
    records = [r for shard in shards for r in shard["records"]]
    base = duel.build_config(arm="none", select_worlds=config["select_worlds"],
                             report_worlds=config["report_worlds"])
    out = duel.summarize(records, base, seed0=config["seed0"], replicates=1000)
    totals = out["work_totals"]
    def ratio(name):
        denominator = totals["baseline"].get(name, 0)
        return totals["arm"].get(name, 0) / denominator if denominator else None
    cpu_ratio = ratio("decision_cpu_seconds")
    out.update({
        "schema": "learned-search-dev-summary-v1", "arm": config["arm"],
        "claim": "small DEV paired screen; not confirmation, promotion or deployment",
        "arm_description": "learned root allocation and optional bounded-trick value; production fresh-world report",
        "config": config, "completed_clusters": len(shards),
        "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": cpu_ratio,
        "arm_over_baseline_decision_wall": ratio("decision_wall_seconds"),
        "candidate_evaluation_ratio": ratio("rollouts"),
        "no_more_measured_decision_cpu": cpu_ratio is not None and cpu_ratio <= 1.0,
        "equal_work_strength_claim": False,
        "exact_lead": exact_lead_summary(shards),
        "exact_follow": exact_follow_summary(shards),
        "work_caveat": ("N is matched against the production ballot per searched state, not full cost. "
                        "An explicit candidate N override can reduce learned selection cost. "
                        "Different trajectories/extra unlocked decisions change aggregate work. "
                        "CPU includes enumeration, model calls and report. A ratio above 1 cannot "
                        "support an equal-work improvement claim; this small run is a cost diagnostic."),
    })
    return out


def _publish(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    # A crash may leave a temporary file, never an occupied scientific slot.
    # Unique temporary names allow a restart to reuse all completed pairs.
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    rank = RANKS[cluster % len(RANKS)]
    if (shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or len(rows) != 2
            or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank or r.get("arm") != config["arm"] for r in rows)):
        raise ValueError("completed shard does not contain its exact mirrored pair")
    return shard


def execution_source_identity(package):
    """One first-consumption stamp, not repeated per state or worker.

    Include Python dependencies (engine, game driver, heuristic and sampler),
    not just the adapter. Otherwise an old pair could mix with changed rules
    or continuation semantics when a run resumes. Bind any loaded native
    candidate as well; ignored bytecode caches are not source artifacts.
    """
    paths = sorted([*package.rglob("*.py"), *package.rglob("*.so")])
    return {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def bind_output_config(output, config):
    output.mkdir(parents=True, exist_ok=True)
    path = output / "config.json"
    if path.exists():
        if json.loads(path.read_text()) != config:
            raise ValueError("existing output belongs to a different configuration")
    else:
        _publish(path, config)


def _run_pending(config, pending, shards, *, output, workers,
                 executor_factory=None, task_fn=run_cluster):
    """Run at most ``workers`` pairs, retaining successes after a failure.

    Failure is published as soon as its future completes.  Futures already
    running are drained so their valid immutable shards remain reusable; work
    not yet running is cancelled and never replenished.
    """
    if not pending:
        return
    initial_completed = len(shards)
    requested = initial_completed + len(pending)
    failure_path = output / "failure.json"
    failed: set[int] = set()
    first_error = None
    started = time.perf_counter()
    next_cluster = iter(pending)
    tasks = {}
    if executor_factory is None:
        ctx = multiprocessing.get_context("spawn")
        executor_factory = lambda n: ProcessPoolExecutor(max_workers=n, mp_context=ctx)
    pool = executor_factory(min(workers, len(pending)))

    def publish_failure():
        _publish(failure_path, {
            "type": type(first_error).__name__,
            "message": str(first_error),
            "failed_clusters": sorted(failed),
            "completed_clusters": sorted(s["cluster"] for s in shards),
            "recovery": "rerun the identical command; completed mirrored pairs are retained",
        })

    def submit_one():
        cluster = next(next_cluster)
        tasks[pool.submit(task_fn, config, cluster)] = cluster

    def progress():
        elapsed = time.perf_counter() - started
        done_new = len(shards) - initial_completed
        if first_error is not None:
            print(f"{len(shards)}/{requested} pairs "
                  f"({100*len(shards)/requested:.1f}%) "
                  f"elapsed={elapsed:.1f}s draining after failure "
                  f"workers={workers}", flush=True)
        else:
            eta = (f"{elapsed / done_new * (len(pending) - done_new):.1f}s"
                   if done_new else "pending first pair")
            print(f"{len(shards)}/{requested} pairs "
                  f"({100*len(shards)/requested:.1f}%) "
                  f"elapsed={elapsed:.1f}s eta={eta} workers={workers}", flush=True)

    try:
        for _ in range(min(workers, len(pending))):
            submit_one()
        while tasks:
            finished, still_pending = wait(
                set(tasks), timeout=30, return_when=FIRST_COMPLETED)
            if not finished:
                progress()
                continue
            submitted = tasks
            tasks = {future: submitted[future] for future in still_pending}
            for future in finished:
                cluster = submitted[future]
                try:
                    shard = future.result()
                    _publish(output / f"cluster-{shard['cluster']:05}.json", shard)
                    shards.append(shard)
                except BaseException as exc:
                    failed.add(cluster)
                    if first_error is None:
                        first_error = exc
                    publish_failure()
            if first_error is None:
                while len(tasks) < workers:
                    try:
                        submit_one()
                    except StopIteration:
                        break
            else:
                # Already-submitted but not-yet-running tasks must not become
                # new work after the first failure.
                retained = {}
                for future, cluster in tasks.items():
                    if not future.cancel():
                        retained[future] = cluster
                tasks = retained
                publish_failure()
            progress()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if first_error is not None:
        raise first_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--allow-legacy", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm", choices=("none", "uniform", "prior", "value", "both"), default="both")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--leaf-tricks", type=int, choices=(0, 1, 3), default=1)
    parser.add_argument("--paired-advantage", action="store_true",
                        help="rank and allocate by paired improvement over the incumbent")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--select-worlds", type=int, default=30)
    parser.add_argument("--candidate-select-worlds", type=int,
                        help="candidate-only selection N for outcome-blind CPU budget calibration")
    parser.add_argument("--report-worlds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.clusters < 1 or args.workers < 1 or args.select_worlds < 1 or args.report_worlds < 30:
        parser.error("positive clusters/workers/selection and >=30 report worlds required")
    if args.candidate_select_worlds is not None and args.candidate_select_worlds < 1:
        parser.error("candidate-select-worlds must be positive")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    heads = loaded_heads(str(Path(args.checkpoint).resolve()), args.allow_legacy, args.batch_size)
    config = {k: v for k, v in vars(args).items() if k not in {"out", "workers"}}
    config["checkpoint"] = str(Path(args.checkpoint).resolve())
    config["checkpoint_sha256"] = heads.metadata["checkpoint_sha256"]
    # Source changes must not silently mix different policies into one sample.
    package = Path(__file__).resolve().parents[1]
    config["source_sha256"] = execution_source_identity(package)
    config["runtime"] = {"python": platform.python_version(), "platform": platform.platform(),
                         "environment": {k: v for k, v in sorted(os.environ.items())
                                         if k.startswith("SHENGJI_") or k in
                                         {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"}}}
    config["model_metadata"] = heads.metadata
    bind_output_config(args.out, config)
    shards = []
    pending = []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    try:
        _run_pending(config, pending, shards, output=args.out, workers=args.workers)
    except Exception as exc:
        if not (args.out / "failure.json").exists():
            _publish(args.out / "failure.json", {
                "type": type(exc).__name__, "message": str(exc),
                "failed_clusters": [],
                "completed_clusters": sorted(s["cluster"] for s in shards),
                "recovery": "rerun the identical command; completed mirrored pairs are retained",
            })
        raise
    finally:
        if shards:
            _publish(args.out / "summary.json", summary_for(sorted(shards, key=lambda s: s["cluster"]), config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
