#!/usr/bin/env python3
"""Retained-state model/horizon diagnostic, not a fresh gameplay strength test.

prepare selects input-only, rank/position-stratified roots from Luna FIT records.
run reuses those exact roots, shared ranking worlds and independent reference
worlds. Reference regret is restricted to the union of nominated actions and
the production ballot. Each completed state is durable and resumable.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np

from shengji.ai.cwv_policy import sample_worlds, shared_evaluator
from shengji.ai.mcbot import _child_seed
from shengji.ai.registry import make_bot
from shengji.harvest.legal import enumerate_legal
from shengji.harvest.rebuild import state_for_record, hands_snapshot
from shengji.harvest.schema import record_sha256
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train.data import deal_key
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def prepare_panel(records, output, *, seed=20260907):
    """One hashed-input-selected FIT position per rank/current-trick position.

    Outcomes, played action and model scores NEVER enter the selection key.
    Unknown extra record metadata is retained via its hash, not featurized.
    This importer checks reconstruction itself; it does not relax harvest's
    separate public record schema or admit these records to model training.
    """
    output = Path(output)
    if output.exists():
        raise ValueError("panel output already exists")
    chosen = {}
    seen = set()
    considered = 0
    with Path(records).open() as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("decision_kind") != "play":
                continue
            provenance = row.get("provenance", {})
            if provenance.get("split") != "fit":
                raise ValueError("diagnostic preparation accepts only provenance split=fit")
            if row.get("record_sha256") != record_sha256(row):
                raise ValueError("source record hash mismatch")
            key = deal_key(row["deck"])
            root_key = (key, row["source_ref"], row["seat"], len(row["plays_prefix"]))
            if root_key in seen:
                raise ValueError("duplicate source position")
            seen.add(root_key)
            considered += 1
            position = len(row["plays_prefix"]) % 4
            stratum = (row["setup"]["trump_rank"], position)
            priority = digest([seed, *root_key])
            if stratum not in chosen or priority < chosen[stratum][0]:
                chosen[stratum] = priority, key, row
    entries = []
    for (rank, position), (priority, key, row) in sorted(chosen.items()):
        rnd = state_for_record(row)
        if rnd.phase != "play" or rnd.turn != row["seat"] or len(rnd.trick.plays) != position:
            raise ValueError("selected root phase/seat/position mismatch")
        if hands_snapshot(rnd) != row["hidden_hands"]:
            raise ValueError("selected root hidden hands mismatch")
        entries.append({"id": priority, "deal_key": key, "rank": rank,
                        "position": position, "ply": len(row["plays_prefix"]),
                        "source_ref": row["source_ref"],
                        "record_sha256": row["record_sha256"],
                        "provenance": row["provenance"], "snapshot": _state_snapshot(rnd)})
    # Interleave positions instead of running every lead first. Selection and
    # ordering are fixed before predictions; interrupted prefixes stay explicit.
    entries.sort(key=lambda e: (e["position"], e["id"]))
    grouped = [[e for e in entries if e["position"] == p] for p in range(4)]
    entries = [group[i] for i in range(max(map(len, grouped), default=0))
               for group in grouped if i < len(group)]
    if not entries:
        raise ValueError("empty fit panel")
    panel = {"schema": "cwv-horizon-panel-v1", "source": str(Path(records).resolve()),
             "source_sha256": file_hash(records), "selection_seed": seed,
             "selection": "minimum hash of seed,deal_key,source_ref,seat,prefix_length per rank/position",
             "scope": "opened FIT development positions; not blind holdout or strength evidence",
             "records_considered": considered, "entries": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    _publish(output, panel)
    return panel


_EVALUATORS = None


def initialize_worker(checkpoints):
    global _EVALUATORS
    _EVALUATORS = {name: shared_evaluator(path, threads=1, encoding="mlp-static")
                   for name, path in checkpoints}


def run_state(entry, config):
    from shengji.train.cwv_horizon_audit import (
        score_horizon_matrix, topk_with_incumbent, reference_returns, run_fixed_ballot)

    start = time.perf_counter()
    rnd = _round_from_snapshot(entry["snapshot"])
    seat = rnd.turn
    seed = int(entry["id"][:15], 16) ^ config["seed"]
    production = make_bot("mc-s0-report-lcb", seed=seed)
    ballot = production._candidates(rnd, seat)
    incumbent = ballot[0]
    legal = enumerate_legal(rnd, seat, cap=None, must_include=ballot)
    actions = legal.actions
    keys = [tuple(sorted(a)) for a in actions]
    if len(set(keys)) != len(keys) or not keys or (legal.count is not None and len(keys) != legal.count):
        raise ValueError("exhaustive legal population mismatch")
    key_index = {key: i for i, key in enumerate(keys)}
    ranking_seed = _child_seed(production.rng.getstate(), "cwv-full-legal-worlds-v1")
    ranking, attempts = sample_worlds(make_bot("mc-s0-report-lcb", seed=ranking_seed),
                                     rnd, seat, config["ranking_worlds"])
    ref_seed = _child_seed((seed,), "cwv-horizon-independent-reference-v1")
    references, ref_attempts = sample_worlds(make_bot("mc-s0-report-lcb", seed=ref_seed),
                                           rnd, seat, config["reference_worlds"])
    if len(ranking) != config["ranking_worlds"] or len(references) != config["reference_worlds"]:
        raise ValueError("shared world population underfilled")
    horizons = config.get("horizons", ["immediate", "finished"])
    if not horizons or len(set(horizons)) != len(horizons) or set(horizons) - {"immediate", "finished"}:
        raise ValueError("invalid horizon selection")
    signatures = None
    signature_seconds = 0.0
    if config.get("diversity", False):
        from shengji.train.cwv_action_diversity_audit import (
            accepted_action_signatures, diverse_topk_with_incumbent)
        before_signatures = time.perf_counter()
        signatures = accepted_action_signatures(rnd, seat, actions, ranking)
        signature_seconds = time.perf_counter() - before_signatures
    arms = {}
    union = {key_index[tuple(sorted(a))] for a in ballot}
    for horizon in horizons:
        finished = horizon == "finished"
        print(f"state {entry['id'][:8]} {horizon}: {len(actions)} legal x {len(ranking)} worlds", flush=True)
        matrices = score_horizon_matrix(rnd, seat, actions, ranking, _EVALUATORS,
                                       finish_trick=finished, batch_size=config["batch_size"])
        for name, matrix in matrices.items():
            means = matrix.mean(axis=0)
            selected = topk_with_incumbent(actions, means, incumbent, config["alternatives"])
            variants = [("", selected)]
            if signatures is not None:
                diverse = diverse_topk_with_incumbent(
                    actions, means, incumbent, signatures, config["alternatives"])
                if len(diverse) != len(selected) or diverse[0] != selected[0]:
                    raise ValueError("diversity changed cardinality/incumbent")
                variants.append(("/diverse", diverse))
            for suffix, selected in variants:
                arms[f"{name}/{horizon}{suffix}"] = {
                    "shortlist_indices": list(selected),
                    "ranking_values": means[list(selected)].tolist(),
                    "effective_classes_kept": (None if signatures is None else
                                               len({signatures[i] for i in selected}))}
                union.update(selected)
        del matrices
    union_indices = sorted(union)
    union_actions = [actions[i] for i in union_indices]
    union_lookup = {index: offset for offset, index in enumerate(union_indices)}
    ref = reference_returns(rnd, seat, union_actions, references)
    levels = ref["levels"]
    ref_mean = levels.mean(axis=0)
    incumbent_offset = union_lookup[key_index[tuple(sorted(incumbent))]]
    for horizon in horizons:
        finished = horizon == "finished"
        matrices = score_horizon_matrix(rnd, seat, union_actions, references, _EVALUATORS,
                                       finish_trick=finished, batch_size=config["batch_size"])
        for name, matrix in matrices.items():
            for suffix in (["", "/diverse"] if signatures is not None else [""]):
                arm = arms[f"{name}/{horizon}{suffix}"]
                selected = arm["shortlist_indices"]
                result = run_fixed_ballot(rnd, seat, [actions[i] for i in selected], seed=seed,
                                         selection_worlds=config["selection_worlds"],
                                         report_worlds=config["report_worlds"])
                picked = key_index[tuple(sorted(result["played"]))]
                if picked not in selected:
                    raise ValueError("final MC pick outside retained shortlist")
                offsets = [union_lookup[i] for i in selected]
                chosen_value = float(ref_mean[union_lookup[picked]])
                retained_value = float(ref_mean[offsets].max())
                arm.update({"played": result["played"], "final_mc_record": result["record"],
                            "reference_value_final": chosen_value,
                            "reference_value_best_retained": retained_value,
                            "final_lift_vs_incumbent": chosen_value - float(ref_mean[incumbent_offset]),
                            "union_restricted_coverage_regret": float(ref_mean.max()) - retained_value,
                            "selection_regret_inside_retained": retained_value - chosen_value,
                            "reference_world_value_mae": float(np.abs(matrix - levels).mean()),
                            "reference_action_mean_mae": float(np.abs(matrix.mean(axis=0) - ref_mean).mean())})
    return {"schema": "cwv-horizon-state-v1", "config_sha256": digest(config),
            "state_id": entry["id"], "deal_key": entry["deal_key"], "rank": entry["rank"],
            "position": entry["position"], "ply": entry["ply"], "legal_count": len(actions),
            "source_ref": entry.get("source_ref"), "record_sha256": entry.get("record_sha256"),
            "provenance": entry.get("provenance"),
            "actions": actions, "incumbent": incumbent, "arms": arms,
            "ranking_worlds_sha256": digest(ranking), "reference_worlds_sha256": digest(references),
            "ranking_attempts": attempts, "reference_attempts": ref_attempts,
            "effective_signatures_sha256": None if signatures is None else digest(signatures),
            "effective_signatures_wall_seconds": signature_seconds,
            "reference": {"scope": "union-restricted, not full-legal oracle regret",
                          "policy": "production heuristic full continuation in sampled worlds",
                          "units": "category_signed_level (model half-integer units), before averaging",
                          "action_indices": union_indices, "levels": levels.tolist(),
                          "points": ref["points"].tolist()},
            "wall_seconds": time.perf_counter() - start}


def summarize(rows, total):
    metrics = ("reference_world_value_mae", "reference_action_mean_mae",
               "union_restricted_coverage_regret", "selection_regret_inside_retained",
               "final_lift_vs_incumbent")
    values = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        for arm, detail in row["arms"].items():
            for metric in metrics:
                values[arm][metric][row["deal_key"]].append(detail[metric])
    means = {arm: {metric: float(np.mean([np.mean(v) for v in deals.values()]))
                   for metric, deals in by_metric.items()} for arm, by_metric in values.items()}
    return {"schema": "cwv-horizon-summary-v1", "completed_states": len(rows),
            "planned_states": total, "complete": len(rows) == total,
            "distinct_deals": len({r["deal_key"] for r in rows}),
            "aggregation": "equal deal weight after averaging selected positions within each deal",
            "interpretation": "development diagnostic; finite sampled-world union reference, not strength",
            "arms": means}


def run_panel(args):
    panel = json.loads(args.panel.read_text())
    if panel.get("schema") != "cwv-horizon-panel-v1" or not panel.get("entries"):
        raise ValueError("invalid panel")
    checkpoints = []
    for item in args.checkpoint:
        name, path = item.split("=", 1)
        if not name or "/" in name or name in dict(checkpoints):
            raise ValueError("checkpoint names must be unique and contain no slash")
        checkpoints.append((name, str(Path(path).resolve())))
    config = {"schema": "cwv-horizon-config-v1", "panel_sha256": file_hash(args.panel),
              "panel_path": str(args.panel.resolve()),
              "checkpoint_sha256": {name: file_hash(path) for name, path in checkpoints},
              "checkpoints": checkpoints, "seed": args.seed,
              "ranking_worlds": args.ranking_worlds, "reference_worlds": args.reference_worlds,
              "selection_worlds": args.selection_worlds, "report_worlds": args.report_worlds,
              "alternatives": args.alternatives, "batch_size": args.batch_size,
              "horizons": getattr(args, "horizon", None) or ["immediate", "finished"],
              "diversity": getattr(args, "diversity", False),
              "source": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
              "script_sha256": file_hash(__file__)}
    # Normalize tuple/list representation before comparing with reopened JSON.
    config = json.loads(json.dumps(config))
    bind_output_config(args.out, config)
    entries = panel["entries"]
    if len({e["id"] for e in entries}) != len(entries):
        raise ValueError("duplicate panel state identity")
    completed, pending = [], []
    for entry in entries:
        path = args.out / f"state-{entry['id']}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row.get("state_id") != entry["id"] or row.get("config_sha256") != digest(config):
                raise ValueError("completed state binding mismatch")
            completed.append(row)
        else:
            pending.append(entry)
    if args.max_new_states is not None:
        pending = pending[:args.max_new_states]
    tasks = iter(pending)
    first_error = None
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_worker, initargs=(checkpoints,)) as pool:
        active = {}

        def submit():
            entry = next(tasks, None)
            if entry is not None:
                active[pool.submit(run_state, entry, config)] = entry

        for _ in range(args.workers):
            submit()
        while active:
            done, _ = wait(active, timeout=30, return_when=FIRST_COMPLETED)
            if not done:
                print(f"waiting: {len(completed)}/{len(entries)} complete; {len(active)} active", flush=True)
            for future in done:
                entry = active.pop(future)
                try:
                    row = future.result()
                except Exception as exc:
                    first_error = first_error or exc
                    _publish(args.out / f"failure-{entry['id']}.json",
                             {"state_id": entry["id"], "error": str(exc),
                              "config_sha256": digest(config)})
                    # Drain and save work already running. Do not start more
                    # after a defect, or discard peers merely for finishing later.
                    continue
                _publish(args.out / f"state-{entry['id']}.json", row)
                completed.append(row)
                _publish(args.out / "summary.json", summarize(completed, len(entries)))
                print(f"completed {len(completed)}/{len(entries)} ({100*len(completed)/len(entries):.1f}%), "
                      f"state wall {row['wall_seconds']:.1f}s", flush=True)
            # Observe all completed failures before replenishing this batch.
            if first_error is None:
                for _ in done:
                    submit()
    summary = summarize(completed, len(entries))
    _publish(args.out / "summary.json", summary)
    if first_error is not None:
        raise RuntimeError("state diagnostic failed; completed peers retained") from first_error
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--records", type=Path, required=True)
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--seed", type=int, default=20260907)
    run = sub.add_parser("run")
    run.add_argument("--panel", type=Path, required=True)
    run.add_argument("--checkpoint", action="append", required=True, help="name=/path/to/best.pt")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--seed", type=int, default=20260907)
    for name, default in (("ranking-worlds", 32), ("reference-worlds", 64),
                          ("selection-worlds", 30), ("report-worlds", 300),
                          ("alternatives", 4), ("batch-size", 128), ("workers", 1)):
        run.add_argument(f"--{name}", type=int, default=default)
    run.add_argument("--max-new-states", type=int, help="stop after useful partial work; resume same output later")
    run.add_argument("--horizon", choices=["immediate", "finished"], action="append",
                     help="evaluate only named horizons; default is both")
    run.add_argument("--diversity", action="store_true",
                     help="also compare fixed-size effective-action-diverse shortlists")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        panel = prepare_panel(args.records, args.out, seed=args.seed)
        print(f"prepared {len(panel['entries'])} FIT positions", flush=True)
    else:
        if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
            parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
        if any(getattr(args, n) < 1 for n in ("ranking_worlds", "reference_worlds", "selection_worlds",
                                             "report_worlds", "alternatives", "batch_size", "workers")):
            parser.error("positive work counts required")
        if args.max_new_states is not None and args.max_new_states < 1:
            parser.error("max-new-states must be positive")
        run_panel(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
