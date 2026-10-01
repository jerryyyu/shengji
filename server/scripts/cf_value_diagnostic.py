"""Counterfactual value diagnostic on a fixed audit set (#663 step 3, #677).

Two subcommands, both read-only on their inputs:

  sample  draw the audit set ONCE from decision-record shards and/or production
          room logs; the JSONL it writes is the paired input of every run.
  run     for each position: shared worlds (production sampler, fixed seed),
          each head's SERVED admission + decision on those worlds, the union
          (both admitted sets + played + E random legal actions), each head's
          value means on the union; then the metrics, stratified.

Examples (nice 19, single process):

  python scripts/cf_value_diagnostic.py sample \\
      --shards /path/runPVR1 --stride 80 --max-shards 200 --n 400 --seed 1 \\
      --out audit.jsonl

  python scripts/cf_value_diagnostic.py run --audit audit.jsonl \\
      --current smv3out-491ee4bf.npz --current-sha256 491ee4bf... \\
      --previous soft-8ecd4fea.npz --previous-sha256 ccade130... \\
      --worlds 64 --extras 8 --seed 1 --out-json out.json --out-md out.md

This does NOT duplicate #663 step 1 (Codex): step 1 measures the actual K=8
admission under production, own world draws; this fixes the worlds and asks
the counterfactual value question with the admitted set swapped.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.train.cf_value_diagnostic import (  # noqa: E402
    HEADS, SCHEMA_AUDIT, AuditError, audit_row, audit_set_digest, markdown_summary,
    position_metrics, run_position, sample_audit_set, stratified)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


# ------------------------------------------------------------------- sample

def iter_shard_rows(store: str, *, stride: int, max_shards: int | None):
    shard_dir = os.path.join(store, "shards")
    files = sorted(glob.glob(os.path.join(shard_dir, "cluster-*.jsonl")))[::max(1, stride)]
    if max_shards is not None:
        files = files[:max_shards]
    for path in files:
        source = os.path.relpath(path, store)
        with open(path) as fh:
            for line in fh:
                row = audit_row(json.loads(line), source=f"{os.path.basename(store)}:{source}")
                if row is not None:
                    yield row


def iter_roomlog_rows(logs_dir: str):
    """Production room logs through the harvest's own extractor (read-only)."""
    from shengji.harvest.room_log import extract_room_logs
    files = sorted(Path(p) for p in glob.glob(os.path.join(logs_dir, "*.jsonl")))
    result = extract_room_logs(files, cap=256, repo=Path(logs_dir))
    for record in result.public:
        row = audit_row(record, source=f"roomlog:{record.get('source_ref', '')}")
        if row is not None:
            yield row


def cmd_sample(args) -> int:
    def rows():
        for store in args.shards or []:
            yield from iter_shard_rows(store, stride=args.stride, max_shards=args.max_shards)
        for logs in args.roomlogs or []:
            yield from iter_roomlog_rows(logs)

    chosen = sample_audit_set(rows(), n=args.n, seed=args.seed)
    if not chosen:
        print("no eligible positions", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for row in chosen:
            fh.write(json.dumps({"schema": SCHEMA_AUDIT, **row}, separators=(",", ":")) + "\n")
    by_stratum: dict[str, int] = {}
    for row in chosen:
        name = f"{row['phase']}/{row['bucket']}"
        by_stratum[name] = by_stratum.get(name, 0) + 1
    print(json.dumps({"audit": str(out), "n": len(chosen), "seed": args.seed,
                      "sha256_keys": audit_set_digest(chosen), "strata": by_stratum}, indent=1))
    return 0


# ---------------------------------------------------------------------- run

def load_audit(path: str, limit: int | None):
    rows = []
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    if limit is not None:
        rows = rows[:limit]
    return rows


def build_bots(args):
    from shengji.train.pv_search_policy import make_pv_search_bot
    bots, heads = {}, {}
    for name in HEADS:
        path = getattr(args, name)
        given = getattr(args, f"{name}_sha256")
        actual = _sha256(path)
        if given is not None and given != actual:
            raise SystemExit(f"{name}: sha256 mismatch {actual[:12]} != {given[:12]}")
        if given is None:
            print(f"{name}: sha256 {actual} (computed, not pinned)", file=sys.stderr)
        bots[name] = make_pv_search_bot(path, sha256=actual, worlds=args.worlds,
                                        candidates=args.candidates, cap=args.cap,
                                        batch_size=args.batch_size, seed=0,
                                        serving_budget_seconds=None, threads=1)
        heads[name] = {"path": str(path), "sha256": actual, "encoder_version": bots[name].version}
    return bots, heads


def cmd_run(args) -> int:
    from shengji.harvest.legal import enumerate_legal
    from shengji.harvest.rebuild import state_for_record

    rows = load_audit(args.audit, args.limit)
    if not rows:
        print("empty audit set", file=sys.stderr)
        return 2
    bots, heads = build_bots(args)
    legal_fn = lambda rnd, seat, played: list(  # noqa: E731
        enumerate_legal(rnd, seat, cap=args.cap, must_include=[list(played)]).actions)
    positions, metrics, failures = [], [], []
    started = time.perf_counter()
    for i, row in enumerate(rows):
        t0 = time.perf_counter()
        try:
            table = run_position(row, bots, worlds_n=args.worlds, extras=args.extras, seed=args.seed,
                                 rebuild=state_for_record, legal_fn=legal_fn)
            metrics.append(position_metrics(table, tie_eps=args.tie_eps))
            positions.append(table)
        except AuditError as exc:
            failures.append({"key": row.get("key"), "error": str(exc)})
        if args.progress and (i + 1) % args.progress == 0:
            print(f"{i + 1}/{len(rows)} positions, {time.perf_counter() - started:.0f}s "
                  f"(last {time.perf_counter() - t0:.2f}s)", file=sys.stderr)
        if args.max_seconds and time.perf_counter() - started > args.max_seconds:
            print(f"stopping at {i + 1}/{len(rows)}: --max-seconds reached", file=sys.stderr)
            break
    result = {
        "schema": "cf-value-diagnostic-result-v1",
        "config": {"audit": str(args.audit), "audit_sha256": _sha256(args.audit),
                   "audit_keys_sha256": audit_set_digest(rows), "positions_requested": len(rows),
                   "worlds": args.worlds, "extras": args.extras, "seed": args.seed,
                   "candidates": args.candidates, "cap": args.cap, "tie_eps": args.tie_eps,
                   "heads": heads},
        "seconds": time.perf_counter() - started,
        "failures": failures,
        "stratified": stratified(positions, metrics),
        "positions": positions if args.keep_positions else None,
        "metrics": metrics if args.keep_positions else None,
    }
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_json, "w") as fh:
            json.dump(result, fh, indent=1)
    summary = markdown_summary(result)
    if failures:
        summary += f"\n{len(failures)} positions refused (see failures in the JSON).\n"
    if args.out_md:
        Path(args.out_md).write_text(summary)
    print(summary)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="draw the fixed audit set")
    s.add_argument("--shards", action="append", help="decision-record store dir (has shards/cluster-*.jsonl); repeatable")
    s.add_argument("--roomlogs", action="append", help="production room-log dir (*.jsonl); repeatable")
    s.add_argument("--stride", type=int, default=16)
    s.add_argument("--max-shards", type=int, default=None)
    s.add_argument("--n", type=int, default=400)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_sample)
    r = sub.add_parser("run", help="run both heads on the audit set")
    r.add_argument("--audit", required=True)
    r.add_argument("--current", required=True, help="current production package (.npz)")
    r.add_argument("--current-sha256", default=None)
    r.add_argument("--previous", required=True, help="previous production package (.npz)")
    r.add_argument("--previous-sha256", default=None)
    r.add_argument("--worlds", type=int, default=64)
    r.add_argument("--extras", type=int, default=8)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--candidates", type=int, default=8)
    r.add_argument("--cap", type=int, default=4000)
    r.add_argument("--batch-size", type=int, default=128)
    r.add_argument("--tie-eps", type=float, default=0.02)
    r.add_argument("--limit", type=int, default=None, help="first N audit rows only")
    r.add_argument("--max-seconds", type=float, default=None)
    r.add_argument("--progress", type=int, default=10)
    r.add_argument("--keep-positions", action="store_true", help="store every per-position table in the JSON")
    r.add_argument("--out-json", default=None)
    r.add_argument("--out-md", default=None)
    r.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
