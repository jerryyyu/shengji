"""Score saved compact Luna calls on the opened historical panel.

This is a no-provider, fixed-continuation diagnostic.  The recorded Luna0
choice is retained as a named historical arm; it is never called production,
fresh-fit, or validation data.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Mapping, Sequence

from scripts import luna_historical_compare as compare
from scripts import luna_quality_analyze as quality
from shengji.luna import game
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.turn import DecisionPacket


SCHEMA = "luna-historical-analyzer-v1"
MODE = "opened-historical"
CONTINUATIONS = ("smart-all", "heuristic-all")
PRIMARY_CONTINUATION = "smart-all"
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260906
MAX_WORKERS = 16
ARMS = ("historical", "compact1", "batch4")
CALL_TERMINAL_STATUSES = frozenset({
    "historical-comparison-complete",
    "historical-comparison-complete-with-refusals",
    "historical-comparison-truncated",
})


class HistoricalAnalyzeError(ValueError):
    """A historical panel, saved call, score, or resume binding drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _load(path: Path) -> tuple[dict[str, object], str]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalAnalyzeError(f"invalid analyzer input {path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise HistoricalAnalyzeError(f"non-canonical analyzer input {path}")
    return value, _sha_bytes(raw)


def _publish(path: Path, value: Mapping[str, object], *, equal_ok: bool = False) -> None:
    quality._publish(Path(path), value, equal_ok=equal_ok)


def _replace(path: Path, value: Mapping[str, object]) -> None:
    """Replace mutable manifest/progress state while keeping private bytes."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    stage = Path(name)
    try:
        stage.unlink()
        _publish(stage, value)
        stage.replace(path)
    finally:
        if stage.exists():
            stage.unlink()


def _runtime_binding() -> dict[str, object]:
    """Hash executing engine/AI sources and any resolved native extensions."""
    from shengji.engine import combos, fast
    package_root = Path(game.__file__).resolve().parents[1]
    source_hashes: dict[str, str] = {}
    native_hashes: dict[str, str] = {}
    for dirname in ("engine", "ai"):
        root = package_root / dirname
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(package_root))
            if path.suffix in (".py", ".pyx"):
                source_hashes[relative] = _sha_bytes(path.read_bytes())
            elif path.suffix in (".so", ".dylib", ".pyd"):
                native_hashes[relative] = _sha_bytes(path.read_bytes())
    activation = package_root / "engine" / "fast.py"
    if activation.exists():
        source_hashes[str(activation.relative_to(package_root))] = _sha_bytes(activation.read_bytes())
    native = getattr(fast, "_fast", None)
    native_origin = getattr(native, "__file__", None) if native is not None else None
    resolved_native = None
    if native_origin:
        native_path = Path(native_origin).resolve()
        if not native_path.is_file():
            raise HistoricalAnalyzeError("resolved native engine missing")
        resolved_native = {"origin": str(native_path),
                           "sha256": _sha_bytes(native_path.read_bytes())}
    have_fast = bool(getattr(fast, "HAVE_FAST", False) and native is not None)
    active = bool(getattr(fast, "_saved", {})) and have_fast \
        and getattr(combos, "decompose", None) is getattr(fast, "decompose", None)
    return {"source_hashes": source_hashes, "native_hashes": native_hashes,
            "engine_fast_use_fast": bool(getattr(fast, "_USE_FAST", active)),
            "engine_fast_active": active,
            "engine_fast_have_fast": have_fast,
            "resolved_native": resolved_native}


def _score_position(payload: tuple[str, dict[str, object], dict[str, int], tuple[int, ...]]) -> dict[str, object]:
    packet_hash, packet_payload, chosen, indices = payload
    packet = DecisionPacket.from_mapping(packet_payload)
    rnd = game._round_from_snapshot(packet.state)
    initial = game._state_snapshot(rnd)
    scores: dict[str, dict[str, int]] = {}
    for index in indices:
        if isinstance(index, bool) or not isinstance(index, int) \
                or not 0 <= index < len(packet.candidates):
            raise HistoricalAnalyzeError("historical score candidate index drift")
        scores[str(index)] = {}
        for continuation in CONTINUATIONS:
            bot = game.ProductionBallotBot(seed=0)
            bot.rollout_policy, bot.EXACT_ENDGAME = game._continuation(
                continuation, packet.team)
            sampled = {seat: list(rnd.hands[seat]) for seat in range(4)
                       if seat != rnd.turn}
            session = bot._new_exact_world_session(rnd, list(rnd.buried))
            points = bot._rollout(rnd, rnd.turn, sampled, list(rnd.buried),
                                  list(packet.candidates[index]),
                                  exact_session=session)
            scores[str(index)][continuation] = game.signed_level_utility(
                int(points), banker_seat=rnd.banker, perspective_seat=packet.team)
            if game._state_snapshot(rnd) != initial:
                raise HistoricalAnalyzeError("historical score mutated input")
    return {"schema": SCHEMA, "mode": MODE, "status": "ok",
            "packet_sha256": packet_hash, "coordinate": list(packet.coordinate),
            "role": chosen.get("role"), "decision_ordinal": packet.decision_index,
            "chosen": dict(chosen), "scores": scores}


def _bootstrap(values: Sequence[float]) -> dict[str, object] | None:
    return quality._bootstrap(values, seed=BOOTSTRAP_SEED,
                              replicates=BOOTSTRAP_REPLICATES)


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Average each contrast within deal coordinates before bootstrapping."""
    by_deal: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
    for row in rows:
        by_deal.setdefault(tuple(row["coordinate"]), []).append(row)
    contrasts = ("historical_vs_compact1", "historical_vs_batch4",
                 "compact1_vs_batch4")
    result: dict[str, object] = {}
    for contrast in contrasts:
        if contrast == "historical_vs_compact1":
            left, right = "historical", "compact1"
        elif contrast == "historical_vs_batch4":
            left, right = "historical", "batch4"
        else:
            left, right = "compact1", "batch4"
        continuations: dict[str, object] = {}
        for continuation in CONTINUATIONS:
            deal_values = []
            for coordinate in sorted(by_deal):
                values = []
                for row in by_deal[coordinate]:
                    scores = row["scores"]
                    li = row["chosen"][left]
                    ri = row["chosen"][right]
                    values.append(scores[str(li)][continuation] - scores[str(ri)][continuation])
                if values:
                    deal_values.append(sum(values) / len(values))
            continuations[continuation] = _bootstrap(deal_values)
        result[contrast] = continuations
    return result


def _historical_positions(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    positions: dict[str, dict[str, object]] = {}
    for row in rows:
        for raw_position in row.get("positions", ()):
            packet = compare.prepare_position(row, raw_position)
            choice = raw_position.get("chosen_action", {})
            index = choice.get("candidate_index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise HistoricalAnalyzeError("historical choice index drift")
            if packet.sha256 in positions:
                raise HistoricalAnalyzeError("duplicate historical packet")
            positions[packet.sha256] = {"packet": packet,
                                        "row": row, "historical_index": index,
                                        "position": raw_position}
    return positions


def analyze(panel_root: Path, calls_root: Path, out: Path, *, workers: int = 1,
            max_seconds: float = 120, require_complete: bool = True,
            progress_sink: Callable[[dict[str, int]], object] | None = None) -> dict[str, object]:
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= MAX_WORKERS:
        raise HistoricalAnalyzeError("workers must be between 1 and 16")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) \
            or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise HistoricalAnalyzeError("max_seconds must be positive")
    manifest, role_rows, panel_sha, _groups = compare.prepare_panel(
        Path(panel_root), require_complete=require_complete)
    config, config_sha = _load(Path(calls_root) / "config.json")
    inputs = config.get("inputs")
    if config.get("mode") != "historical-snapshots" or type(inputs) is not dict \
            or inputs.get("panel_manifest_sha256") != panel_sha:
        raise HistoricalAnalyzeError("historical call config binding drift")
    try:
        collection_result, collection_sha = _load(Path(calls_root) / "result.json")
    except HistoricalAnalyzeError as exc:
        raise HistoricalAnalyzeError("historical call collection not terminal") from exc
    collection_status = collection_result.get("status")
    if collection_status not in CALL_TERMINAL_STATUSES:
        raise HistoricalAnalyzeError("historical call collection not terminal")
    historical = _historical_positions(role_rows)
    positions = {packet_hash: item["packet"] for packet_hash, item in historical.items()}
    decisions, call_hashes, refused, calls_meta = quality.saved_decisions(
        Path(calls_root), positions)
    matched = {packet_hash for packet_hash in positions
               if packet_hash in decisions["compact1"] and packet_hash in decisions["batch4"]}
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    if out.stat().st_mode & 0o077:
        raise HistoricalAnalyzeError("analyzer output must be private (mode 700)")
    recipe = {"schema": SCHEMA, "mode": MODE, "panel_manifest_sha256": panel_sha,
              "calls_config_sha256": config_sha, "call_hashes": call_hashes,
              "packet_hashes": sorted(matched), "continuations": list(CONTINUATIONS),
              "engine_sha256": _sha_bytes(Path(game.__file__).read_bytes()),
              "runtime_binding": _runtime_binding(),
              "collection_result_sha256": collection_sha,
              "compare_sha256": _sha_bytes(Path(compare.__file__).read_bytes()),
              "saved_call_parser_sha256": _sha_bytes(Path(quality.__file__).read_bytes()),
              "caller_sha256": _sha_bytes(Path(__file__).read_bytes())}
    config_path = out / "config.json"
    if config_path.exists():
        old, _ = _load(config_path)
        if old != recipe:
            raise HistoricalAnalyzeError("conflicting historical analyzer resume recipe")
    else:
        _publish(config_path, recipe)
    rows: list[dict[str, object]] = []
    pending: list[tuple[str, dict[str, object], dict[str, int], tuple[int, ...]]] = []
    for packet_hash in sorted(matched):
        item = historical[packet_hash]
        packet = item["packet"]
        chosen = {"historical": item["historical_index"],
                  "compact1": decisions["compact1"][packet_hash],
                  "batch4": decisions["batch4"][packet_hash],
                  "coordinate": list(packet.coordinate), "role": item["row"]["role"]}
        path = out / f"score-{packet_hash}.json"
        if path.exists():
            row, _ = _load(path)
            if row.get("packet_sha256") != packet_hash or row.get("chosen") != chosen:
                raise HistoricalAnalyzeError("historical score input drift")
            rows.append(row)
            continue
        indices = tuple(sorted(set(chosen[arm] for arm in ARMS)))
        pending.append((packet_hash, packet.payload(), chosen, indices))
    started = time.monotonic()
    initial_completed = len(rows)
    def progress_payload(status: str) -> dict[str, object]:
        completed_new = len(rows) - initial_completed
        return {"schema": SCHEMA, "mode": MODE, "status": status,
                "completed": len(rows), "total": len(matched),
                "uncomputed": max(0, len(pending) - completed_new)}

    _replace(out / "progress.json", progress_payload("running"))

    def publish_row(row: dict[str, object]) -> None:
        _publish(out / f"score-{row['packet_sha256']}.json", row)
        rows.append(row)
        if progress_sink:
            progress_sink({"completed": len(rows),
                           "pending": max(0, len(pending) -
                                           (len(rows) - initial_completed))})
        _replace(out / "progress.json", progress_payload("running"))

    def failed(payload, exc):
        return {"schema": SCHEMA, "mode": MODE, "status": "failed",
                "packet_sha256": payload[0], "coordinate": payload[1]["coordinate"],
                "role": payload[2]["role"], "chosen": payload[2],
                "error": f"{type(exc).__name__}: {exc}"}

    if workers == 1:
        for payload in pending:
            if time.monotonic() - started > max_seconds:
                break
            try:
                row = _score_position(payload)
            except Exception as exc:
                row = failed(payload, exc)
            publish_row(row)
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        futures = {}
        iterator = iter(pending)
        try:
            while len(futures) < workers and time.monotonic() - started < max_seconds:
                payload = next(iterator, None)
                if payload is None:
                    break
                futures[pool.submit(_score_position, payload)] = payload
            while futures:
                remaining = max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                done, _ = wait(tuple(futures), timeout=remaining,
                               return_when=FIRST_COMPLETED)
                if not done:
                    break
                for future in done:
                    payload = futures.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = failed(payload, exc)
                    publish_row(row)
                while len(futures) < workers and time.monotonic() - started < max_seconds:
                    payload = next(iterator, None)
                    if payload is None:
                        break
                    futures[pool.submit(_score_position, payload)] = payload
            # Submitted finite work is drained after a soft admission deadline.
            while futures:
                done, _ = wait(tuple(futures))
                for future in done:
                    payload = futures.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = failed(payload, exc)
                    publish_row(row)
        finally:
            pool.shutdown(wait=True)
    uncomputed = len(pending) - (len(rows) - (len(matched) - len(pending)))
    good = [row for row in rows if row.get("status") == "ok"]
    errors = [row for row in rows if row.get("status") == "failed"]
    summary = {"schema": SCHEMA, "mode": MODE, "positions": len(positions),
               "matched_positions": len(matched), "scored_positions": len(good),
               "unmatched_positions": len(positions) - len(matched),
               "refused_calls": refused, "error_positions": len(errors),
               "deadline_uncomputed_positions": max(0, uncomputed),
               "role_games": len(role_rows),
               "independent_deals": len({tuple(row["coordinate"]) for row in role_rows}),
               "historical_reference_token_usage": None,
               "old_token_usage": None,
               "unknown_old_token_usage": True,
               "collection_status": collection_status,
               "partial_data_caveat": collection_status != "historical-comparison-complete",
               "source_calls": calls_meta,
               "contrasts": summarize(good),
               "continuations": {"primary": PRIMARY_CONTINUATION,
                                  "sensitivity": "heuristic-all"},
               "claim": "Opened historical fixed-continuation diagnostic; not optimal regret, causal tool effect, or paired gameplay."}
    result = {"schema": SCHEMA, "mode": MODE, "private": True,
              "status": ("incomplete" if uncomputed else
                         "complete-with-errors" if errors else "complete"),
              "recipe": recipe, "summary": summary}
    result_body = dict(result)
    result_body["result_sha256"] = _sha(result_body)
    immutable = out / f"result-{result_body['result_sha256']}.json"
    if not immutable.exists():
        _publish(immutable, result_body)
    result = result_body
    _replace(out / "result.json", result)
    _replace(out / "progress.json", progress_payload(str(result["status"])))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", required=True, type=Path)
    parser.add_argument("--calls-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=120)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = analyze(args.panel_root, args.calls_root, args.out,
                         workers=args.workers, max_seconds=args.max_seconds,
                         require_complete=not args.allow_incomplete)
    except HistoricalAnalyzeError as exc:
        parser.error(str(exc))
    print(json.dumps({"schema": result["schema"], "mode": result["mode"],
                      "status": result["status"], "summary": result["summary"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
