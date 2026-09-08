"""Prepare historical teacher states for the existing compact Luna transport.

No provider is called here. The archived teacher's ordered ballot is retained;
the current engine must reproduce its selected immediate transition. These
opened historical states are not the fresh panel's fit/validation population.
"""
from __future__ import annotations

import copy
import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

from scripts import luna_historical_panel as panel
from scripts import luna_token_pilot as pilot_module
from shengji.luna import game
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.turn import DecisionPacket, PhaseContext, TeamMemory


class HistoricalCompareError(ValueError):
    """Archived evidence cannot be consumed without changing its meaning."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def prepare_position(row: Mapping[str, object], position: Mapping[str, object]) \
        -> DecisionPacket:
    """Validate real engine compatibility, then preserve the historical ballot.

    The old decision hash includes a different observation schema. Keep it in
    source provenance, not in place of the new transport's state-bound hash.
    Both compact arms start with empty memory, unlike the historical session.
    """
    try:
        snapshot = position["snapshot"]
        rnd = game._round_from_snapshot(snapshot)
        if game._state_snapshot(rnd) != snapshot:
            raise HistoricalCompareError("historical snapshot round-trip drift")
        coordinate = tuple(row["coordinate"])
        game.LunaCoordinate(*coordinate)
        role = row["role"]
        if role not in ("banker-team", "attacker-team"):
            raise HistoricalCompareError("historical role drift")
        team = row["treatment_team"]
        expected_team = rnd.banker % 2 if role == "banker-team" else 1 - rnd.banker % 2
        if type(team) is not int or team != expected_team or rnd.turn % 2 != team:
            raise HistoricalCompareError("historical mover/team drift")
        if coordinate[:2] != (rnd.trump_rank, rnd.banker):
            raise HistoricalCompareError("historical coordinate/state drift")
        original_ballot = position["candidate_ballot"]
        ballot = [candidate["cards"] for candidate in original_ballot]
        if type(ballot) is not list or len(ballot) < 2 or any(
                type(action) is not list or not action or
                any(type(card) is not str for card in action) for action in ballot):
            raise HistoricalCompareError("historical candidate ballot drift")
        if len({tuple(sorted(action)) for action in ballot}) != len(ballot):
            raise HistoricalCompareError("historical duplicate candidate drift")
        choice = position["chosen_action"]
        chosen = choice["cards"]
        if type(chosen) is not list or chosen not in ballot:
            raise HistoricalCompareError("historical chosen action drift")
        index = choice["candidate_index"]
        if type(index) is not int or not 0 <= index < len(ballot) or ballot[index] != chosen:
            raise HistoricalCompareError("historical chosen index drift")
        if type(position["decision_ordinal"]) is not int or position["decision_ordinal"] < 0:
            raise HistoricalCompareError("historical decision ordinal drift")
        # Validate every offered action, but only claim cross-version transition
        # equivalence for the chosen action whose archived after-state exists.
        for action in ballot:
            replay = copy.deepcopy(rnd)
            try:
                replay.play(replay.turn, list(action))
            except Exception as exc:
                raise HistoricalCompareError("historical candidate legality drift") from exc
            if action == chosen and game._state_snapshot(replay) != position["state_after_action"]:
                raise HistoricalCompareError("historical chosen transition drift")
        state_sha = _sha({"team": team, "snapshot": snapshot})
        return DecisionPacket(
            coordinate=coordinate, mirror=int(role == "attacker-team"),
            team=team, acting_seat=rnd.turn,
            decision_index=position["decision_ordinal"], decision_sha256=state_sha,
            state=copy.deepcopy(snapshot), candidates=tuple(tuple(a) for a in ballot),
            production_prior_index=0, memory=TeamMemory.initial(team, state_sha),
            phase=PhaseContext(), budget={
                "rollout_calls": 0, "rollout_calls_limit": game.MAX_ROLLOUT_CALLS_PER_DECISION,
                "used": 0, "round_used": 0,
                "decision_limit": game.MAX_EVALUATIONS_PER_DECISION,
                "round_limit": game.MAX_EVALUATIONS_PER_ROUND,
            })
    except HistoricalCompareError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HistoricalCompareError("historical packet input drift") from exc


def group_positions(rows):
    """One role and earliest selected threshold per group; independent deals.

    A position satisfying multiple thresholds occurs once. Different roles or
    times from one deal never share a model batch; they remain one statistical
    cluster in any later readout.
    """
    groups = {}
    seen = set()
    for row in rows:
        for position in row["positions"]:
            packet = prepare_position(row, position)
            if packet.sha256 in seen:
                raise HistoricalCompareError("historical duplicate position")
            seen.add(packet.sha256)
            thresholds = position["thresholds"]
            if type(thresholds) is not list or not thresholds or any(
                    type(t) is not int or t not in (0, 6, 12, 18) for t in thresholds):
                raise HistoricalCompareError("historical threshold drift")
            key = (row["role"], min(thresholds))
            group = groups.setdefault(key, [])
            if any(existing.coordinate == packet.coordinate for existing in group):
                raise HistoricalCompareError("historical batch repeats a deal")
            group.append(packet)
    return {key: tuple(sorted(packets, key=lambda p: p.coordinate))
            for key, packets in sorted(groups.items())}


def load_panel(root: Path, *, require_complete: bool = True):
    """Verify exported bytes at first consumption, without replaying old games."""
    root = Path(root)
    manifest, digest = panel._read_json(root / "manifest.json")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if (manifest.get("schema") != panel.SCHEMA or manifest.get("mode") != panel.MODE
            or manifest.get("manifest_sha256") != _sha(body)
            or manifest.get("binding", {}).get("report_sha256") != panel.REPORT_SHA256):
        raise HistoricalCompareError("historical manifest binding drift")
    rows, seen = [], set()
    for entry in manifest.get("shards", ()):
        coordinate, role = tuple(entry["coordinate"]), entry["role"]
        game.LunaCoordinate(*coordinate)
        if role not in panel.ROLES or (coordinate, role) in seen:
            raise HistoricalCompareError("historical shard roster drift")
        seen.add((coordinate, role))
        filename = entry["filename"]
        if Path(filename).name != filename:
            raise HistoricalCompareError("historical shard path drift")
        row, row_sha = panel._read_json(root / filename)
        if (row_sha != entry["sha256"] or tuple(row.get("coordinate", ())) != coordinate
                or row.get("role") != role or row.get("schema") != panel.SCHEMA
                or row.get("mode") != panel.MODE or row.get("incomplete") is not False
                or entry.get("incomplete") is not False
                or entry.get("position_count") != len(row.get("positions", ()))):
            raise HistoricalCompareError("historical shard bytes or identity drift")
        binding = row.get("binding", {})
        if any(binding.get(k) != v for k, v in manifest["binding"].items()):
            raise HistoricalCompareError("historical shard provenance drift")
        if binding.get("coordinate") != list(coordinate) or binding.get("role") != role:
            raise HistoricalCompareError("historical shard coordinate binding drift")
        rows.append(row)
    # This archived population is 13 ranks x two bankers x two role games,
    # with ONE replicate per deal. It is not today's 52-root fresh design.
    expected = {(tuple(c), role) for c in game.LunaDesign().root_coordinates
                if c[2] == 0 for role in panel.ROLES}
    if require_complete and (manifest.get("incomplete") is not False or seen != expected):
        raise HistoricalCompareError("historical complete population required")
    if (manifest.get("counts") != {"roles": len(rows),
                                  "positions": sum(len(r["positions"]) for r in rows)}):
        raise HistoricalCompareError("historical manifest count drift")
    return manifest, rows, digest


def prepare_panel(root: Path, *, require_complete: bool = True):
    manifest, rows, digest = load_panel(root, require_complete=require_complete)
    groups = group_positions(rows)
    if not groups:
        raise HistoricalCompareError("historical panel has no usable positions")
    return manifest, rows, digest, groups


def describe_panel(rows, groups):
    packets = [p for group in groups.values() for p in group]
    return {"mode": panel.MODE, "role_games": len(rows),
            "independent_deals": len({tuple(row["coordinate"]) for row in rows}),
            "positions": len(packets),
            "nt_deals": len({p.coordinate for p in packets if p.state["trump_is_nt"]}),
            "group_counts": {f"{role}:{threshold}": len(group)
                             for (role, threshold), group in groups.items()},
            "scheduled_calls": {"compact1": len(packets),
                                "batch4": sum((len(group) + 3) // 4
                                              for group in groups.values())},
            "missing_thresholds": {
                f"{row['coordinate']}:{row['role']}": row["missing_thresholds"]
                for row in rows},
            "historical_reference_new_provider_calls": 0,
            "historical_reference_token_usage": None,
            "split": "opened-historical-not-fresh-fit-or-validation"}


def run_compare(root: Path, out: Path, *, tokens: int, wall_seconds: int,
                call_seconds: int = 90, codex_binary: Path = Path("codex"),
                pilot_factory=None, require_complete: bool = True):
    """Use the existing compact transport, budgets and immutable call journal.

    Historical choices stay in provenance, never in the model's packet. Both
    queried arms have the SAME play-only prompt, effort and empty memory. The
    recorded reference is the different, stateful rollout-enabled interface.
    """
    if min(tokens, wall_seconds, call_seconds) < 1:
        raise HistoricalCompareError("historical comparison limits must be positive")
    manifest, rows, digest, groups = prepare_panel(root, require_complete=require_complete)
    args = argparse.Namespace(mode="historical-snapshots", private_root=Path(root),
                              out=Path(out), codex_binary=Path(codex_binary),
                              arms=["compact1", "batch4"], tokens=tokens,
                              wall_seconds=wall_seconds, call_seconds=call_seconds)
    pilot = (pilot_factory or pilot_module.Pilot)(args)
    pilot.configure({"panel_manifest_sha256": digest, "source": manifest["binding"],
                     "caller_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "opened_historical": True, "retry_failed_calls": False,
                     "continue_independent_refusals": True,
                     "historical_reference": "recorded-luna0-high-stateful-rollout-enabled",
                     "historical_choices_exposed_to_provider": False})
    stopped, dispatched = None, 0
    try:
        for group_number, packets in enumerate(groups.values()):
            order = args.arms if group_number % 2 == 0 else list(reversed(args.arms))
            # Alternate arm order on identical, independent-deal groups.
            for start in range(0, len(packets), 4):
                batch = packets[start:start + 4]
                for arm in order:
                    calls = [(p,) for p in batch] if arm == "compact1" else [batch]
                    for packet_group in calls:
                        pilot.call(arm, dispatched, packet_group)
                        dispatched += 1
    except RuntimeError as exc:
        if not str(exc).startswith("pilot admission budget exhausted"):
            raise
        stopped = str(exc)
    failed = sum(row.get("accepted") is not True for row in pilot.rows)
    return pilot.finish({
        "status": ("historical-comparison-truncated" if stopped else
                   "historical-comparison-complete-with-refusals" if failed else
                   "historical-comparison-complete"),
        "panel": describe_panel(rows, groups), "panel_manifest_sha256": digest,
        "actual_call_count": dispatched, "failed_call_count": failed,
        "stopped": stopped,
        "interpretation": "Opened historical-distribution interface comparison, not "
            "fresh validation, paired gameplay, or a causal estimate for rollout tools. "
            "The saved teacher used high effort, growing session memory and rollout tools; "
            "both compact arms are play-only snapshots. Common-continuation scoring is "
            "separate. Retain failures and all deal clusters, not just agreement or wins."})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="make bounded provider calls")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tokens", type=int)
    parser.add_argument("--wall-seconds", type=int)
    parser.add_argument("--call-seconds", type=int, default=90)
    parser.add_argument("--codex-binary", type=Path, default=Path("codex"))
    args = parser.parse_args(argv)
    if args.execute:
        if args.out is None or args.tokens is None or args.wall_seconds is None:
            parser.error("--execute requires --out, --tokens and --wall-seconds")
        result = run_compare(args.panel_root, args.out, tokens=args.tokens,
                             wall_seconds=args.wall_seconds, call_seconds=args.call_seconds,
                             codex_binary=args.codex_binary)
    else:
        _, rows, _, groups = prepare_panel(args.panel_root)
        result = describe_panel(rows, groups)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
