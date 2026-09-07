"""Small-receipt readout of batch4-versus-compact1 mirrored Luna games.

This does not invoke a provider or replay trajectories. The live collector
already validates each transition; the readout validates terminal arithmetic
and its root/arm/split bindings, keeping both mirrors in one sampling unit.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from scripts import luna_quality_games as collector
from scripts.luna_quality_analyze import _bootstrap
from shengji.luna import game, quality_panel
from shengji.luna.canonical import canonical_json_bytes


def _interval(values: list[float]) -> dict | None:
    # A single deal gives a point, not an estimable population uncertainty.
    if len(values) < 2:
        return {"mean": values[0], "deals": 1, "interval95": None} if values else None
    return _bootstrap(values)


def _pair_summary(pairs: list[dict]) -> dict:
    return {
        "complete_pairs": len(pairs),
        "complete_pair_root_suits": dict(sorted(Counter(p["root_suit"] for p in pairs).items())),
        "complete_pair_ranks": dict(sorted(Counter(p["coordinate"][0] for p in pairs).items())),
        "complete_pair_splits": dict(sorted(Counter(p["split"] for p in pairs).items())),
        "batch4_signed_levels_per_game": _interval([p["mean_signed_levels"] for p in pairs]),
        "batch4_game_win_rate": _interval([p["batch4_win_fraction"] for p in pairs]),
        "paired_deal_wins_ties_losses": {
            "wins": sum(p["mean_signed_levels"] > 0 for p in pairs),
            "ties": sum(p["mean_signed_levels"] == 0 for p in pairs),
            "losses": sum(p["mean_signed_levels"] < 0 for p in pairs)}}


def analyze(out: Path) -> dict:
    out = Path(out)
    config = collector._load_json(out / "config.json")
    inputs = config["inputs"]
    if inputs["comparison"] != "batch4-vs-compact1-paired-gameplay-play-only":
        raise collector.QualityGameplayError("not a paired gameplay comparison")
    expected_assignment = {
        "mirror0": {"team0": "batch4", "team1": "compact1"},
        "mirror1": {"team0": "compact1", "team1": "batch4"}}
    if inputs["agent_assignment"] != expected_assignment:
        raise collector.QualityGameplayError("gameplay arm assignment drift")
    scope = inputs.get("scope")
    if scope is not None and scope != "bounded-coordinate-tranche":
        raise collector.QualityGameplayError("gameplay scope drift")
    roster = inputs["root_split_roster"]
    seen = set()
    pairs, missing = [], []
    completed_games = 0
    for root in roster:
        coordinate = tuple(root["coordinate"])
        game.LunaCoordinate(*coordinate)
        if coordinate in seen:
            raise collector.QualityGameplayError("duplicate gameplay deal")
        seen.add(coordinate)
        if root["split"] != quality_panel.deal_split(coordinate):
            raise collector.QualityGameplayError("gameplay split drift")
        collector._strict_sha(root["root_sha256"], "gameplay root")
        levels = []
        for mirror in game.MIRRORS:
            terminal_path = out / collector._game_name(coordinate, mirror, "terminal")
            metadata_path = out / collector._game_name(coordinate, mirror, "metadata")
            # Publication may have stopped between files. Retain the partial
            # evidence but do not convert it into a completed game or pair.
            if not terminal_path.exists() or not metadata_path.exists():
                missing.append({"coordinate": list(coordinate), "mirror": mirror,
                                "terminal_present": terminal_path.exists(),
                                "metadata_present": metadata_path.exists()})
                continue
            terminal = collector._load_json(terminal_path)
            metadata = collector._load_json(metadata_path)
            game.validate_terminal_receipt(terminal, root_sha256=root["root_sha256"],
                                           coordinate=coordinate, mirror=mirror)
            expected_metadata = {
                "schema": collector.RESULT_SCHEMA + "-game-metadata",
                "comparison": "batch4-vs-compact1-play-only",
                "coordinate": list(coordinate), "mirror": mirror,
                "split": root["split"], "root_sha256": root["root_sha256"],
                "agent_for_team": {"0": game.agent_for_team(mirror, 0),
                                   "1": game.agent_for_team(mirror, 1)},
                "arms": {"agent0": "batch4", "agent1": "compact1"},
                "continuation": "play-only",
                "terminal_receipt_sha256": terminal["receipt_sha256"],
                "trajectory_sha256": terminal["trajectory_sha256"]}
            if metadata != expected_metadata:
                raise collector.QualityGameplayError("gameplay metadata binding drift")
            # Terminal utility is team 0's, not agent 0's. Batch4 changes team
            # in mirror 1; failing to flip this sign cancels the very contrast.
            levels.append(terminal["signed_level_utility"] * (1 if mirror == 0 else -1))
            completed_games += 1
        if len(levels) == 2:
            pairs.append({"coordinate": list(coordinate), "split": root["split"],
                          "root_suit": root["root_suit"],
                          "batch4_signed_levels": levels,
                          "mean_signed_levels": sum(levels) / 2,
                          "batch4_win_fraction": sum(v > 0 for v in levels) / 2})
    result_path = out / "result.json"
    progress = sorted(out.glob("progress-*.json"))
    # At most one small result/progress receipt; no full call/trajectory scan
    # or second replay is needed just to display costs and failures.
    accounting_path = result_path if result_path.exists() else (progress[-1] if progress else None)
    accounting = collector._load_json(accounting_path) if accounting_path else {}
    if accounting.get("status") in {"paired-gameplay-complete",
                                    "paired-gameplay-tranche-complete"} and missing:
        raise collector.QualityGameplayError("completed gameplay is missing games")
    complete = not missing and bool(roster)
    return {
        "schema": "luna-quality-gameplay-readout-v1",
        **({"scope": scope,
            "source_panel_count": inputs["source_panel_count"]}
           if scope is not None else {}),
        "status": (("complete-tranche" if complete else "partial-tranche")
                   if scope is not None else
                   ("complete-panel" if complete else "partial-panel")),
        "planned_deals": len(roster), "planned_games": 2 * len(roster),
        "completed_games": completed_games,
        "missing_games": missing, "pairs": pairs,
        **_pair_summary(pairs),
        "cost_receipt": accounting_path.name if accounting_path else None,
        "reported_or_reserved_tokens": accounting.get("charged_tokens"),
        "per_arm_costs_and_failures": accounting.get("pilot_arms"),
        "interpretation": (
            "Direct batch4 vs compact1, both play-only full-information Luna. "
            "Signed levels are from batch4's perspective per game, not twice "
            "the zero-sum payoff. Bootstrap resamples complete deals with both "
            "mirrors together; incomplete pairs are excluded, not imputed. "
            "Partial-panel intervals can be completion-biased. Non-significance "
            "does not establish equivalence. No MC or rollout-enabled comparison; "
            "no deployment or data-promotion authority. Trajectories not replayed.")}


def _pool_inputs(runs: list[Path]) -> list[dict]:
    """Permit budget/date changes, not policy changes or duplicate planned deals."""
    configs, identity, coordinates, roots = [], None, set(), set()
    for run in runs:
        config = collector._load_json(run / "config.json")
        inputs = config["inputs"]
        # Full published recipe/runtime is retained; only per-tranche resource
        # ceilings, start time and the explicitly disjoint roster may differ.
        required = {"arms", "call_seconds", "mode", "model", "effort", "runtime",
                    "source", "provider_concurrency", "inputs"}
        if not required <= config.keys() or inputs.get("scope") != "bounded-coordinate-tranche":
            raise collector.QualityGameplayError("pooled gameplay requires bound tranche recipes")
        normalized = {k: v for k, v in config.items()
                      if k not in {"created_unix", "tokens", "wall_seconds", "inputs"}}
        normalized["inputs"] = {k: v for k, v in inputs.items()
                                if k not in {"root_split_roster", "selected_coordinate_count"}}
        if identity is not None and normalized != identity:
            raise collector.QualityGameplayError("pooled gameplay recipe or panel drift")
        identity = normalized
        roster = inputs["root_split_roster"]
        if not roster or inputs["selected_coordinate_count"] != len(roster):
            raise collector.QualityGameplayError("pooled gameplay tranche roster drift")
        for row in roster:
            coordinate = tuple(row["coordinate"])
            if coordinate in coordinates or row["root_sha256"] in roots:
                raise collector.QualityGameplayError("overlapping pooled gameplay deals")
            coordinates.add(coordinate)
            roots.add(row["root_sha256"])
        configs.append(config)
    return configs


def _pooled_costs(readouts: list[dict]) -> dict | None:
    costs = [row["per_arm_costs_and_failures"] for row in readouts]
    if any(not cost or set(cost) != set(collector.ARMS) for cost in costs):
        return None  # Missing accounting is not zero cost or zero failures.
    result = {}
    for arm in collector.ARMS:
        rows = [cost[arm] for cost in costs]
        total = {k: sum(row[k] for row in rows) for k in (
            "calls", "accepted_decisions", "failed_calls", "unknown_usage_calls")}
        usage = {k: sum(row["usage"][k] for row in rows) for k in (
            "input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_output_tokens", "total_tokens", "wall_ms")}
        decisions, tokens, wall = total["accepted_decisions"], usage["total_tokens"], usage["wall_ms"]
        result[arm] = {**total, "usage": usage,
                      "reported_tokens_per_accepted_decision": tokens / decisions if decisions else None,
                      "serial_decisions_per_minute": decisions * 60_000 / wall if wall else None}
    return result


def analyze_many(runs: list[Path]) -> dict:
    """Combine the fixed 8+44 tranches without replay or average-of-averages."""
    if not runs:
        raise collector.QualityGameplayError("pooled gameplay needs at least one run")
    paths = [Path(run) for run in runs]
    configs = _pool_inputs(paths)
    readouts = [analyze(path) for path in paths]
    pairs = [pair for row in readouts for pair in row["pairs"]]
    pairs.sort(key=lambda pair: tuple(pair["coordinate"]))
    planned = {tuple(root["coordinate"]) for config in configs
               for root in config["inputs"]["root_split_roster"]}
    costs = _pooled_costs(readouts)
    tokens = [row["reported_or_reserved_tokens"] for row in readouts]
    return {
        "schema": "luna-quality-gameplay-pooled-readout-v1",
        "status": ("complete-requested-tranches" if all(not row["missing_games"] for row in readouts)
                   else "partial-requested-tranches"),
        "covers_source_panel": planned == set(game.LunaDesign().root_coordinates),
        "planned_deals": len(planned), "planned_games": 2 * len(planned),
        "completed_games": sum(row["completed_games"] for row in readouts),
        "missing_games": [game_row for row in readouts for game_row in row["missing_games"]],
        "pairs": pairs, **_pair_summary(pairs),
        "per_arm_costs_and_failures": costs,
        "cost_accounting_complete": costs is not None and all(v is not None for v in tokens),
        "reported_or_reserved_tokens": sum(tokens) if all(v is not None for v in tokens) else None,
        "runs": [{"path": str(path.resolve()), "config_sha256": collector._sha(config),
                  "readout": row} for path, config, row in zip(paths, configs, readouts)],
        "interpretation": (
            "Exploratory pool of disjoint same-recipe tranches; includes the already-opened first tranche, "
            "not a fresh confirmation. Each complete deal contributes one equally weighted mirrored mean, "
            "not one vote per tranche or decision. Incomplete pairs are explicit, excluded, and can bias "
            "partial estimates. Report the fresh tranche separately. Cost ratios use summed counts, not "
            "averaged ratios. No MC/historic-teacher comparison, trajectory replay or data promotion.")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, action="append",
                        help="repeat for disjoint same-recipe tranches")
    args = parser.parse_args(argv)
    result = analyze(args.run[0]) if len(args.run) == 1 else analyze_many(args.run)
    print(canonical_json_bytes(result).decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
