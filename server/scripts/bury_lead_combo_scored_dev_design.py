#!/usr/bin/env python3
"""Design the bounded scored-DEV follow-up to the bury/S6 capacity probe.

This module is deliberately declarative and read-only.  It freezes the
opened-DEV population, selection/report split, continuation sensitivity arms,
work ceiling, sealed-result sequence, and the maximum authority an external
PASS may grant.  It neither imports gameplay code nor writes, launches, scores,
aggregates, or opens an outcome artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path


SCHEMA = "bury-lead-combo-scored-dev-design-v1"
DESIGN_ID = "bury-lead-combo-scored-dev-64-v1"
CODE_GIT = "8ab5db26cc9b31844cccc6c9c9feffb7832646ac"
CODE_REVIEW_LEDGER_GIT = "ecf9c79e6d785b833c266ffe3cc6d46921159fdd"

CAPACITY_FILE_SHA256 = (
    "e1e4cb38ad4c2cd6f0d2e13e24180d906197cafc7363dde4352fd4d9ef33103d")
CAPACITY_INTERNAL_SHA256 = (
    "437d11925e2fe0f71fa253ed0ab76332084e3658f2e1687a974daa810294003e")
CAPACITY_BYTES = 6_849
CAPACITY_REVIEW_COMMENT_ID = 5_280_799_087
CAPACITY_REVIEW_URL = (
    "https://github.com/jerryyyu/shengji/pull/78#issuecomment-5280799087")
CAPACITY_REVIEW_BODY_SHA256 = (
    "300fdc46728e17a949006fcc0163a4be467ce3b80d49710e655d61c98bae492d")
CAPACITY_REVIEW_BODY_BYTES = 3_648

CAPACITY_RUNTIME = {
    "git": CODE_GIT,
    "tree_dirty": False,
    "python": "3.14.4",
    "fast_binary_sha256":
        "dfe7b84b7556c70db62f433fbbb3d122c3f243900d97ac258a2eb1d63e101233",
    "population_source_sha256":
        "f5ef09e10cc1d9af6bc590df3d289809761839c88a4737d73566654726f27fa2",
    "scorer_source_sha256":
        "295d424bf03b98898c4796cf08a156e66e24fd3bb0747799f0b7522956309434",
    "continuation_source_sha256":
        "84c2943f8553ef58b8e74ad60e4f614aa383685adffbb54a212a66ea0dd6e705",
    "journal_source_sha256":
        "e3a1968ea212851387d146c6d9e77397dfacd118e056f59608a0b4fb400cd7ea",
    "controller_source_sha256":
        "18a248c80a43f670160ebc0dff5fcff575238557ff9b588ddc6ffce940656ab3",
}

POPULATION_ID = "s3a-bury-v2-opened-dev-136m-v1"
POPULATION_STATES = 512
SELECTION_SHA256 = (
    "b7391090eb4f00a3eb3cdbcb440aac4d2cc1b94db26de1a2f1e170fe1b08f033")
SELECTION_ROWS_SHA256 = (
    "d7077957d183a1f8c420cde2f0fff11514e8b03dd777c7b3587b75a16d0cdb6f")
SELECTION_ROWS = (
    (136000457, 592, "shape_rich", "combo_count"),
    (136000412, 503, "shape_rich", "feasible_void_count"),
    (136000013, 548, "shape_rich", "groups_with_plain_void"),
    (136000186, 416, "shape_rich", "groups_with_structured_throw"),
    (136000492, 458, "shape_rich", "groups_with_tractor"),
    (136000404, 551, "shape_rich", "max_pair_run"),
    (136000488, 245, "shape_rich", "pair_unit_spread"),
    (136000131, 467, "shape_rich", "retained_point_spread"),
    (136000305, 571, "shape_rich", "combo_count"),
    (136000144, 530, "shape_rich", "feasible_void_count"),
    (136000000, 546, "shape_rich", "groups_with_plain_void"),
    (136000066, 397, "shape_rich", "groups_with_structured_throw"),
    (136000315, 525, "shape_rich", "groups_with_tractor"),
    (136000411, 491, "shape_rich", "max_pair_run"),
    (136000184, 374, "shape_rich", "pair_unit_spread"),
    (136000422, 322, "shape_rich", "retained_point_spread"),
    (136000009, 570, "shape_rich", "combo_count"),
    (136000147, 555, "shape_rich", "feasible_void_count"),
    (136000288, 535, "shape_rich", "groups_with_plain_void"),
    (136000082, 439, "shape_rich", "groups_with_structured_throw"),
    (136000173, 554, "shape_rich", "groups_with_tractor"),
    (136000033, 510, "shape_rich", "max_pair_run"),
    (136000445, 356, "shape_rich", "pair_unit_spread"),
    (136000230, 416, "shape_rich", "retained_point_spread"),
    (136000482, 564, "shape_rich", "combo_count"),
    (136000161, 450, "shape_rich", "feasible_void_count"),
    (136000048, 403, "shape_rich", "groups_with_plain_void"),
    (136000133, 410, "shape_rich", "groups_with_structured_throw"),
    (136000151, 401, "shape_rich", "groups_with_tractor"),
    (136000477, 439, "shape_rich", "max_pair_run"),
    (136000421, 367, "shape_rich", "pair_unit_spread"),
    (136000367, 302, "shape_rich", "retained_point_spread"),
    (136000012, 399, "hash_uniform_anchor", "uniform_anchor"),
    (136000112, 338, "hash_uniform_anchor", "uniform_anchor"),
    (136000142, 419, "hash_uniform_anchor", "uniform_anchor"),
    (136000176, 389, "hash_uniform_anchor", "uniform_anchor"),
    (136000159, 325, "hash_uniform_anchor", "uniform_anchor"),
    (136000461, 375, "hash_uniform_anchor", "uniform_anchor"),
    (136000064, 361, "hash_uniform_anchor", "uniform_anchor"),
    (136000325, 248, "hash_uniform_anchor", "uniform_anchor"),
    (136000397, 353, "hash_uniform_anchor", "uniform_anchor"),
    (136000308, 367, "hash_uniform_anchor", "uniform_anchor"),
    (136000251, 454, "hash_uniform_anchor", "uniform_anchor"),
    (136000494, 274, "hash_uniform_anchor", "uniform_anchor"),
    (136000210, 386, "hash_uniform_anchor", "uniform_anchor"),
    (136000041, 416, "hash_uniform_anchor", "uniform_anchor"),
    (136000001, 354, "hash_uniform_anchor", "uniform_anchor"),
    (136000447, 279, "hash_uniform_anchor", "uniform_anchor"),
    (136000358, 371, "hash_uniform_anchor", "uniform_anchor"),
    (136000458, 491, "hash_uniform_anchor", "uniform_anchor"),
    (136000446, 362, "hash_uniform_anchor", "uniform_anchor"),
    (136000193, 360, "hash_uniform_anchor", "uniform_anchor"),
    (136000280, 370, "hash_uniform_anchor", "uniform_anchor"),
    (136000113, 550, "hash_uniform_anchor", "uniform_anchor"),
    (136000179, 370, "hash_uniform_anchor", "uniform_anchor"),
    (136000337, 353, "hash_uniform_anchor", "uniform_anchor"),
    (136000352, 341, "hash_uniform_anchor", "uniform_anchor"),
    (136000039, 464, "hash_uniform_anchor", "uniform_anchor"),
    (136000162, 348, "hash_uniform_anchor", "uniform_anchor"),
    (136000499, 424, "hash_uniform_anchor", "uniform_anchor"),
    (136000119, 238, "hash_uniform_anchor", "uniform_anchor"),
    (136000106, 437, "hash_uniform_anchor", "uniform_anchor"),
    (136000330, 272, "hash_uniform_anchor", "uniform_anchor"),
    (136000386, 345, "hash_uniform_anchor", "uniform_anchor"),
)

MODES = ("baseline", "all_boss", "boss_near")
SELECTION_WORLDS = 30
REPORT_WORLDS = 30
SELECTION_BASE_SEED = 20_260_814
REPORT_BASE_SEED = 20_260_815
ATTEMPT_FACTOR = 20
MENU_SLOTS = ("incumbent_live", "incumbent_widened", "expanded")
TOTAL_COMBOS_PER_WORLD = 26_640
FULL_SELECTION_ROLLOUTS = TOTAL_COMBOS_PER_WORLD * SELECTION_WORLDS
REPORT_SLOT_ROLLOUTS_PER_MODE = len(SELECTION_ROWS) * len(MENU_SLOTS) * REPORT_WORLDS
TOTAL_CANDIDATE_ROLLOUTS = (
    FULL_SELECTION_ROLLOUTS
    + len(MODES) * REPORT_SLOT_ROLLOUTS_PER_MODE)
MAX_STATE_SELECTION_ROLLOUTS = 592 * SELECTION_WORLDS
MAX_STATE_REPORT_ROLLOUTS_PER_MODE = len(MENU_SLOTS) * REPORT_WORLDS
POSITIVE_STATE_GATE = 41

FORBIDDEN_KEYS = frozenset({
    "actions", "hands", "buried", "attacker_points", "winner", "scores",
    "utility", "candidate_values", "world_values",
})


class DesignRefused(RuntimeError):
    """The scored-DEV design or its immutable input drifted."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hex(value: object, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _forbidden(value: object, path: str = "$") -> list[str]:
    problems = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                problems.append(f"forbidden design field {path}.{key}")
            problems.extend(_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(_forbidden(child, f"{path}[{index}]"))
    return problems


def _selection_rows() -> list[dict[str, object]]:
    return [
        {
            "deal_seed": seed,
            "combo_count": count,
            "selection_group": group,
            "selection_reason": reason,
        }
        for seed, count, group, reason in SELECTION_ROWS
    ]


def build_design() -> dict[str, object]:
    rows = _selection_rows()
    value: dict[str, object] = {
        "schema": SCHEMA,
        "design_id": DESIGN_ID,
        "provenance": {
            "code_git": CODE_GIT,
            "code_review_ledger_git": CODE_REVIEW_LEDGER_GIT,
            "capacity_result": {
                "file_sha256": CAPACITY_FILE_SHA256,
                "internal_sha256": CAPACITY_INTERNAL_SHA256,
                "bytes": CAPACITY_BYTES,
                "runtime": dict(CAPACITY_RUNTIME),
                "selection_sha256": SELECTION_SHA256,
                "selection_rows_sha256": SELECTION_ROWS_SHA256,
                "candidate_rollouts": 1_776,
                "total_arm_seconds": "3.315673417997459",
                "baseline_seconds": "0.31519825799841783",
                "all_boss_seconds": "1.5574503089992504",
                "boss_near_seconds": "1.443024850999791",
            },
            "capacity_result_review": {
                "comment_id": CAPACITY_REVIEW_COMMENT_ID,
                "url": CAPACITY_REVIEW_URL,
                "reviewer_login": "jerryyyu",
                "created_at": "2026-08-13T13:04:41Z",
                "body_sha256": CAPACITY_REVIEW_BODY_SHA256,
                "body_bytes": CAPACITY_REVIEW_BODY_BYTES,
                "verdict": "PASS_SCORE_FREE_CAPACITY_RESULT_ONLY",
                "required_followup": (
                    "pin capacity engine and five source identities in the "
                    "scored packet plus its new fold scorer/controller"),
            },
        },
        "population": {
            "id": POPULATION_ID,
            "opened_reusable_dev": True,
            "source_population_already_opened": True,
            "source_outcomes_read": False,
            "population_states": POPULATION_STATES,
            "shape_rich_states": 32,
            "hash_uniform_anchor_states": 32,
            "selected_states": len(rows),
            "selection_sha256": SELECTION_SHA256,
            "selection_rows_sha256": SELECTION_ROWS_SHA256,
            "rows": rows,
            "total_combos_per_common_world": TOTAL_COMBOS_PER_WORLD,
        },
        "execution_specification": {
            "modes": list(MODES),
            "selection": {
                "mode": "baseline",
                "worlds": SELECTION_WORLDS,
                "base_seed": SELECTION_BASE_SEED,
                "purpose": (
                    "choose three fixed menu slots before any report value"),
                "menus": {
                    "incumbent_live": (
                        "best selection-fold live lead after incumbent bury"),
                    "incumbent_widened": (
                        "best selection-fold retained/S6/live lead after "
                        "incumbent bury"),
                    "expanded": (
                        "best selection-fold joint sourced bury/lead combo"),
                },
                "candidate_zero_preserved": True,
                "all_menu_slots_nonempty": True,
                "menu_nesting_required": (
                    "incumbent_live subset incumbent_widened subset expanded"),
                "stable_tie_break": "lowest canonical candidate index",
            },
            "report": {
                "worlds": REPORT_WORLDS,
                "base_seed": REPORT_BASE_SEED,
                "slots": list(MENU_SLOTS),
                "modes": list(MODES),
                "same_fixed_slots_across_modes": True,
                "same_world_commitment_across_slots_and_modes": True,
                "same_sampler_delta_and_rng_final_across_modes": True,
                "selection_and_report_worlds_disjoint": True,
                "slot_duplicates_preserved_for_exact_work": True,
            },
            "sampler": {
                "attempt_factor": ATTEMPT_FACTOR,
                "accepted_worlds_required_per_state_fold": 30,
                "underfill_result": "HOLD_WITHOUT_OUTCOME_ACCESS",
                "impossible_worlds_required": 0,
                "hidden_pre_bury_kitty_required": [],
            },
            "runtime": {
                "required_git_ancestor": CODE_GIT,
                "capacity_evidence_identity_required": dict(CAPACITY_RUNTIME),
                "unchanged_execution_components_required": {
                    field: CAPACITY_RUNTIME[field]
                    for field in (
                        "fast_binary_sha256", "population_source_sha256",
                        "scorer_source_sha256",
                        "continuation_source_sha256",
                        "journal_source_sha256",
                    )
                },
                "capacity_controller_is_evidence_only": True,
                "new_fold_scorer_sha256": "POPULATE_AND_REVIEW_IN_PACKET",
                "new_controller_sha256": "POPULATE_AND_REVIEW_IN_PACKET",
                "compiled_strict": True,
                "tree_dirty": False,
                "systemd_cgroup_required": True,
                "serial_state_execution": True,
                "maximum_wall_seconds": 3_600,
                "capacity_projection_seconds": "457.7782545270285386837837838",
                "capacity_safety_factor": "7.86406947992643388841844814932",
            },
            "work": {
                "baseline_selection_candidate_rollouts":
                    FULL_SELECTION_ROLLOUTS,
                "report_slot_rollouts_per_mode":
                    REPORT_SLOT_ROLLOUTS_PER_MODE,
                "report_modes": len(MODES),
                "total_candidate_rollouts": TOTAL_CANDIDATE_ROLLOUTS,
                "max_state_selection_rollouts":
                    MAX_STATE_SELECTION_ROLLOUTS,
                "max_state_report_rollouts_per_mode":
                    MAX_STATE_REPORT_ROLLOUTS_PER_MODE,
                "all_work_exact_not_normalized": True,
            },
        },
        "sealed_output_contract": {
            "scored_state_records": len(rows),
            "one_record_contains_all_three_modes": True,
            "per_state_atomic_immutable_record": True,
            "source_outcomes_read": False,
            "new_outcomes_computed": True,
            "new_outcomes_sealed_until_review": True,
            "attempted_and_actual_play_committed": True,
            "failed_throw_uses_engine_actual_result": True,
            "selected_slot_actions_only_hashed_in_supervisor": True,
            "interrupted_run_status": "HOLD",
            "missing_only_resume_authorized": False,
            "completed_records_preserved_for_future_review": True,
            "score_free_supervisor_final": True,
            "supervisor_final_contains_only": [
                "record hashes", "state/mode/fold identities", "world hashes",
                "work", "sampler counters", "continuation dose", "timing",
            ],
            "supervisor_final_review_before_record_open": True,
            "one_reviewed_aggregate_after_supervisor_pass": True,
            "aggregate_is_opened_dev_exploration_only": True,
            "aggregate_terminal_review_required": True,
        },
        "estimands": {
            "lead_source": (
                "report-fold banker value of incumbent_widened minus "
                "incumbent_live, using baseline-selected fixed slots"),
            "joint_bury_source": (
                "report-fold banker value of expanded minus "
                "incumbent_widened, using baseline-selected fixed slots"),
            "joint_total": (
                "report-fold banker value of expanded minus incumbent_live"),
            "continuation_sensitivity": (
                "the same fixed report slots and worlds under baseline, "
                "all_boss, and boss_near continuations"),
            "cluster_unit": "one selected public banker state",
            "post_selection_report_values_only": True,
            "attacker_points_are_converted_by_existing_banker_objective": True,
            "scoring_contract": {
                "bot_class": "MCS0ReportLCB",
                "baseline_rollout_policy_class": "HeuristicBot",
                "alternative_rollout_policy_class": "S6ThrowRolloutPolicy",
                "continuation_actor_visible": True,
                "recursive_mc_continuation": False,
                "level_objective": False,
                "exact_endgame": False,
                "perspective": "banker_value_is_negative_attacker_objective",
                "nonbaseline_play_calls_required_positive": True,
                "baseline_dose_required_null": True,
            },
        },
        "decision_rule": {
            "integrity_failure": "HOLD",
            "primary_gates": ["lead_source", "joint_bury_source"],
            "positive_state_threshold_each_gate": POSITIVE_STATE_GATE,
            "threshold_basis": (
                "exact one-sided sign tail 0.0163828795494116, below "
                "Bonferroni alpha 0.025 for two gates"),
            "additional_requirements": [
                "baseline report mean strictly positive",
                "shape-rich and hash-anchor baseline means nonnegative",
                "all_boss and boss_near report means nonnegative",
                "at least one selected slot differs from its control",
                "all 64 states and exact work complete",
            ],
            "advance_scope": (
                "design a fresh live-versus-source-versus-candidate-count-"
                "matched-random screen; never claim whole-game strength"),
            "otherwise": "SELECT_NONE_FOR_FRESH_SCREEN_DESIGN",
        },
        "maximum_pass_scope": {
            "controller_implementation_design_authorized": True,
            "packet_implementation_authorized": False,
            "packet_freeze_authorized": False,
            "execution_authorized": False,
            "scored_record_access_authorized": False,
            "aggregation_authorized": False,
            "report_access_authorized": False,
            "confirmatory_inference_authorized": False,
            "retry_authorized": False,
            "extension_authorized": False,
            "strength_claim_authorized": False,
            "training_authorized": False,
            "production_promotion_authorized": False,
            "production_deployment_authorized": False,
        },
    }
    value["internal_sha256"] = _digest(value)
    return value


def design_problems(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return ["design is not an object"]
    problems = _forbidden(value)
    expected = build_design()
    if set(value) != set(expected):
        problems.append("design top-level fields")
    material = dict(value)
    recorded = material.pop("internal_sha256", None)
    if recorded != _digest(material):
        problems.append("design internal digest")
    for key, target in expected.items():
        if value.get(key) != target:
            problems.append(f"design {key}")

    population = value.get("population")
    if isinstance(population, Mapping):
        rows = population.get("rows")
        if isinstance(rows, list):
            seeds = [row.get("deal_seed") for row in rows
                     if isinstance(row, Mapping)]
            counts = [row.get("combo_count") for row in rows
                      if isinstance(row, Mapping)]
            groups = [row.get("selection_group") for row in rows
                      if isinstance(row, Mapping)]
            if (len(rows) != 64 or len(seeds) != len(set(seeds))
                    or groups.count("shape_rich") != 32
                    or groups.count("hash_uniform_anchor") != 32
                    or any(isinstance(count, bool) or not isinstance(count, int)
                           for count in counts)
                    or sum(counts) != TOTAL_COMBOS_PER_WORLD
                    or min(counts, default=0) != 238
                    or max(counts, default=0) != 592):
                problems.append("design independent selection arithmetic")

    spec = value.get("execution_specification")
    work = spec.get("work") if isinstance(spec, Mapping) else None
    if not isinstance(work, Mapping) or (
            work.get("baseline_selection_candidate_rollouts")
            != TOTAL_COMBOS_PER_WORLD * SELECTION_WORLDS
            or work.get("report_slot_rollouts_per_mode")
            != len(SELECTION_ROWS) * len(MENU_SLOTS) * REPORT_WORLDS
            or work.get("total_candidate_rollouts")
            != (TOTAL_COMBOS_PER_WORLD * SELECTION_WORLDS
                + len(MODES) * len(SELECTION_ROWS)
                * len(MENU_SLOTS) * REPORT_WORLDS)):
        problems.append("design independent work arithmetic")

    authority = value.get("maximum_pass_scope")
    if (not isinstance(authority, Mapping)
            or authority.get("controller_implementation_design_authorized")
            is not True
            or any(item is not False for key, item in authority.items()
                   if key != "controller_implementation_design_authorized")):
        problems.append("design authority boundary")
    return sorted(set(problems))


def _pairs(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise DesignRefused(f"duplicate JSON key {key!r}")
        value[key] = child
    return value


def _constant(value: str):
    raise DesignRefused(f"non-finite JSON constant {value}")


def verify_design(path: Path, expected_sha256: str) -> dict[str, object]:
    if not _hex(expected_sha256):
        raise DesignRefused("expected design SHA is not lowercase hex")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DesignRefused(f"cannot open design: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_mode & 0o222 or before.st_uid != os.getuid()):
            raise DesignRefused(
                "design must be owned, nonwritable, regular, and unlinked")
        chunks = []
        while True:
            block = os.read(descriptor, 1 << 20)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as exc:
        raise DesignRefused(f"design path disappeared: {exc}") from exc
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    if identity(before) != identity(after) or identity(after) != identity(current):
        raise DesignRefused("design changed while being read")
    raw = b"".join(chunks)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DesignRefused("design file SHA drifted")
    try:
        value = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DesignRefused(f"design JSON is invalid: {exc}") from exc
    if not isinstance(value, dict) or raw != _canonical(value) + b"\n":
        raise DesignRefused("design JSON is not canonical")
    problems = design_problems(value)
    if problems:
        raise DesignRefused("; ".join(problems))
    return value


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--design", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        value = build_design()
    else:
        value = verify_design(args.design, args.expected_sha256)
    print(_canonical(value).decode())


if __name__ == "__main__":
    main()
