"""Sweep driver: ``train_v0.train`` over a grid of config overrides, one
shared encoding cache, one summary table.

    train_sweep.py --data DIR [--data DIR ...] [--eval-luna PATH] --grid GRID.json
        --out DIR [--device mps|cpu] [--base BASE.json] [--set KEY=JSON ...]
        [--cache-dir DIR] [--cache-workers N] [--resident-bytes B]
        [--privacy-witness-every N [--allow-sampled-privacy-witness]]

``GRID.json`` is a JSON list of override objects, e.g.::

    [{}, {"aux_search_mean": 1.0}, {"prior_target": "final"},
     {"hidden": 128, "weight_decay": 1e-3}, {"prior_weight": 0.5, "seed": 2}]

Each key is a ``train_v0.train`` keyword argument (``OVERRIDE_KEYS``);
``--base`` / ``--set`` supply values applied to every config first.  An
unknown key refuses the whole grid before anything runs (a typo must never
be a silently ignored override); an invalid value fails that config only.

What one sweep does
-------------------
1. builds the encoding cache ONCE under ``<out>/cache`` (``--cache-workers``
   shards at a time; the privacy witness on every row unless sampling is
   explicitly allowed) for the data stores and the Luna set, before any
   config runs, so every run reuses it (each row records
   ``cache.rebuilt == 0``);
2. runs ``train_v0.train`` per config in grid order into
   ``<out>/runs/<NN>-<config sha256[:12]>/`` (a complete train_v0 output:
   receipt, metrics, checkpoints); a run that raises is recorded as
   ``failed`` with its error (traceback in ``error.txt``) and the sweep
   continues;
3. writes ``sweep.json`` + ``sweep.md`` after every config: one row per
   config, in grid order -- config hash, overrides, epochs run, best epoch,
   then the HEADLINE numbers from the TEST split (held out from epoch
   selection and the calibration fit): value MAE / MSE for the model and
   the stratified prior, the paired |error| difference with its
   deal-bootstrap 95% CI, prior CE of the model vs uniform and the smoothed
   incumbent (for the training target), the aux search-mean MAE when the
   head is on; the same value numbers for Luna when given; the VALIDATION
   value MAE labelled as tuning telemetry (the split that chose the epoch
   and fitted the calibration; not held out); and wall time.

Rows are pure functions of the receipts (the numbers equal a standalone
``train_v0`` run with the same config; the config hash is checked against
the receipt).  Tier i: engine + torch only; nothing here spends LLM tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .data import Residency, default_cache_workers, default_resident_bytes, encoder_identity
from .train_v0 import (DEFAULTS, HEADLINE, SPLIT_ROLES, TrainError, build_config,
                       config_sha256, git_identity, prepare_stores, refuse_overlap, train,
                       versions)

SWEEP_SCHEMA = "shengji-train-sweep-v2"    # v2: test-split headline, val = tuning
#: ``train_v0.train`` keyword arguments a grid entry / base may set
OVERRIDE_KEYS = ("epochs", "seed", "prior_target", "limit_clusters", "prior_weight", "lr",
                 "weight_decay", "batch_size", "patience", "val_fraction", "test_fraction",
                 "huber_delta", "aux_points", "aux_weight", "aux_search_mean", "hidden",
                 "n_boot", "window")


class SweepError(RuntimeError):
    """The sweep cannot be carried out as specified (fail closed)."""


# --------------------------------------------------------------------- grid

def check_overrides(overrides: Any, *, where: str) -> dict:
    """The override object of one grid entry (or the base), validated for
    shape and key names only; values are validated per config."""
    if not isinstance(overrides, Mapping):
        raise SweepError(f"{where}: expected an object of overrides, got "
                         f"{type(overrides).__name__}")
    unknown = sorted(set(overrides) - set(OVERRIDE_KEYS))
    if unknown:
        raise SweepError(f"{where}: unknown override key(s) {unknown}; "
                         f"allowed: {list(OVERRIDE_KEYS)}")
    return dict(overrides)


def load_grid(path: str | os.PathLike) -> list[dict]:
    """The grid file: a JSON list of override objects (at least one)."""
    try:
        grid = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SweepError(f"{path}: cannot read the grid: {exc}") from exc
    if not isinstance(grid, list) or not grid:
        raise SweepError(f"{path}: the grid must be a non-empty JSON list of objects")
    return [check_overrides(entry, where=f"{path}[{i}]") for i, entry in enumerate(grid)]


def parse_set(items: Sequence[str] | None) -> dict:
    """``KEY=JSON`` pairs (``epochs=2``, ``prior_target="final"``) as a base
    override object; a bare word that is not JSON is taken as a string."""
    out: dict = {}
    for item in items or ():
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise SweepError(f"--set {item!r}: expected KEY=JSON")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        out[key] = value
    return check_overrides(out, where="--set")


def effective_config(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict:
    """Base then overrides, keyed by ``OVERRIDE_KEYS`` (``train`` kwargs)."""
    return {**dict(base), **dict(overrides)}


# ------------------------------------------------------------------ summary

def _pick(d: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(d, Mapping) or key not in d:
            return None
        d = d[key]
    return d


def _split_summary(final: Mapping[str, Any] | None, prior_target: str) -> dict | None:
    """The row fields for one evaluation split of a receipt's ``final``."""
    if not final:
        return None
    value = final.get("value") or {}
    diff = value.get("paired_diff_model_minus_prior") or {}
    block = _pick(final, "prior", prior_target) or {}
    aux = final.get("aux_search_mean")
    return {
        "n": final.get("n"),
        "deals": final.get("deals"),
        "held_out": final.get("held_out"),
        "role": final.get("role"),
        "value_mae": _pick(value, "model", "mae"),
        "value_mse": _pick(value, "model", "mse"),
        "prior_mae": _pick(value, "stratified_prior", "mae"),
        "prior_mse": _pick(value, "stratified_prior", "mse"),
        "diff_abs_error": {"mean": _pick(diff, "abs_error", "mean"),
                           "ci95": _pick(diff, "abs_error", "ci95"),
                           "clusters": _pick(diff, "abs_error", "clusters")},
        "diff_sq_error": {"mean": _pick(diff, "sq_error", "mean"),
                          "ci95": _pick(diff, "sq_error", "ci95")},
        "prior_ce": {
            "target": prior_target, "n": block.get("n"),
            "model": block.get("model_ce"), "uniform": block.get("uniform_ce"),
            "incumbent": block.get("incumbent_ce"), "incumbent_eps": block.get("incumbent_eps"),
            "diff_model_minus_uniform": _pick(block, "diff_model_minus_uniform", "mean"),
            "diff_model_minus_incumbent": _pick(block, "diff_model_minus_incumbent", "mean"),
            "nll_played": block.get("nll_played"), "top1_agreement": block.get("top1_agreement"),
        },
        "aux_search_mae": _pick(aux, "model", "mae"),
        "aux_search_prior_mae": _pick(aux, "stratified_prior", "mae"),
        "aux_search_rows": aux.get("n") if aux else None,
        "calibration_mae_after": _pick(final, "calibration", "mae_after"),
        "calibration_in_sample": _pick(final, "calibration", "in_sample"),
    }


def summarize_receipt(receipt: Mapping[str, Any]) -> dict:
    """The sweep row fields derived from one ``train`` receipt: ``test``
    (the headline, held out), ``val`` (tuning telemetry) and ``luna``."""
    config = receipt["config"]
    counts = receipt.get("counts") or {}
    luna_counts = _pick(receipt, "luna", "counts") or {}
    if receipt.get("headline") != HEADLINE:
        raise SweepError(f"receipt headline {receipt.get('headline')!r} != {HEADLINE!r}")
    return {
        "config_sha256": receipt["config_sha256"],
        "config": {k: config.get(k) for k in OVERRIDE_KEYS},
        "epochs": len(receipt.get("epochs") or []),
        "best_epoch": receipt.get("best_epoch"),
        "stopped_early": receipt.get("stopped_early"),
        "wall_secs": receipt.get("wall_secs"),
        "cache": {"rebuilt": int(counts.get("cache_rebuilt", 0))
                  + int(luna_counts.get("cache_rebuilt", 0)),
                  "reused": int(counts.get("cache_reused", 0))
                  + int(luna_counts.get("cache_reused", 0))},
        "split": receipt.get("split"),
        "headline": receipt.get("headline"),
        "selection": receipt.get("selection"),
        "test": _split_summary(_pick(receipt, "final", "test"), config["prior_target"]),
        "val": _split_summary(_pick(receipt, "final", "val"), config["prior_target"]),
        "luna": _split_summary(_pick(receipt, "final", "luna"), config["prior_target"]),
        "residency": receipt.get("residency"),
        "privacy_witness": receipt.get("privacy_witness"),
        "receipt": _pick(receipt, "checkpoints", "best"),
    }


# ----------------------------------------------------------------- markdown

def _f(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _ci(block: Mapping[str, Any] | None, nd: int = 3) -> str:
    if not block or block.get("mean") is None:
        return "-"
    lo, hi = (block.get("ci95") or [None, None])[:2]
    return f"{_f(block['mean'], nd)} [{_f(lo, nd)}, {_f(hi, nd)}]"


def describe_overrides(overrides: Mapping[str, Any]) -> str:
    if not overrides:
        return "baseline"
    return ", ".join(f"{k}={json.dumps(v)}" for k, v in sorted(overrides.items()))


TABLE_HEADER = ("| # | config | hash | ep | best | TEST MAE model / prior "
                "| TEST diff abs err [95% CI] | TEST MSE model / prior "
                "| TEST prior CE model / uniform / incumbent | TEST aux MAE (prior) "
                "| Luna MAE model / prior | Luna diff abs err [95% CI] "
                "| val MAE model / prior (tuning) | wall s |")
TABLE_RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"


def render_markdown(summary: Mapping[str, Any]) -> str:
    """``sweep.md``: the run identity and one table row per config."""
    lines = [
        "# train_v0 sweep",
        "",
        f"* data: {', '.join(summary['data'])}",
        f"* eval_luna: {summary.get('eval_luna') or '-'}",
        f"* device: {summary.get('device')}; git: {_pick(summary, 'git', 'sha')}"
        f"{' (dirty)' if _pick(summary, 'git', 'dirty') else ''}; "
        f"encoder: {str(_pick(summary, 'encoder', 'implementation_sha256'))[:12]}",
        f"* base: {describe_overrides(summary['base']) if summary.get('base') else 'train_v0 defaults'}",
        f"* cache: {_pick(summary, 'cache', 'dir')} "
        f"(shards built up front: {_pick(summary, 'cache', 'built')}, "
        f"workers: {_pick(summary, 'cache', 'workers')}, "
        f"privacy witness every {_pick(summary, 'privacy_witness', 'every')} row(s)"
        f"{' [SAMPLED]' if _pick(summary, 'privacy_witness', 'sampled') else ''})",
        f"* residency budget: {_pick(summary, 'residency', 'budget_bytes')} bytes "
        f"(data decodes to {_pick(summary, 'residency', 'decoded_bytes_data')} bytes)",
        f"* configs: {summary['status']['ok']} ok, {summary['status']['failed']} failed; "
        f"wall {_f(summary.get('wall_secs'), 1)} s",
        "",
        f"HEADLINE = the TEST split ({SPLIT_ROLES['test']['role']}).  "
        f"The val column is {SPLIT_ROLES['val']['role']}.",
        "",
        TABLE_HEADER,
        TABLE_RULE,
    ]
    for row in summary["rows"]:
        label = describe_overrides(row.get("overrides") or {})
        if row["status"] != "ok":
            lines.append(f"| {row['index']} | {label} | {str(row.get('config_sha256') or '-')[:12]} "
                         f"| FAILED: {row.get('error')} | | | | | | | | | | "
                         f"{_f(row.get('wall_secs'), 1)} |")
            continue
        test = row["test"] or {}
        val = row.get("val") or {}
        luna = row.get("luna") or {}
        ce = test.get("prior_ce") or {}
        aux = ("-" if test.get("aux_search_mae") is None
               else f"{_f(test['aux_search_mae'], 2)} ({_f(test.get('aux_search_prior_mae'), 2)})")
        lines.append(
            f"| {row['index']} | {label} | {row['config_sha256'][:12]} | {row['epochs']} "
            f"| {row['best_epoch']} | {_f(test.get('value_mae'))} / {_f(test.get('prior_mae'))} "
            f"| {_ci(test.get('diff_abs_error'))} "
            f"| {_f(test.get('value_mse'))} / {_f(test.get('prior_mse'))} "
            f"| {_f(ce.get('model'))} / {_f(ce.get('uniform'))} / {_f(ce.get('incumbent'))} "
            f"({ce.get('target')}) | {aux} "
            f"| {_f(luna.get('value_mae'))} / {_f(luna.get('prior_mae'))} "
            f"| {_ci(luna.get('diff_abs_error'))} "
            f"| {_f(val.get('value_mae'))} / {_f(val.get('prior_mae'))} "
            f"| {_f(row.get('wall_secs'), 1)} |")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------- sweep

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_sweep(*, data: list[str], grid: Sequence[Mapping[str, Any]], out: str | os.PathLike,
              eval_luna: str | None = None, device: str | None = None,
              base: Mapping[str, Any] | None = None, cache_dir: str | None = None,
              cache_workers: int | None = None, resident_bytes: int | None = None,
              privacy_witness_every: int = 1, allow_sampled_privacy_witness: bool = False,
              argv: list[str] | None = None,
              log: Callable[[str], None] | None = print) -> dict:
    """Run the grid; returns the summary (also written as ``sweep.json`` /
    ``sweep.md``).  Raises ``SweepError`` for a malformed grid / base and
    ``TrainDataError`` / ``TrainError`` when the shared cache cannot be
    built or the Luna set overlaps the data stores; a config that fails is
    a ``failed`` row."""
    base = check_overrides(base or {}, where="base")
    grid = [check_overrides(entry, where=f"grid[{i}]") for i, entry in enumerate(grid)]
    if not grid:
        raise SweepError("the grid is empty")
    say = log or (lambda _s: None)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    workers = default_cache_workers() if cache_workers is None else max(1, int(cache_workers))
    data = [str(Path(d).resolve()) for d in data]
    luna_path = None if eval_luna is None else str(Path(eval_luna).resolve())
    budget = default_resident_bytes() if resident_bytes is None else int(resident_bytes)
    if budget <= 0:
        raise SweepError("--resident-bytes must be positive")
    exec_kw = dict(cache_dir=str(cache), cache_workers=workers, resident_bytes=budget,
                   privacy_witness_every=privacy_witness_every,
                   allow_sampled_privacy_witness=allow_sampled_privacy_witness)

    # the shared cache, once, before any config runs (nothing stays resident)
    seed = int(base.get("seed", DEFAULTS["seed"]))
    say(f"sweep: {len(grid)} config(s); building the shared cache under {cache} "
        f"with {workers} worker(s), privacy witness every {privacy_witness_every} row(s)")
    residency = Residency(budget)
    prepare_kw = dict(witness_seed=seed, progress=say, cache_workers=workers,
                      residency=residency, witness_every=privacy_witness_every,
                      allow_sampled_witness=allow_sampled_privacy_witness)
    prepared = prepare_stores(data, cache, limit_clusters=base.get("limit_clusters"),
                              **prepare_kw)
    built = {"shards": int(prepared.counts["shards"]),
             "rebuilt": int(prepared.counts["cache_rebuilt"]),
             "reused": int(prepared.counts["cache_reused"]),
             "records": int(prepared.counts["records_total"]),
             "deals": int(prepared.counts["deals_total"]),
             "decoded_bytes": int(prepared.counts["decoded_bytes"])}
    if luna_path is not None:
        luna_prepared = prepare_stores([luna_path], cache, limit_clusters=None, **prepare_kw)
        refuse_overlap(prepared.block_store, luna_prepared.block_store,
                       label=f"--eval-luna {luna_path}")
        built["shards"] += int(luna_prepared.counts["shards"])
        built["rebuilt"] += int(luna_prepared.counts["cache_rebuilt"])
        built["reused"] += int(luna_prepared.counts["cache_reused"])
        built["luna_records"] = int(luna_prepared.counts["records_total"])
        built["luna_deals"] = int(luna_prepared.counts["deals_total"])
        del luna_prepared
    del prepared
    residency.clear()
    say(f"sweep: cache ready: shards={built['shards']} rebuilt={built['rebuilt']} "
        f"reused={built['reused']} deals={built['deals']}")

    summary: dict = {
        "schema": SWEEP_SCHEMA,
        "argv": list(argv) if argv is not None else None,
        "started": started_at,
        "wall_secs": None,
        "device": device,
        "versions": versions(),
        "git": git_identity(),
        "encoder": encoder_identity(),
        "data": data,
        "eval_luna": luna_path,
        "base": base,
        "grid": grid,
        "headline": HEADLINE,
        "roles": {name: SPLIT_ROLES[name]["role"] for name in ("val", "test", "luna")},
        "cache": {"dir": str(cache), "workers": workers, "built": built["rebuilt"],
                  "shards": built["shards"], "reused_up_front": built["reused"],
                  "records": built["records"], "deals": built["deals"],
                  "luna_records": built.get("luna_records"),
                  "luna_deals": built.get("luna_deals")},
        "privacy_witness": {"every": int(privacy_witness_every),
                            "sampled": int(privacy_witness_every) != 1,
                            "allowed_sampled": bool(allow_sampled_privacy_witness)},
        "residency": {"budget_bytes": residency.budget,
                      "decoded_bytes_data": built["decoded_bytes"]},
        "rows": [],
        "status": {"ok": 0, "failed": 0},
    }

    def flush() -> None:
        summary["wall_secs"] = round(time.perf_counter() - started, 3)
        summary["status"] = {"ok": sum(1 for r in summary["rows"] if r["status"] == "ok"),
                             "failed": sum(1 for r in summary["rows"] if r["status"] != "ok")}
        _write_json(out_dir / "sweep.json", summary)
        (out_dir / "sweep.md").write_text(render_markdown(summary), encoding="utf-8")

    for index, overrides in enumerate(grid):
        cfg = effective_config(base, overrides)
        t0 = time.perf_counter()
        row: dict = {"index": index, "overrides": dict(overrides), "status": "ok",
                     "error": None, "config_sha256": None, "run": None}
        try:
            config = build_config(data=data, eval_luna=luna_path, **cfg)
            sha = config_sha256(config)
            run_dir = out_dir / "runs" / f"{index:02d}-{sha[:12]}"
            row.update(config_sha256=sha, run=str(run_dir))
            say(f"sweep [{index + 1}/{len(grid)}] {describe_overrides(overrides)} "
                f"-> {run_dir.name}")
            receipt = train(data=data, out=run_dir, eval_luna=luna_path, device=device,
                            argv=argv, log=log, **exec_kw, **cfg)
            if receipt["config_sha256"] != sha:
                raise SweepError(f"receipt config hash {receipt['config_sha256'][:12]} != "
                                 f"planned {sha[:12]}: an override was not applied")
            row.update(summarize_receipt(receipt))
            row["wall_secs"] = receipt.get("wall_secs")
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal to the sweep
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                       wall_secs=round(time.perf_counter() - t0, 3))
            if row["run"]:
                run_path = Path(row["run"])
                run_path.mkdir(parents=True, exist_ok=True)
                (run_path / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            say(f"sweep [{index + 1}/{len(grid)}] FAILED: {row['error']}")
        summary["rows"].append(row)
        flush()
    say(f"sweep: done ok={summary['status']['ok']} failed={summary['status']['failed']} "
        f"wall={summary['wall_secs']}s -> {out_dir / 'sweep.md'}")
    return summary


# ----------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train_sweep", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", action="append", required=True,
                        help="shard store / merged store directory (repeatable)")
    parser.add_argument("--eval-luna", default=None,
                        help="Luna private split (evaluation only; must share no deal with --data)")
    parser.add_argument("--grid", required=True, help="JSON list of override objects")
    parser.add_argument("--out", required=True, help="sweep output directory")
    parser.add_argument("--device", default=None, help="mps|cpu (default: mps when available)")
    parser.add_argument("--base", default=None,
                        help="JSON object of overrides applied to every config first")
    parser.add_argument("--set", action="append", default=None, metavar="KEY=JSON",
                        help="a base override (repeatable), e.g. --set epochs=2")
    parser.add_argument("--cache-dir", default=None,
                        help="shared encoding cache (default: <out>/cache)")
    parser.add_argument("--cache-workers", type=int, default=None,
                        help=f"shards encoded at a time (default: min(8, cpu) = "
                             f"{default_cache_workers()})")
    parser.add_argument("--resident-bytes", type=int, default=None,
                        help="residency budget for decoded shard blocks (default: 40%% of "
                             "physical memory; see train_v0)")
    parser.add_argument("--privacy-witness-every", type=int, default=1, metavar="N",
                        help="privacy witness on every N-th row (default 1 = every row; "
                             "N > 1 needs --allow-sampled-privacy-witness)")
    parser.add_argument("--allow-sampled-privacy-witness", action="store_true",
                        help="permit --privacy-witness-every N > 1 (recorded in the summary)")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    full_argv = sys.argv if argv is None else ["train_sweep", *argv]

    def log(line: str) -> None:
        print(line, flush=True)

    try:
        base = {}
        if args.base:
            try:
                base = json.loads(Path(args.base).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SweepError(f"{args.base}: cannot read the base: {exc}") from exc
            base = check_overrides(base, where=args.base)
        base.update(parse_set(args.set))
        grid = load_grid(args.grid)
        summary = run_sweep(data=args.data, grid=grid, out=args.out, eval_luna=args.eval_luna,
                            device=args.device, base=base, cache_dir=args.cache_dir,
                            cache_workers=args.cache_workers,
                            resident_bytes=args.resident_bytes,
                            privacy_witness_every=args.privacy_witness_every,
                            allow_sampled_privacy_witness=args.allow_sampled_privacy_witness,
                            argv=full_argv, log=log)
    except (SweepError, TrainError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - a data refusal before any run
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"sweep -> {Path(args.out) / 'sweep.md'}", flush=True)
    return 0 if summary["status"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
