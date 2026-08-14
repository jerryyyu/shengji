#!/usr/bin/env python3
"""Design an exact-champion Pair omission-dose census, never run it.

The reviewed Pair scored-packet design says its SmartBot capture weights are
not the live champion's natural role/band dose.  This module closes only that
design gap.  It authenticates the reviewed source design, freezes a fresh
DEV/CALIB seed population, and specifies a score-free census whose instrumented
actors must remain action-for-action identical to ``mc-s0-report-lcb``.

There is deliberately no census implementation, evaluator import, packet or
admission writer, process launcher, artifact reader, gameplay path, or result
interpretation here.  A review may authorize implementation review only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import subprocess
from pathlib import Path
from types import ModuleType


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent

SCHEMA = "pair-ballot-champion-natural-dose-design-v1"
SOURCE_SCHEMA = "pair-ballot-affected-scored-packet-design-v1"
SOURCE_GIT = "289fdf0495da6ad691d8ac760409378f63955545"
SOURCE_MERGE_GIT = "05fb245487cafe0f80878217bb9a013c9f03ee38"
SOURCE_REVIEW_GIT = "6c5c0000b2c61335d66d74916c5b43c454b0093e"
SOURCE_REVIEW_PARENT = "b7a52c3904daab1fcb7c29bfbd5b36b4be47c762"
SOURCE_MERGE_FIRST_PARENT = "6b5ed7e56d3360779e527522d4413ea837d8b77f"
SOURCE_PATH = "server/scripts/pair_ballot_affected_scored_packet_design.py"
SOURCE_SHA256 = (
    "c25820e33053eefab7f5bacd4572391f47fa9897eb6820170b881515c3862f6e")
SOURCE_ARTIFACT_SHA256 = (
    "6fb5b5eb3938856234ef362b5f4017e10782e834c94c45ee645ec6f9b4634e41")
SOURCE_INTERNAL_SHA256 = (
    "0e909f6c3e399aaabd9b5bb357a540b64fbbf1df13dc48bfa268876f1d3b8417")
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
CANONICAL_REF = "origin/main"
REVIEWER = "Claude <noreply@anthropic.com>"
SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

RUN_ID = "pair-ballot-champion-natural-dose-census-v1"
POLICY = "mc-s0-report-lcb"
SPLITS = ("dev", "calib")
BANDS = ("early", "mid", "late")
ROLES = ("attacker", "defender")
SALT = "pair-ballot-champion-natural-dose-v1"
CANDIDATE_SEED0 = 600_000_000_000
TARGET_PER_SPLIT = 4_096
TOTAL_DEALS = TARGET_PER_SPLIT * len(SPLITS)
LOGICAL_LANES = 16
DEALS_PER_LANE = TOTAL_DEALS // LOGICAL_LANES
ROOT_WORLDS = 30
REPORT_WORLDS = 300
BOT_SEED_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)
POPULATION_SHA256 = (
    "e66d251a040bbd473e016cd06a1a6a28381f459e34372d2bc43840e3783d025a")
POPULATION_SEED_HI = 600_000_008_341
POPULATION_DOMAIN_HI = POPULATION_SEED_HI + max(BOT_SEED_OFFSETS)
LANE_MANIFEST_SHA256 = (
    "f5684a8b4953670153af5d20cee2f2dbe6e1d7c77b42bca5b477c0e538f9c3fe")

# These are the complete deal-plus-role seed domains already reserved by the
# Pair capture/screen designs that can plausibly collide with this high-range
# census.  The proposed contiguous 600B domain must sit strictly between the
# checkpoint screen and attacker-gate domains.  Pinning the intervals here
# makes "fresh" a falsifiable arithmetic claim rather than prose.
KNOWN_PAIR_SEED_DOMAINS = (
    ("affected-state-capture-v3", 310_000_000, 321_999_999),
    ("pair-aware-whole-round-screen-v3",
     445_300_000_000, 466_802_621_839),
    ("checkpoint-capacity-v1", 499_000_000_000, 499_382_502_159),
    ("checkpoint-screen-v1", 500_000_000_000, 521_502_621_839),
    ("pair-cap-attacker-gate-capacity-v1",
     620_000_000_000, 620_022_500_119),
    ("pair-cap-attacker-gate-evaluation-v1",
     621_000_000_000, 634_824_078_319),
)

LANE_VECTOR = (
    (0, 512, 248, 264, "e065b5fdc265f364d948467db9df630ed8c6d1b3333cdfc5a30f32dee0adf1ee"),
    (1, 512, 261, 251, "960d7d030f8180e9e0eb4df467aa0c68efb31c61f464189ae136564a4bbfd81f"),
    (2, 512, 260, 252, "09b724f9f234b265866c2dab65a7bbd164bdb0f87f1fd633709a407603081345"),
    (3, 512, 242, 270, "1698e718b6d81022cd14d0f84fa3ac6cdeb41e645f090a61f055f372f57d5380"),
    (4, 512, 253, 259, "8e8b6e81a3e25ea75a1d07cb8e1e6b02520beffdfea30aeda7ed20d0acf6dca8"),
    (5, 512, 265, 247, "abae7d2b771cc63aef157cae5383e8967241c9961763a83efae8ce799d1f8877"),
    (6, 512, 277, 235, "c392ba431c1193948e5d82ed4ca5db4f7eebd40acf1de885e9e71a399e1e9e48"),
    (7, 512, 260, 252, "08cb8d99e15e16f7107653e89f8f5ad1bc0c6e492cfbf22d54799ee7fd917adf"),
    (8, 512, 248, 264, "5fb4b31e42b5bcf2c8c708096c55a71b63e9764e953c7f689e0171e9deddc3c6"),
    (9, 512, 261, 251, "577a73f94b5bb5600c20f702726bf25efaed83a6b3d2092ef1bafa8341d5f891"),
    (10, 512, 266, 246, "b3877e98ad8904a773a1e0992ec338ca2e0d069684a3ea890dd68cd0c7dcd221"),
    (11, 512, 248, 264, "13ce430dcb4f8003ea2180f3a89183309b1b62c1a2ef8a5c78258350d3378a32"),
    (12, 512, 260, 252, "3bec279b8b16c29f1839bfd8673eedcc5e8e55268959ddb526f05c7111310379"),
    (13, 512, 251, 261, "6995f9758f47b786132b9f611ac76937d1b6391079bc9b74292b198d0e6afebf"),
    (14, 512, 260, 252, "591434cb17072a8ee6e30d840def10dfe53b15bafb6caedef5f35874539a6be9"),
    (15, 512, 236, 276, "f86470a9031670fdcdc691e74b257ae83f29de808a06625737b12742d7f57450"),
)

_sha256 = hashlib.sha256


class DoseDesignRefused(ValueError):
    """The natural-dose design or its reviewed provenance drifted."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _digest(raw: bytes) -> str:
    return _sha256(raw).hexdigest()


def _strict_json(raw: bytes, *, label: str) -> object:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise DoseDesignRefused(f"{label} duplicate key {key!r}")
            value[key] = item
        return value

    def bad_constant(value: str) -> None:
        raise DoseDesignRefused(f"{label} non-finite value {value}")

    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=bad_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DoseDesignRefused(f"{label} is not strict JSON") from exc


def _stable_bytes(path: Path, *, label: str, frozen: bool = False) -> bytes:
    lexical = path.absolute()
    try:
        before = os.lstat(lexical)
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or before.st_nlink != 1
                or (frozen and before.st_mode & 0o222)):
            raise DoseDesignRefused(
                f"{label} must be regular, unlinked"
                + (" and non-writable" if frozen else ""))
        fd = os.open(lexical, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        current = os.lstat(lexical)
    except OSError as exc:
        raise DoseDesignRefused(f"cannot read stable {label}") from exc
    identity = lambda item: (
        item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
        item.st_ctime_ns)
    if not (identity(before) == identity(opened)
            == identity(after) == identity(current)):
        raise DoseDesignRefused(f"{label} changed while read")
    return b"".join(chunks)


def _git(*args: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO, check=True, capture_output=True,
            text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DoseDesignRefused("git provenance command failed") from exc
    return result.stdout


def _git_text(*args: str) -> str:
    value = _git(*args)
    if not isinstance(value, str):
        raise DoseDesignRefused("git returned bytes for text request")
    return value


def _git_bytes(ref: str, path: str) -> bytes:
    value = _git("show", f"{ref}:{path}", binary=True)
    if not isinstance(value, bytes):
        raise DoseDesignRefused("git returned text for byte request")
    return value


def _reviewed_source() -> tuple[dict, dict]:
    if (_git_text("rev-parse", SOURCE_GIT).strip() != SOURCE_GIT
            or _git_text("rev-parse", SOURCE_REVIEW_GIT).strip()
            != SOURCE_REVIEW_GIT
            or _git_text("rev-parse", f"{SOURCE_REVIEW_GIT}^").strip()
            != SOURCE_REVIEW_PARENT):
        raise DoseDesignRefused("reviewed source ancestry drift")
    parents = _git_text(
        "show", "-s", "--format=%P", SOURCE_MERGE_GIT).strip().split()
    if parents != [SOURCE_MERGE_FIRST_PARENT, SOURCE_GIT]:
        raise DoseDesignRefused("reviewed source merge topology drift")
    names = _git_text(
        "diff-tree", "--no-commit-id", "--name-only", "-r",
        SOURCE_REVIEW_GIT).splitlines()
    actor = _git_text(
        "show", "-s", "--format=%an <%ae>%n%cn <%ce>",
        SOURCE_REVIEW_GIT).splitlines()
    message = _git_text("show", "-s", "--format=%B", SOURCE_REVIEW_GIT)
    if (names != [REVIEW_LEDGER] or actor != [REVIEWER, REVIEWER]
            or SESSION_TRAILER not in message
            or "design-only PASS" not in message
            or "289fdf0" not in message):
        raise DoseDesignRefused("reviewed source review provenance drift")
    parent_ledger = _git_bytes(SOURCE_REVIEW_PARENT, REVIEW_LEDGER)
    reviewed_ledger = _git_bytes(SOURCE_REVIEW_GIT, REVIEW_LEDGER)
    delta = (reviewed_ledger[len(parent_ledger):]
             if reviewed_ledger.startswith(parent_ledger) else b"")
    required = (
        b"Pair V3 scored packet design (PR #86, `289fdf0`)",
        b"No execution marker is emitted",
        b"grants no runtime, execution, scoring, strength, retry",
    )
    if not delta or any(item not in delta for item in required):
        raise DoseDesignRefused("reviewed source review statement drift")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SOURCE_REVIEW_GIT,
         CANONICAL_REF], cwd=REPO, capture_output=True)
    if ancestor.returncode != 0:
        raise DoseDesignRefused("reviewed source review is not canonical")
    tracked = _git_bytes(SOURCE_GIT, SOURCE_PATH)
    merged = _git_bytes(SOURCE_MERGE_GIT, SOURCE_PATH)
    live = _stable_bytes(REPO / SOURCE_PATH, label="source design")
    if not tracked == merged == live or _digest(live) != SOURCE_SHA256:
        raise DoseDesignRefused("reviewed source bytes drift")
    module = ModuleType("_reviewed_pair_scored_design")
    module.__file__ = str(REPO / SOURCE_PATH)
    exec(compile(live, module.__file__, "exec"), module.__dict__)
    payload = module.build_design()
    module.validate_design(payload)
    if (payload.get("schema") != SOURCE_SCHEMA
            or payload.get("design_sha256") != SOURCE_INTERNAL_SHA256
            or _digest(_canonical(payload)) != SOURCE_ARTIFACT_SHA256):
        raise DoseDesignRefused("reviewed source artifact drift")
    boundary = payload.get("natural_dose_boundary", {})
    future = boundary.get("future_champion_trajectory_census", {})
    expected = {
        "required_before_whole_game_or_value_for_compute_claim": True,
        "exact_policy_identity_required": POLICY,
        "all_natural_search_reachable_omission_events_counted": True,
        "counts_required_by_role": list(ROLES),
        "counts_required_by_band": list(BANDS),
        "fresh_design_and_independent_review_required": True,
        "included_in_this_scored_packet": False,
        "implementation_authorized": False,
        "execution_authorized": False,
    }
    if future != expected:
        raise DoseDesignRefused("natural-dose requirement drift")
    provenance = {
        "source_design_git": SOURCE_GIT,
        "source_merge_git": SOURCE_MERGE_GIT,
        "source_review_git": SOURCE_REVIEW_GIT,
        "source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA256,
        "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
        "source_internal_sha256": SOURCE_INTERNAL_SHA256,
        "review_is_design_only": True,
        "execution_authority_inherited": False,
    }
    return payload, provenance


def split_for_seed(seed: int) -> str:
    raw = _sha256(f"{SALT}|split|{seed}".encode()).digest()
    return SPLITS[int.from_bytes(raw[:8], "big") % len(SPLITS)]


def selected_population() -> list[dict]:
    counts = {split: 0 for split in SPLITS}
    rows = []
    seed = CANDIDATE_SEED0
    while any(counts[split] < TARGET_PER_SPLIT for split in SPLITS):
        split = split_for_seed(seed)
        if counts[split] < TARGET_PER_SPLIT:
            rows.append({"index": len(rows), "seed": seed, "split": split})
            counts[split] += 1
        seed += 1
    return rows


def lane_manifest(population: list[dict]) -> list[dict]:
    lanes = []
    for lane_index in range(LOGICAL_LANES):
        rows = population[lane_index::LOGICAL_LANES]
        lanes.append({
            "lane_index": lane_index,
            "deals": len(rows),
            "deals_by_split": {
                split: sum(row["split"] == split for row in rows)
                for split in SPLITS
            },
            "seed_manifest_sha256": _digest(_canonical(rows)),
        })
    return lanes


def _overlap(left_lo: int, left_hi: int,
             right_lo: int, right_hi: int) -> bool:
    return not (left_hi < right_lo or right_hi < left_lo)


def build_design() -> dict:
    source, provenance = _reviewed_source()
    population = selected_population()
    lanes = lane_manifest(population)
    observed_vector = tuple((
        lane["lane_index"], lane["deals"],
        lane["deals_by_split"]["dev"], lane["deals_by_split"]["calib"],
        lane["seed_manifest_sha256"],
    ) for lane in lanes)
    if (len(population) != TOTAL_DEALS
            or population[-1]["seed"] != POPULATION_SEED_HI
            or _digest(_canonical(population)) != POPULATION_SHA256
            or observed_vector != LANE_VECTOR
            or _digest(_canonical(list(LANE_VECTOR)))
            != LANE_MANIFEST_SHA256
            or any(_overlap(
                CANDIDATE_SEED0, POPULATION_DOMAIN_HI, low, high)
                for _, low, high in KNOWN_PAIR_SEED_DOMAINS)):
        raise DoseDesignRefused("fresh population reconstruction drift")
    payload = {
        "schema": SCHEMA,
        "status": "design only; census implementation does not exist",
        "provenance": provenance,
        "source_requirement": source["natural_dose_boundary"][
            "future_champion_trajectory_census"],
        "estimand": {
            "name": "exact champion natural search-reachable pair omission dose",
            "trajectory": "four-seat champion self-play",
            "policy": POLICY,
            "opponent_policy": POLICY,
            "unit": "natural lead state on a complete champion trajectory",
            "omission": (
                "one or more legal in-hand pair actions absent from the current "
                "candidate ballot"),
            "search_eligible": (
                "the exact champion decision reaches candidate search under "
                "the reviewed search_reachable predicate"),
            "bands": {"early": "trick < 4", "mid": "4 <= trick < 12",
                      "late": "trick >= 12"},
            "roles": list(ROLES),
            "counts_all_eligible_omission_states": True,
            "not_only_first_event_per_deal_or_band": True,
            "not_smartbot_trajectory_dose": True,
            "evaluation_self_play_dose_not_human_production_dose": True,
            "no_outcome_or_utility_estimand": True,
        },
        "population": {
            "splits": list(SPLITS),
            "salt": SALT,
            "candidate_seed0": CANDIDATE_SEED0,
            "candidate_seed_hi_inclusive": POPULATION_SEED_HI,
            "complete_game_and_actor_seed_domain": {
                "low": CANDIDATE_SEED0,
                "high": POPULATION_DOMAIN_HI,
            },
            "known_pair_seed_domains": [
                {"name": name, "low": low, "high": high}
                for name, low, high in KNOWN_PAIR_SEED_DOMAINS
            ],
            "selection": (
                "scan ascending seeds and keep the earliest 4096 in each "
                "sha256(salt|split|seed) split"),
            "deals": TOTAL_DEALS,
            "deals_by_split": {
                split: TARGET_PER_SPLIT for split in SPLITS},
            "selected_seed_manifest_sha256": POPULATION_SHA256,
            "fresh_and_disjoint_from_known_pair_populations_verified": True,
            "partial_split_publication_permitted": False,
            "logical_lanes": LOGICAL_LANES,
            "deals_per_lane": DEALS_PER_LANE,
            "lane_assignment": "selected population index modulo 16",
            "lane_manifest": lanes,
            "lane_manifest_sha256": LANE_MANIFEST_SHA256,
        },
        "instrumentation_contract": {
            "instrumented_actors": 4,
            "instrumented_policy": POLICY,
            "reference_actors": 4,
            "reference_policy": POLICY,
            "bot_seed_offsets": list(BOT_SEED_OFFSETS),
            "same_game_and_bot_rng_seeds_across_instrumented_and_reference":
                True,
            "instrumentation_calls_current_and_retain_all_pair_candidate_ballots":
                True,
            "instrumentation_calls_pair_actions_and_search_reachable": True,
            "instrumentation_occurs_before_the_natural_lead_decision": True,
            "candidate_ballots_and_pair_enumeration_must_be_pure": True,
            "candidate_view": "acting hand plus public round state only",
            "opponent_hands_or_future_information_visible": False,
            "pair_actions": "every legal in-hand pair action",
            "role_definition": "seat parity relative to current banker",
            "band_definition": "completed tricks before the natural lead",
            "instrumentation_consumes_no_rng_and_cannot_change_actions": True,
            "complete_declaration_bury_play_histories_must_be_byte_equal": True,
            "winner_points_and_utility_are_transient_and_discarded": True,
            "outcomes_may_be_computed_by_engine_but_are_never_serialized": True,
            "root_worlds": ROOT_WORLDS,
            "report_worlds": REPORT_WORLDS,
            "every_search_is_literal_n30_r300": True,
            "forced_no_search_decisions_permitted_only_with_zero_counter_delta":
                True,
            "short_zero_void_fallback_or_exact_endgame": "refuse census",
            "exact_policy_git_source_ballot_contract_native_and_python_bound_at_packet":
                True,
        },
        "score_free_output_contract": {
            "per_lane_fields": [
                "schema", "run_id", "lane_index", "deals", "deals_by_split",
                "lead_states_by_split_role_band",
                "omission_states_by_split_role_band",
                "eligible_omission_states_by_split_role_band",
                "missing_pair_actions_by_split_role_band", "search_work",
                "sampler", "instrumented_transcript_commitment",
                "reference_transcript_commitment", "elapsed_ns",
                "authority",
            ],
            "aggregate_reconstructs_all_16_exact_lanes": True,
            "aggregate_publishes_exact_counts_denominators_and_weights": True,
            "cell_weights_are_eligible_omission_counts_divided_by_all_eligible_omissions": True,
            "band_and_role_weights_are_exact_marginals_of_cell_counts": True,
            "all_split_role_band_cells_are_present": True,
            "zero_event_cells_are_published_not_imputed": True,
            "raw_actions_states_hands_decks_buries_and_histories_published": False,
            "winner_points_scores_utilities_labels_and_effects_published": False,
            "report_or_sealed_strength_artifact_read": False,
            "closed_schema_and_recursive_outcome_alias_refusal": True,
            "score_free_supervisor_final_review_before_aggregate": True,
            "result_interpretation_requires_separate_review": True,
        },
        "future_implementation": {
            "implementation_review_required": True,
            "concurrent_capacity_preflight_required": True,
            "host_specific_packet_review_required": True,
            "one_consumed_admission_required": True,
            "systemd_cgroup_required": True,
            "restart": "no",
            "interruption_spends_admission_and_publishes_no_aggregate": True,
            "retry_or_resume": False,
            "fresh_run_id": RUN_ID,
            "request_and_attestation_namespaces_must_be_distinct": True,
        },
        "interpretation_boundary": {
            "may_describe_exact_champion_self_play_role_band_dose": True,
            "may_inform_a_fresh_scored_packet_design_after_terminal_review":
                True,
            "does_not_rewrite_the_reviewed_scored_packet": True,
            "current_air_pair_screen_is_complementary_but_lacks_all_band_counts":
                True,
            "does_not_estimate_human_production_traffic": True,
            "does_not_measure_pair_retention_effect": True,
            "does_not_authorize_scored_packet_or_whole_game_run": True,
            "does_not_establish_utility_per_compute_or_strength": True,
        },
        "authority": {
            "design_review_only": True,
            "implementation_authorized": False,
            "capacity_preflight_authorized": False,
            "packet_freeze_authorized": False,
            "census_execution_authorized": False,
            "population_open_authorized": False,
            "scored_output_access_authorized": False,
            "aggregation_authorized": False,
            "report_access_authorized": False,
            "scored_pair_packet_authorized": False,
            "whole_game_execution_authorized": False,
            "retry_authorized": False,
            "extension_authorized": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    if (sum(payload["population"]["deals_by_split"].values()) != TOTAL_DEALS
            or sum(lane["deals"] for lane in lanes) != TOTAL_DEALS
            or not math.isclose(
                source["estimands"]["band_weights"]["early"]
                + source["estimands"]["band_weights"]["mid"]
                + source["estimands"]["band_weights"]["late"],
                1.0, rel_tol=0.0, abs_tol=1e-15)):
        raise DoseDesignRefused("natural-dose design consistency drift")
    payload["design_sha256"] = _digest(_canonical(payload))
    return payload


def validate_design(payload: object) -> None:
    if not isinstance(payload, dict):
        raise DoseDesignRefused("natural-dose design is not an object")
    body = dict(payload)
    observed = body.pop("design_sha256", None)
    if observed != _digest(_canonical(body)):
        raise DoseDesignRefused("natural-dose design digest drift")
    if _canonical(payload) != _canonical(build_design()):
        raise DoseDesignRefused("natural-dose design reconstruction drift")


def verify_design(path: Path) -> dict:
    raw = _stable_bytes(path, label="natural-dose design", frozen=True)
    payload = _strict_json(raw, label="natural-dose design")
    if raw != _canonical(payload):
        raise DoseDesignRefused("natural-dose design is not canonical JSON")
    validate_design(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--design", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            if args.design is not None:
                raise DoseDesignRefused("build accepts no design path")
            print(_canonical(build_design()).decode(), end="")
        else:
            if args.design is None:
                raise DoseDesignRefused("verify requires --design")
            design = verify_design(args.design)
            print(json.dumps({
                "schema": design["schema"],
                "design_sha256": design["design_sha256"],
                "deals": design["population"]["deals"],
                "implementation_authorized": False,
                "census_execution_authorized": False,
            }, sort_keys=True))
    except (DoseDesignRefused, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
