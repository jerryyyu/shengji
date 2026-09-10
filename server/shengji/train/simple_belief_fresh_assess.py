"""Saved-gameplay fresh ownership assessment (no gameplay policy rerun)."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..engine.round import actual_play_after
try:
    from . import simple_belief_gameplay as gameplay
except ModuleNotFoundError as exc:  # gameplay's value path has optional torch
    if exc.name != "torch":
        raise
    gameplay = None
from .harvest_labels import record_deal_key
from .simple_belief_data import canonical, digest
from .simple_belief_features import actor_features, ownership_targets
from .simple_belief_reference import corrected_reference
from .simple_belief_r4 import ownership_array
from .simple_belief_sampler import SmallBeliefPredictor
from .r4_runtime_client import R4RuntimeClient, actor_for_round


SCHEMA = "simple-belief-fresh-assess-v1"
REFERENCE_SCHEMA = "simple-belief-reference-readout-v1"
R4_SCHEMA = "simple-belief-r4-compare-v1"
STATE_INDICES = (0, 16, 32, 48)
ARM_NAMES = ("synthetic-primary", "hard-geometry-label-permutation")


def _json(path: Path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc


def _atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(json.dumps(value, sort_keys=True, indent=2,
                                   allow_nan=False).encode() + b"\n")
    partial.replace(path)


def _config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: value for key, value in config.items() if key != "config_sha256"},
        sort_keys=True).encode()).hexdigest()


def _bind_config(root: Path) -> tuple[dict, Path, str]:
    if gameplay is None:
        raise ValueError("fresh assessment requires the gameplay RL dependencies")
    config = _json(root / "config.json")
    if not isinstance(config, dict) or config.get("schema") is None:
        raise ValueError("gameplay config is incomplete")
    if config.get("config_sha256") != _config_hash(config):
        raise ValueError("gameplay config digest differs")
    required = ("source", "small_checkpoint", "small_checkpoint_sha256",
                "cache_recipe", "cache_recipe_sha256", "archive_server",
                "training_root", "output")
    if any(key not in config for key in required) or not isinstance(config["source"], dict):
        raise ValueError("gameplay config source/model binding is incomplete")
    if gameplay.execution_source_identity(Path(__file__).parents[1]) != config['source']:
        raise ValueError('fresh assessment executing source differs')
    for name, expected in config['training_manifests'].items():
        if digest((Path(config['training_root']) / name / 'manifest.json').read_bytes()) != expected:
            raise ValueError('fresh assessment R4 manifest differs')
    checkpoint = Path(config["small_checkpoint"]).resolve()
    checkpoint_sha = digest(checkpoint.read_bytes())
    if checkpoint_sha != config["small_checkpoint_sha256"]:
        raise ValueError("small belief checkpoint bytes changed")
    cache = Path(config["cache_recipe"]).resolve()
    cache_file = cache / "recipe.json" if cache.is_dir() else cache
    if digest(cache_file.read_bytes()) != config["cache_recipe_sha256"]:
        raise ValueError("cache recipe bytes changed")
    planned = [gameplay.spec_for(i) for i in range(14)]
    recipe_sha, _ = gameplay._fresh_check(cache_file, planned)
    if recipe_sha != config["cache_recipe_sha256"]:
        raise ValueError("fresh gameplay cache binding differs")
    return config, cache_file, config["cache_recipe_sha256"]


def _validate_common(config: dict, spec: dict, row: dict) -> dict:
    if row is None:
        raise ValueError(f"ordinary gameplay arm missing for cluster {spec['index']}")
    if not isinstance(row, dict) or row.get("spec") != spec or row.get("arm") != "ordinary":
        raise ValueError("ordinary gameplay arm identity differs")
    outcome = row.get("outcome")
    if not isinstance(outcome, dict) or not isinstance(outcome.get("transcript"), list):
        raise ValueError("ordinary gameplay outcome is incomplete")
    for key in ("buried", "attacker_points", "kitty_bonus", "team0_signed_levels"):
        if key not in outcome:
            raise ValueError("ordinary gameplay outcome is incomplete")
    return outcome


def _replay_states(spec: dict, row: dict) -> tuple[str, dict[int, tuple[object, int]], dict]:
    if gameplay is None:
        raise ValueError("fresh assessment requires the gameplay RL dependencies")
    outcome = _validate_common({}, spec, row)
    rnd, _ = gameplay.prepare_round(spec)
    if rnd.buried:
        raise ValueError("prepared round unexpectedly has a burial")
    # The saved burial is the sole hidden input used to reach the common
    # baseline state; no treatment transcript is reconstructed here.
    rnd.bury(rnd.banker, list(outcome["buried"]))
    deal_key = record_deal_key({"deck": rnd.deck})
    snapshots: dict[int, tuple[object, int]] = {}
    transcript = outcome["transcript"]
    for index, event in enumerate(transcript):
        if index in STATE_INDICES:
            if rnd.phase != "play" or rnd.turn is None:
                raise ValueError("ordinary state index is unreachable")
            snapshots[index] = (copy.deepcopy(rnd), rnd.turn)
        if not isinstance(event, dict) or event.get("seat") != rnd.turn:
            raise ValueError("ordinary transcript turn differs")
        attempted = event.get("attempted")
        stored = event.get("cards", event.get("actual", event.get("actual_play_after")))
        if not isinstance(attempted, list) or not isinstance(stored, list):
            raise ValueError("ordinary transcript action is incomplete")
        before = rnd.last_trick
        rnd.play(rnd.turn, attempted)
        actual = list(actual_play_after(rnd, event["seat"], before))
        if actual != stored:
            raise ValueError("ordinary transcript actual_play_after differs")
    if len(transcript) in STATE_INDICES and rnd.phase == "play" and rnd.turn is not None:
        snapshots[len(transcript)] = (copy.deepcopy(rnd), rnd.turn)
    if rnd.phase == "play":
        raise ValueError("ordinary gameplay transcript is incomplete")
    if list(rnd.buried) != list(outcome["buried"]):
        raise ValueError("ordinary gameplay burial differs")
    if outcome.get("banker") != rnd.banker:
        raise ValueError("ordinary gameplay banker differs")
    for attr, key in (("attacker_points", "attacker_points"), ("kitty_bonus", "kitty_bonus")):
        if getattr(rnd, attr) != outcome[key]:
            raise ValueError(f"ordinary gameplay outcome {key} differs")
    points = rnd.attacker_points
    level = (-max(1, (points - 80) // 40) if points >= 80 else
             3 if points == 0 else 2 if points < 40 else 1)
    expected_team_value = level if rnd.banker % 2 == 0 else -level
    if outcome["team0_signed_levels"] != expected_team_value:
        raise ValueError("ordinary gameplay team value differs")
    if deal_key is None:
        raise ValueError("fresh gameplay deal key is missing")
    return deal_key, snapshots, outcome


def _state_key(deal_key: str, index: int, transcript: list) -> str:
    return digest(canonical(["simple-belief-fresh-state-v1", deal_key, index,
                             transcript[:index]]))


def _score(probabilities, targets, uncertain):
    truth = np.eye(3)[targets]
    return float(np.square(np.asarray(probabilities) - truth)[uncertain].sum(axis=-1).mean())


def _assess_deal(config, spec, ordinary, small_predictor, client) -> dict:
    deal_key, snapshots, outcome = _replay_states(spec, ordinary)
    rows_ref, rows_r4 = [], []
    for index in STATE_INDICES:
        if index not in snapshots:
            continue
        rnd, seat = snapshots[index]
        features, allowed = actor_features(rnd, seat)
        model_p = np.asarray(small_predictor(rnd, seat))
        if model_p.shape != (4, 54, 3) or not np.isfinite(model_p).all():
            raise ValueError("small belief predictor probabilities are invalid")
        actor = actor_for_round(rnd, seat, config["archive_server"])
        response = client.predict(actor)
        if (not isinstance(response, dict) or not isinstance(response.get("arms"), dict)
                or set(response["arms"]) != set(ARM_NAMES)):
            raise ValueError("R4 response identity does not provide both arms")
        r4_p = {arm: ownership_array(actor, response["arms"][arm]["ownership"])
                for arm in ARM_NAMES}
        seed = int(hashlib.sha256(f"simple-belief-fresh-reference-v1|{deal_key}|{index}".encode()).hexdigest()[:16], 16)
        reference = corrected_reference(rnd, seat, seed=seed, n=256)
        # Labels are deliberately obtained only after every prediction above.
        targets = ownership_targets(rnd, seat)
        uncertain = allowed.sum(axis=-1) > 1
        if not uncertain.any():
            continue
        state = _state_key(deal_key, index, outcome["transcript"])
        model_brier = _score(model_p, targets, uncertain)
        raw_brier = _score(reference["probabilities"], targets, uncertain)
        corrected = raw_brier - float(np.asarray(reference["brier_correction"])[uncertain].mean())
        rows_ref.append({"state_key": state, "ply": index, "seat": seat,
                         "trump_rank": rnd.trump_rank, "is_nt": bool(rnd.trump_is_nt),
                         "is_banker": rnd.banker == seat, "uncertain_cells": int(uncertain.sum()),
                         "model_brier": model_brier, "reference_raw_brier": raw_brier,
                         "reference_corrected_brier": corrected,
                         "reference_wall_seconds": float(reference["wall_seconds"]),
                         "reference_unique_worlds": int(reference["unique_worlds"]),
                         "reference_attempts": int(reference["attempts"]),
                         "probabilities": model_p.tolist(),
                         "reference_probabilities": reference["probabilities"].tolist(),
                         "targets": targets.tolist(), "uncertain": uncertain.tolist()})
        rows_r4.append({"state_key": state, "ply": index, "actor_sha256": actor.sha256(),
                        "incomplete_declaration_history": not actor.declaration_history_complete,
                        "inference_seconds_both_cohorts": float(response.get("inference_wall_s", 0.0)),
                        "model_brier": model_brier, "reference_corrected_brier": corrected,
                        "arms": {arm: {"probabilities": p.tolist(),
                                       "brier": _score(p, targets, uncertain)}
                                 for arm, p in r4_p.items()}})
    return {"deal_key": deal_key, "spec": spec, "rows_reference": rows_ref,
            "rows_r4": rows_r4, "outcome": outcome}


def _derive_children(output: Path, combined: dict, config: dict, elapsed: float) -> None:
    ref = {"schema": REFERENCE_SCHEMA, "deals": len(combined["deals"]),
           "positions": sum(len(x["rows_reference"]) for x in combined["deals"]),
           "deterministic_positions_skipped": 0,
           "unreachable_or_deterministic_state_indices_skipped": sum(
               4 - len(x["rows_reference"]) for x in combined["deals"]),
           "scope": "fresh gameplay ownership states; no independent generalization claim"}
    r4 = {"schema": R4_SCHEMA, "deals": len(combined["deals"]),
          "positions": sum(len(x["rows_r4"]) for x in combined["deals"]),
          "inference_seconds_both_cohorts": sum(
              float(row.get("inference_seconds_both_cohorts", 0.0))
              for deal in combined["deals"] for row in deal["rows_r4"]),
          "scope": "fresh gameplay ownership states; old-R4 training overlap pending"}
    recipe = {"schema": SCHEMA, "config_sha256": config["config_sha256"],
              "state_indices": list(STATE_INDICES), "ordinary_worlds": 256,
              "deals": [x["deal_key"] for x in combined["deals"]]}
    _atomic(output / "recipe.json", recipe)
    _atomic(output / "reference" / "recipe.json", {**recipe, "schema": REFERENCE_SCHEMA})
    _atomic(output / "r4" / "recipe.json", {**recipe, "schema": R4_SCHEMA})
    reference_deals = {x["deal_key"]: {"deal_key": x["deal_key"],
                                       "identity": config["config_sha256"],
                                       "rows": x["rows_reference"]}
                       for x in combined["deals"]}
    r4_deals = {x["deal_key"]: {"deal_key": x["deal_key"],
                                "identity": config["config_sha256"],
                                "rows": x["rows_r4"]}
                for x in combined["deals"]}
    # Existing calibration/readout loaders consume one deal JSON per file;
    # these child files are derived views, never another inference pass.
    for deal, payload in reference_deals.items():
        _atomic(output / "reference" / f"{deal.removeprefix('deck:')}.json", payload)
    for deal, payload in r4_deals.items():
        _atomic(output / "r4" / f"{deal.removeprefix('deck:')}.json", payload)
    _atomic(output / "reference" / "summary.json", {**ref, "wall_seconds": elapsed})
    _atomic(output / "r4" / "summary.json", {**r4, "wall_seconds": elapsed})


def assess(gameplay_root: str | Path, output: str | Path, *, limit: int = 14) -> dict:
    if type(limit) is not int or not 1 <= limit <= 14:
        raise ValueError("limit must be between 1 and 14")
    started = time.monotonic()
    root, output = Path(gameplay_root), Path(output)
    config, cache_file, cache_sha = _bind_config(root)
    if output.exists() and (output / "recipe.json").exists():
        recipe = _json(output / "recipe.json")
        if recipe.get("config_sha256") != config["config_sha256"]:
            raise ValueError("fresh assessment output config differs")
    combined_path = output / "perdeal.json"
    combined = _json(combined_path) if combined_path.exists() else {
        "schema": SCHEMA, "config_sha256": config["config_sha256"], "deals": []}
    if combined.get("schema") != SCHEMA or combined.get("config_sha256") != config["config_sha256"]:
        raise ValueError("fresh assessment combined identity differs")
    by_cluster = {x["spec"]["index"]: x for x in combined.get("deals", [])}
    specs = [gameplay.spec_for(i) for i in range(limit)]
    ordinary_rows = {}
    for spec in specs:
        row = gameplay.load_existing_arm(config, spec, "ordinary", None)
        if row is None:
            raise ValueError(f"ordinary gameplay arm missing for cluster {spec['index']}")
        ordinary_rows[spec["index"]] = row
    if any(spec['index'] not in by_cluster for spec in specs):
        # Bind model and R4 once for the complete fresh scoring pass.
        predictor = SmallBeliefPredictor(config["small_checkpoint"], cache_sha)
        client = R4RuntimeClient(config["archive_server"], config["training_root"])
        try:
            if set(client.identity) != set(ARM_NAMES):
                raise ValueError("R4 identity does not provide both arms")
            if ("r4_identity" in combined
                    and combined["r4_identity"] != client.identity):
                raise ValueError("fresh assessment R4 identity differs")
            combined["r4_identity"] = client.identity
            for spec in specs:
                if spec["index"] not in by_cluster:
                    by_cluster[spec["index"]] = _assess_deal(
                        config, spec, ordinary_rows[spec["index"]], predictor, client)
                    combined["deals"] = [by_cluster[i] for i in sorted(by_cluster)]
                    combined["config_sha256"] = config["config_sha256"]
                    _atomic(combined_path, combined)
        finally:
            client.close()
    combined["deals"] = [by_cluster[i] for i in sorted(by_cluster)]
    _atomic(combined_path, combined)
    # Limit bounds newly requested work, not retained evidence. Keep derived
    # summaries consistent with all per-deal files when reopening a lower limit.
    _derive_children(output, combined, config, time.monotonic() - started)
    return {"schema": SCHEMA, "deals": len(combined["deals"]),
            "positions": sum(len(x["rows_reference"]) for x in combined["deals"]),
            "wall_seconds": time.monotonic() - started, "output": str(output)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gameplay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 15), default=14)
    args = parser.parse_args(argv)
    print(json.dumps(assess(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
