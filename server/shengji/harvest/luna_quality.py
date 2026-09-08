"""Native importer for flat batch4-versus-compact1 gameplay artifacts.

Consumes completed games, including losses and lone completed mirrors, once
through the existing Luna engine replay. Partial trajectories stay in their
source directories; they are counted, never given invented terminal targets.
No model calls, historical attempt manifests, or automatic training admission.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from ..luna import game, quality_panel
from .common import ExtractResult, InputRegistry, sha256_bytes
from .luna_rpc import FORCED_POLICY, LunaFormatError, extract_games

SOURCE = "luna-quality"
COMPARISON = "batch4-vs-compact1-paired-gameplay-play-only"
CONTINUATION = "mixed-batch4-vs-compact1-play-only"


@dataclass
class QualityGame:
    trajectory: dict
    terminal: dict
    trajectory_ref: str
    provenance: dict

    @property
    def ref(self) -> str:
        return self.trajectory_ref

    @property
    def events(self) -> list[dict]:
        return self.trajectory["events"]

    @property
    def authority(self) -> dict:
        return dict(self.terminal["authority"])

    def decision_labels(self, event: dict) -> dict:
        arm = ("batch4", "compact1")[game.agent_for_team(
            self.trajectory["mirror"], event["seat"] % 2)]
        policy = f"{self.provenance['model']}:{arm}:play-only"
        if len(event["legal_ballot"]) == 1:
            policy = FORCED_POLICY
        return {"policy": policy, "provenance": {**self.provenance, "teacher_arm": arm}}


def _sources(roots: Sequence[Path], split: str, registry: InputRegistry,
             counts: dict, inventory: list) -> Iterator[QualityGame]:
    seen_coordinates, seen_roots = set(), set()
    for root in roots:
        root = Path(root)
        config_raw = registry.read_bytes(root / "config.json")
        config = json.loads(config_raw)
        inputs = config["inputs"]
        transport = inputs["transport"]
        if (inputs["comparison"] != COMPARISON
                or inputs["agent_assignment"] != {
                    "mirror0": {"team0": "batch4", "team1": "compact1"},
                    "mirror1": {"team0": "compact1", "team1": "batch4"}}
                or config.get("model") != game.MODEL
                or transport.get("model") != config["model"]
                or transport.get("reasoning_effort") != config.get("effort")
                or not isinstance(config.get("effort"), str)
                or transport.get("policy_mode") != "play-only"
                or transport.get("tools") != "disabled"):
            raise LunaFormatError("quality gameplay recipe drift")
        config_sha = sha256_bytes(config_raw)
        for row in inputs["root_split_roster"]:
            coordinate = tuple(row["coordinate"])
            game.LunaCoordinate(*coordinate)
            root_sha = row["root_sha256"]
            if coordinate in seen_coordinates or root_sha in seen_roots:
                raise LunaFormatError("overlapping quality gameplay deals")
            seen_coordinates.add(coordinate)
            seen_roots.add(root_sha)
            if row["split"] != quality_panel.deal_split(coordinate):
                raise LunaFormatError("quality gameplay source split drift")
            if row["split"] != split:
                continue  # Do not even open unselected split trajectories.
            counts["planned_deals"] += 1
            rank, banker, replicate = coordinate
            for mirror in game.MIRRORS:
                stem = f"game-{rank}-b{banker}-r{replicate}-m{mirror}"
                paths = {kind: root / f"{stem}-{kind}.json"
                         for kind in ("trajectory", "terminal", "metadata")}
                if not all(path.is_file() for path in paths.values()):
                    counts["missing_or_partial_games"] += 1
                    inventory.append({"root": str(root), "stem": stem,
                                      "status": "missing-or-partial",
                                      "present": [kind for kind, p in paths.items() if p.is_file()]})
                    continue
                trajectory_raw = registry.read_bytes(paths["trajectory"])
                sealed = game.SealedTrajectory.reopen(trajectory_raw)
                terminal = registry.read_json(paths["terminal"])
                metadata = registry.read_json(paths["metadata"])
                game.validate_terminal_receipt(
                    terminal, root_sha256=root_sha, trajectory_sha256=sealed.sha256,
                    coordinate=coordinate, mirror=mirror)
                if (sealed.body["coordinate"] != list(coordinate)
                        or sealed.body["mirror"] != mirror
                        or sealed.body["root_sha256"] != root_sha):
                    raise LunaFormatError("quality gameplay trajectory identity drift")
                expected = {
                    "schema": "luna-quality-gameplay-v1-game-metadata",
                    "comparison": "batch4-vs-compact1-play-only",
                    "coordinate": list(coordinate), "mirror": mirror,
                    "split": split, "root_sha256": root_sha,
                    "agent_for_team": {"0": game.agent_for_team(mirror, 0),
                                       "1": game.agent_for_team(mirror, 1)},
                    "arms": {"agent0": "batch4", "agent1": "compact1"},
                    "continuation": "play-only",
                    "terminal_receipt_sha256": terminal["receipt_sha256"],
                    "trajectory_sha256": sealed.sha256}
                if metadata != expected:
                    raise LunaFormatError("quality gameplay metadata binding drift")
                inventory.append({"root": str(root), "stem": stem, "status": "complete",
                                  "trajectory_sha256": sealed.sha256})
                yield QualityGame(dict(sealed.body), terminal,
                                  f"{root.name}/{paths['trajectory'].name}", {
                                      "config_sha256": config_sha, "root_sha256": root_sha,
                                      "coordinate": list(coordinate), "mirror": mirror,
                                      "split": split, "model": config["model"],
                                      "effort": config["effort"], "tools": "disabled",
                                      "continuation": CONTINUATION})


def extract_quality_games(roots: Sequence[Path], *, split: str,
                          cap: int | None = 256) -> ExtractResult:
    """Explicit one-split export; no outcomes, ranks or winners are selectors."""
    if split not in ("fit", "validation") or not roots:
        raise LunaFormatError("quality gameplay requires roots and one explicit split")
    registry, counts, inventory = InputRegistry(), {
        "planned_deals": 0, "missing_or_partial_games": 0}, []
    result = extract_games(_sources(roots, split, registry, counts, inventory),
                           source=SOURCE, cap=cap, registry=registry)
    result.counts.update(counts)
    result.extras = {"split": split, "game_inventory": inventory,
                     "continuation": CONTINUATION}
    result.notes.extend([
        "Raw full-information play-only decisions, not the historical rollout-enabled teacher.",
        "Every completed selected-split game is retained regardless of winner or mirror completion.",
        "Incomplete raw trajectories remain at source; no terminal outcome is imputed.",
        "Synthetic deck and hidden burial are private; config and terminal authority are carried, not granted.",
        "Fit and validation require separate explicit exports. Do not pass validation files to fitting; "
        "the trainer's random deal split does not enforce these source holdout labels."])
    return result
