"""Fail-closed runner for the paired 512-state lead-ballot pilot.

Each record owns every arm for one state.  Proposal/oracle/report folds use
independent named streams; every arm is reported on the same ordered report
worlds.  Sharding is by state, never by arm.

Eight-state deterministic smoke (run twice to different output paths):

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python scripts/pilot_run.py \
      --states rl_data/pilot_states.v4.json --limit 8 \
      --out runs/logs/pilot-smoke-a.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                                  # noqa: E402
from shengji.ai.registry import make_bot                              # noqa: E402
from shengji.pilot_arms import ARMS, propose                          # noqa: E402
from shengji.pilot_folds import draw_folds                            # noqa: E402
from shengji.pilot_score import (choose_action, oracle_reference,     # noqa: E402
                                 report_regret, score_action, union_ballot,
                                 worlds_for_equal_work)

RUN_SCHEMA = "lead-ballot-pilot-v1"
SOURCES = {"original": "rl_data/highn_corpus_all.jsonl",
           "late": "rl_data/highn_late_air.jsonl",
           "deep": "rl_data/deep_leads.v1.jsonl"}
EQUAL_WORK_ARMS = tuple(a for a in ARMS
                        if a not in ("full_universe", "mc_more_full_work"))
SAMPLER_COUNTERS = ("zero_world_decisions", "rejected_worlds",
                    "impossible_worlds")


def digest(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def stable_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     default=list).encode()
    return hashlib.sha256(raw).hexdigest()


def sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in SAMPLER_COUNTERS}


def sampler_delta(before: dict, bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) - before[name]
            for name in SAMPLER_COUNTERS}


def load_rows(states: list[dict]) -> dict[tuple[str, int, int], dict]:
    """Index each needed corpus once; the old runner rescanned it per state."""
    wanted = {}
    for state in states:
        source = state["source"]
        if source not in SOURCES:
            raise RuntimeError(f"unknown state source {source!r}")
        wanted.setdefault(source, set()).add((state["seed"], state["ply"]))
    found = {}
    for source, keys in wanted.items():
        path = SOURCES[source]
        if not os.path.exists(path):
            raise RuntimeError(f"missing source corpus {path}")
        with open(path) as fh:
            for line in fh:
                row = json.loads(line)
                key = (row["seed"], row["ply"])
                if key not in keys:
                    continue
                full = (source, *key)
                if full in found:
                    raise RuntimeError(f"duplicate source row {full}")
                found[full] = row
    missing = [(st["source"], st["seed"], st["ply"]) for st in states
               if (st["source"], st["seed"], st["ply"]) not in found]
    if missing:
        raise RuntimeError(f"{len(missing)} selected states missing from sources: "
                           f"{missing[:3]}")
    return found


#: The six arms registered for the DEV screen, asserted rather than assumed.
REGISTERED_ARMS = ("current", "v3", "random_fill", "quota",
                   "mc_more_full_work", "full_universe")

#: The ONE immutable full-DEV protocol. Every value a full run may use is
#: registered here and compared, not merely recorded. Recording alone let a
#: typo launch a valid-looking wrong experiment: mistyped shards still carry a
#: consistent manifest, so eight of them aggregate cleanly as long as they
#: share the same typo (Codex).
FULL_DEV_PROTOCOL = {
    "phase": "full",
    "states_sha256": "af78748586034f6f97e96a167008b2c5"
                     "40c0e4b1670a683ef6b5f05ec85d3e7b",
    "budget": 14,
    "work_target": 168,
    "band": 0.05,
    "full_proposal_worlds": 12,
    "oracle_worlds": 12,
    "report_worlds": 12,
    "salt": "pilot-run-v1",
    "shard_count": 8,
    "limit": 0,
    "side": "dev",
}


def protocol_violations(args, spec, states_sha) -> list[str]:
    """Every way a FULL launch can silently differ from the registered one."""
    got = {"phase": "full", "states_sha256": states_sha,
           "budget": args.budget, "work_target": args.work,
           "band": args.band,
           "full_proposal_worlds": args.full_proposal_worlds,
           "oracle_worlds": args.oracle_worlds,
           "report_worlds": args.report_worlds,
           "salt": args.salt, "shard_count": args.shard_count,
           "limit": args.limit, "side": spec.get("side")}
    bad = []
    for k, want in FULL_DEV_PROTOCOL.items():
        if got.get(k) != want:
            bad.append(f"{k}: {got.get(k)!r}, registered {want!r}")
    if list(ARMS) != list(REGISTERED_ARMS):
        bad.append(f"required_arms {list(ARMS)}, registered "
                   f"{list(REGISTERED_ARMS)}")
    return bad


SAMPLER_FLAGS = ("SHENGJI_WEIGHTED_SPLITS", "SHENGJI_UNIFORM_DEAL",
                 "SHENGJI_PHYSICAL_FILLS")


def preflight(args) -> tuple[dict, list[dict], list[dict]]:
    """Refuse unstable inputs before loading corpora or constructing a bot."""
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise RuntimeError("set SHENGJI_FAST=1 for the pinned pilot")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise RuntimeError("compiled engine was requested but is not active")
    if os.path.exists(args.out) or os.path.exists(args.out + ".partial"):
        raise RuntimeError(f"refusing to overwrite {args.out}")
    if git_output("status", "--porcelain"):
        raise RuntimeError("pilot scoring refuses a dirty tree")
    if not 0 <= args.shard_index < args.shard_count:
        raise RuntimeError("shard index must satisfy 0 <= index < count")

    # An experimental sampler flag would change the belief distribution every
    # arm searches under, so a run with one set is not the frozen-production
    # estimand this pilot is defined on. Refuse rather than record it.
    live = [f for f in SAMPLER_FLAGS if os.environ.get(f)]
    if live:
        raise RuntimeError(
            f"experimental sampler flag(s) set: {live}. DEV-512 scores the "
            f"sampler production deploys; unset them.")

    # Digest BEFORE parsing. Verifying after load would already have accepted
    # whatever the file said, and the whole point is to prove the bytes are the
    # registered artifact before anything downstream trusts them.
    if not args.expected_states_sha256:
        raise RuntimeError("--expected-states-sha256 is required; a run whose "
                           "state set is not pinned cannot be aggregated with "
                           "another shard")
    actual = digest(args.states)
    if actual != args.expected_states_sha256:
        raise RuntimeError(
            f"state artifact digest mismatch\n  expected "
            f"{args.expected_states_sha256}\n  actual   {actual}")

    with open(args.states) as fh:
        spec = json.load(fh)

    # Every replay corpus AND split must be present locally with the digest the
    # artifact recorded. `rl_data` is gitignored, so a machine can have a
    # matching HEAD, artifact hash, ballot and compiled binary and still lack
    # the rows it must replay — which is exactly how the first Air launch
    # failed, four shards deep into a launch that looked fully preflighted
    # (Codex G5). Checking identity of the CODE is not checking presence of the
    # DATA.
    for name, meta in spec.get("sources", {}).items():
        for kind, key in (("corpus", "corpus_sha256_16"),
                          ("split", "split_sha256_16")):
            path = meta.get(kind)
            if not path:
                raise RuntimeError(f"artifact source {name!r} records no {kind}")
            if not os.path.exists(path):
                raise RuntimeError(
                    f"missing replay {kind} for source {name!r}: {path}. This "
                    f"machine has the artifact but not the data it replays.")
            live = digest(path)[:16]
            if live != meta[key]:
                raise RuntimeError(
                    f"replay {kind} for {name!r} does not match the artifact "
                    f"provenance: live {live}, recorded {meta[key]}")

    phase = "smoke" if args.limit else "full"
    if phase == "full":
        # A full DEV result must be the registered contract exactly. A smoke
        # run is allowed to be small, but is LABELLED so the aggregator cannot
        # pool it into a DEV verdict.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import pilot_states as PS
        if spec.get("side") != "dev":
            raise RuntimeError(f"full run needs the DEV side, got "
                               f"{spec.get('side')!r}; CALIB and REPORT are "
                               f"untouched by selection")
        if spec.get("replay_errors"):
            raise RuntimeError(f"{spec['replay_errors']} replay error(s) in "
                               f"the artifact")
        bad = PS.check_contract(spec["states"], spec.get("requested", 512),
                                spec.get("replay_errors", 0))
        if bad:
            raise RuntimeError("state artifact violates the registered "
                               "contract: " + "; ".join(bad))

    if phase == "full":
        bad = protocol_violations(args, spec, actual)
        if bad:
            raise RuntimeError(
                "full run does not match the registered protocol:\n  "
                + "\n  ".join(bad))

    experiment_states = list(spec["states"])
    if args.limit:
        experiment_states = experiment_states[:args.limit]
    states = experiment_states[args.shard_index::args.shard_count]
    if not states:
        raise RuntimeError("state shard is empty")
    return spec, experiment_states, states, phase, actual


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True,
                    help="frozen state artifact; no default, because the old "
                         "default named a file that does not exist")
    ap.add_argument("--expected-states-sha256", default="",
                    help="full sha256 of --states, compared BEFORE parsing")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--budget", type=int, default=14)
    ap.add_argument("--work", type=int, default=168)
    ap.add_argument("--band", type=float, default=0.05)
    ap.add_argument("--report-worlds", type=int, default=12)
    ap.add_argument("--full-proposal-worlds", type=int, default=12)
    ap.add_argument("--oracle-worlds", type=int, default=12)
    ap.add_argument("--salt", default="pilot-run-v1")
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        _spec, experiment_states, states, phase, states_sha = preflight(args)
        rows = load_rows(states)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)

    bot = make_bot("mc", seed=1)
    from shengji.engine.ballot import mc_ballot
    protocol = {
        "schema": RUN_SCHEMA,
        "git": git_output("rev-parse", "HEAD"), "tree_dirty": False,
        "states_artifact": args.states, "states_sha256": states_sha,
        "expected_states_sha256": args.expected_states_sha256,
        "phase": phase,
        "sampler_flags": {f: False for f in SAMPLER_FLAGS},
        "ballot": str(mc_ballot(bot)), "required_arms": list(ARMS),
        "budget": args.budget, "work_target": args.work, "band": args.band,
        "report_worlds": args.report_worlds,
        "oracle_worlds": args.oracle_worlds,
        "full_proposal_worlds": args.full_proposal_worlds,
        "salt": args.salt, "experiment_n_states": len(experiment_states),
        "shard_count": args.shard_count,
        "equal_work_arms": list(EQUAL_WORK_ARMS),
        "require_voids": True, "fast_engine": True,
    }
    experiment_id = stable_digest(protocol)
    manifest = {**protocol, "experiment_id": experiment_id,
                "shard_index": args.shard_index, "n_states": len(states),
                "script_sha256": digest(os.path.abspath(__file__))}
    print(json.dumps(manifest, indent=2), flush=True)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pilot_states import replay

    records, work_violations = [], []
    sampler_totals = Counter()
    t0 = time.time()
    arm_seed = int(hashlib.sha256(args.salt.encode()).hexdigest()[:8], 16)
    for i, state in enumerate(states):
        key = f'{state["source"]}:{state["seed"]}:{state["ply"]}'
        row = rows[(state["source"], state["seed"], state["ply"])]
        rnd = replay(row)  # any mismatch is fatal; no skip-and-continue subset
        seat = state["seat"]
        if rnd.turn != seat or rnd.trick is None or rnd.trick.plays:
            raise RuntimeError(f"{key}: selected state is not the declared lead")
        mem = Memory(rnd, seat)

        ballots = {arm: propose(arm, bot, rnd, seat, budget=args.budget,
                                seed=arm_seed, state_key=key) for arm in ARMS}
        prop_worlds = {
            arm: (args.full_proposal_worlds if arm == "full_universe"
                  else worlds_for_equal_work(args.work, len(ballots[arm])))
            for arm in ARMS
        }
        wide_work = (len(ballots["full_universe"])
                     * prop_worlds["full_universe"])
        prop_worlds["mc_more_full_work"] = worlds_for_equal_work(
            wide_work, len(ballots["mc_more_full_work"]))
        counts = {"proposal": max(prop_worlds.values()),
                  "oracle": args.oracle_worlds, "report": args.report_worlds}
        before = sampler_snapshot(bot)
        folds = draw_folds(bot, rnd, seat, mem, counts, salt=args.salt,
                           state_key=key)
        deltas = sampler_delta(before, bot)
        sampler_totals.update(deltas)
        fold_stats = folds.stats()
        shorts = {fold: stat["short"] for fold, stat in fold_stats.items()
                  if stat["short"]}
        forbidden = {name: value for name, value in deltas.items() if value}
        if shorts or forbidden:
            raise RuntimeError(f"{key}: fold/sampler invariant failed: "
                               f"short={shorts}, sampler={forbidden}")

        report_keys = folds.ordered_keys("report")
        report_digest = stable_digest(report_keys)
        rec = {
            "state": key, "deal_seed": state["seed"], "seat": seat,
            "tricks": len(rnd.history), "band": state.get("band"),
            "stratum": state.get("stratum"), "arms": {},
            "fold_stats": fold_stats, "sampler_counter_deltas": deltas,
            "report_world_keys": report_keys,
            "report_world_digest": report_digest,
        }
        chosen = {}
        for arm in ARMS:
            worlds = folds.worlds["proposal"][:prop_worlds[arm]]
            got = choose_action(bot, rnd, seat, worlds, ballots[arm],
                                state_key=key, expect=len(worlds))
            chosen[arm] = got["action"]
            rec["arms"][arm] = {
                "n_candidates": got["n_candidates"], "action": got["action"],
                "kept_heuristic": got["kept_heuristic"],
                "tractor_locked": got["tractor_locked"],
                "work": got["candidate_world_rollouts"],
                "proposal_worlds": len(worlds),
                "report_world_digest": report_digest,
            }
            if not got["tractor_locked"]:
                work = got["candidate_world_rollouts"]
                target = wide_work if arm == "mc_more_full_work" else args.work
                if ((arm == "mc_more_full_work" or arm in EQUAL_WORK_ARMS)
                        and abs(work - target) > args.band * target):
                    work_violations.append([key, arm, work, target])

        ref = oracle_reference(bot, rnd, seat, folds.worlds["oracle"],
                               union_ballot(ballots), state_key=key,
                               expect=args.oracle_worlds)
        rec["oracle_action"] = list(ref.action)
        report_cache = {}

        def cached_report(action):
            action_key = tuple(sorted(action))
            if action_key not in report_cache:
                report_cache[action_key] = score_action(
                    bot, rnd, seat, folds.worlds["report"], list(action_key),
                    state_key=key, fold="report", expect=args.report_worlds)
            return report_cache[action_key]

        reference_scored = cached_report(list(ref.action))
        reference = None
        for arm in ARMS:
            arm_scored = cached_report(chosen[arm])
            outcome = report_regret(
                bot, rnd, seat, folds.worlds["report"], chosen[arm],
                list(ref.action), state_key=key, expect=args.report_worlds,
                arm_scored=arm_scored, reference_scored=reference_scored)
            if tuple(outcome["world_keys"]) != report_keys:
                raise RuntimeError(f"{key}/{arm}: report-world identity drift")
            this_reference = (outcome["reference_returns"],
                              outcome["reference_raw_points"],
                              outcome["reference_brackets"])
            if reference is None:
                reference = this_reference
            elif reference != this_reference:
                raise RuntimeError(f"{key}/{arm}: reference changed across arms")
            rec["arms"][arm].update({
                "regret": outcome["regret"], "arm_mean": outcome["arm_mean"],
                "arm_returns": outcome["arm_returns"],
                "arm_raw_points": outcome["arm_raw_points"],
                "arm_brackets": outcome["arm_brackets"],
                "n_report_worlds": outcome["n_worlds"],
                "matched_oracle": chosen[arm] == list(ref.action),
            })
        assert reference is not None
        rec["reference_returns"], rec["reference_raw_points"], \
            rec["reference_brackets"] = reference
        records.append(rec)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(states)} states, {time.time()-t0:.0f}s",
                  flush=True)

    if work_violations:
        raise RuntimeError(f"{len(work_violations)} work-band violations: "
                           f"{work_violations[:3]}")
    if len(records) != len(states):
        raise RuntimeError(f"record count {len(records)} != state count {len(states)}")

    payload = {
        **manifest, "complete": True, "records": records,
        "work_violations": [], "replay_errors": 0, "protocol_failures": [],
        "sampler_counter_totals": dict(sampler_totals),
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tmp = args.out + ".partial"
    with open(tmp, "x") as fh:
        json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, args.out)
    print(f"wrote complete shard {args.out}: {len(records)} states in "
          f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
