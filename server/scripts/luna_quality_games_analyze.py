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
    pairs, missing, coverage = [], [], Counter()
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
            coverage[root["root_suit"]] += 1
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
        "completed_games": completed_games, "complete_pairs": len(pairs),
        "missing_games": missing, "pairs": pairs,
        "complete_pair_root_suits": dict(sorted(coverage.items())),
        "complete_pair_ranks": dict(sorted(Counter(p["coordinate"][0] for p in pairs).items())),
        "complete_pair_splits": dict(sorted(Counter(p["split"] for p in pairs).items())),
        "batch4_signed_levels_per_game": _interval([p["mean_signed_levels"] for p in pairs]),
        "batch4_game_win_rate": _interval([p["batch4_win_fraction"] for p in pairs]),
        "paired_deal_wins_ties_losses": {
            "wins": sum(p["mean_signed_levels"] > 0 for p in pairs),
            "ties": sum(p["mean_signed_levels"] == 0 for p in pairs),
            "losses": sum(p["mean_signed_levels"] < 0 for p in pairs)},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    print(canonical_json_bytes(analyze(args.run)).decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
