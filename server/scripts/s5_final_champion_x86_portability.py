#!/usr/bin/env python3
"""Fail-closed x86 binding for the reviewed S5 champion replay.

The reviewed S5 producer is frozen at ``f8083cf`` and its live-parent
reopener intentionally accepts only the historical ARM native binary.  This
module does not edit that producer or reinterpret its review.  It qualifies
one Linux/x86 build separately by authenticating the historical parent,
normalising the binary-derived ballot field, and replaying two synthetic,
score-free champion decisions against a byte-pinned cross-architecture
fixture.

The original ``run`` command admitted one partial attempt from a marker
template in its own review request.  That attempt consumed its one-shot slot.
This repaired revision is therefore validation-only: it authenticates a
distinct reviewer attestation and the historical x86 binding, but can never
consume an admission or invoke the producer.  A future retry, if any, requires
a new reviewed controller, admission, and output namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import platform
import random
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent

SCHEMA = "s5-final-champion-x86-portability-v1"
FIXTURE_SCHEMA = "s5-final-champion-portable-fixture-v1"
REVIEW_SCHEMA = "s5-final-champion-x86-portability-review-v1"
REVIEW_PREFIX = "S5_FINAL_CHAMPION_X86_PORTABILITY_V1_REVIEW "
ATTESTATION_SCHEMA = "s5-final-champion-x86-portability-reviewer-attestation-v1"
ATTESTATION_PREFIX = \
    "S5_FINAL_CHAMPION_X86_PORTABILITY_REVIEWER_ATTESTATION_V1 "

# The request template first appeared in this canonical-main commit.  A valid
# attestation must be introduced by a later, independently attributable
# reviewer commit; merely copying the request payload can never satisfy it.
REQUEST_RECORD_GIT = "d8211a8dcb3593bc1c55f3824eeef6f812771319"
INCIDENT_RECORD_GIT = "f26ed204a372215989e958e00474ae90685a3bdb"
LEGACY_PASS_RECORD_GIT = "40b84da9058f05770061abea0d36d631b679859b"
REQUEST_TEMPLATE_DEMOTION_GIT = \
    "d46dc24cbe36846aaf3de4c332cdbb96ea36e30c"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_TRAILER_PREFIX = "Claude-Session: https://claude.ai/code/session_"
LEGACY_WRAPPER_GIT = "ff9bed51fce729f23205167df105d7eadd938e84"
LEGACY_WRAPPER_SHA256 = (
    "91519061cafeab14611d1ccb500ef0fea737cd46269b42194cbb44e40e85ba3a"
)

BASE_GIT = "f8083cf0ce9d575f875e601f1e8862280f587e0d"
BASE_SCRIPT_RELATIVE = Path("server/scripts/s5_final_champion_replay.py")
BASE_SCRIPT_SHA256 = (
    "06d837de717ba14f971ad7456aa1f930dbd577c0876e5611f59cc6ba7b547e07"
)
BASE_PARENT_RELATIVE = Path("server/scripts/live_champion_parent.py")
BASE_PARENT_SHA256 = (
    "d6515d6db76290c3ad145f9194a7985d7d78223f688a30c78cdb520de41c521b"
)
BASE_CENSUS_RELATIVE = Path("server/scripts/s5_point_protection_census.py")
BASE_CENSUS_SHA256 = (
    "4f720d63998316ce48946dd342f719cf5e53cd30f2fbda8e69a045cf0a7f00bf"
)
BASE_HEURISTIC_RELATIVE = Path("server/shengji/ai/heuristic.py")
BASE_HEURISTIC_SHA256 = (
    "a99dfb089fd17e7c17ddcc4d76542552d317598fbe233269c3e7c0501b9b15ef"
)
BASE_DESIGN_SHA256 = (
    "59c63e16c740bb8d9afef2c8a4e1a3d0edb16fb8039f319dc2b6f4f56b160521"
)
CHAMPION = "mc-s0-report-lcb"

# The historical parent stays ARM-identical.  The x86 identity below is the
# branch-built binary in the clean staged f8083cf worktree on shengji-perf.
HISTORICAL_FAST_BINARY_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1"
)
HISTORICAL_POLICY_CONTRACT_SHA256 = (
    "59fa033dc22d8a055b5d7f3fbcbaf9d7fb0b71993b74c4d9bb7587e3d90dc72b"
)
HISTORICAL_BALLOT = "mc_candidates@v1[a68f7b8bced6]"
X86_RUNTIME = {
    "system": "Linux",
    "machine": "x86_64",
    "python": "3.14.4",
}
X86_FAST_BINARY_SHA256 = (
    "b4e5e319309be37c483ebabc681a87bb9885e89dcde2b0c6c0f776cd2ceb9b8e"
)
X86_POLICY_CONTRACT_SHA256 = (
    "f04fa58fb518dec5f54a630bf5e5e2dd25a40f465bf449e601d4ffc1f188768a"
)
X86_BALLOT = "mc_candidates@v1[ec84724ab56a]"
POLICY_CONTRACT_WITHOUT_BALLOT_SHA256 = (
    "6898c2e42f42502e8cebe6b74543a4c3fdbba33f0286a7cc3969bab1ca8c2e05"
)

FIXTURE_PATH = SCRIPT.with_name("s5_final_champion_portable_fixture.v1.json")
# Patched after the canonical JSON is added; kept explicit so a fixture edit
# cannot validate itself merely by changing its internal self-hash.
FIXTURE_FILE_SHA256 = (
    "a9a10e543d9d9edce1ce07a9942e9c69f2c035b467e086706486222af5e12446"
)
FIXTURE_PAYLOAD_SHA256 = (
    "8e83e9595942e6fbb92118afe562bd71dd0290a32d3a210718c778e8f3ac4e50"
)

CANONICAL_OUTPUT_RELATIVE = Path(
    "server/runs/logs/human-v8-s5-final-champion-replay-v1/result.json"
)
ADMISSION_RELATIVE = Path(
    "server/runs/locks/"
    "human-v8-s5-final-champion-replay-x86-v1.execution.consumed.json"
)

FIXTURE_SPECS = (
    {"name": "lead", "game_seed": 2, "champion_seed": 7001,
     "target_seat": 3, "expected_banker": 3, "follow_position": 1},
    {"name": "follow", "game_seed": 2, "champion_seed": 7002,
     "target_seat": 0, "expected_banker": 3, "follow_position": 2},
)

AUTHORITY = {
    "synthetic_score_free_fixture_only": True,
    "sealed_s5_outcomes_read": False,
    "new_diagnostic_execution_authorized": False,
    "retry_authorized": False,
    "strength_execution_authorized": False,
    "strength_claim": False,
    "labels_authorized": False,
    "training_authorized": False,
    "production_promotion": False,
    "production_deployment": False,
}


class PortabilityRefused(RuntimeError):
    """The S5 source, parent, x86 runtime, or review boundary drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PortabilityRefused(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PortabilityRefused(f"{label} is not an object")
    return value


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_base_worktree(base: Path) -> Path:
    """Require an independent clean tracked f8083cf worktree."""
    base = base.resolve()
    if base.is_symlink() or not (base / ".git").is_file():
        raise PortabilityRefused("base S5 root is not a Git worktree")
    if base == REPO.resolve():
        raise PortabilityRefused("x86 adapter and frozen base must be separate")
    try:
        head = _git(base, "rev-parse", "HEAD")
        dirty = _git(base, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError) as exc:
        raise PortabilityRefused("cannot authenticate base S5 worktree") from exc
    if head != BASE_GIT:
        raise PortabilityRefused("base S5 worktree is not exact f8083cf")
    if dirty:
        raise PortabilityRefused("base S5 worktree has tracked changes")
    fixed_sources = {
        BASE_SCRIPT_RELATIVE: BASE_SCRIPT_SHA256,
        BASE_PARENT_RELATIVE: BASE_PARENT_SHA256,
        BASE_CENSUS_RELATIVE: BASE_CENSUS_SHA256,
        BASE_HEURISTIC_RELATIVE: BASE_HEURISTIC_SHA256,
    }
    for relative, expected in fixed_sources.items():
        path = base / relative
        if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
            raise PortabilityRefused(f"frozen source drift: {relative}")
    return base


def _load_base_s5(base: Path):
    """Load the unchanged producer before importing any gameplay module."""
    base = validate_base_worktree(base)
    server = base / "server"
    scripts = server / "scripts"
    for name in (str(scripts), str(server)):
        if name not in sys.path:
            sys.path.insert(0, name)
    for name in ("live_champion_parent", "s5_point_protection_census"):
        loaded = sys.modules.get(name)
        if loaded is not None and not _is_under(Path(loaded.__file__), base):
            raise PortabilityRefused(
                f"{name} was imported from outside the frozen base")
    path = base / BASE_SCRIPT_RELATIVE
    spec = importlib.util.spec_from_file_location(
        "s5_final_champion_replay_f8083cf", path)
    if spec is None or spec.loader is None:
        raise PortabilityRefused("cannot load frozen S5 producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.SCRIPT).resolve() != path.resolve():
        raise PortabilityRefused("frozen S5 module resolved outside base")
    return module


def _prepare_fixture_round(s5, spec: Mapping[str, object]):
    from shengji.ai.smart import SmartBot
    from shengji.engine.game import Game

    game = Game(random.Random(int(spec["game_seed"])))
    rnd = game.start_round()
    policies = [SmartBot() for _ in range(4)]
    target = int(spec["target_seat"])
    policies[target] = s5.make_bot(
        CHAMPION, seed=int(spec["champion_seed"]))
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker != spec["expected_banker"]:
        raise PortabilityRefused("fixture banker drift")
    rnd.bury(rnd.banker,
             policies[rnd.banker].decide_bury(rnd, rnd.banker))
    while len(rnd.trick.plays) < int(spec["follow_position"]) - 1:
        seat = rnd.turn
        rnd.play(seat, policies[seat].decide_play(rnd, seat))
    if rnd.turn != target:
        raise PortabilityRefused("fixture target turn drift")
    return rnd, policies[target]


def _fixture_case(s5, spec: Mapping[str, object]) -> dict:
    rnd, bot = _prepare_fixture_round(s5, spec)
    target = int(spec["target_seat"])
    state = {
        "game_seed": spec["game_seed"],
        "target_seat": target,
        "follow_position": spec["follow_position"],
        "banker": rnd.banker,
        "turn": rnd.turn,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "actor_is_attacker": rnd.is_attacker(target),
        "actor_hand": sorted(rnd.hands[target]),
        "hand_sizes": [len(hand) for hand in rnd.hands],
        "trick_leader": rnd.trick.leader,
        "trick_plays": [
            [play.seat, sorted(play.cards)] for play in rnd.trick.plays],
        "history": [
            [play.seat, sorted(play.cards)]
            for trick in rnd.history for play in trick.plays],
        "declarer": getattr(rnd, "declarer", None),
    }
    candidates = [list(action) for action in bot._candidates(rnd, target)]
    if len(candidates) <= 1 or len({tuple(action) for action in candidates}) != \
            len(candidates):
        raise PortabilityRefused("fixture ballot is uncontested/duplicated")
    played = list(bot.decide_play(rnd, target))
    record = bot.last_decision_record
    if not isinstance(record, Mapping):
        raise PortabilityRefused("fixture champion decision has no record")
    if ([list(action) for action in record.get("candidates", [])] != candidates
            or list(record.get("played", [])) != played
            or record.get("policy") != CHAMPION):
        raise PortabilityRefused("fixture champion record drift")
    return {
        **dict(spec),
        "state_sha256": sha256_bytes(canonical_json(state)),
        "candidates": [sorted(action) for action in candidates],
        "played": sorted(played),
        "played_index": record.get("played_index"),
        "raw_winner_index": record.get("raw_winner_index"),
        "reason": record.get("reason"),
        "work": record.get("work"),
        "sampler_counters": record.get(
            "sampler_counters", {}).get("delta"),
    }


def build_fixture(s5) -> dict:
    cases = [_fixture_case(s5, spec) for spec in FIXTURE_SPECS]
    payload = {
        "schema": FIXTURE_SCHEMA,
        "base_git": BASE_GIT,
        "champion": CHAMPION,
        "cases": cases,
        "cases_sha256": sha256_bytes(canonical_json(cases)),
        "authority": {
            "synthetic_states_only": True,
            "score_free": True,
            "round_outcomes_read": False,
            "utilities_read": False,
            "sealed_s5_evidence_read": False,
            "strength_claim": False,
            "production_deployment": False,
        },
    }
    payload["fixture_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def require_fixture(s5) -> dict:
    if (FIXTURE_PATH.is_symlink() or not FIXTURE_PATH.is_file()
            or sha256_file(FIXTURE_PATH) != FIXTURE_FILE_SHA256):
        raise PortabilityRefused("portable fixture file identity drift")
    frozen = _load_object(FIXTURE_PATH, "portable S5 fixture")
    frozen_copy = dict(frozen)
    claimed = frozen_copy.pop("fixture_sha256", None)
    if claimed != sha256_bytes(canonical_json(frozen_copy)):
        raise PortabilityRefused("portable fixture self-hash drift")
    if claimed != FIXTURE_PAYLOAD_SHA256:
        raise PortabilityRefused("portable fixture payload identity drift")
    current = build_fixture(s5)
    if current != frozen:
        raise PortabilityRefused("portable champion ballot/action replay drift")
    return frozen


def _sealed_parent_problems(parent) -> list[str]:
    problems = []
    artifacts = (
        (parent.RLCB_CLOSEOUT_PATH, parent.RLCB_CLOSEOUT_SHA256,
         "RLCB-C1 artifact closeout"),
        (parent.RLCB_AGGREGATE_PATH, parent.RLCB_AGGREGATE_SHA256,
         "RLCB-C1 aggregate"),
        (parent.RLCB_FREEZE_PATH, parent.RLCB_FREEZE_SHA256,
         "RLCB-C1 freeze receipt"),
    )
    for path, expected, label in artifacts:
        if path.is_symlink() or not path.is_file():
            problems.append(f"{label} missing/non-regular")
        elif sha256_file(path) != expected:
            problems.append(f"{label} digest drift")
    if problems:
        return problems
    try:
        closeout = _load_object(
            parent.RLCB_CLOSEOUT_PATH, "RLCB-C1 artifact closeout")
        aggregate = _load_object(
            parent.RLCB_AGGREGATE_PATH, "RLCB-C1 aggregate")
    except PortabilityRefused as exc:
        return [str(exc)]
    return parent._portable_confirmation_problems(closeout, aggregate)


def _module_provenance_problems(s5) -> list[str]:
    """Refuse a preloaded gameplay module from outside exact f8083cf."""
    problems = []
    base = Path(s5.REPO).resolve()
    required = (
        "shengji.ai.registry", "shengji.ai.mcbot", "shengji.ai.smart",
        "shengji.ai.heuristic", "shengji.ai.memory", "shengji.ai.env",
        "shengji.engine.ballot", "shengji.engine.cards",
        "shengji.engine.combos", "shengji.engine.fast",
        "shengji.engine.game", "shengji.engine.legal",
        "shengji.engine.round",
    )
    for name in required:
        try:
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
        except (AttributeError, ImportError, OSError, TypeError) as exc:
            problems.append(
                f"gameplay module unavailable: {name}: {type(exc).__name__}")
            continue
        if not _is_under(path, base):
            problems.append(f"gameplay module loaded outside base: {name}")
    return problems


def _x86_policy_problems(s5) -> list[str]:
    parent = s5.LIVE_PARENT
    c1 = parent.C1
    problems = _module_provenance_problems(s5)
    problems += list(c1.protocol_problems(require_receipt=False))
    sources = c1.source_sha256s()
    if {name: sources.get(name) for name in parent.CHAMPION_SOURCE_SHA256S} != \
            parent.CHAMPION_SOURCE_SHA256S:
        problems.append("champion transitive source drift")
    heuristic = Path(s5.SERVER) / "shengji/ai/heuristic.py"
    if heuristic.is_symlink() or sha256_file(heuristic) != BASE_HEURISTIC_SHA256:
        problems.append("champion rollout heuristic drift/PR71 substitution")
    try:
        contract = c1.policy_contract(CHAMPION)
        ballot = contract.pop("ballot", None)
        normalised = c1.stable_digest(contract)
        full = c1.policy_contract_sha256s().get(CHAMPION)
    except Exception as exc:
        problems.append(
            f"champion policy contract failed: {type(exc).__name__}: {exc}")
    else:
        if ballot != X86_BALLOT:
            problems.append("x86 ballot identity drift")
        if normalised != POLICY_CONTRACT_WITHOUT_BALLOT_SHA256:
            problems.append("platform-neutral champion contract drift")
        if full != X86_POLICY_CONTRACT_SHA256:
            problems.append("x86 full champion contract drift")
    try:
        bot = s5.make_bot(CHAMPION, seed=7)
    except Exception as exc:
        problems.append(
            f"champion construction failed: {type(exc).__name__}: {exc}")
    else:
        if (bot.N_DETERMINIZATIONS != 30
                or bot.REPORT_FOLD_WORLDS != 300
                or bot.REPORT_RULE != "lcb"
                or bot.REQUIRE_EXACT_WORK is not True):
            problems.append("report-LCB decision semantics drift")
        if any(getattr(bot, name, False) for name in (
                "MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME",
                "ADAPTIVE_ALLOCATION", "RANDOM_ALLOCATION")):
            problems.append("champion enables descendant treatment")
    try:
        fly = tomllib.loads((Path(s5.REPO) / "fly.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        problems.append(f"fly policy config unreadable: {exc}")
    else:
        if fly.get("env", {}).get("SHENGJI_BOT") != CHAMPION:
            problems.append("fly policy no longer names report-LCB")
    return sorted(set(problems))


def require_x86_parent(s5) -> dict:
    """Authenticate the historical parent plus one exact x86 runtime."""
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise PortabilityRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise PortabilityRefused("compiled engine requested but not active")
    current_runtime = {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    problems = []
    if current_runtime != X86_RUNTIME:
        problems.append("x86 runtime identity drift")
    if sha256_file(fast._fast.__file__) != X86_FAST_BINARY_SHA256:
        problems.append("x86 compiled binary identity drift")
    problems += _sealed_parent_problems(s5.LIVE_PARENT)
    problems += _x86_policy_problems(s5)
    if problems:
        raise PortabilityRefused("; ".join(sorted(set(problems))))
    fixture = require_fixture(s5)
    historical = s5.LIVE_PARENT.expected_parent()
    if (historical.get("fast_binary_sha256") !=
            HISTORICAL_FAST_BINARY_SHA256
            or historical.get("policy_contract_sha256") !=
            HISTORICAL_POLICY_CONTRACT_SHA256):
        raise PortabilityRefused("historical ARM parent identity drift")
    return {
        "schema": SCHEMA,
        "base_git": BASE_GIT,
        "historical_parent": historical,
        "compatible_x86": {
            **X86_RUNTIME,
            "fast_binary_sha256": X86_FAST_BINARY_SHA256,
            "ballot": X86_BALLOT,
            "policy_contract_sha256": X86_POLICY_CONTRACT_SHA256,
            "policy_contract_without_ballot_sha256":
                POLICY_CONTRACT_WITHOUT_BALLOT_SHA256,
            "fixture_file_sha256": FIXTURE_FILE_SHA256,
            "fixture_payload_sha256": fixture["fixture_sha256"],
        },
        "authority": dict(AUTHORITY),
    }


def review_claim(*, wrapper_git: str) -> dict:
    if wrapper_git != LEGACY_WRAPPER_GIT:
        raise PortabilityRefused("legacy review claim requires exact PR74 head")
    return {
        "schema": REVIEW_SCHEMA,
        "wrapper_git": wrapper_git,
        "wrapper_sha256": LEGACY_WRAPPER_SHA256,
        "base_git": BASE_GIT,
        "base_script_sha256": BASE_SCRIPT_SHA256,
        "base_design_sha256": BASE_DESIGN_SHA256,
        "historical_arm_parent_preserved": True,
        "historical_fast_binary_sha256": HISTORICAL_FAST_BINARY_SHA256,
        "x86_runtime": dict(X86_RUNTIME),
        "x86_fast_binary_sha256": X86_FAST_BINARY_SHA256,
        "x86_ballot": X86_BALLOT,
        "x86_policy_contract_sha256": X86_POLICY_CONTRACT_SHA256,
        "policy_contract_without_ballot_sha256":
            POLICY_CONTRACT_WITHOUT_BALLOT_SHA256,
        "fixture_file_sha256": FIXTURE_FILE_SHA256,
        "fixture_payload_sha256": FIXTURE_PAYLOAD_SHA256,
        "portable_fixture_replayed_on_arm_and_x86": True,
        "pr71_source_substitution": False,
        "original_s5_review_required": True,
        "existing_one_diagnostic_may_execute_on_x86": True,
        "new_diagnostic_execution_authorized": False,
        "retry_authorized": False,
        "strength_execution_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def review_claim_sha256() -> str:
    return sha256_bytes(canonical_json(
        review_claim(wrapper_git=LEGACY_WRAPPER_GIT)))


def reviewer_attestation(*, wrapper_git: str) -> dict:
    return {
        "schema": ATTESTATION_SCHEMA,
        "request_record_git": REQUEST_RECORD_GIT,
        "incident_record_git": INCIDENT_RECORD_GIT,
        "legacy_pass_record_git": LEGACY_PASS_RECORD_GIT,
        "request_template_demotion_git": REQUEST_TEMPLATE_DEMOTION_GIT,
        "legacy_wrapper_git": LEGACY_WRAPPER_GIT,
        "legacy_review_claim_sha256": review_claim_sha256(),
        "repair_git": wrapper_git,
        "repair_script_sha256": sha256_file(SCRIPT),
        "reviewer_name": REVIEWER_NAME,
        "reviewer_email": REVIEWER_EMAIL,
        "partial_attempt_acknowledged": True,
        "old_admission_spent": True,
        "retry_authorized": False,
        "diagnostic_execution_authorized": False,
        "verdict": "PASS_PORTABILITY_ONLY",
    }


def _canonical_commit_problems(repo: Path, *, main_ref: str,
                               record_relative: Path,
                               attestation_line: str) -> list[str]:
    """Bind the attestation to one independently authored main commit."""
    problems = []
    try:
        commits = _git(
            repo, "log", main_ref, "--format=%H", "--fixed-strings",
            f"-S{attestation_line}", "--", record_relative.as_posix(),
        ).splitlines()
        if len(commits) != 1:
            return ["attestation has no unique introducing main commit"]
        commit = commits[0]
        parents = _git(repo, "show", "-s", "--format=%P", commit).split()
        name = _git(repo, "show", "-s", "--format=%an", commit)
        email = _git(repo, "show", "-s", "--format=%ae", commit)
        message = _git(repo, "show", "-s", "--format=%B", commit)
        changed = _git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            commit).splitlines()
        committed = _git(repo, "show", f"{commit}:{record_relative}").splitlines()
        required_ancestors = (REQUEST_RECORD_GIT, INCIDENT_RECORD_GIT,
                              LEGACY_PASS_RECORD_GIT,
                              REQUEST_TEMPLATE_DEMOTION_GIT)
        ancestors = [subprocess.run(
            ["git", "merge-base", "--is-ancestor", required, commit],
            cwd=repo, capture_output=True).returncode == 0
            for required in required_ancestors]
        on_main = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, main_ref],
            cwd=repo, capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"cannot authenticate reviewer commit: {type(exc).__name__}"]
    if len(parents) != 1:
        problems.append("reviewer commit must have exactly one parent")
    if not all(ancestors) or commit in required_ancestors or not on_main:
        problems.append("reviewer commit does not descend from incident chain")
    if name != REVIEWER_NAME or email != REVIEWER_EMAIL:
        problems.append("reviewer commit author provenance drift")
    if not any(line.startswith(REVIEWER_TRAILER_PREFIX)
               for line in message.splitlines()):
        problems.append("reviewer commit session provenance drift")
    if changed != [record_relative.as_posix()]:
        problems.append("reviewer commit changed files beyond canonical ledger")
    if committed.count(attestation_line) != 1:
        problems.append("reviewer commit does not introduce one exact attestation")
    if parents:
        try:
            parent_lines = _git(
                repo, "show", f"{parents[0]}:{record_relative}").splitlines()
        except (OSError, subprocess.SubprocessError):
            problems.append("cannot authenticate reviewer parent ledger")
        else:
            if parent_lines.count(attestation_line) != 0:
                problems.append(
                    "attestation was already present before reviewer commit")
    return problems


def _legacy_marker_problems(repo: Path, *, main_ref: str,
                            record_relative: Path,
                            request_line: str) -> list[str]:
    """Recognise the request and late legacy PASS, never either as approval."""
    problems = []
    try:
        request_lines = _git(
            repo, "show", f"{REQUEST_RECORD_GIT}:{record_relative}").splitlines()
        legacy_lines = _git(
            repo, "show", f"{LEGACY_PASS_RECORD_GIT}:{record_relative}").splitlines()
        demoted_lines = _git(
            repo, "show",
            f"{REQUEST_TEMPLATE_DEMOTION_GIT}:{record_relative}").splitlines()
        current_lines = _git(
            repo, "show", f"{main_ref}:{record_relative}").splitlines()
        history = _git(
            repo, "rev-list", "--first-parent", "--reverse", main_ref,
            "--", record_relative.as_posix(),
        ).splitlines()
        changes = []
        prior_count = 0
        for historical_commit in history:
            historical_lines = _git(
                repo, "show",
                f"{historical_commit}:{record_relative}").splitlines()
            current_count = historical_lines.count(request_line)
            if current_count != prior_count:
                changes.append(historical_commit)
            prior_count = current_count
        incident_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", INCIDENT_RECORD_GIT,
             LEGACY_PASS_RECORD_GIT], cwd=repo, capture_output=True,
        ).returncode == 0
        demotion_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", LEGACY_PASS_RECORD_GIT,
             REQUEST_TEMPLATE_DEMOTION_GIT], cwd=repo, capture_output=True,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"cannot authenticate legacy marker chain: {type(exc).__name__}"]
    if request_lines.count(request_line) != 1:
        problems.append("request commit does not contain one exact template")
    if legacy_lines.count(request_line) != 2:
        problems.append("legacy PASS commit does not contain the known duplicate")
    if demoted_lines.count(request_line) != 1:
        problems.append("request demotion did not leave one legacy PASS marker")
    if current_lines.count(request_line) != 1:
        problems.append("unexpected duplicate/removal of legacy request marker")
    if set(changes) != {REQUEST_RECORD_GIT, LEGACY_PASS_RECORD_GIT,
                        REQUEST_TEMPLATE_DEMOTION_GIT}:
        problems.append("legacy marker changed outside the pinned incident chain")
    if not incident_ancestor:
        problems.append("legacy PASS does not descend from incident record")
    if not demotion_ancestor:
        problems.append("request demotion does not descend from legacy PASS")
    return problems


def require_review_marker(path: Path, *, wrapper_git: str,
                          canonical_repo: Path = REPO,
                          record_relative: Path = Path("HANDOFF_REVIEW.md"),
                          main_ref: str = "origin/main") -> dict:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise PortabilityRefused("review record is unreadable") from exc
    requests = [line for line in lines if line.startswith(REVIEW_PREFIX)]
    if len(requests) != 1:
        raise PortabilityRefused(
            "exactly one demoted-history legacy PASS marker is required")
    try:
        request = json.loads(requests[0][len(REVIEW_PREFIX):])
    except (TypeError, ValueError) as exc:
        raise PortabilityRefused("S5 x86 request marker is invalid JSON") from exc
    if request != review_claim(wrapper_git=LEGACY_WRAPPER_GIT):
        raise PortabilityRefused("S5 x86 request marker differs from contract")
    matches = [line for line in lines if line.startswith(ATTESTATION_PREFIX)]
    if len(matches) != 1:
        raise PortabilityRefused(
            "exactly one reviewer attestation is required; request is not PASS")
    try:
        attestation = json.loads(matches[0][len(ATTESTATION_PREFIX):])
    except (TypeError, ValueError) as exc:
        raise PortabilityRefused("reviewer attestation is invalid JSON") from exc
    expected = reviewer_attestation(wrapper_git=wrapper_git)
    if attestation != expected:
        raise PortabilityRefused("reviewer attestation differs from contract")
    canonical_repo = canonical_repo.resolve()
    try:
        canonical_bytes = subprocess.run(
            ["git", "show", f"{main_ref}:{record_relative.as_posix()}"],
            cwd=canonical_repo, check=True, capture_output=True,
        ).stdout
        if path.read_bytes() != canonical_bytes:
            raise PortabilityRefused(
                "review record is not byte-identical to canonical main")
    except (OSError, subprocess.SubprocessError) as exc:
        raise PortabilityRefused("cannot resolve canonical review ledger") from exc
    problems = _legacy_marker_problems(
        canonical_repo, main_ref=main_ref, record_relative=record_relative,
        request_line=requests[0])
    problems += _canonical_commit_problems(
        canonical_repo, main_ref=main_ref, record_relative=record_relative,
        attestation_line=matches[0])
    if problems:
        raise PortabilityRefused("; ".join(problems))
    return attestation


def _require_wrapper_head(expected_git: str) -> None:
    try:
        head = _git(REPO, "rev-parse", "HEAD")
        dirty = _git(REPO, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError) as exc:
        raise PortabilityRefused("cannot authenticate wrapper Git") from exc
    if head != expected_git:
        raise PortabilityRefused("wrapper Git differs from reviewed Git")
    if dirty:
        raise PortabilityRefused("wrapper worktree has tracked changes")


def canonical_admission_path(base: Path) -> Path:
    """Return the sole historical admission path that is now spent."""
    base = base.resolve()
    path = (base / ADMISSION_RELATIVE).resolve()
    if not _is_under(path, base):
        raise PortabilityRefused("S5 x86 admission path escaped base")
    return path


def run(args) -> dict:
    # The original x86 admission was consumed by the 2026-08-13 partial
    # self-admission incident.  Refuse before any review, source, result, or
    # admission access so this revision cannot accidentally become retry
    # authority.
    raise PortabilityRefused(
        "S5 x86 diagnostic is permanently held after spent partial attempt; "
        "this revision grants no retry")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("verify-fixture")
    fixture.add_argument("--base-root", required=True)
    fixture.add_argument("--expected-wrapper-git", required=True)
    verify = commands.add_parser("verify-x86")
    verify.add_argument("--base-root", required=True)
    verify.add_argument("--review-record", required=True)
    verify.add_argument("--expected-wrapper-git", required=True)
    claim = commands.add_parser("review-claim")
    claim.add_argument("--wrapper-git", required=True)
    attestation = commands.add_parser("reviewer-attestation")
    attestation.add_argument("--wrapper-git", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--base-root", required=True)
    execute.add_argument("--census", required=True)
    execute.add_argument("--source-manifest", required=True)
    execute.add_argument("--source-root", required=True)
    execute.add_argument("--review-record", required=True)
    execute.add_argument("--expected-wrapper-git", required=True)
    execute.add_argument("--out", required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.command == "review-claim":
        print(canonical_json(review_claim(
            wrapper_git=args.wrapper_git)).decode(), end="")
        return
    if args.command == "reviewer-attestation":
        print(ATTESTATION_PREFIX + canonical_json(reviewer_attestation(
            wrapper_git=args.wrapper_git)).decode(), end="")
        return
    if args.command == "run":
        # Dispatch the permanently retired execution surface before opening a
        # worktree, review ledger, source, output, or admission path.
        run(args)
        raise AssertionError("retired S5 run unexpectedly returned")
    _require_wrapper_head(args.expected_wrapper_git)
    base = validate_base_worktree(Path(args.base_root))
    s5 = _load_base_s5(base)
    if args.command == "verify-fixture":
        fixture = require_fixture(s5)
        print(json.dumps({
            "status": "S5_PORTABLE_FIXTURE_VERIFIED",
            "fixture_sha256": fixture["fixture_sha256"],
            "score_free": True,
        }, sort_keys=True))
        return
    if args.command == "verify-x86":
        design = s5.build_design()
        if design.get("design_sha256") != BASE_DESIGN_SHA256:
            raise PortabilityRefused("frozen S5 design identity drift")
        record = Path(args.review_record).resolve()
        s5._census_review_marker(record)
        s5._review_marker(record, expected_git=BASE_GIT, design=design)
        require_review_marker(record, wrapper_git=args.expected_wrapper_git)
        binding = require_x86_parent(s5)
        print(json.dumps({
            "status": "S5_X86_PORTABILITY_VERIFIED",
            "base_git": binding["base_git"],
            "x86_fast_binary_sha256":
                binding["compatible_x86"]["fast_binary_sha256"],
            "fixture_payload_sha256":
                binding["compatible_x86"]["fixture_payload_sha256"],
            "diagnostic_executed": False,
            "strength_claim": False,
        }, sort_keys=True))
        return
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except PortabilityRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
