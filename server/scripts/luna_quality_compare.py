"""Compare compact1 and batch4 on fresh production decision panels.

This is an independent-state teacher-response and token diagnostic, not a
quality, value, or paired-gameplay result. The existing
``luna_token_pilot.Pilot`` owns provider calls, pending reservations,
immutable call files, and usage; a separate evaluator scores these choices.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from shengji.luna import game
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna import quality_panel
from scripts import luna_token_pilot as token_pilot


ARMS = ("compact1", "batch4")
GROUP_SIZE = 4
DEFAULT_TOKENS = 6_000_000
DEFAULT_WALL_SECONDS = 10_800
DEFAULT_CALL_SECONDS = 90


class QualityCompareError(ValueError):
    """A panel source, packet, or comparison input was refused."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _load_canonical(path: Path) -> tuple[dict[str, object], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityCompareError(f"invalid panel source {path}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise QualityCompareError(f"non-canonical panel source {path}")
    return value, _sha_bytes(raw)


def _verify_panel(panel_root: Path, *, require_population: bool = False) \
        -> tuple[dict[str, object], list[dict[str, object]], str]:
    """Read manifest and each listed shard exactly once, verifying each hash."""
    manifest, manifest_sha = _load_canonical(Path(panel_root) / "manifest.json")
    if manifest.get("schema") != quality_panel.SCHEMA \
            or manifest.get("private") is not True:
        raise QualityCompareError("panel manifest schema/source drift")
    entries = manifest.get("shards")
    if type(entries) is not list or not entries:
        raise QualityCompareError("panel manifest shard list drift")
    if require_population and len(entries) != len(game.LunaDesign().root_coordinates):
        raise QualityCompareError("panel population is not the fresh 52-root design")
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, int, int]] = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"coordinate", "sha256", "status"}:
            raise QualityCompareError("panel manifest shard entry drift")
        coordinate = entry.get("coordinate")
        coord = game.LunaCoordinate(*(coordinate or ()))
        key = coord.cluster_key
        if key in seen:
            raise QualityCompareError("panel manifest duplicate coordinate")
        seen.add(key)
        path = quality_panel.shard_path(Path(panel_root), key)
        row, row_sha = _load_canonical(path)
        if (row_sha != entry["sha256"]
                or tuple(row.get("coordinate", ())) != key
                or row.get("status") != entry["status"]):
            raise QualityCompareError("panel shard hash or coordinate mismatch")
        if row.get("production_policy") != quality_panel.PRODUCTION_POLICY:
            raise QualityCompareError("panel production source drift")
        rows.append(row)
    rows.sort(key=lambda row: tuple(row["coordinate"]))
    return manifest, rows, manifest_sha


def _stage_packets(row: Mapping[str, object]) -> list[tuple[int, game.LunaCoordinate, object]]:
    coordinate = tuple(row["coordinate"])
    coord = game.LunaCoordinate(*coordinate)
    stages = row.get("stages")
    if type(stages) is not list:
        raise QualityCompareError("panel stage list drift")
    result: list[tuple[int, game.LunaCoordinate, object]] = []
    for stage in stages:
        if type(stage) is not dict:
            raise QualityCompareError("panel stage shape drift")
        ordinal = stage.get("decision_ordinal")
        snapshot = stage.get("snapshot")
        ballot = stage.get("candidate_ballot")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) \
                or type(snapshot) is not dict or type(ballot) is not list \
                or len(ballot) < 2 \
                or ordinal not in quality_panel.REQUESTED_ORDINALS:
            raise QualityCompareError("panel stage identity/ballot drift")
        rebuilt = game._round_from_snapshot(snapshot)
        before = game._state_snapshot(rebuilt)
        fresh = game.LunaSelfPlayGame(rebuilt, coordinate=coordinate, mirror=0,
                                      seed_secret=b"0" * 32)
        if game._state_snapshot(fresh.rnd) != before:
            raise QualityCompareError("LunaSelfPlayGame constructor advanced state")
        driver = token_pilot.TurnDriver(fresh, token_pilot.ReadyResponse())
        packet = token_pilot.driver_packet(driver)
        packet = replace(packet, decision_index=ordinal)
        expected_ballot = tuple(tuple(cards) for cards in ballot)
        if packet.state != snapshot or packet.candidates != expected_ballot:
            raise QualityCompareError("panel packet state or ballot mismatch")
        result.append((ordinal, coord, packet))
    return result


def build_groups(rows: Sequence[Mapping[str, object]]) \
        -> tuple[dict[int, tuple[object, ...]], dict[tuple[str, int, int], list[int]]]:
    """Build deterministic stage groups without filtering incomplete deals."""
    grouped: dict[int, list[object]] = {}
    missing: dict[tuple[str, int, int], list[int]] = {}
    for row in rows:
        coord = tuple(row["coordinate"])
        available = {stage.get("decision_ordinal") for stage in row.get("stages", ())}
        missing[coord] = [ordinal for ordinal in quality_panel.REQUESTED_ORDINALS
                          if ordinal not in available]
        for ordinal, _, packet in _stage_packets(row):
            grouped.setdefault(ordinal, []).append(packet)
    result: dict[int, tuple[object, ...]] = {}
    for ordinal, packets in grouped.items():
        packets.sort(key=lambda packet: tuple(packet.coordinate))
        coords = [packet.coordinate for packet in packets]
        if len(coords) != len(set(coords)):
            raise QualityCompareError("stage group mixes a coordinate more than once")
        result[ordinal] = tuple(packets)
    return result, missing


def _caller_sha() -> str:
    return _sha_bytes(Path(__file__).read_bytes())


def run_compare(panel_root: Path, out: Path, *, tokens: int = DEFAULT_TOKENS,
                wall_seconds: int = DEFAULT_WALL_SECONDS,
                call_seconds: int = DEFAULT_CALL_SECONDS,
                codex_binary: Path = Path("codex"),
                pilot_factory: Callable[[object], object] | None = None,
                require_population: bool = True,
                continue_independent_refusals: bool = False) -> dict[str, object]:
    manifest, rows, manifest_sha = _verify_panel(panel_root,
                                                 require_population=require_population)
    groups, missing = build_groups(rows)
    if not groups:
        raise QualityCompareError("panel contains no usable decisions")
    args = argparse.Namespace(mode="snapshots", private_root=Path(panel_root),
                              out=Path(out), codex_binary=Path(codex_binary),
                              arms=list(ARMS), tokens=tokens,
                              wall_seconds=wall_seconds, call_seconds=call_seconds)
    pilot = (pilot_factory or token_pilot.Pilot)(args)
    inputs = {"panel_manifest_sha256": manifest_sha,
              "panel_schema": manifest["schema"],
              "panel_shards": [{"coordinate": row["coordinate"],
                                 "sha256": _sha(row)} for row in rows],
              "production_policy": quality_panel.PRODUCTION_POLICY,
              "requested_ordinals": list(quality_panel.REQUESTED_ORDINALS),
              "caller_sha256": _caller_sha()}
    if continue_independent_refusals:
        inputs["refusal_policy"] = {
            "continue_independent_refusals": True,
            "failed_calls_are_retained": True,
            "failed_batch_loses_all_slots": True,
            "retry": False,
        }
    pilot.configure(inputs)
    call_count = 0
    refused_packet_count = 0
    stopped = None
    for ordinal in sorted(groups):
        packets = groups[ordinal]
        groups4 = [packets[start:start + GROUP_SIZE]
                   for start in range(0, len(packets), GROUP_SIZE)]
        stage_position = quality_panel.REQUESTED_ORDINALS.index(ordinal)
        order = ARMS if stage_position % 2 == 0 else tuple(reversed(ARMS))
        for arm in order:
            for group_index, packet_group in enumerate(groups4):
                slots = packet_group if arm == "compact1" else (packet_group,)
                for slot, payload in enumerate(slots):
                    index = ordinal * 1000 + group_index * 10 + slot
                    batch = tuple(payload) if arm == "batch4" else (payload,)
                    row, _ = pilot.call(arm, index, batch)
                    call_count += 1
                    if not row["accepted"]:
                        refused_packet_count += len(batch)
                        if continue_independent_refusals:
                            continue
                        stopped = "stopped-on-refusal"
                        break
                if stopped:
                    break
            if stopped:
                break
        if stopped:
            break
    known = sum(row.get("usage") is not None for row in pilot.rows)
    unknown = sum(row.get("usage") is None for row in pilot.rows)
    failed = sum(not row.get("accepted", False) for row in pilot.rows)
    processed_packets = sum(len(row.get("decisions", ()))
                            for row in pilot.rows if row.get("accepted"))
    if continue_independent_refusals and stopped is None and failed:
        status = "comparison-panel-complete-with-refusals"
    else:
        status = stopped or "comparison-panel-complete"
    result = pilot.finish({
        "status": status,
        "interpretation": (
            "Independent-state compact1/batch4 token diagnostic only; source is "
            "production MC panel awaiting teacher relabels. No quality score, "
            "value ground truth, paired-gameplay, or long-memory claim."),
        "panel_source": {"panel_manifest_sha256": manifest_sha,
                          "production_policy": quality_panel.PRODUCTION_POLICY,
                          "splits": {"fit": 0, "validation": 1}},
        "missing_stages": {str(key): value for key, value in sorted(missing.items())},
        "stage_ordinals": sorted(groups),
        "distinct_coordinates": len(rows),
        "actual_packet_count": sum(len(value) for value in groups.values()),
        "actual_call_count": call_count,
        "processed_packet_count": processed_packets,
        "refused_packet_count": refused_packet_count,
        "failed_call_count": failed,
        "continue_independent_refusals": continue_independent_refusals,
        "known_usage_calls": known,
        "unknown_usage_calls": unknown,
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tokens", type=int, default=DEFAULT_TOKENS)
    parser.add_argument("--wall-seconds", type=int, default=DEFAULT_WALL_SECONDS)
    parser.add_argument("--call-seconds", type=int, default=DEFAULT_CALL_SECONDS)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--continue-independent-refusals", action="store_true",
                        help="retain failed independent calls and continue the fixed schedule")
    args = parser.parse_args(argv)
    if args.tokens < 1 or args.wall_seconds < 1 or args.call_seconds < 1:
        parser.error("token and time limits must be positive")
    try:
        run_compare(args.panel_root, args.out, tokens=args.tokens,
                    wall_seconds=args.wall_seconds, call_seconds=args.call_seconds,
                    codex_binary=args.codex_binary,
                    continue_independent_refusals=args.continue_independent_refusals)
    except Exception as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
