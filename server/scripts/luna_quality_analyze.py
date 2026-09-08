"""Analyze saved compact1/batch4 calls against a fresh production panel.

The output is a fixed-continuation proxy diagnostic, not an optimal-regret
label or a paired-gameplay result.  This script never contacts a provider.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import json
import math
import random
import time
import uuid
from pathlib import Path
from typing import Callable, Mapping, Sequence

from scripts import luna_quality_compare as source
from scripts import luna_token_pilot as pilot
from shengji.luna import game
from shengji.luna.atomic_io import publish_exclusive_bytes
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.turn import DecisionPacket


SCHEMA = "luna-quality-analyzer-v1"
CONTINUATIONS = ("smart-all", "heuristic-all")
PRIMARY_CONTINUATION = "smart-all"
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260906
MAX_WORKERS = 16


class QualityAnalyzeError(ValueError):
    """A saved source, call, quality row, or resume recipe was refused."""


def _now() -> float:
    """Clock seam for bounded admission; evaluation never consults it."""
    return time.monotonic()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _load(path: Path) -> tuple[dict[str, object], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityAnalyzeError(f"invalid source {path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise QualityAnalyzeError(f"non-canonical source {path}")
    return value, _sha_bytes(raw)


def _publish(path: Path, value: Mapping[str, object], *, equal_ok=False) -> None:
    publish_exclusive_bytes(path, canonical_json_bytes(dict(value)), mode=0o600,
                            existing_equal_ok=equal_ok)


def _publish_progress(out: Path, value: Mapping[str, object]) -> None:
    """Replace mutable progress through an atomic immutable staging file."""
    stage = Path(out) / f".progress-{uuid.uuid4().hex}.json"
    _publish(stage, value)
    stage.replace(Path(out) / "progress.json")


@dataclass(frozen=True)
class Position:
    packet: DecisionPacket
    row: Mapping[str, object]
    stage: Mapping[str, object]
    split: str


def panel_positions(
        panel_root: Path, *, require_population: bool = True
        ) -> tuple[dict[str, object], dict[str, Position], str]:
    manifest, rows, manifest_sha = source._verify_panel(
        Path(panel_root), require_population=require_population)
    positions: dict[str, Position] = {}
    for row in rows:
        stages = row.get("stages")
        if type(stages) is not list:
            raise QualityAnalyzeError("panel stages drift")
        packets = source._stage_packets(row)
        by_ordinal = {stage["decision_ordinal"]: stage for stage in stages}
        for ordinal, _, packet in packets:
            stage = by_ordinal.get(ordinal)
            if stage is None:
                raise QualityAnalyzeError("panel stage binding drift")
            if packet.sha256 in positions:
                raise QualityAnalyzeError("duplicate panel packet")
            positions[packet.sha256] = Position(
                packet, row, stage, str(row.get("split", "")))
    return manifest, positions, manifest_sha


def _call_files(calls_root: Path) -> list[tuple[Path, dict[str, object], str]]:
    files = sorted(Path(calls_root).glob("compact1-[0-9]*.json")) + \
        sorted(Path(calls_root).glob("batch4-[0-9]*.json"))
    result = []
    for path in files:
        row, digest = _load(path)
        if row.get("arm") not in ("compact1", "batch4"):
            raise QualityAnalyzeError("call arm drift")
        result.append((path, row, digest))
    return result


def saved_decisions(
        calls_root: Path, positions: Mapping[str, Position]
        ) -> tuple[dict[str, dict[str, int]], dict[str, str], int,
                   list[dict[str, object]]]:
    """Verify accepted call packets and return arm->packet->candidate index."""
    decisions: dict[str, dict[str, int]] = {"compact1": {}, "batch4": {}}
    call_hashes: dict[str, str] = {}
    refused = 0
    calls_meta: list[dict[str, object]] = []
    seen_packets: dict[str, set[str]] = {"compact1": set(), "batch4": set()}
    for path, call, digest in _call_files(calls_root):
        arm = call["arm"]
        call_hashes[path.name] = digest
        packet_hashes = call.get("packet_hashes")
        packets_raw = call.get("packets")
        if type(packet_hashes) is not list or type(packets_raw) is not list \
                or len(packet_hashes) != len(packets_raw):
            raise QualityAnalyzeError("call packet collection drift")
        if any(type(packet_hash) is not str for packet_hash in packet_hashes):
            raise QualityAnalyzeError("call packet hash drift")
        if len(set(packet_hashes)) != len(packet_hashes):
            raise QualityAnalyzeError("duplicate arm packet")
        decoded = [DecisionPacket.from_mapping(raw) for raw in packets_raw]
        if [packet.sha256 for packet in decoded] != packet_hashes:
            raise QualityAnalyzeError("call packet SHA mismatch")
        if seen_packets[arm].intersection(packet_hashes):
            raise QualityAnalyzeError("duplicate arm packet")
        seen_packets[arm].update(packet_hashes)
        if any(packet_hash not in positions for packet_hash in packet_hashes):
            raise QualityAnalyzeError("call packet is not in panel")
        accepted = call.get("accepted") is True
        if not accepted:
            refused += 1
            calls_meta.append({"name": path.name, "sha256": digest,
                               "arm": arm, "accepted": False,
                               "usage_known": call.get("usage") is not None})
            continue
        raw_decisions = call.get("decisions")
        if type(raw_decisions) is not list or len(raw_decisions) != len(decoded):
            raise QualityAnalyzeError("accepted decision count mismatch")
        for packet_hash, decision, packet in zip(packet_hashes, raw_decisions,
                                                  decoded, strict=True):
            if (type(decision) is not dict
                    or set(decision) != {"packet_sha256", "candidate_index",
                                         "confidence", "planning_note"}
                    or decision.get("packet_sha256") != packet_hash):
                raise QualityAnalyzeError("accepted decision packet binding drift")
            index = decision.get("candidate_index")
            if isinstance(index, bool) or not isinstance(index, int) \
                    or not 0 <= index < len(packet.candidates):
                raise QualityAnalyzeError("accepted candidate index drift")
            if packet_hash in decisions[arm]:
                raise QualityAnalyzeError("duplicate arm packet decision")
            decisions[arm][packet_hash] = index
        calls_meta.append({"name": path.name, "sha256": digest,
                           "arm": arm, "accepted": True,
                           "packet_count": len(decoded),
                           "usage_known": call.get("usage") is not None})
    return decisions, call_hashes, refused, calls_meta


def production_index(position: Position) -> int | None:
    """Resolve the recorded production action into the wide panel ballot."""
    stage = position.stage
    candidates = [tuple(cards) for cards in stage["candidate_ballot"]]
    production_ballot = stage.get("production_ballot")
    production_play_index = stage.get("production_play_index")
    if (type(production_ballot) is list and isinstance(production_play_index, int)
            and not isinstance(production_play_index, bool)
            and 0 <= production_play_index < len(production_ballot)):
        action = tuple(production_ballot[production_play_index])
        if action in candidates:
            return candidates.index(action)
    # A failed throw may have no wide-ballot equivalent; never substitute 0.
    action = stage.get("attempted_action")
    if type(action) is list and tuple(action) in candidates:
        return candidates.index(tuple(action))
    return None


def _evaluate_position(payload: tuple[str, dict[str, object], dict[str, object],
                                         tuple[int, ...]]) -> dict[str, object]:
    packet_hash, packet_payload, chosen, indices = payload
    packet = DecisionPacket.from_mapping(packet_payload)
    rnd = game._round_from_snapshot(packet.state)
    initial_state = game._state_snapshot(rnd)
    scores: dict[str, dict[str, int]] = {}
    for index in indices:
        if isinstance(index, bool) or not 0 <= index < len(packet.candidates):
            raise QualityAnalyzeError("evaluation candidate index drift")
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
            if game._state_snapshot(rnd) != initial_state:
                raise QualityAnalyzeError("rollout mutated evaluation input")
    return {"schema": SCHEMA, "status": "ok", "packet_sha256": packet_hash,
            "coordinate": list(packet.coordinate),
            "split": source.quality_panel.deal_split(packet.coordinate),
            "decision_index": packet.decision_index,
            "chosen": chosen, "production_index": chosen["production"],
            "scores": scores}


def _bootstrap(values: Sequence[float], *, seed: int = BOOTSTRAP_SEED,
               replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, object] | None:
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n
             for _ in range(replicates)]
    means.sort()
    return {"replicates": replicates, "seed": seed,
            "mean": sum(values) / n,
            "interval95": [means[int(.025 * (replicates - 1))],
                           means[int(.975 * (replicates - 1))]],
            "deals": n}


def summarize(rows: Sequence[Mapping[str, object]], *, refused_calls: int = 0,
              unmatched_positions: int = 0) -> dict[str, object]:
    ordered_rows = sorted(
        rows,
        key=lambda row: (tuple(row["coordinate"]),
                         row.get("decision_index", -1),
                         row.get("packet_sha256", ""),
                         canonical_json_bytes(row)))

    def metrics_for(subset):
        by_deal: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
        for row in sorted(
                subset,
                key=lambda value: (tuple(value["coordinate"]),
                                   value.get("decision_index", -1),
                                   value.get("packet_sha256", ""),
                                   canonical_json_bytes(value))):
            by_deal.setdefault(tuple(row["coordinate"]), []).append(row)
        metrics: dict[str, object] = {}
        for arm in ("compact1", "batch4"):
            metrics[arm] = {}
            for continuation in CONTINUATIONS:
                arm_values: list[float] = []
                for deal in sorted(by_deal):
                    deal_rows = by_deal[deal]
                    diffs = []
                    for row in deal_rows:
                        scores = row["scores"]
                        chosen = row["chosen"][arm]
                        production = row["production_index"]
                        if production is not None:
                            diffs.append(scores[str(chosen)][continuation]
                                          - scores[str(production)][continuation])
                    if diffs:
                        arm_values.append(sum(diffs) / len(diffs))
                metrics[arm][f"vs_production:{continuation}"] = _bootstrap(arm_values)
        arm_values = {}
        for continuation in CONTINUATIONS:
            diffs = []
            for deal in sorted(by_deal):
                deal_rows = by_deal[deal]
                per_position = []
                for row in deal_rows:
                    scores = row["scores"]
                    per_position.append(
                        scores[str(row["chosen"]["compact1"])][continuation]
                        - scores[str(row["chosen"]["batch4"])][continuation])
                if per_position:
                    diffs.append(sum(per_position) / len(per_position))
            arm_values[continuation] = _bootstrap(diffs)
        return by_deal, metrics, arm_values

    by_deal, metrics, arm_values = metrics_for(ordered_rows)
    split_metrics = {}
    for split in ("fit", "validation"):
        split_rows = [row for row in ordered_rows if row.get("split") == split]
        split_deals, split_arm, split_pair = metrics_for(split_rows)
        split_metrics[split] = {"positions": len(split_rows),
                                "deals": len(split_deals),
                                "arms_vs_production": split_arm,
                                "compact1_vs_batch4": split_pair}
    return {"schema": SCHEMA, "positions": len(ordered_rows),
            "deals": len(by_deal), "matched_positions": len(rows),
            "unmatched_positions": unmatched_positions,
            "refused_calls": refused_calls,
            "continuations": {"primary": PRIMARY_CONTINUATION,
                               "sensitivity": "heuristic-all"},
            "arms_vs_production": metrics,
            "compact1_vs_batch4": arm_values,
            "by_split": split_metrics,
            "bootstrap": {"replicates": BOOTSTRAP_REPLICATES,
                          "seed": BOOTSTRAP_SEED},
            "deadline_semantics": (
                "soft admission deadline; submitted finite positions were drained"),
            "claim": "Fixed-continuation proxy only; not optimal regret, value ground truth, or paired gameplay."}


def analyze(panel_root: Path, calls_root: Path, out: Path, *, workers: int = 1,
            max_seconds: float = 120, progress_sink: Callable[[dict[str, int]], object] | None = None,
            require_population: bool = True) -> dict[str, object]:
    if isinstance(workers, bool) or not isinstance(workers, int) \
            or not 1 <= workers <= MAX_WORKERS:
        raise QualityAnalyzeError("workers must be between 1 and 16")
    if (isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise QualityAnalyzeError("max_seconds must be positive")
    manifest, positions, manifest_sha = panel_positions(
        panel_root, require_population=require_population)
    decisions, call_hashes, refused, calls_meta = saved_decisions(calls_root, positions)
    matched = {packet_hash for packet_hash in positions
               if packet_hash in decisions["compact1"]
               and packet_hash in decisions["batch4"]}
    # A missing production equivalent only removes the production contrast;
    # teacher-vs-teacher compact1/batch4 remains a valid matched position.
    usable = matched
    unmatched = len(positions) - len(matched)
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    if out.stat().st_mode & 0o077:
        raise QualityAnalyzeError("analyzer output must be private (mode 700)")
    recipe = {"schema": SCHEMA, "panel_manifest_sha256": manifest_sha,
              "calls": call_hashes, "packet_hashes": sorted(positions),
              "continuations": list(CONTINUATIONS),
              "bootstrap_seed": BOOTSTRAP_SEED,
              "bootstrap_replicates": BOOTSTRAP_REPLICATES,
              "caller_sha256": _sha_bytes(Path(__file__).read_bytes())}
    config_path = out / "config.json"
    if config_path.exists():
        old, _ = _load(config_path)
        if old != recipe:
            raise QualityAnalyzeError("conflicting analyzer resume recipe")
    else:
        _publish(config_path, recipe)
    rows: list[dict[str, object]] = []
    pending: list[tuple[str, dict[str, object], dict[str, object], tuple[int, ...]]] = []
    for packet_hash in sorted(usable):
        position = positions[packet_hash]
        chosen = {"compact1": decisions["compact1"][packet_hash],
                  "batch4": decisions["batch4"][packet_hash],
                  "production": production_index(position)}
        path = out / f"quality-{packet_hash}.json"
        if path.exists():
            row, _ = _load(path)
            if row.get("packet_sha256") != packet_hash or row.get("chosen") != chosen:
                raise QualityAnalyzeError("quality shard input drift")
            rows.append(row)
        else:
            indices = tuple(sorted(index for index in set(chosen.values())
                                   if index is not None))
            pending.append((packet_hash, position.packet.payload(), chosen, indices))
    started = _now()
    completed = len(rows)
    initial_completed = completed
    _publish_progress(out, {"schema": SCHEMA, "status": "running",
                            "completed": completed,
                            "total": len(usable), "uncomputed": len(pending)})

    def publish_row(row: dict[str, object]) -> None:
        nonlocal completed
        _publish(out / f"quality-{row['packet_sha256']}.json", row)
        rows.append(row)
        completed += 1
        _publish_progress(out, {"schema": SCHEMA, "status": "running",
                                "completed": completed,
                                "total": len(usable),
                                "uncomputed": max(0, len(pending) -
                                                  (completed - initial_completed))})
        if progress_sink:
            progress_sink({"completed": completed,
                           "pending": max(0, len(pending) -
                                          (completed - initial_completed))})

    deadline_uncomputed = 0
    if workers == 1:
        for payload in pending:
            if _now() - started > max_seconds:
                break
            try:
                row = _evaluate_position(payload)
            except Exception as exc:
                row = {"schema": SCHEMA, "packet_sha256": payload[0],
                       "coordinate": payload[1]["coordinate"],
                       "split": source.quality_panel.deal_split(payload[1]["coordinate"]),
                       "status": "failed", "error": f"{type(exc).__name__}: {exc}",
                       "chosen": payload[2], "production_index": payload[2]["production"]}
            publish_row(row)
        deadline_uncomputed = len(pending) - (completed - initial_completed)
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        futures = {}
        iterator = iter(pending)
        timed_out = False

        def consume(done):
            for future in done:
                payload = futures.pop(future)
                try:
                    row = future.result()
                except Exception as exc:
                    row = {"schema": SCHEMA, "packet_sha256": payload[0],
                           "coordinate": payload[1]["coordinate"],
                           "split": source.quality_panel.deal_split(payload[1]["coordinate"]),
                           "status": "failed",
                           "error": f"{type(exc).__name__}: {exc}",
                           "chosen": payload[2], "production_index": payload[2]["production"]}
                publish_row(row)

        try:
            while len(futures) < workers and _now() - started < max_seconds:
                payload = next(iterator, None)
                if payload is None:
                    break
                futures[pool.submit(_evaluate_position, payload)] = payload
            while futures:
                remaining = max_seconds - (_now() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                done, _ = wait(tuple(futures), timeout=remaining,
                               return_when=FIRST_COMPLETED)
                if not done:
                    timed_out = True
                    break
                consume(done)
                while (len(futures) < workers
                       and _now() - started < max_seconds):
                    payload = next(iterator, None)
                    if payload is None:
                        break
                    futures[pool.submit(_evaluate_position, payload)] = payload
            if timed_out:
                # A soft deadline stops new admissions only.  Drain already
                # submitted finite positions so completed futures are retained
                # and no worker is abandoned or killed.
                while futures:
                    done, _ = wait(tuple(futures))
                    consume(done)
            deadline_uncomputed = len(pending) - (completed - initial_completed)
        finally:
            pool.shutdown(wait=True)
    good = [row for row in rows if row.get("status", "ok") == "ok"]
    summary = summarize(good, refused_calls=refused,
                        unmatched_positions=unmatched + len(rows) - len(good))
    summary.update({"source_calls": calls_meta,
                    "known_usage_calls": sum(meta["usage_known"]
                                              for meta in calls_meta),
                    "unknown_usage_calls": sum(not meta["usage_known"]
                                                for meta in calls_meta),
                    "missing_panel_positions": len(positions) - len(matched),
                    "failed_quality_positions": len(rows) - len(good),
                    "deadline_uncomputed_positions": deadline_uncomputed,
                    "fit_positions": sum(position.split == "fit"
                                         for position in positions.values()
                                         if position.packet.sha256 in matched),
                    "validation_positions": sum(position.split == "validation"
                                                for position in positions.values()
                                                if position.packet.sha256 in matched),
                    "missing_production_positions": sum(
                        production_index(position) is None for position in positions.values()
                        if position.packet.sha256 in matched)})
    result = {"schema": SCHEMA, "private": True, "recipe": recipe,
              "summary": summary}
    if deadline_uncomputed == 0:
        _publish(out / "manifest.json", result, equal_ok=True)
        _publish_progress(out, {"schema": SCHEMA, "status": "complete",
                                "completed": completed, "total": len(usable),
                                "uncomputed": 0})
    else:
        result["status"] = "incomplete"
        result["deadline_semantics"] = (
            "soft admission deadline; submitted finite positions were drained")
        _publish_progress(out, {"schema": SCHEMA, "status": "incomplete",
                                "completed": completed, "total": len(usable),
                                "uncomputed": deadline_uncomputed})
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--calls-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=120)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_seconds) or args.max_seconds <= 0:
        parser.error("--max-seconds must be positive")
    analyze(args.panel_root, args.calls_root, args.out,
            workers=args.workers, max_seconds=args.max_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
