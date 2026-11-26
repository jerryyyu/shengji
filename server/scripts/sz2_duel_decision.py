"""Apply the S156 decision to a sealed saved SZ2-A readout."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from sz2_duel_exports import FT500_PACKAGE_SHA


ARM = "SZ2-A"
SEED0 = 2665000000
DEALS = 1000
MEAN_BAR = 0.02
LB80_BAR = 0.0
READER_SHA = "f8a722626c01a80f441d38ad6e47d69fd52661cb431a5be4be1fdeff2bd44140"
PREDECLARE = Path(__file__).resolve().parents[2] / "dev/s156/SZ2_A_DECISION.md"
HEX = r"[0-9a-f]{64}"
TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
MAX_JSON_BYTES = 256 * 1024
CHECKS = {
    "completion", "names", "arm_fault_ceilings", "worlds_delivered", "served_belief_fallback",
    "completion_shape", "bbw_fallback_ceiling", "unified_prior", "unified_readout", "outcome_consistency",
}


def _is_sha(value):
    return isinstance(value, str) and re.fullmatch(HEX, value) is not None


def _pinned_json(path, expected_sha, label):
    if not _is_sha(expected_sha):
        raise ValueError(f"invalid expected {label} SHA-256")
    with path.open("rb") as source:
        data = source.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError(f"{label} differs from its independent SHA-256")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _expected_sides(recipe, medium_sha, small_sha):
    if (not _is_sha(medium_sha) or not _is_sha(small_sha)
            or len({medium_sha, small_sha, FT500_PACKAGE_SHA}) != 3):
        raise ValueError("decision A needs distinct frozen M and S readouts, excluding FT500")
    if recipe.get("schema") != "utd-h2h-recipe-r1" or recipe.get("duel") != "UTH":
        raise ValueError("expected the UTH recipe")
    arm = recipe["arms"][ARM]
    if (type(arm.get("seed0")) is not int or arm["seed0"] != SEED0
            or type(arm.get("deals")) is not int or arm["deals"] != DEALS):
        raise ValueError("recipe is not the registered 1,000-deal decision arm")
    sides = {}
    for role, tag, digest in (("exploiter", "ex", medium_sha), ("defender", "def", small_sha)):
        name = arm.get(f"{role}_name")
        short = digest[:8]
        suffix = f"-sc8-ushare{short}-uvalue{short}-ureply{short}"
        if (arm.get(f"{tag}_package_sha256") != digest or not isinstance(name, str) or not name.endswith(suffix)):
            raise ValueError(f"recipe {role} differs from the frozen readout")
        sides[role] = {"name": name, "package_sha256": digest}
    return sides


def _check_result_binding(result, recipe, recipe_sha, predeclare_sha, sides):
    reader_sha = recipe.get("reader_sha256")
    if (reader_sha != READER_SHA or result.get("reader_sha256") != reader_sha
            or result.get("schema") != "uth-read-r1" or result.get("duel") != "UTH" or result.get("arm") != ARM):
        raise ValueError("result is not decision A from the frozen UTH reader")
    if any(result.get(role) != side for role, side in sides.items()):
        raise ValueError("result side identities differ from the frozen decision arm")
    binding = result["binding"]
    sums = binding.get("sums_sha256")
    terminal = binding.get("terminal")
    if (binding.get("recipe_sha256") != recipe_sha or binding.get("predeclare_sha256") != predeclare_sha
            or not _is_sha(sums) or not _is_sha(binding.get("duel_jsonl_sha256"))
            or not isinstance(terminal, str)
            or not re.fullmatch(rf"UTD DONE {TIMESTAMP} recipe={recipe_sha} rows={2 * DEALS} sums={sums} rc=0", terminal)):
        raise ValueError("result lacks the matching recipe, predeclaration and completed seal binding")


def _check_validity(result):
    validity = result["validity"]
    checks = validity.get("checks")
    if validity.get("verdict") != "VALID" or not isinstance(checks, list):
        raise ValueError("result must pass the sealed reader's validity checks")
    by_name = {}
    for check in checks:
        name = check.get("check")
        if not isinstance(name, str) or name in by_name or check.get("verdict") != "VALID":
            raise ValueError("result has an invalid or duplicate reader check")
        by_name[name] = check
    if not CHECKS <= by_name.keys():
        raise ValueError("result lacks required reader validity checks")
    detail = by_name["outcome_consistency"]["detail"]
    if type(detail.get("rows")) is not int or detail["rows"] != 2 * DEALS or detail.get("inconsistent") != 0:
        raise ValueError("result lacks valid outcome counts for the full paired arm")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def decide(result_path, result_sha, recipe_path, recipe_sha, medium_sha, small_sha):
    predeclare_sha = hashlib.sha256(PREDECLARE.read_bytes()).hexdigest()
    recipe = _pinned_json(recipe_path, recipe_sha, "recipe")
    if recipe.get("predeclare_sha256") != predeclare_sha:
        raise ValueError("recipe does not bind the checked-in S156 predeclaration")
    sides = _expected_sides(recipe, medium_sha, small_sha)
    result = _pinned_json(result_path, result_sha, "result")
    _check_result_binding(result, recipe, recipe_sha, predeclare_sha, sides)
    _check_validity(result)
    outcome = result["outcome"]
    bar = outcome["bar"]
    if bar.get("beats_mean") != MEAN_BAR or bar.get("beats_lb80") != LB80_BAR:
        raise ValueError("result carries a different decision bar")
    levels = outcome["levels"]
    if (type(levels.get("n")) is not int or levels["n"] != DEALS
            or not _finite(levels.get("mean")) or not _finite(levels.get("lb80"))):
        raise ValueError("invalid levels statistics for the full paired arm")
    passes = levels["mean"] >= MEAN_BAR and levels["lb80"] > LB80_BAR
    verdict = outcome.get("verdict")
    if verdict not in ("BEATS", "NON-INFERIOR", "WORSE") or (verdict == "BEATS") != passes:
        raise ValueError("result verdict disagrees with the S156 bar")
    return {"arm": ARM, "decision": "SIZE-PAYS" if passes else "MISSES-DEV-BAR", "paired_deals": DEALS,
            "mean_levels_per_round": levels["mean"], "lb80_levels_per_round": levels["lb80"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog="Exit 0 for SIZE-PAYS, 3 for a valid miss, or 2 for a refused result.")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--result-sha256", required=True, help="independently sealed saved result SHA-256")
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--recipe-sha256", required=True, help="SHA-256 frozen before play")
    parser.add_argument("--medium-sha256", required=True, help="independently frozen M readout package SHA-256")
    parser.add_argument("--small-sha256", required=True, help="independently frozen S readout package SHA-256")
    args = parser.parse_args(argv)
    try:
        decision = decide(args.result, args.result_sha256, args.recipe, args.recipe_sha256,
                          args.medium_sha256, args.small_sha256)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError) as exc:
        print(f"decision refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(decision, allow_nan=False))
    return 0 if decision["decision"] == "SIZE-PAYS" else 3


if __name__ == "__main__":
    sys.exit(main())
