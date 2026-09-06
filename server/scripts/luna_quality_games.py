"""Run the bounded PT-Luna batch4/compact1 paired-gameplay comparison.

This is a private, play-only diagnostic.  The two arms play the same fixed
root twice, with the mirror swapping the arm's team assignment.  Calls are
made through the existing token pilot and every accepted response is consumed
by the existing :class:`TurnDriver` before the next state is admitted.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence, Callable

from shengji.luna import game
from shengji.luna import quality_panel
from shengji.luna import token_batch
from shengji.luna import transport
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.turn import DecisionPacket, PlannerResponse, TurnDriver, Usage
from scripts import luna_quality_compare as quality_compare
from scripts import luna_token_pilot as token_pilot


ARMS = ("batch4", "compact1")
MAX_BATCH = 4
DEFAULT_TOKENS = 6_000_000
DEFAULT_WALL_SECONDS = 10_800
DEFAULT_CALL_SECONDS = 90
# Two arms share the live population. Eight independent games give batch4
# roughly four eligible movers rather than systematically underfilling it.
WAVE_SIZE = 8
RESULT_SCHEMA = "luna-quality-gameplay-v1"


class QualityGameplayError(ValueError):
    """A panel, saved call, response, or gameplay artifact was refused."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _load_json(path: Path) -> object:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityGameplayError(f"invalid JSON artifact {path}") from exc
    if canonical_json_bytes(value) != raw:
        raise QualityGameplayError(f"non-canonical artifact {path}")
    return value


def _publish(path: Path, value: object) -> None:
    from shengji.luna.atomic_io import publish_exclusive_bytes
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    publish_exclusive_bytes(path, canonical_json_bytes(value), mode=0o600,
                            existing_equal_ok=True)


def _strict_sha(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise QualityGameplayError(f"{label} must be a lowercase SHA-256")
    return value


def _verify_game_roster(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Verify each source root without selecting on status or trajectory."""
    roster = []
    for row in rows:
        coordinate = tuple(row.get("coordinate", ()))
        try:
            coord = game.LunaCoordinate(*coordinate)
        except Exception as exc:
            raise QualityGameplayError("panel coordinate drift") from exc
        root_snapshot = row.get("root_snapshot")
        if type(root_snapshot) is not dict:
            raise QualityGameplayError("panel root snapshot absent")
        root_sha = _strict_sha(row.get("root_sha256"), "panel root SHA")
        if row.get("split") != quality_panel.deal_split(coordinate):
            raise QualityGameplayError("panel root split drift")
        if row.get("root_rank") != coord.trump_rank:
            raise QualityGameplayError("panel root rank drift")
        try:
            root = game._round_from_snapshot(root_snapshot)
            if game.root_identity(root) != root_sha:
                raise QualityGameplayError("panel root identity drift")
            if row.get("root_suit") != game.root_trump_mode(root):
                raise QualityGameplayError("panel root trump mode drift")
        except QualityGameplayError:
            raise
        except Exception as exc:
            raise QualityGameplayError("panel root snapshot drift") from exc
        roster.append({"coordinate": list(coord.cluster_key),
                       "root_sha256": root_sha,
                       "root_suit": row["root_suit"],
                       "split": quality_panel.deal_split(coord.cluster_key),
                       "row_sha256": _sha(dict(row))})
    if len({tuple(row["coordinate"]) for row in roster}) != len(roster):
        raise QualityGameplayError("panel root roster duplicate")
    return roster


def _verify_panel(panel_root: Path, *, require_population: bool = True):
    """Use the quality-panel verifier, then add gameplay root checks."""
    manifest, rows, manifest_sha = quality_compare._verify_panel(
        Path(panel_root), require_population=require_population)
    roster = _verify_game_roster(rows)
    if require_population and {
            tuple(item["coordinate"]) for item in roster
    } != set(game.LunaDesign().root_coordinates):
        raise QualityGameplayError("panel population coordinate roster drift")
    return manifest, rows, manifest_sha


def _caller_sha() -> str:
    return _sha_bytes(Path(__file__).read_bytes())


def _game_name(coordinate: tuple[str, int, int], mirror: int,
               suffix: str) -> str:
    rank, banker, replicate = coordinate
    return f"game-{rank}-b{banker}-r{replicate}-m{mirror}-{suffix}.json"


@dataclass
class _Game:
    coordinate: tuple[str, int, int]
    mirror: int
    source: Mapping[str, object]
    game: game.LunaSelfPlayGame
    driver: TurnDriver
    ready: token_pilot.ReadyResponse


def _make_games(rows: Sequence[Mapping[str, object]]) -> list[_Game]:
    result: list[_Game] = []
    for row in rows:
        coordinate = tuple(row["coordinate"])
        root_sha = _strict_sha(row["root_sha256"], "panel root SHA")
        # The source secret is intentionally not needed: ballots are fixed by
        # the root identity and are identical for both mirrors.
        seed = bytes.fromhex(root_sha)
        for mirror in game.MIRRORS:
            fresh = game.LunaSelfPlayGame(root=game._round_from_snapshot(
                row["root_snapshot"]), coordinate=coordinate, mirror=mirror,
                seed_secret=seed)
            if fresh.root_sha256 != root_sha:
                raise QualityGameplayError("game root identity drift")
            ready = token_pilot.ReadyResponse()
            result.append(_Game(coordinate, mirror, row, fresh,
                                TurnDriver(fresh, ready), ready))
    return result


def _packet(record: _Game) -> DecisionPacket:
    return token_pilot.driver_packet(record.driver)


def _unb64(value: object, label: str) -> bytes:
    if type(value) is not str:
        raise QualityGameplayError(f"saved {label} evidence drift")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise QualityGameplayError(f"saved {label} evidence drift") from exc


def _saved_responses(row: Mapping[str, object],
                     packets: Sequence[DecisionPacket]) -> tuple[PlannerResponse, ...]:
    """Reconstruct accepted compact responses from private bytes, never fake them."""
    evidence = row.get("private_evidence")
    checked = tuple(packets)
    if type(evidence) is not dict or evidence.get("schema") != token_batch.BATCH_SCHEMA:
        raise QualityGameplayError("accepted call lacks compact private evidence")
    if evidence.get("packets") != [p.payload() for p in checked]:
        raise QualityGameplayError("saved packet payload drift")
    if row.get("packet_hashes") != [p.sha256 for p in checked]:
        raise QualityGameplayError("saved packet hash drift")
    prompt = _unb64(evidence.get("prompt_base64"), "prompt")
    expected_prompt = token_batch.compact_prompt(checked).encode("utf-8")
    if prompt != expected_prompt:
        raise QualityGameplayError("saved compact prompt drift")
    schema = evidence.get("output_schema")
    expected_schema = token_batch.batch_output_schema()
    if schema != expected_schema or _unb64(evidence.get("schema_base64"), "schema") != canonical_json_bytes(schema):
        raise QualityGameplayError("saved compact schema drift")
    final_raw = _unb64(evidence.get("final_base64"), "final response")
    final = transport._strict_json(final_raw, "saved final response")
    stdout = _unb64(evidence.get("stdout_base64"), "trace")
    stderr = _unb64(evidence.get("stderr_base64"), "stderr")
    if evidence.get("stderr_base64") is not None and type(stderr) is not bytes:
        raise QualityGameplayError("saved stderr drift")
    wall_ms = evidence.get("wall_ms")
    if isinstance(wall_ms, bool) or not isinstance(wall_ms, int) or wall_ms < 0:
        raise QualityGameplayError("saved usage wall drift")
    try:
        _events, raw_usage, message = transport._events_and_usage(stdout)
    except Exception as exc:
        raise QualityGameplayError("saved provider trace drift") from exc
    if evidence.get("raw_usage") != raw_usage:
        raise QualityGameplayError("saved usage telemetry drift")
    if transport._strict_json(message.encode("utf-8"), "saved agent message") != final:
        raise QualityGameplayError("saved response message drift")
    request = evidence.get("request")
    if type(request) is not dict:
        raise QualityGameplayError("saved provider request absent")
    required_request = {"schema", "model", "reasoning_effort", "policy_mode",
                        "prompt_profile", "disabled_features", "packet_sha256",
                        "memory_sha256", "prompt_sha256", "output_schema_sha256",
                        "timeout_seconds"}
    if set(request) != required_request or request.get("schema") != "pt-luna-codex-batch-request-v1":
        raise QualityGameplayError("saved provider request shape drift")
    if (request["packet_sha256"] != [p.sha256 for p in checked]
            or request["memory_sha256"] != [p.memory.sha256 for p in checked]
            or request["prompt_sha256"] != _sha_bytes(prompt)
            or request["output_schema_sha256"] != _sha(expected_schema)
            or request["policy_mode"] != "play-only"
            or request["model"] != game.MODEL
            or request["reasoning_effort"] != "medium"
            or request["prompt_profile"] != "baseline"):
        raise QualityGameplayError("saved provider request binding drift")
    if request["disabled_features"] != list(transport.DISABLED_FEATURES):
        raise QualityGameplayError("saved provider feature binding drift")
    provider_request_sha = _sha_bytes(canonical_json_bytes(request))
    if evidence.get("provider_request_sha256") != provider_request_sha:
        raise QualityGameplayError("saved provider request hash drift")
    response_body = {"schema": "pt-luna-codex-batch-response-v1", "final": final,
                     "usage": raw_usage, "trace_sha256": _sha_bytes(stdout),
                     "stderr_sha256": _sha_bytes(stderr), "returncode": 0}
    provider_response_sha = _sha_bytes(canonical_json_bytes(response_body))
    if evidence.get("provider_response_sha256") != provider_response_sha:
        raise QualityGameplayError("saved provider response hash drift")
    try:
        intents = token_batch.decode_batch(final, checked)
        responses = tuple(PlannerResponse(
            intent, token_batch._usage(raw_usage, wall_ms, len(checked), slot), 0,
            packet.team, packet.sha256, packet.memory.sha256,
            provider_request_sha, provider_response_sha)
            for slot, (packet, intent) in enumerate(zip(checked, intents, strict=True)))
    except Exception as exc:
        raise QualityGameplayError("saved response decode drift") from exc
    if evidence.get("usage") != Usage(
            raw_usage["input_tokens"], raw_usage["output_tokens"],
            raw_usage["input_tokens"] + raw_usage["output_tokens"], wall_ms,
            raw_usage["cached_input_tokens"], raw_usage["cache_write_input_tokens"],
            raw_usage["reasoning_output_tokens"]).payload():
        raise QualityGameplayError("saved allocated usage drift")
    expected_decisions = [{
        "packet_sha256": packet.sha256,
        "candidate_index": response.intent.candidate_index,
        "confidence": response.intent.confidence,
        "planning_note": response.intent.planning_note,
    } for packet, response in zip(checked, responses, strict=True)]
    if row.get("decisions") != expected_decisions:
        raise QualityGameplayError("saved response decision drift")
    expected_usage = {
        key: sum(response.usage.payload()[key] for response in responses)
        for key in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                    "output_tokens", "reasoning_output_tokens", "total_tokens", "wall_ms")}
    row_usage = row.get("usage")
    if (type(row_usage) is not dict
            or any(row_usage.get(k) != v for k, v in expected_usage.items()
                   if k in row_usage)
            or any(k not in row_usage for k in
                   ("input_tokens", "cached_input_tokens", "output_tokens",
                    "reasoning_output_tokens", "total_tokens", "wall_ms"))):
        raise QualityGameplayError("saved row usage drift")
    return responses


def _responses(row: Mapping[str, object], packets: Sequence[DecisionPacket],
               direct: object) -> tuple[PlannerResponse, ...]:
    if direct is None:
        try:
            return _saved_responses(row, packets)
        except QualityGameplayError:
            raise
        except Exception as exc:
            raise QualityGameplayError("saved response evidence drift") from exc
    if type(direct) not in (list, tuple) or len(direct) != len(packets):
        raise QualityGameplayError("provider response count drift")
    try:
        return tuple(value if type(value) is PlannerResponse
                     else PlannerResponse.from_mapping(value) for value in direct)
    except Exception as exc:
        raise QualityGameplayError("provider response shape drift") from exc


def _validate_call_row(row: object, arm: str, index: int,
                       packets: Sequence[DecisionPacket]) -> Mapping[str, object]:
    if type(row) is not dict or type(row.get("accepted")) is not bool:
        raise QualityGameplayError("pilot call row shape drift")
    if row.get("arm", arm) != arm or row.get("index", index) != index:
        raise QualityGameplayError("pilot call identity drift")
    if row.get("packet_hashes") != [packet.sha256 for packet in packets]:
        raise QualityGameplayError("pilot call packet hash drift")
    return row


def _preflight_responses(packets: Sequence[DecisionPacket],
                         responses: Sequence[PlannerResponse]) -> None:
    if len(packets) != len(responses):
        raise QualityGameplayError("provider response count drift")
    for packet, response in zip(packets, responses, strict=True):
        try:
            TurnDriver._validate_response(response, packet)
        except Exception as exc:
            raise QualityGameplayError("provider response packet binding drift") from exc
        if response.intent.kind != "play" or response.intent.candidate_index is None \
                or response.intent.candidate_index >= len(packet.candidates):
            raise QualityGameplayError("play-only response candidate drift")


def _state_body(records: Sequence[_Game], *, call_index: int) -> dict[str, object]:
    games = []
    for record in sorted(records, key=lambda item: (item.coordinate, item.mirror)):
        games.append({"coordinate": list(record.coordinate), "mirror": record.mirror,
                      "root_sha256": record.game.root_sha256,
                      "state": game._state_snapshot(record.game.rnd),
                      "memories": {str(team): memory.payload()
                                   for team, memory in record.driver.memories.items()},
                      "decision_index": record.driver.decision_index,
                      "complete": record.game.complete,
                      "failed": record.game.failed})
    return {"schema": RESULT_SCHEMA + "-state", "call_index": call_index,
            "games": games}


def _publish_completed(record: _Game, root: Path) -> None:
    if not record.game.complete:
        return
    terminal = record.game.terminal_receipt().payload()
    sealed = record.game.sealed_trajectory()
    trajectory = sealed.body
    _publish(root / _game_name(record.coordinate, record.mirror, "terminal"), terminal)
    _publish(root / _game_name(record.coordinate, record.mirror, "trajectory"), trajectory)
    _publish(root / _game_name(record.coordinate, record.mirror, "metadata"), {
        "schema": RESULT_SCHEMA + "-game-metadata",
        "comparison": "batch4-vs-compact1-play-only",
        "coordinate": list(record.coordinate), "mirror": record.mirror,
        "split": quality_panel.deal_split(record.coordinate),
        "root_sha256": record.game.root_sha256,
        "agent_for_team": {"0": game.agent_for_team(record.mirror, 0),
                            "1": game.agent_for_team(record.mirror, 1)},
        "arms": {"agent0": "batch4", "agent1": "compact1"},
        "continuation": "play-only",
        "terminal_receipt_sha256": terminal["receipt_sha256"],
        "trajectory_sha256": sealed.sha256,
    })


def _pilot_inputs(manifest: Mapping[str, object], manifest_sha: str,
                  roster: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {"comparison": "batch4-vs-compact1-paired-gameplay-play-only",
            "panel_manifest_sha256": manifest_sha,
            "panel_schema": manifest.get("schema"),
            "root_split_roster": [dict(row) for row in roster],
            "caller_sha256": _caller_sha(),
            "arms": list(ARMS),
            "agent_assignment": {"mirror0": {"team0": "batch4", "team1": "compact1"},
                                 "mirror1": {"team0": "compact1", "team1": "batch4"}},
            "transport": {"policy_mode": "play-only", "prompt_profile": "baseline",
                            "model": game.MODEL, "reasoning_effort": "medium",
                            "tools": "disabled", "disabled_features": list(transport.DISABLED_FEATURES),
                            "max_batch": MAX_BATCH},
            "wave_size": WAVE_SIZE,
            "provider_refusal": "retain failed call; quarantine affected deal and any unfinished mirror; "
                                "continue other fixed deals; no retries or replacement deals",
            "schedule": "sorted coordinate waves of eight; mirror0 then mirror1; "
                        "cycle-even batch4 then compact1, cycle-odd compact1 then batch4; "
                        "one live game per coordinate per cycle"}


def _progress(root: Path, records: Sequence[_Game], pilot: object,
              *, status: str, error: str | None = None,
              call_count: int = 0) -> dict[str, object]:
    body = {"schema": RESULT_SCHEMA + "-progress", "status": status,
            "error": error, "call_count": call_count,
            "pilot_arms": token_pilot.summarize(getattr(pilot, "rows", [])),
            "charged_tokens": getattr(pilot, "charged", None),
            "completed_games": sum(item.game.complete for item in records),
            "failed_games": sum(bool(item.game.failed) for item in records),
            "total_games": len(records),
            "state": _state_body(records, call_index=call_count),
            "games": [{"coordinate": list(item.coordinate), "mirror": item.mirror,
                       "root_sha256": item.game.root_sha256,
                       "complete": item.game.complete, "failed": item.game.failed,
                       "decision_index": item.driver.decision_index}
                      for item in sorted(records, key=lambda x: (x.coordinate, x.mirror))]}
    # Progress is an append-only witness.  A restart can therefore publish a
    # different state without colliding with an earlier immutable receipt.
    _publish(root / f"progress-{call_count:08d}-{_sha(body)[:16]}.json", body)
    return body


def _quarantine_refusal(root: Path, records: Sequence[_Game], chosen: Sequence[_Game],
                        row: Mapping[str, object], call_index: int) -> None:
    """Keep a failed provider call from discarding unrelated, independent deals.

    Do not invent a move or retry. Its incomplete deal cannot contribute a
    paired score, so do not spend on that deal's remaining mirror either.
    Already completed games and every earlier call remain intact.
    """
    coordinates = {item.coordinate for item in chosen}
    reason = f"provider refusal at call {call_index}: {row.get('error')}"
    affected = []
    for item in records:
        if item.coordinate in coordinates and not item.game.complete and not item.game.failed:
            item.game.fail(reason)
            affected.append({"coordinate": list(item.coordinate), "mirror": item.mirror})
    _publish(root / f"refusal-{call_index:08d}.json", {
        "schema": RESULT_SCHEMA + "-refusal", "call_index": call_index,
        "arm": row["arm"], "packet_hashes": row["packet_hashes"],
        "reason": reason, "quarantined": affected, "retry": False})


def run_gameplay(panel_root: Path, out: Path, *, tokens: int = DEFAULT_TOKENS,
                 wall_seconds: int = DEFAULT_WALL_SECONDS,
                 call_seconds: int = DEFAULT_CALL_SECONDS,
                 codex_binary: Path = Path("codex"),
                 pilot_factory: Callable[[object], object] | None = None,
                 require_population: bool = True) -> dict[str, object]:
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in (tokens, wall_seconds, call_seconds)):
        raise QualityGameplayError("token and time limits must be positive")
    manifest, rows, manifest_sha = _verify_panel(
        Path(panel_root), require_population=require_population)
    roster = _verify_game_roster(rows)
    records = _make_games(rows)
    args = argparse.Namespace(mode="gameplay", private_root=Path(panel_root),
                              out=Path(out), codex_binary=Path(codex_binary),
                              arms=list(ARMS), tokens=tokens,
                              wall_seconds=wall_seconds, call_seconds=call_seconds)
    pilot = (pilot_factory or token_pilot.Pilot)(args)
    root = Path(out)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pilot.configure(_pilot_inputs(manifest, manifest_sha, roster))
    call_index = 0
    try:
        for wave_start in range(0, len(rows), WAVE_SIZE):
            wave_coordinates = {tuple(row["coordinate"])
                                for row in rows[wave_start:wave_start + WAVE_SIZE]}
            # Complete mirror 0 for this coordinate wave before admitting any
            # mirror 1 state.  This is the explicit mirror0-then-mirror1
            # phase boundary recorded in the run manifest.
            for mirror in game.MIRRORS:
                wave = [item for item in records
                        if item.coordinate in wave_coordinates
                        and item.mirror == mirror]
                cycle = 0
                while any(not item.game.complete and not item.game.failed for item in wave):
                    processed_coordinates: set[tuple[str, int, int]] = set()
                    priority = (ARMS if cycle % 2 == 0 else tuple(reversed(ARMS)))
                    for arm in priority:
                        if arm == "batch4":
                            eligible = [item for item in sorted(wave, key=lambda x: (x.coordinate, x.mirror))
                                        if not item.game.complete and not item.game.failed
                                        and item.coordinate not in processed_coordinates
                                        and game.agent_for_team(item.mirror, item.game.acting_team) == 0]
                            for start in range(0, len(eligible), MAX_BATCH):
                                chosen = eligible[start:start + MAX_BATCH]
                                packets = tuple(_packet(item) for item in chosen)
                                row, direct = pilot.call("batch4", call_index, packets)
                                row = _validate_call_row(row, "batch4", call_index, packets)
                                if not row.get("accepted"):
                                    _quarantine_refusal(root, records, chosen, row, call_index)
                                    call_index += 1
                                    _progress(root, records, pilot, status="running-with-refusals",
                                              call_count=call_index)
                                    continue
                                responses = _responses(row, packets, direct)
                                _preflight_responses(packets, responses)
                                for item, response in zip(chosen, responses, strict=True):
                                    item.ready.response = response
                                for item in chosen:
                                    item.driver.step()
                                    processed_coordinates.add(item.coordinate)
                                    _publish_completed(item, root)
                                _publish(root / f"state-{call_index:08d}.json",
                                         _state_body(chosen, call_index=call_index))
                                call_index += 1
                        else:
                            for item in sorted(wave, key=lambda x: (x.coordinate, x.mirror)):
                                if item.game.complete or item.game.failed or item.coordinate in processed_coordinates:
                                    continue
                                if game.agent_for_team(item.mirror, item.game.acting_team) != 1:
                                    continue
                                packet = _packet(item)
                                row, direct = pilot.call("compact1", call_index, (packet,))
                                row = _validate_call_row(row, "compact1", call_index, (packet,))
                                if not row.get("accepted"):
                                    _quarantine_refusal(root, records, (item,), row, call_index)
                                    call_index += 1
                                    _progress(root, records, pilot, status="running-with-refusals",
                                              call_count=call_index)
                                    continue
                                response = _responses(row, (packet,), direct)
                                _preflight_responses((packet,), response)
                                item.ready.response = response[0]
                                item.driver.step()
                                processed_coordinates.add(item.coordinate)
                                _publish_completed(item, root)
                                _publish(root / f"state-{call_index:08d}.json",
                                         _state_body((item,), call_index=call_index))
                                call_index += 1
                    cycle += 1
    except Exception as exc:
        _progress(root, records, pilot, status="stopped", error=f"{type(exc).__name__}: {exc}",
                  call_count=call_index)
        raise
    if not all(item.game.complete or item.game.failed for item in records):
        return _progress(root, records, pilot, status="stopped", call_count=call_index)
    failed_games = sum(bool(item.game.failed) for item in records)
    result = {"schema": RESULT_SCHEMA,
              "status": ("paired-gameplay-panel-complete-with-refusals" if failed_games
                         else "paired-gameplay-complete"),
              "interpretation": "Matched batch4-vs-compact1 play-only paired gameplay; both Luna agents are real and mirror assignments swap teams. No MC arm, rollout-enabled arm, or strength claim.",
              "panel_manifest_sha256": manifest_sha, "root_split_roster": roster,
              "caller_sha256": _caller_sha(), "games": len(records),
              "completed_games": sum(item.game.complete for item in records),
              "failed_games": failed_games, "call_count": call_index,
              "arms": list(ARMS), "mirror_order": [0, 1],
              "transport": {"policy_mode": "play-only", "prompt_profile": "baseline",
                          "model": game.MODEL, "reasoning_effort": "medium",
                          "tools": "disabled", "disabled_features": list(transport.DISABLED_FEATURES),
                            "max_batch": MAX_BATCH},
              "pilot_arms": token_pilot.summarize(getattr(pilot, "rows", [])),
              "charged_tokens": getattr(pilot, "charged", None),
              "wave_size": WAVE_SIZE,
              "schedule": "sorted coordinate waves of eight; mirror0 then mirror1; "
                          "cycle-even batch4 then compact1, cycle-odd compact1 then batch4; "
                          "one live game per coordinate per cycle"}
    _publish(root / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--tokens", type=int, required=True)
    parser.add_argument("--wall-seconds", type=int, required=True)
    parser.add_argument("--call-seconds", type=int, default=DEFAULT_CALL_SECONDS)
    args = parser.parse_args(argv)
    if any(value < 1 for value in (args.tokens, args.wall_seconds, args.call_seconds)):
        parser.error("token and time limits must be positive")
    try:
        run_gameplay(args.panel_root, args.out, tokens=args.tokens,
                     wall_seconds=args.wall_seconds, call_seconds=args.call_seconds,
                     codex_binary=args.codex_binary)
    except Exception as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
