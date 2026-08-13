#!/usr/bin/env python3
"""Score-free geometry gate for a future exploratory H0 population.

The spent H0-v3 run and its 555 completed utilities stay closed.  This module
opens no files, has no CLI or scorer, and cannot train, infer strength, promote,
or deploy.  Its one job is to validate every candidate menu in a *new* OPEN_DEV
population before a later experiment is designed.  SYNTHETIC exists only for
tests.

The repair to H0-v3 is deliberately narrow: production and analysis menus are
different bounded sources, so their sizes are not compared.  Every OPEN_DEV
candidate is instead submitted to the game engine at the authenticated round
and seat.  A failed lead throw is an accepted attempted action (the engine may
replace it with a forced component); an illegal follow or bury is refused.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Mapping, NamedTuple, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import h0_human_counterfactual_controller as H0  # noqa: E402
from shengji.engine.cards import SUITS  # noqa: E402
from shengji.engine.round import Round  # noqa: E402


SCHEMA = "human-h0-open-dev-geometry-v1"
POPULATION_KINDS = {"SYNTHETIC", "OPEN_DEV"}
SOURCE_SCOPES = {
    "SYNTHETIC": "SYNTHETIC_FIXTURE",
    "OPEN_DEV": "NEW_OPEN_DEV_CAPTURE",
}
AUTHORITY = {
    "population_scope": "SYNTHETIC_OR_NEW_OPEN_DEV_ONLY",
    "score_free": True,
    "outcomes_computed": False,
    "scoring_authorized": False,
    "report_population_authorized": False,
    "sealed_outcomes_authorized": False,
    "prior_h0_artifacts_authorized": False,
    "confirmatory_inference_authorized": False,
    "strength_claim": False,
    "labels_authorized": False,
    "training_authorized": False,
    "production_promotion": False,
    "production_deployment": False,
}
ROW_KEYS = {
    "row_key", "decision_key", "split", "surface_type", "deal_key",
    "surface", "phase", "role", "human_action",
}
FORBIDDEN_INPUT_KEYS = {
    "attacker_points", "estimand", "estimands", "label", "labels", "lcb",
    "mean_utility", "outcome", "outcomes", "points", "raw_attacker_points",
    "result", "results", "reward", "rewards", "score", "scores",
    "selection_utility", "utilities", "utility", "verdict", "winner",
    "winner_index",
}
CLOSED_H0_DIGESTS = {
    H0.CORPUS_MANIFEST_SHA256,
    H0.SOURCE_MANIFEST_SHA256,
    H0.DESIGN_PACKET_SHA256,
}
PLAY_SOURCES = {
    "human_action", "live_production_ballot", "matched_random_proposal",
    "v11pair_top_proposal",
}
BURY_STATIC_SOURCES = {
    "human_action", "structured_bury_ballot", "incumbent",
    "point_preserving", "trump_preserving", "pair_preserving", "short_suit",
    "low_strength",
}
BURY_PROFILES = {
    "point_preserving", "trump_preserving", "pair_preserving", "short_suit",
    "low_strength",
}
BURY_VOID_PROFILES = {
    "point_preserving", "trump_preserving", "pair_preserving", "low_strength",
}
REFUSAL_CODES = {
    "CANDIDATE_BUILD", "CANDIDATE_CAP", "CANDIDATE_CANONICAL",
    "CANDIDATE_SCHEMA", "CANDIDATE_SOURCE", "DIAGNOSTIC_RECONCILIATION",
    "DIAGNOSTIC_SCHEMA", "DIAGNOSTIC_TYPE", "DUPLICATE_CANDIDATE",
    "EMPTY_CANDIDATES", "ENGINE_CONTEXT", "HUMAN_ACTION_MISSING",
    "ILLEGAL_CANDIDATE",
}


class GeometryRefused(RuntimeError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


class CandidateSet(NamedTuple):
    candidates: Sequence[Mapping[str, object]]
    diagnostics: Mapping[str, object]


class EngineContext(NamedTuple):
    rnd: object
    seat: int
    net: object | None = None
    production_bot: object | None = None


def canonical_json(value: object) -> bytes:
    return (json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ) + "\n").encode()


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _is_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _reject_outcomes(value: object, path: str = "row") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_INPUT_KEYS:
                raise GeometryRefused(
                    "OUTCOME_BEARING_INPUT",
                    f"forbidden input key at {path}.{normalized}")
            _reject_outcomes(child, f"{path}.{normalized}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_outcomes(child, f"{path}[{index}]")


def _action(value: object) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple)) or not value
            or any(not isinstance(card, str) or not card for card in value)):
        raise GeometryRefused("MALFORMED_ACTION", "action is not cards")
    return H0.action_key(value)


def _identity(row: Mapping[str, object], population_kind: str) -> dict:
    if not isinstance(row, Mapping):
        raise GeometryRefused("ROW_IDENTITY_TYPE", "row is not an object")
    _reject_outcomes(row)
    if set(row) != ROW_KEYS:
        raise GeometryRefused("ROW_IDENTITY_SCHEMA", "row schema is not closed")
    split = "SYNTHETIC" if population_kind == "SYNTHETIC" else "DEV"
    if row["split"] != split or row["surface_type"] not in {"play", "bury"}:
        raise GeometryRefused("ROW_IDENTITY_DRIFT", "split/surface drift")
    if not all(isinstance(row[name], str) and row[name] for name in (
            "row_key", "decision_key", "deal_key", "surface", "phase", "role")):
        raise GeometryRefused("ROW_IDENTITY_TYPE", "row identity is malformed")
    expected_key = f"{split}|{row['surface_type']}|{row['decision_key']}"
    if row["row_key"] != expected_key:
        raise GeometryRefused("ROW_IDENTITY_DRIFT", "row key identity drift")
    if row["surface_type"] == "play":
        good = (row["surface"] in {"lead", "follow"}
                and row["phase"] in {"early", "mid", "late"}
                and row["role"] in {"attacker", "defender"})
    else:
        good = (row["surface"] == "bury" and row["phase"] == "bury"
                and row["role"] == "banker")
    if not good:
        raise GeometryRefused("ROW_IDENTITY_DRIFT", "row cell identity drift")
    _action(row["human_action"])
    return {name: copy.deepcopy(row[name]) for name in sorted(ROW_KEYS)}


def _bury_source(source: str) -> bool:
    if source in BURY_STATIC_SOURCES:
        return True
    base, marker, offset = source.rpartition(":boundary+")
    if marker:
        try:
            n = int(offset)
        except ValueError:
            return False
        if offset != str(n):
            return False
        if base in BURY_PROFILES:
            return 1 <= n <= 5
        source = base
        if not 1 <= n <= 3:
            return False
    if not source.startswith("void:"):
        return False
    parts = source[5:].split("+")
    if len(parts) == 2:
        return parts[0] in SUITS and parts[1] in BURY_VOID_PROFILES
    return (not marker and len(parts) == 3 and parts[0] in SUITS
            and parts[1] in SUITS and parts[0] != parts[1]
            and parts[2] in {"point_preserving", "trump_preserving"})


def _sources_valid(sources: object, surface: str) -> bool:
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(source, str) for source in sources)
            or sources != sorted(set(sources))):
        return False
    return all(
        source in PLAY_SOURCES if surface == "play" else _bury_source(source)
        for source in sources)


def _diagnostics(identity: Mapping[str, object], candidates: list[dict],
                 value: object) -> None:
    if not isinstance(value, Mapping):
        raise GeometryRefused("DIAGNOSTIC_SCHEMA", "diagnostics not an object")
    if identity["surface_type"] == "play":
        keys = {
            "live_candidates", "analysis_actions", "novel_pool",
            "human_in_live_ballot", "v11_proposed", "random_proposed",
            "v11_random_same", "v11_score_count",
        }
        integers = {
            "live_candidates", "analysis_actions", "novel_pool",
            "v11_score_count",
        }
        if (set(value) != keys
                or any(isinstance(value[k], bool) or not isinstance(value[k], int)
                       or value[k] < 0 for k in integers)
                or any(not isinstance(value[k], bool) for k in keys - integers)):
            raise GeometryRefused("DIAGNOSTIC_TYPE", "play diagnostic drift")
        live = [c for c in candidates
                if "live_production_ballot" in c["sources"]]
        human = [c for c in candidates if "human_action" in c["sources"]]
        v11 = [c for c in candidates if "v11pair_top_proposal" in c["sources"]]
        random_items = [c for c in candidates
                        if "matched_random_proposal" in c["sources"]]
        cap = (H0.DESIGN.LIVE_LEAD_MAX_CANDIDATES
               if identity["surface"] == "lead"
               else H0.DESIGN.LIVE_FOLLOW_MAX_CANDIDATES)
        overlap = bool(v11 and random_items
                       and _action(v11[0]["cards"]) ==
                       _action(random_items[0]["cards"]))
        reconciles = (
            value["live_candidates"] == len(live)
            and 1 <= len(live) <= cap
            and all("live_production_ballot" in c["sources"]
                    for c in candidates[:len(live)])
            and all("live_production_ballot" not in c["sources"]
                    for c in candidates[len(live):])
            and len(human) == 1
            and 1 <= value["analysis_actions"]
            and value["novel_pool"] <= value["analysis_actions"]
            and value["v11_score_count"] == value["novel_pool"]
            and value["human_in_live_ballot"] ==
            ("live_production_ballot" in human[0]["sources"])
            and value["v11_proposed"] == (len(v11) == 1)
            and value["random_proposed"] == (len(random_items) == 1)
            and value["v11_proposed"] == (value["novel_pool"] > 0)
            and value["random_proposed"] == value["v11_proposed"]
            and value["v11_random_same"] == overlap
            and not any({"human_action", "live_production_ballot"}
                        & set(c["sources"]) for c in v11 + random_items)
        )
        if not reconciles:
            raise GeometryRefused(
                "DIAGNOSTIC_RECONCILIATION", "play diagnostics do not close")
        # The repaired seam: analysis_actions and len(live) are independent.
        return

    keys = {
        "structured_candidates", "structured_generated_unique",
        "structured_truncated", "human_in_structured_ballot",
    }
    if (set(value) != keys
            or any(isinstance(value[k], bool) or not isinstance(value[k], int)
                   or value[k] < 0 for k in (
                       "structured_candidates", "structured_generated_unique"))
            or not isinstance(value["structured_truncated"], bool)
            or not isinstance(value["human_in_structured_ballot"], bool)):
        raise GeometryRefused("DIAGNOSTIC_TYPE", "bury diagnostic drift")
    structured = [c for c in candidates
                  if "structured_bury_ballot" in c["sources"]]
    human = [c for c in candidates if "human_action" in c["sources"]]
    generated = value["structured_generated_unique"]
    cap = H0.DESIGN.BURY_STRUCTURED_MAX_CANDIDATES
    if (len(human) != 1 or value["structured_candidates"] != len(structured)
            or len(structured) != min(generated, cap)
            or value["structured_truncated"] != (generated > cap)
            or value["human_in_structured_ballot"] !=
            ("structured_bury_ballot" in human[0]["sources"])
            or candidates[:len(structured)] != structured
            or not structured or candidates[0] is not structured[0]
            or "incumbent" not in candidates[0]["sources"]
            or sum("incumbent" in candidate["sources"]
                   for candidate in candidates) != 1):
        raise GeometryRefused(
            "DIAGNOSTIC_RECONCILIATION", "bury diagnostics do not close")
    reasons = [
        source
        for candidate in candidates
        for source in candidate["sources"]
        if source not in {"human_action", "structured_bury_ballot"}
    ]
    if len(reasons) != len(set(reasons)):
        raise GeometryRefused(
            "CANDIDATE_SOURCE", "bury source is assigned more than once")
    for candidate in candidates:
        sources = set(candidate["sources"])
        structured_source = "structured_bury_ballot" in sources
        reasons = sources - {"human_action", "structured_bury_ballot"}
        if (structured_source != bool(reasons)
                or (not structured_source and sources != {"human_action"})):
            raise GeometryRefused("CANDIDATE_SOURCE", "bury source drift")


def _candidate_set(identity: Mapping[str, object], value: CandidateSet) -> list[dict]:
    if not isinstance(value, CandidateSet):
        raise GeometryRefused("CANDIDATE_SCHEMA", "candidate set type drift")
    candidates = copy.deepcopy(list(value.candidates))
    cap = (H0.DESIGN.PLAY_MAX_UNIQUE_CANDIDATES
           if identity["surface_type"] == "play"
           else H0.DESIGN.BURY_MAX_UNIQUE_CANDIDATES)
    if not candidates:
        raise GeometryRefused("EMPTY_CANDIDATES", "candidate set is empty")
    if len(candidates) > cap:
        raise GeometryRefused("CANDIDATE_CAP", "candidate cap exceeded")
    actions = []
    for item in candidates:
        if (not isinstance(item, Mapping)
                or set(item) != {"cards", "sources"}):
            raise GeometryRefused("CANDIDATE_SCHEMA", "candidate schema drift")
        action = _action(item["cards"])
        if item["cards"] != list(action):
            raise GeometryRefused(
                "CANDIDATE_CANONICAL", "candidate cards are not canonical")
        if not _sources_valid(item["sources"], str(identity["surface_type"])):
            raise GeometryRefused("CANDIDATE_SOURCE", "candidate source drift")
        actions.append(action)
    if len(actions) != len(set(actions)):
        raise GeometryRefused("DUPLICATE_CANDIDATE", "candidate actions duplicate")
    human = _action(identity["human_action"])
    if (human not in actions
            or "human_action" not in candidates[actions.index(human)]["sources"]
            or sum("human_action" in c["sources"] for c in candidates) != 1):
        raise GeometryRefused("HUMAN_ACTION_MISSING", "human source drift")
    _diagnostics(identity, candidates, value.diagnostics)
    return candidates


def _phase(rnd) -> str:
    trick = len(rnd.history) + 1
    return "early" if trick <= 8 else "mid" if trick <= 17 else "late"


def _engine_candidates(row: Mapping[str, object], identity: Mapping[str, object],
                       context: EngineContext) -> CandidateSet:
    if (not isinstance(context, EngineContext)
            or type(context.rnd) is not Round
            or isinstance(context.seat, bool) or not isinstance(context.seat, int)
            or not 0 <= context.seat < 4
            or getattr(context.rnd, "turn", None) != context.seat):
        raise GeometryRefused("ENGINE_CONTEXT", "round/seat context drift")
    rnd, seat = context.rnd, context.seat
    if identity["surface_type"] == "play":
        trick = getattr(rnd, "trick", None)
        surface = "lead" if trick is not None and not trick.plays else "follow"
        try:
            role = "attacker" if Round.is_attacker(rnd, seat) else "defender"
        except Exception as exc:
            raise GeometryRefused("ENGINE_CONTEXT", "team identity missing") from exc
        if (getattr(rnd, "phase", None) != "play" or trick is None
                or (identity["surface"], identity["phase"], identity["role"])
                != (surface, _phase(rnd), role) or context.net is None):
            raise GeometryRefused("ENGINE_CONTEXT", "play state identity drift")
        try:
            candidates, diagnostics = H0.build_play_union(
                rnd, seat, row["human_action"], str(row["split"]),
                str(row["decision_key"]), context.net, context.production_bot)
        except H0.ControllerRefused as exc:
            raise GeometryRefused("CANDIDATE_BUILD", "play union refused") from exc
    else:
        if (getattr(rnd, "phase", None) != "bury" or rnd.banker != seat
                or (identity["surface"], identity["phase"], identity["role"])
                != ("bury", "bury", "banker")):
            raise GeometryRefused("ENGINE_CONTEXT", "bury state identity drift")
        try:
            candidates, diagnostics = H0.build_bury_union(
                rnd, seat, row["human_action"])
        except H0.ControllerRefused as exc:
            raise GeometryRefused("CANDIDATE_BUILD", "bury union refused") from exc
    result = CandidateSet(candidates, diagnostics)
    validated = _candidate_set(identity, result)
    for item in validated:
        clone = copy.deepcopy(rnd)
        try:
            if identity["surface_type"] == "play":
                # Evidence gates must never inherit the rollout-only follow
                # validation bypass from a supplied state.
                clone._trusted_rollout = False
                Round.play(clone, seat, list(item["cards"]))
            else:
                Round.bury(clone, seat, list(item["cards"]))
        except Exception as exc:
            raise GeometryRefused("ILLEGAL_CANDIDATE", "engine rejected action") from exc
    return CandidateSet(validated, diagnostics)


def _cell(identity: Mapping[str, object]) -> str:
    return ":".join(str(identity[name]) for name in (
        "split", "surface_type", "surface", "phase", "role"))


def _record(identity: Mapping[str, object], value: CandidateSet) -> dict:
    candidates = _candidate_set(identity, value)
    return {
        "schema": SCHEMA,
        "status": "VALID_CANDIDATE_GEOMETRY",
        **identity,
        "cell": _cell(identity),
        "candidates": candidates,
        "candidate_diagnostics": copy.deepcopy(dict(value.diagnostics)),
        "candidate_manifest_sha256": sha256(candidates),
        "authority": dict(AUTHORITY),
    }


def _refusal(identity: Mapping[str, object], code: str) -> dict:
    return {
        "schema": SCHEMA,
        "status": "REFUSED_SCORE_FREE",
        **identity,
        "cell": _cell(identity),
        "reason_code": code if code in REFUSAL_CODES else "CANDIDATE_BUILD",
        "authority": dict(AUTHORITY),
    }


def prevalidate_population(
    rows: Sequence[Mapping[str, object]],
    prepare: Callable[[Mapping[str, object]], CandidateSet | EngineContext],
    *, population_id: str, population_kind: str, source_scope: str,
    source_manifest_sha256: str,
) -> dict:
    """Validate every row and publish only score-free candidate geometry."""
    if (not isinstance(population_kind, str)
            or population_kind not in POPULATION_KINDS
            or source_scope != SOURCE_SCOPES.get(population_kind)
            or not _is_sha(source_manifest_sha256)
            or (population_kind == "OPEN_DEV"
                and source_manifest_sha256 in CLOSED_H0_DIGESTS)
            or not isinstance(population_id, str) or not population_id):
        raise GeometryRefused("POPULATION_AUTHORITY", "population scope drift")
    material = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise GeometryRefused("ROW_IDENTITY_TYPE", "row is not an object")
        material.append(copy.deepcopy(dict(row)))
    if not material:
        raise GeometryRefused("EMPTY_POPULATION", "population is empty")
    identities = [_identity(row, population_kind) for row in material]
    row_keys = [identity["row_key"] for identity in identities]
    semantic = [(identity["deal_key"], identity["decision_key"])
                for identity in identities]
    if len(row_keys) != len(set(row_keys)) or len(semantic) != len(set(semantic)):
        raise GeometryRefused("ROW_KEYS", "decision identity duplicated")

    records = []
    for row, identity in zip(material, identities, strict=True):
        try:
            prepared = prepare(copy.deepcopy(row))
            if population_kind == "OPEN_DEV":
                prepared = _engine_candidates(row, identity, prepared)
            elif not isinstance(prepared, CandidateSet):
                raise GeometryRefused(
                    "CANDIDATE_SCHEMA", "synthetic candidate set required")
            records.append(_record(identity, prepared))
        except GeometryRefused as exc:
            records.append(_refusal(identity, exc.code))

    cells: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        cells[record["cell"]]["selected"] += 1
        cells[record["cell"]][
            "valid" if record["status"] == "VALID_CANDIDATE_GEOMETRY"
            else "refused"] += 1
    counts = Counter(
        "valid" if record["status"] == "VALID_CANDIDATE_GEOMETRY"
        else "refused" for record in records)
    deal_sets = {
        status: {record["deal_key"] for record in records
                 if status == "selected" or record["status"] == (
                     "VALID_CANDIDATE_GEOMETRY" if status == "valid"
                     else "REFUSED_SCORE_FREE")}
        for status in ("selected", "valid", "refused")
    }
    payload = {
        "schema": SCHEMA,
        "population_id": population_id,
        "population_kind": population_kind,
        "source_scope": source_scope,
        "source_manifest_sha256": source_manifest_sha256,
        "input_manifest_sha256": sha256(material),
        "input_row_keys": row_keys,
        "records": records,
        "counts": {
            "selected": len(records), "valid": counts["valid"],
            "refused": counts["refused"],
        },
        "deal_clusters": {name: len(value) for name, value in deal_sets.items()},
        "coverage_cells": {
            cell: {name: value[name] for name in ("selected", "valid", "refused")}
            for cell, value in sorted(cells.items())
        },
        "authority": dict(AUTHORITY),
    }
    payload["geometry_manifest_sha256"] = sha256(records)
    payload["artifact_sha256"] = sha256(payload)
    validate_artifact(payload, expected_sha256=payload["artifact_sha256"])
    return payload


def validate_artifact(payload: Mapping[str, object], *, expected_sha256: str) -> None:
    """Recheck closed geometry against a separately stored trusted digest."""
    keys = {
        "schema", "population_id", "population_kind", "source_scope",
        "source_manifest_sha256", "input_manifest_sha256", "input_row_keys",
        "records", "counts", "deal_clusters", "coverage_cells", "authority",
        "geometry_manifest_sha256", "artifact_sha256",
    }
    if (not isinstance(payload, Mapping) or set(payload) != keys
            or payload.get("schema") != SCHEMA
            or not isinstance(payload.get("population_id"), str)
            or not payload.get("population_id")
            or not isinstance(payload.get("population_kind"), str)
            or payload.get("population_kind") not in POPULATION_KINDS
            or payload.get("source_scope") !=
            SOURCE_SCOPES.get(payload.get("population_kind"))
            or not all(_is_sha(payload.get(name)) for name in (
                "source_manifest_sha256", "input_manifest_sha256",
                "geometry_manifest_sha256", "artifact_sha256"))
            or (payload.get("population_kind") == "OPEN_DEV"
                and payload.get("source_manifest_sha256") in CLOSED_H0_DIGESTS)
            or payload.get("authority") != AUTHORITY
            or not _is_sha(expected_sha256)):
        raise GeometryRefused("ARTIFACT_SCHEMA", "artifact authority drift")
    own = sha256({key: value for key, value in payload.items()
                  if key != "artifact_sha256"})
    if payload["artifact_sha256"] != own or own != expected_sha256:
        raise GeometryRefused("ARTIFACT_HASH", "artifact digest drift")
    records, row_keys = payload["records"], payload["input_row_keys"]
    if (not isinstance(records, list) or not records
            or not isinstance(row_keys, list)
            or any(not isinstance(record, Mapping) for record in records)
            or [record.get("row_key") for record in records] != row_keys
            or len(row_keys) != len(set(row_keys))
            or payload["geometry_manifest_sha256"] != sha256(records)):
        raise GeometryRefused("ARTIFACT_ROWS", "artifact row population drift")
    counts = Counter()
    cells: dict[str, Counter[str]] = defaultdict(Counter)
    semantic = []
    material = []
    common = {"schema", "status", *ROW_KEYS, "cell", "authority"}
    for record in records:
        if not isinstance(record, Mapping):
            raise GeometryRefused("ARTIFACT_RECORD", "record is not an object")
        identity = _identity(
            {name: record.get(name) for name in ROW_KEYS},
            str(payload["population_kind"]))
        material.append(identity)
        semantic.append((identity["deal_key"], identity["decision_key"]))
        if (record.get("schema") != SCHEMA or record.get("authority") != AUTHORITY
                or record.get("cell") != _cell(identity)):
            raise GeometryRefused("ARTIFACT_RECORD", "record identity drift")
        if record.get("status") == "VALID_CANDIDATE_GEOMETRY":
            if set(record) != common | {
                    "candidates", "candidate_diagnostics",
                    "candidate_manifest_sha256"}:
                raise GeometryRefused("ARTIFACT_RECORD", "valid schema drift")
            candidates = _candidate_set(identity, CandidateSet(
                record["candidates"], record["candidate_diagnostics"]))
            if record["candidate_manifest_sha256"] != sha256(candidates):
                raise GeometryRefused("ARTIFACT_RECORD", "candidate digest drift")
            status = "valid"
        elif record.get("status") == "REFUSED_SCORE_FREE":
            if (set(record) != common | {"reason_code"}
                    or record.get("reason_code") not in REFUSAL_CODES):
                raise GeometryRefused("ARTIFACT_RECORD", "refusal schema drift")
            status = "refused"
        else:
            raise GeometryRefused("ARTIFACT_RECORD", "unknown record status")
        counts[status] += 1
        cells[record["cell"]]["selected"] += 1
        cells[record["cell"]][status] += 1
    if (len(semantic) != len(set(semantic))
            or payload["input_manifest_sha256"] != sha256(material)):
        raise GeometryRefused(
            "ARTIFACT_ROWS", "row identity/input manifest drift")
    expected_counts = {
        "selected": len(records), "valid": counts["valid"],
        "refused": counts["refused"],
    }
    expected_deals = {
        status: len({record["deal_key"] for record in records
                     if status == "selected" or record["status"] == (
                         "VALID_CANDIDATE_GEOMETRY" if status == "valid"
                         else "REFUSED_SCORE_FREE")})
        for status in ("selected", "valid", "refused")
    }
    expected_cells = {
        cell: {name: value[name] for name in ("selected", "valid", "refused")}
        for cell, value in sorted(cells.items())
    }
    tables = (payload["counts"], payload["deal_clusters"])
    if (any(not isinstance(table, dict)
            or set(table) != {"selected", "valid", "refused"}
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in table.values()) for table in tables)
            or not isinstance(payload["coverage_cells"], dict)
            or any(not isinstance(value, dict) or value != expected_cells.get(cell)
                   for cell, value in payload["coverage_cells"].items())
            or payload["counts"] != expected_counts
            or payload["deal_clusters"] != expected_deals
            or payload["coverage_cells"] != expected_cells):
        raise GeometryRefused("ARTIFACT_COUNTS", "coverage does not close")
