"""Capture, diagnose and freeze fresh teacher-v1 gate states.

This is state selection only.  It never computes or stores the 512-world
teacher tensor.  Every deal is assigned one target decision, one data split
and one representative/challenge pool from named hash streams before play.
The small N=30/v11 selector diagnostic is a separate immutable artifact; the
freezer may inspect only those named diagnostics when selecting boundary and
uncertainty rows.

Typical sequence (commands shown for one shard; capture/diagnose can be
sharded):

  teacher_v1_states.py capture --shard-count 8 --shard-index 0 --out ...
  teacher_v1_states.py diagnose --input ... --expected-input-sha256 ... --out ...
  teacher_v1_states.py freeze --stage a --input diagnosed-0.json ... --out ...

No mode launches Stage C or reads candidate outcomes from DEV/CALIB/REPORT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                              # noqa: E402
from shengji.ai.registry import make_bot                          # noqa: E402
from shengji.engine.ballot import mc_ballot                       # noqa: E402
from shengji.engine.game import Game                              # noqa: E402
from shengji.teacher_v1 import (CAPTURE_DEALS_PER_SHARD,           # noqa: E402
                                CAPTURE_MAX_DEALS, CAPTURE_PACKET_ID,
                                CAPTURE_PYTHON, CAPTURE_SEED_END,
                                CAPTURE_SHARDS, EXPERIMENT,
                                EXPERIMENTAL_SAMPLER_BALLOT_FLAGS,
                                GATE_SCHEMA, REPRESENTATIVE_CELLS,
                                SAMPLER_COUNTERS, SEED_START,
                                STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STAGE_B_STATES,
                                STAGE_B_BOUNDARY_STATES,
                                STAGE_B_REPRESENTATIVE_PER_CELL,
                                STAGE_B_UNCERTAINTY_STATES,
                                STATE_SCHEMA, STATE_SET_SCHEMA,
                                TeacherProtocolError, action_key,
                                ballot_problems, derive_stream,
                                capture_coverage, capture_packet,
                                capture_shard_seeds,
                                is_run_id, is_sha256,
                                json_canonical,
                                phase_for_trick, replay_state,
                                sampler_delta, sampler_snapshot,
                                split_for_deal, stable_digest, state_id)

CAPTURE_SCHEMA = "teacher-v1-capture-shard-v1"
DIAGNOSTIC_SCHEMA = "teacher-v1-selector-diagnostic-v1"
ACTOR = "mc-strong"
SELECTOR_WORLDS = 30
V11_CHECKPOINT_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
DEFAULT_EXAM_SPLITS = (
    "rl_data/corpus_split.v1.json",
    "rl_data/corpus_split_late.v1.json",
    "rl_data/deep_lead_split.v1.json",
)
DEFAULT_EXAM_SPLIT_SHA256 = {
    "rl_data/corpus_split.v1.json":
        "bbc061f9c08f19f490d8b789d5c8f15542e28bdaa5504efb1adfe7ba40d9edc2",
    "rl_data/corpus_split_late.v1.json":
        "9b974ab16f3a76fb089efe8541690d9ecbfdcad9b174bb0623b7d456d0b2aa1c",
    "rl_data/deep_lead_split.v1.json":
        "9d72dcafffc1d8ac983be81f0f33275236f21f850aed019f9d081e0291812df6",
}

# Packet-specific bridge after Stage A exposed a JSON-domain-only labeller
# defect.  The 64 selected states and every source that produced/replays them
# remain frozen at the entry commit; Stage-A labels/gate live at the exact
# two-file repair commit.  Stage B may cross that history only through this
# named transition and a clean freezer-only descendant.
STAGE_B_SOURCE_TRANSITION_ID = (
    "teacher-v3-stage-b-freeze-after-json-repair-v1"
)
STAGE_B_TRANSITION_DIAGNOSTIC_GIT = (
    "be25b4d64a85025f8d728f11359bf66bedf5d21a"
)
STAGE_B_TRANSITION_GATE_GIT = (
    "b41d8b3e193cbaefd6ccc5ee757ea7b2c502b618"
)
STAGE_B_TRANSITION_STATE_SHA256 = (
    "e016373e8ecb9b6c7b6f3c14f8f4b14d9845f76478137f7a2c07249628cb4648"
)
STAGE_B_TRANSITION_GATE_SHA256 = (
    "731dfa936b6f572866538ead701cdf48d231ef3d1d3a6a0034c2debb1517635b"
)
STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS = (
    "server/scripts/teacher_v1_label.py",
    "server/tests/test_teacher_v1.py",
)
STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS = (
    "server/scripts/teacher_v1_states.py",
    "server/tests/test_teacher_v1.py",
)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def git_changed_paths(parent: str, child: str) -> tuple[str, ...]:
    output = git_output("diff", "--name-only", f"{parent}..{child}")
    return tuple(sorted(line for line in output.splitlines() if line))


def git_is_ancestor(parent: str, child: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", parent, child],
        check=False, capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr,
        )
    return result.returncode == 0


def stage_b_source_transition_problems(
        diagnostic: dict, state_set: dict, state_set_sha256: str,
        gate: dict, gate_sha256: str, live: dict,
        transition_id: str | None) -> tuple[list[str], dict | None]:
    """Authorize only the exact label-only Stage-A -> freezer repair bridge."""
    if transition_id != STAGE_B_SOURCE_TRANSITION_ID:
        return ["Stage-B source transition id missing or unknown"], None

    bad = []
    if state_set_sha256 != STAGE_B_TRANSITION_STATE_SHA256:
        bad.append("Stage-B transition state-set SHA-256 drift")
    if gate_sha256 != STAGE_B_TRANSITION_GATE_SHA256:
        bad.append("Stage-B transition Stage-A gate SHA-256 drift")
    if diagnostic.get("git") != STAGE_B_TRANSITION_DIAGNOSTIC_GIT:
        bad.append("Stage-B transition diagnostic git drift")
    if state_set.get("git") != STAGE_B_TRANSITION_DIAGNOSTIC_GIT:
        bad.append("Stage-B transition state-set git drift")
    if gate.get("git") != STAGE_B_TRANSITION_GATE_GIT:
        bad.append("Stage-B transition gate git drift")
    current_git = live.get("git")
    if (not isinstance(current_git, str) or len(current_git) != 40
            or any(char not in "0123456789abcdef" for char in current_git)):
        bad.append("Stage-B transition current git syntax")

    try:
        historical_ancestry = git_is_ancestor(
            STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
            STAGE_B_TRANSITION_GATE_GIT,
        )
        freezer_ancestry = git_is_ancestor(
            STAGE_B_TRANSITION_GATE_GIT, current_git)
        historical_paths = git_changed_paths(
            STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
            STAGE_B_TRANSITION_GATE_GIT,
        )
        freezer_paths = git_changed_paths(
            STAGE_B_TRANSITION_GATE_GIT, current_git)
    except (OSError, subprocess.SubprocessError, TypeError) as exc:
        bad.append(f"Stage-B transition git diff failed: {type(exc).__name__}")
        historical_ancestry, freezer_ancestry = False, False
        historical_paths, freezer_paths = (), ()
    if not historical_ancestry:
        bad.append("Stage-B transition historical ancestry")
    if not freezer_ancestry:
        bad.append("Stage-B transition freezer ancestry")
    if historical_paths != STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS:
        bad.append("Stage-B transition historical diff scope")
    if freezer_paths != STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS:
        bad.append("Stage-B transition freezer diff scope")

    gate_sources = gate.get("gate_source_digests", {})
    old_state_source = diagnostic.get("state_script_sha256")
    if (state_set.get("state_script_sha256") != old_state_source
            or gate_sources.get("state_script") != old_state_source):
        bad.append("Stage-B transition frozen state-source chain drift")
    if live.get("state_script_sha256") == old_state_source:
        bad.append("Stage-B transition did not version the freezer")

    current_unchanged_sources = {
        "compiled_engine": live.get("fast_binary_sha256"),
        "fast_router": live.get("fast_router_sha256"),
        "gate_script": sha256_file(
            os.path.join(os.path.dirname(__file__), "teacher_v1_gate.py")),
        "label_script": sha256_file(
            os.path.join(os.path.dirname(__file__), "teacher_v1_label.py")),
        "producer_receipt_script": sha256_file(
            os.path.join(os.path.dirname(__file__), "teacher_v1_receipt.py")),
        "teacher_contract": sha256_file(os.path.join(
            os.path.dirname(__file__), "../shengji/teacher_v1.py")),
    }
    for name, expected in current_unchanged_sources.items():
        if gate_sources.get(name) != expected:
            bad.append(f"Stage-B transition {name} source drift")
    if (diagnostic.get("fast_binary_sha256")
            != live.get("fast_binary_sha256")):
        bad.append("Stage-B transition compiled engine drift")
    if diagnostic.get("fast_router_sha256") != live.get("fast_router_sha256"):
        bad.append("Stage-B transition fast router drift")

    binding = None if bad else {
        "schema": "teacher-v1-stage-b-source-transition-v1",
        "transition_id": STAGE_B_SOURCE_TRANSITION_ID,
        "diagnostic_git": STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
        "stage_a_gate_git": STAGE_B_TRANSITION_GATE_GIT,
        "freezer_git": current_git,
        "state_set_sha256": state_set_sha256,
        "stage_a_gate_sha256": gate_sha256,
        "diagnostic_to_gate_paths": list(historical_paths),
        "gate_to_freezer_paths": list(freezer_paths),
        "historical_ancestry": historical_ancestry,
        "freezer_ancestry": freezer_ancestry,
        "frozen_state_script_sha256": old_state_source,
        "freezer_script_sha256": live.get("state_script_sha256"),
    }
    return sorted(set(bad)), binding


def write_exclusive(path: str, payload: dict) -> None:
    partial = path + ".partial"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(partial, "x", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    except FileExistsError as exc:
        raise TeacherProtocolError(
            f"refusing existing partial artifact {partial}; no resume or "
            "replacement"
        ) from exc
    try:
        # A hard link is the publication compare-and-swap: it succeeds only
        # when the final name does not exist, including when that name is a
        # dangling symlink.  Unlike os.replace, a competitor that wins after
        # the partial is opened can never have its bytes overwritten.
        os.link(partial, path)
    except FileExistsError as exc:
        raise TeacherProtocolError(
            f"refusing to overwrite {path}; completed partial remains at "
            f"{partial}"
        ) from exc
    try:
        os.unlink(partial)
    except OSError as exc:
        raise TeacherProtocolError(
            f"published {path} but could not remove partial {partial}"
        ) from exc


def runtime(smoke: bool) -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise TeacherProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise TeacherProtocolError("set SHENGJI_FAST=1")
    enabled = [name for name in EXPERIMENTAL_SAMPLER_BALLOT_FLAGS
               if name in os.environ]
    if enabled:
        raise TeacherProtocolError(
            f"experimental sampler/ballot flags must be unset: {enabled}"
        )
    python = sys.version.split()[0]
    if not smoke and python != CAPTURE_PYTHON:
        raise TeacherProtocolError(
            f"real teacher work requires Python {CAPTURE_PYTHON}, got {python}"
        )
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise TeacherProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty and not smoke:
        raise TeacherProtocolError("real teacher state work refuses a dirty tree")
    return {
        "git": git_output("rev-parse", "HEAD"), "tree_dirty": bool(dirty),
        "promotable": not smoke,
        "host": os.uname().nodename, "python": python,
        "fast_engine": True, "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "fast_router_sha256": sha256_file(fast.__file__),
        "fast_binary_sha256": sha256_file(fast._fast.__file__),
        "state_script_sha256": sha256_file(__file__),
    }


def actor_identity() -> dict:
    import shengji.ai.mcbot as mcbot
    import shengji.ai.memory as memory
    import shengji.ai.registry as registry
    import shengji.engine.round as round_mod
    import shengji.teacher_v1 as teacher
    bot = make_bot(ACTOR, seed=1)
    ballot = mc_ballot(bot)
    paths = {
        "mcbot": mcbot.__file__, "memory": memory.__file__,
        "registry": registry.__file__, "engine_round": round_mod.__file__,
        "teacher_replay": teacher.__file__,
    }
    source_digests = json_canonical({
        name: sha256_file(path) for name, path in sorted(paths.items())
    })
    ballot_identity = json_canonical({
        **asdict(ballot), "digest": ballot.digest,
    })
    return json_canonical({
        "policy": ACTOR,
        "identity": stable_digest({
            "files": source_digests,
            "ballot": ballot_identity,
        }),
        "source_digests": source_digests,
        "ballot": ballot_identity,
        "checkpoint": None,
    })


def target_for_deal(experiment_id: str, seed: int) -> dict:
    """Pre-play target, split and selector pool for one deal."""
    stream = derive_stream(
        experiment_id=experiment_id, deal_seed=seed,
        state_id=f"deal:{seed}", purpose="state_selection", fold="capture",
    )
    raw = hashlib.sha256(str(stream["seed"]).encode()).digest()
    phase = ("early", "mid", "late")[raw[0] % 3]
    if phase == "early":
        trick = raw[1] % 5
    elif phase == "mid":
        trick = 5 + raw[1] % 7
    else:
        trick = 12 + raw[1] % 8
    decision = "lead" if raw[2] % 2 == 0 else "follow"
    position = 0 if decision == "lead" else 1 + raw[3] % 3
    # 3/4 representative, 1/4 challenge: the same population proportions as
    # 1,536/512 in the full pilot and 48/16 in Stage A.
    pool = "representative" if raw[4] % 4 else "challenge"
    return {
        "stream": stream, "phase": phase, "trick": trick,
        "decision": decision, "position": position,
        "selector_pool": pool, "split": split_for_deal(experiment_id, seed),
    }


def load_exam_exclusion(paths: list[str]) -> tuple[set[int], dict]:
    seeds: set[int] = set()
    sources = []
    required = {os.path.realpath(path): digest
                for path, digest in DEFAULT_EXAM_SPLIT_SHA256.items()}
    observed_required = set()
    for path in paths:
        if not os.path.exists(path):
            raise TeacherProtocolError(f"missing exam split identity {path}")
        with open(path) as fh:
            payload = json.load(fh)
        digest = sha256_file(path)
        resolved = os.path.realpath(path)
        if resolved in required:
            observed_required.add(resolved)
            if digest != required[resolved]:
                raise TeacherProtocolError(
                    f"exam split digest drift for {path}: {digest}, expected "
                    f"{required[resolved]}")
        assigned = {int(seed) for seed in payload.get("assign", {})}
        seeds |= assigned
        sources.append({
            "path": path, "sha256": digest,
            "deals": len(assigned),
        })
    missing = sorted(path for path in required if path not in observed_required)
    if missing:
        raise TeacherProtocolError(
            f"required DEV/CALIB/REPORT split identities missing: {missing}")
    return seeds, {"verified": True, "overlap": 0, "sources": sources,
                   "excluded_deals": len(seeds)}


def _actual_packet(args) -> dict:
    return {
        "packet_id": args.packet_id,
        "seed0": args.seed0,
        "seed_end_inclusive": args.seed0 + args.max_deals - 1,
        "max_deals": args.max_deals,
        "shard_count": args.shard_count,
        "sharding": f"interleaved_seed_offset_mod_{args.shard_count}",
        "deals_per_shard": len(range(
            args.seed0 + args.shard_index,
            args.seed0 + args.max_deals,
            args.shard_count,
        )),
    }


def registered_capture_problems(payload: dict) -> list[str]:
    """Prove one capture artifact is one exact shard of the frozen packet."""
    bad = []
    if payload.get("schema") != CAPTURE_SCHEMA or not payload.get("complete"):
        bad.append("capture schema/completion")
    if payload.get("packet_id") != CAPTURE_PACKET_ID:
        bad.append("capture packet id")
    if payload.get("capture_packet") != capture_packet():
        bad.append("capture packet identity/range")
    if (payload.get("seed_start") != SEED_START
            or payload.get("seed0") != SEED_START
            or payload.get("max_deals") != CAPTURE_MAX_DEALS
            or payload.get("shard_count") != CAPTURE_SHARDS):
        bad.append("capture top-level packet identity/range")
    shard = payload.get("shard_index")
    if not isinstance(shard, int) or not 0 <= shard < CAPTURE_SHARDS:
        bad.append("capture shard index")
        return bad
    expected = capture_shard_seeds(shard)
    scanned = payload.get("scanned_seeds")
    if scanned != expected:
        bad.append(f"capture shard {shard} seed coverage")
    if payload.get("scanned_seeds_sha256") != stable_digest(expected):
        bad.append(f"capture shard {shard} seed digest")
    if payload.get("scanned_deals") != CAPTURE_DEALS_PER_SHARD:
        bad.append(f"capture shard {shard} deal count")
    records = payload.get("records", [])
    if payload.get("records_digest") != stable_digest(records):
        bad.append(f"capture shard {shard} record digest")
    if payload.get("n_records") != len(records):
        bad.append(f"capture shard {shard} record count")
    reached = [row.get("seed") for row in records]
    unreachable = payload.get("unreachable_seeds")
    if not isinstance(unreachable, list):
        bad.append(f"capture shard {shard} unreachable identities")
        unreachable = []
    if payload.get("unreachable_targets") != len(unreachable):
        bad.append(f"capture shard {shard} unreachable count")
    if (len(reached) != len(set(reached))
            or set(reached) & set(unreachable)
            or sorted(reached + unreachable) != expected):
        bad.append(f"capture shard {shard} processed-seed partition")
    for row in records:
        if row.get("packet_id") != CAPTURE_PACKET_ID:
            bad.append(f"capture shard {shard} row packet id")
            break
    if (payload.get("promotable") is not True or payload.get("tree_dirty")
            or not payload.get("fast_engine")
            or not payload.get("require_voids")):
        bad.append(f"capture shard {shard} runtime is not evidence-grade")
    exclusion = payload.get("exam_exclusion", {})
    if (not exclusion.get("verified") or exclusion.get("overlap") != 0
            or len(exclusion.get("sources", [])) != len(DEFAULT_EXAM_SPLITS)):
        bad.append(f"capture shard {shard} exam exclusion")
    actor = payload.get("actor", {})
    if actor.get("policy") != ACTOR or not actor.get("identity"):
        bad.append(f"capture shard {shard} actor identity")
    return sorted(set(bad))


def registered_diagnostic_problems(payload: dict) -> list[str]:
    """Prove a selector artifact is the exact child of one capture shard."""
    bad = []
    if payload.get("schema") != DIAGNOSTIC_SCHEMA or not payload.get("complete"):
        bad.append("diagnostic schema/completion")
    if payload.get("packet_id") != CAPTURE_PACKET_ID:
        bad.append("diagnostic packet id")
    if payload.get("capture_packet") != capture_packet():
        bad.append("diagnostic packet identity/range")
    shard = payload.get("capture_shard_index")
    if not isinstance(shard, int) or not 0 <= shard < CAPTURE_SHARDS:
        bad.append("diagnostic capture shard index")
        return bad
    expected = capture_shard_seeds(shard)
    if payload.get("capture_scanned_seeds") != expected:
        bad.append(f"diagnostic shard {shard} capture coverage")
    if payload.get("capture_scanned_seeds_sha256") != stable_digest(expected):
        bad.append(f"diagnostic shard {shard} capture coverage digest")
    parent_sha = payload.get("capture_input_sha256")
    if (not is_sha256(parent_sha)
            or payload.get("input_sha256") != parent_sha):
        bad.append(f"diagnostic shard {shard} exact parent hash")
    records = payload.get("records", [])
    if payload.get("records_digest") != stable_digest(records):
        bad.append(f"diagnostic shard {shard} record digest")
    if payload.get("n_records") != len(records):
        bad.append(f"diagnostic shard {shard} record count")
    state_ids = [row.get("state_id") for row in records]
    if (payload.get("diagnosed_state_ids") != state_ids
            or payload.get("diagnosed_state_ids_sha256")
            != stable_digest(state_ids)):
        bad.append(f"diagnostic shard {shard} state coverage")
    reached = [row.get("state", {}).get("seed") for row in records]
    unreachable = payload.get("capture_unreachable_seeds", [])
    if (len(reached) != len(set(reached))
            or set(reached) & set(unreachable)
            or sorted(reached + unreachable) != expected):
        bad.append(f"diagnostic shard {shard} processed-seed partition")
    if any(row.get("state", {}).get("packet_id") != CAPTURE_PACKET_ID
           for row in records):
        bad.append(f"diagnostic shard {shard} row packet id")
    if (payload.get("promotable") is not True or payload.get("tree_dirty")
            or not payload.get("fast_engine")
            or not payload.get("require_voids")):
        bad.append(f"diagnostic shard {shard} runtime is not evidence-grade")
    exclusion = payload.get("exam_exclusion", {})
    if (not exclusion.get("verified") or exclusion.get("overlap") != 0
            or len(exclusion.get("sources", [])) != len(DEFAULT_EXAM_SPLITS)):
        bad.append(f"diagnostic shard {shard} exam exclusion")
    actor = payload.get("actor", {})
    if actor.get("policy") != ACTOR or not actor.get("identity"):
        bad.append(f"diagnostic shard {shard} actor identity")
    if payload.get("selector_worlds") != SELECTOR_WORLDS:
        bad.append(f"diagnostic shard {shard} selector dose")
    return sorted(set(bad))


def diagnostic_population_problems(manifests: list[dict]) -> tuple[list[str], dict]:
    """Validate all and only the eight children of the entry capture packet."""
    bad = []
    if len(manifests) != CAPTURE_SHARDS:
        bad.append(f"diagnostic shard count {len(manifests)}, required {CAPTURE_SHARDS}")
    for index, payload in enumerate(manifests):
        bad += [f"input {index}: {problem}"
                for problem in registered_diagnostic_problems(payload)]
    indices = [payload.get("capture_shard_index") for payload in manifests]
    if (not all(isinstance(value, int) for value in indices)
            or sorted(indices) != list(range(CAPTURE_SHARDS))):
        bad.append(f"diagnostic shard identities {indices}")
    parent_hashes = [payload.get("capture_input_sha256") for payload in manifests]
    if len(parent_hashes) != len(set(parent_hashes)):
        bad.append("repeated capture parent artifact")
    if manifests:
        first = manifests[0]
        for index, payload in enumerate(manifests[1:], 1):
            for key in (
                "packet_id", "capture_packet", "git", "actor",
                "exam_exclusion", "selector_worlds", "selector_policy",
                "v11_checkpoint_sha256", "python", "fast_binary_sha256",
                "fast_router_sha256", "state_script_sha256",
            ):
                if payload.get(key) != first.get(key):
                    bad.append(f"diagnostic {index}: conflicting {key}")
    scanned = [seed for payload in manifests
               for seed in payload.get("capture_scanned_seeds", [])]
    expected = list(range(SEED_START, CAPTURE_SEED_END + 1))
    if len(scanned) != len(set(scanned)) or sorted(scanned) != expected:
        bad.append(
            "diagnostic population is not exact/nonoverlapping entry coverage"
        )
    coverage = {
        **capture_coverage(),
        "capture_parent_sha256": {
            str(payload.get("capture_shard_index")): payload.get("capture_input_sha256")
            for payload in manifests
        },
        "diagnostic_records_sha256": {
            str(payload.get("capture_shard_index")): payload.get("records_digest")
            for payload in manifests
        },
    }
    return sorted(set(bad)), coverage


def state_set_packet_problems(payload: dict) -> list[str]:
    """Reject a state set whose provenance is only plausible-looking metadata."""
    bad = []
    if payload.get("packet_id") != CAPTURE_PACKET_ID:
        bad.append("state-set capture packet id")
    if payload.get("capture_packet") != capture_packet():
        bad.append("state-set capture packet identity/range")
    coverage = payload.get("capture_coverage", {})
    registered = capture_coverage()
    for key, value in registered.items():
        if coverage.get(key) != value:
            bad.append(f"state-set capture coverage {key}")
    inputs = payload.get("diagnostic_inputs", [])
    if len(inputs) != CAPTURE_SHARDS:
        bad.append(f"state-set diagnostic inputs {len(inputs)}, required 8")
    indices = [item.get("capture_shard_index") for item in inputs
               if isinstance(item, dict)]
    if (len(indices) != CAPTURE_SHARDS
            or not all(isinstance(index, int) for index in indices)
            or sorted(indices) != list(range(CAPTURE_SHARDS))):
        bad.append("state-set diagnostic shard identities")
    diagnostic_hashes = [item.get("sha256") for item in inputs
                         if isinstance(item, dict)]
    if (len(diagnostic_hashes) != CAPTURE_SHARDS
            or len(set(diagnostic_hashes)) != CAPTURE_SHARDS
            or any(not is_sha256(value) for value in diagnostic_hashes)):
        bad.append("state-set diagnostic artifact hashes")
    parent_map = coverage.get("capture_parent_sha256", {})
    diagnostic_map = coverage.get("diagnostic_records_sha256", {})
    expected_keys = {str(index) for index in range(CAPTURE_SHARDS)}
    for name, values in (
        ("capture-parent", parent_map),
        ("diagnostic-record", diagnostic_map),
    ):
        if (not isinstance(values, dict) or set(values) != expected_keys
                or any(not is_sha256(value) for value in values.values())):
            bad.append(f"state-set {name} coverage map")
    for item in inputs:
        if not isinstance(item, dict):
            continue
        index = item.get("capture_shard_index")
        if parent_map.get(str(index)) != item.get("capture_parent_sha256"):
            bad.append("state-set capture-parent binding")
        if diagnostic_map.get(str(index)) != item.get(
                "diagnostic_records_sha256"):
            bad.append("state-set diagnostic-record binding")
    if (payload.get("promotable") is not True or payload.get("tree_dirty")
            or not payload.get("fast_engine")
            or not payload.get("require_voids")):
        bad.append("state-set runtime is not evidence-grade")
    states = payload.get("states", [])
    if payload.get("states_digest") != stable_digest(states):
        bad.append("state-set states digest")
    transition = payload.get("source_transition")
    transition_required = (
        payload.get("stage") == "b"
        and (payload.get("excluded_stage_a") or {}).get("sha256")
        == STAGE_B_TRANSITION_STATE_SHA256
        and (payload.get("stage_a_gate") or {}).get("sha256")
        == STAGE_B_TRANSITION_GATE_SHA256
    )
    if transition_required and not isinstance(transition, dict):
        bad.append("state-set Stage-B source transition missing")
    if transition is not None:
        expected = {
            "schema": "teacher-v1-stage-b-source-transition-v1",
            "transition_id": STAGE_B_SOURCE_TRANSITION_ID,
            "diagnostic_git": STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
            "stage_a_gate_git": STAGE_B_TRANSITION_GATE_GIT,
            "state_set_sha256": STAGE_B_TRANSITION_STATE_SHA256,
            "stage_a_gate_sha256": STAGE_B_TRANSITION_GATE_SHA256,
            "diagnostic_to_gate_paths": list(
                STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS),
            "gate_to_freezer_paths": list(
                STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS),
            "historical_ancestry": True,
            "freezer_ancestry": True,
        }
        if (not isinstance(transition, dict)
                or any(transition.get(key) != value
                       for key, value in expected.items())
                or transition.get("freezer_git") != payload.get("git")
                or transition.get("freezer_script_sha256")
                != payload.get("state_script_sha256")
                or transition.get("state_set_sha256")
                != (payload.get("excluded_stage_a") or {}).get("sha256")
                or transition.get("stage_a_gate_sha256")
                != (payload.get("stage_a_gate") or {}).get("sha256")
                or not is_sha256(
                    transition.get("frozen_state_script_sha256"))):
            bad.append("state-set Stage-B source transition binding")
    return sorted(set(bad))


def _all_bot_counters(policies) -> dict[str, int]:
    return {name: sum(int(getattr(bot, name, 0)) for bot in policies)
            for name in SAMPLER_COUNTERS}


def _clean_actor_counters(counters: dict) -> list[str]:
    bad = []
    if counters["sample_attempts"] != (
        counters["accepted_worlds"] + counters["failed_worlds"]
    ):
        bad.append("actor sampler attempts do not reconcile")
    forbidden = {name: counters[name] for name in (
        "failed_worlds", "rejected_worlds", "impossible_worlds",
        "short_search_decisions", "zero_world_decisions",
    ) if counters[name]}
    if forbidden:
        bad.append(f"actor strict counters {forbidden}")
    return bad


def capture_deal(seed: int, target: dict, actor: dict,
                 packet_id: str = CAPTURE_PACKET_ID) -> dict | None:
    game = Game(random.Random(seed))
    rnd = game.start_round()
    policies = []
    actor_seeds = []
    for seat in range(4):
        stream = derive_stream(
            experiment_id=EXPERIMENT, deal_seed=seed,
            state_id=f"deal:{seed}", purpose="actor", fold="self_play",
            seat=seat, policy=ACTOR,
        )
        actor_seeds.append(stream)
        policies.append(make_bot(ACTOR, seed=stream["seed"]))
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = policies[rnd.banker].decide_bury(rnd, rnd.banker)
    final_decl = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"], "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    setup = {
        "deck": list(rnd.deck), "initial_banker": None,
        "trump_rank": rnd.trump_rank, "banker": rnd.banker,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations, "final_declaration": final_decl,
        "buried": list(buried),
    }
    rnd.bury(rnd.banker, buried)
    plays = []
    while rnd.phase == "play":
        if (len(rnd.history) == target["trick"] and rnd.trick is not None
                and len(rnd.trick.plays) == target["position"]):
            counters = _all_bot_counters(policies)
            bad = _clean_actor_counters(counters)
            if bad:
                raise TeacherProtocolError(f"seed {seed}: {'; '.join(bad)}")
            seat = rnd.turn
            assert seat is not None
            role = "attacker" if rnd.is_attacker(seat) else "defender"
            row = {
                "schema": STATE_SCHEMA, "experiment_id": EXPERIMENT,
                "packet_id": packet_id,
                "seed": seed, "seat": seat, "ply": len(plays),
                "trick": len(rnd.history), "phase": phase_for_trick(len(rnd.history)),
                "decision": "lead" if not rnd.trick.plays else "follow",
                "role": role, "split": target["split"],
                "selector_pool": target["selector_pool"],
                "selection_stream": target["stream"],
                "target_position": target["position"],
                "actor_seeds": actor_seeds, "actor_identity": actor["identity"],
                "actor_counters": counters, "setup": setup, "plays": plays,
            }
            row["state_id"] = state_id(row)
            # The target is fixed before play; a mismatch means the event loop
            # reached a different estimand and must not be silently accepted.
            if row["phase"] != target["phase"] or row["decision"] != target["decision"]:
                raise TeacherProtocolError(f"seed {seed}: target stratum drift")
            # Selection probability is assigned only when the finite reservoir
            # is frozen; a raw capture is not yet an admitted training row.
            replay_state({**row, "selection_probability": 1.0, "kind": "raw"})
            return row
        seat = rnd.turn
        assert seat is not None
        cards = policies[seat].decide_play(rnd, seat)
        rnd.play(seat, list(cards))
        plays.append({"seat": seat, "cards": list(cards)})
        bad = _clean_actor_counters(_all_bot_counters(policies))
        if bad:
            raise TeacherProtocolError(f"seed {seed}: {'; '.join(bad)}")
    return None


def capture(args) -> None:
    live = runtime(args.smoke)
    actor = actor_identity()
    exam, exclusion = load_exam_exclusion(args.exam_split)
    if not args.smoke and (
        args.packet_id != CAPTURE_PACKET_ID or args.seed0 != SEED_START
        or args.max_deals != CAPTURE_MAX_DEALS
        or args.shard_count != CAPTURE_SHARDS
    ):
        raise TeacherProtocolError(
            f"real capture requires packet {CAPTURE_PACKET_ID}, seed0 "
            f"{SEED_START}, max_deals {CAPTURE_MAX_DEALS}, "
            f"shard_count {CAPTURE_SHARDS}"
        )
    if args.seed0 < SEED_START:
        raise TeacherProtocolError(f"seed0 must be at least {SEED_START}")
    if not 0 <= args.shard_index < args.shard_count:
        raise TeacherProtocolError("invalid shard index/count")
    records, unreachable_seeds = [], []
    scanned = list(range(
        args.seed0 + args.shard_index,
        args.seed0 + args.max_deals,
        args.shard_count,
    ))
    for index, seed in enumerate(scanned, 1):
        if seed in exam:
            exclusion["overlap"] += 1
            raise TeacherProtocolError(f"fresh seed {seed} overlaps an exam deal")
        row = capture_deal(
            seed, target_for_deal(EXPERIMENT, seed), actor, args.packet_id
        )
        if row is None:
            unreachable_seeds.append(seed)
        else:
            records.append(row)
        if index % 25 == 0:
            print(f"  {index}/{len(scanned)} deals, {len(records)} states", flush=True)
    payload = {
        "schema": CAPTURE_SCHEMA, "experiment_id": EXPERIMENT, **live,
        "packet_id": args.packet_id, "capture_packet": _actual_packet(args),
        "seed_start": SEED_START, "seed0": args.seed0,
        "max_deals": args.max_deals, "shard_index": args.shard_index,
        "shard_count": args.shard_count, "actor": actor,
        "exam_exclusion": exclusion, "one_state_per_deal": True,
        "target_rule": "named hash -> phase/trick/position/pool before play",
        "complete": True, "scanned_deals": len(scanned),
        "scanned_seeds": scanned,
        "scanned_seeds_sha256": stable_digest(scanned),
        "unreachable_targets": len(unreachable_seeds),
        "unreachable_seeds": unreachable_seeds,
        "n_records": len(records),
        "records": records, "records_digest": stable_digest(records),
    }
    if not args.smoke:
        violations = registered_capture_problems(payload)
        if violations:
            raise TeacherProtocolError(
                "capture completion contract: " + "; ".join(violations)
            )
    write_exclusive(args.out, payload)
    print(f"wrote {args.out}: {len(records)} fresh replay states", flush=True)


def _paired_se(diffs: list[float]) -> float:
    if len(diffs) < 2:
        return float("inf")
    mean = sum(diffs) / len(diffs)
    variance = sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)
    return math.sqrt(variance / len(diffs))


def diagnose_row(row: dict, bot, v11) -> dict:
    state = {**row, "selection_probability": 1.0, "kind": "raw"}
    rnd = replay_state(state)
    seat = state["seat"]
    candidates = [list(action_key(action)) for action in bot._candidates(rnd, seat)]
    bad = ballot_problems(rnd, seat, candidates)
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    stream = derive_stream(
        experiment_id=EXPERIMENT, deal_seed=state["seed"],
        state_id=state["state_id"], purpose="belief", fold="selector_n30",
    )
    original_rng = bot.rng
    before = sampler_snapshot(bot)
    values = []
    try:
        bot.rng = random.Random(stream["seed"])
        mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
        for world_index in range(SELECTOR_WORLDS):
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                raise TeacherProtocolError(
                    f"{state['state_id']}: selector world {world_index} rejected"
                )
            hands, buried = sampled
            sign = 1 if rnd.is_attacker(seat) else -1
            values.append([
                sign * bot._score(bot._rollout(rnd, seat, hands, buried, candidate))
                for candidate in candidates
            ])
    finally:
        bot.rng = original_rng
    counters = sampler_delta(before, bot)
    bad = _clean_actor_counters(counters)
    if counters["accepted_worlds"] != SELECTOR_WORLDS:
        bad.append("selector did not accept exactly 30 worlds")
    if bad:
        raise TeacherProtocolError(f"{state['state_id']}: {'; '.join(bad)}")
    means = [sum(row_[i] for row_ in values) / len(values)
             for i in range(len(candidates))]
    best = bot._pick_index(candidates, means, list(range(len(candidates))))
    gap = means[best] - means[0]
    picked = best if best != 0 and gap >= bot.MARGIN else 0
    diffs = [row_[best] - row_[0] for row_ in values]

    v11_seed = derive_stream(
        experiment_id=EXPERIMENT, deal_seed=state["seed"],
        state_id=state["state_id"], purpose="selector_policy",
        fold="v11pair", policy="rl-override-v11pair",
    )
    # A new seeded policy per state makes inference order irrelevant.  The net
    # is deterministic today; the seed still binds a future stochastic edit.
    v11 = make_bot("rl-override-v11pair", seed=v11_seed["seed"])
    v11_action = list(action_key(v11.decide_play(rnd, seat)))
    if v11_action not in candidates:
        raise TeacherProtocolError(
            f"{state['state_id']}: v11 action is outside current ballot"
        )
    smart_action = candidates[0]
    n30_action = candidates[picked]
    return {
        "state": row, "state_id": state["state_id"],
        "selector_stream": stream, "selector_counters": counters,
        "candidates": candidates, "means": means,
        "best_index": best, "n30_index": picked,
        "gap": gap, "gap_se": _paired_se(diffs),
        "smart_action": smart_action, "n30_action": n30_action,
        "v11_action": v11_action, "v11_stream": v11_seed,
        "disagreement": len({action_key(smart_action), action_key(n30_action),
                             action_key(v11_action)}) > 1,
    }


def diagnose(args) -> None:
    live = runtime(args.smoke)
    if sha256_file(args.input) != args.expected_input_sha256:
        raise TeacherProtocolError("capture input digest mismatch")
    with open(args.input) as fh:
        capture_payload = json.load(fh)
    if capture_payload.get("schema") != CAPTURE_SCHEMA \
            or not capture_payload.get("complete"):
        raise TeacherProtocolError("input is not a complete capture shard")
    if not args.smoke:
        violations = registered_capture_problems(capture_payload)
        if violations:
            raise TeacherProtocolError(
                "capture packet contract: " + "; ".join(violations)
            )
    if (not args.smoke and (capture_payload.get("tree_dirty")
                            or not capture_payload.get("promotable"))):
        raise TeacherProtocolError(
            "real selector diagnostics refuse dirty/non-promotable capture")
    for key in ("git", "python", "fast_binary_sha256",
                "fast_router_sha256", "state_script_sha256"):
        if capture_payload.get(key) != live.get(key):
            raise TeacherProtocolError(f"capture/diagnostic {key} drift")
    stored_actor = capture_payload.get("actor", {})
    live_actor = actor_identity()
    if stored_actor != live_actor:
        raise TeacherProtocolError("capture actor identity drift")
    bot = make_bot("mc-strong", seed=1)
    rows = capture_payload.get("records", [])
    diagnostics = []
    for index, row in enumerate(rows, 1):
        diagnostics.append(diagnose_row(row, bot, None))
        if index % 25 == 0:
            print(f"  {index}/{len(rows)} selector diagnostics", flush=True)
    v11_path = "snapshots_v11pair/ep07.npz"
    v11_digest = sha256_file(v11_path)
    if v11_digest != V11_CHECKPOINT_SHA256:
        raise TeacherProtocolError(
            f"frozen v11 selector checkpoint {v11_digest}, expected "
            f"{V11_CHECKPOINT_SHA256}")
    payload = {
        "schema": DIAGNOSTIC_SCHEMA, "experiment_id": EXPERIMENT, **live,
        "packet_id": capture_payload.get("packet_id"),
        "capture_packet": capture_payload.get("capture_packet"),
        "capture_shard_index": capture_payload.get("shard_index"),
        "capture_scanned_seeds": capture_payload.get("scanned_seeds"),
        "capture_scanned_seeds_sha256": capture_payload.get(
            "scanned_seeds_sha256"),
        "capture_unreachable_seeds": capture_payload.get(
            "unreachable_seeds", []),
        "capture_input_sha256": args.expected_input_sha256,
        "input": args.input, "input_sha256": args.expected_input_sha256,
        "actor": capture_payload["actor"],
        "exam_exclusion": capture_payload["exam_exclusion"],
        "one_state_per_deal": True, "selector_worlds": SELECTOR_WORLDS,
        "selector_policy": "current mc-strong N=30 raw-point objective",
        "v11_policy": "rl-override-v11pair@0.02",
        "v11_checkpoint": v11_path,
        "v11_checkpoint_sha256": v11_digest,
        "complete": True, "n_records": len(diagnostics),
        "diagnosed_state_ids": [row["state_id"] for row in diagnostics],
        "diagnosed_state_ids_sha256": stable_digest(
            [row["state_id"] for row in diagnostics]),
        "records": diagnostics, "records_digest": stable_digest(diagnostics),
    }
    if not args.smoke:
        violations = registered_diagnostic_problems(payload)
        if violations:
            raise TeacherProtocolError(
                "diagnostic completion contract: " + "; ".join(violations)
            )
    write_exclusive(args.out, payload)
    print(f"wrote {args.out}: {len(diagnostics)} selector diagnostics", flush=True)


def selection_priority(stage: str, kind: str, row: dict) -> str:
    return hashlib.sha256(
        f"{EXPERIMENT}|{stage}|{kind}|{row['state_id']}".encode()
    ).hexdigest()


def _selected_state(diag: dict, kind: str, probability: float, *,
                    design: str, eligible: int, selected: int,
                    rank: int, deployment_weightable: bool) -> dict:
    state = dict(diag["state"])
    state["kind"] = kind
    state["selection_probability"] = probability
    state["selection_metadata"] = {
        "design": design, "eligible": eligible, "selected": selected,
        "rank": rank, "deployment_weightable": deployment_weightable,
    }
    return state


def select_gate_states(diagnostics: list[dict], stage: str,
                       excluded_deals: set[int]) -> tuple[list[dict], list[str]]:
    rep_q = (STAGE_A_REPRESENTATIVE_PER_CELL if stage == "a"
             else STAGE_B_REPRESENTATIVE_PER_CELL)
    boundary_q = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                  else STAGE_B_BOUNDARY_STATES)
    uncertainty_q = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                     else STAGE_B_UNCERTAINTY_STATES)
    problems = []
    eligible = [diag for diag in diagnostics
                if diag["state"]["seed"] not in excluded_deals]
    by_cell = defaultdict(list)
    for diag in eligible:
        state = diag["state"]
        if state["selector_pool"] == "representative":
            by_cell[(state["phase"], state["role"], state["decision"])].append(diag)
    selected, used = [], set()
    for cell in REPRESENTATIVE_CELLS:
        rows = sorted(by_cell[cell], key=lambda row: selection_priority(stage, "rep", row))
        if len(rows) < rep_q:
            problems.append(f"representative {cell}: {len(rows)} available, need {rep_q}")
            continue
        probability = rep_q / len(rows)
        for rank, diag in enumerate(rows[:rep_q], 1):
            selected.append(_selected_state(
                diag, "representative", probability,
                design="hash_reservoir_within_stratum", eligible=len(rows),
                selected=rep_q, rank=rank, deployment_weightable=True))
            used.add(diag["state_id"])

    challenge = [diag for diag in eligible
                 if diag["state"]["selector_pool"] == "challenge"
                 and diag["state_id"] not in used]
    boundary = sorted(
        challenge,
        key=lambda row: (abs(row["gap"] - 5.0),
                         selection_priority(stage, "boundary", row)),
    )
    if len(boundary) < boundary_q:
        problems.append(f"boundary supply {len(boundary)}, need {boundary_q}")
    boundary = boundary[:boundary_q]
    boundary_ids = {row["state_id"] for row in boundary}
    # These are deterministic challenge ranks, not a probability sample from
    # deployment.  Record conditional inclusion as 1 and explicitly forbid
    # inverse-probability use; q/N here would be a plausible-looking lie.
    selected += [_selected_state(
        row, "boundary", 1.0,
        design="deterministic_closest_to_margin", eligible=len(challenge),
        selected=boundary_q, rank=rank, deployment_weightable=False)
        for rank, row in enumerate(boundary, 1)]

    remaining = [row for row in challenge if row["state_id"] not in boundary_ids]
    disagree = sorted(
        [row for row in remaining if row["disagreement"]],
        key=lambda row: (-row["gap_se"],
                         selection_priority(stage, "uncertainty", row)),
    )
    fallback = sorted(
        [row for row in remaining if not row["disagreement"]],
        key=lambda row: (-row["gap_se"],
                         selection_priority(stage, "uncertainty-fill", row)),
    )
    uncertainty = (disagree + fallback)[:uncertainty_q]
    if len(uncertainty) < uncertainty_q:
        problems.append(f"uncertainty supply {len(uncertainty)}, need {uncertainty_q}")
    selected += [_selected_state(
        row, "uncertainty", 1.0,
        design="deterministic_disagreement_then_se", eligible=len(remaining),
        selected=uncertainty_q, rank=rank, deployment_weightable=False)
        for rank, row in enumerate(uncertainty, 1)]
    selected.sort(key=lambda state: selection_priority(
        stage, state["kind"], {"state_id": state["state_id"]}
    ))
    return selected, problems


def stage_a_exclusion_problems(payload: dict, diagnostic: dict,
                               diagnostic_sha256s: set[str]) -> list[str]:
    """Validate the exact Stage-A asset whose deals Stage B will exclude."""
    bad = []
    bad += state_set_packet_problems(payload)
    if payload.get("schema") != STATE_SET_SCHEMA:
        bad.append("excluded Stage-A set schema")
    if payload.get("experiment_id") != EXPERIMENT:
        bad.append("excluded Stage-A experiment")
    if payload.get("stage") != "a":
        bad.append("excluded state set is not Stage A")
    if not payload.get("complete"):
        bad.append("excluded Stage-A set is incomplete")
    states = payload.get("states", [])
    if payload.get("states_digest") != stable_digest(states):
        bad.append("excluded Stage-A states digest")
    if (payload.get("requested") != STAGE_A_STATES
            or payload.get("selected") != STAGE_A_STATES
            or len(states) != STAGE_A_STATES):
        bad.append(
            f"excluded Stage-A count {len(states)}, required {STAGE_A_STATES}")
    ids = [state.get("state_id") for state in states]
    deals = [state.get("seed") for state in states]
    if len(ids) != len(set(ids)) or len(deals) != len(set(deals)):
        bad.append("excluded Stage-A set duplicates a state/deal")

    for key in ("git", "actor", "exam_exclusion", "python",
                "fast_binary_sha256", "fast_router_sha256",
                "state_script_sha256"):
        if payload.get(key) != diagnostic.get(key):
            bad.append(f"excluded Stage-A {key} drift")
    if (payload.get("tree_dirty") or not payload.get("promotable")
            or not payload.get("fast_engine")
            or not payload.get("require_voids")):
        bad.append("excluded Stage-A runtime is not clean/compiled/strict")
    stored_inputs = {
        item.get("sha256") for item in payload.get("diagnostic_inputs", [])
        if isinstance(item, dict)
    }
    if stored_inputs != diagnostic_sha256s:
        bad.append("excluded Stage-A diagnostic population drift")

    representative = Counter(
        (state.get("phase"), state.get("role"), state.get("decision"))
        for state in states if state.get("kind") == "representative"
    )
    for cell in REPRESENTATIVE_CELLS:
        if representative[cell] != STAGE_A_REPRESENTATIVE_PER_CELL:
            bad.append(f"excluded Stage-A representative {cell}")
    for kind in ("boundary", "uncertainty"):
        if sum(state.get("kind") == kind for state in states) != \
                STAGE_A_OTHER_STATES // 2:
            bad.append(f"excluded Stage-A {kind} composition")
    return sorted(set(bad))


def stage_a_gate_problems(payload: dict, state_set_sha256: str,
                          state_set: dict | None = None, *,
                          runtime_identity: dict | None = None,
                          verify_artifacts: bool = False,
                          source_transition: dict | None = None) -> list[str]:
    """Recompute enough of Stage A that a plausible PASS JSON is insufficient."""
    bad = []
    if payload.get("schema") != GATE_SCHEMA:
        bad.append("Stage-A gate schema")
    if payload.get("complete") is not True:
        bad.append("Stage-A gate is incomplete")
    if payload.get("experiment_id") != EXPERIMENT or payload.get("stage") != "A":
        bad.append("Stage-A gate identity")
    if (payload.get("verdict") != "PASS"
            or payload.get("stage_b_authorized") is not True
            or payload.get("problems")):
        bad.append("Stage-A mechanics gate did not pass")
    if (not is_sha256(state_set_sha256)
            or payload.get("state_input_sha256") != state_set_sha256):
        bad.append("Stage-A gate is not bound to the excluded state set")
    if ((payload.get("state_set") or {}).get("sha256") != state_set_sha256):
        bad.append("Stage-A gate exact state-set artifact binding")
    if payload.get("n_states") != STAGE_A_STATES:
        bad.append(f"Stage-A gate states {payload.get('n_states')}, required 64")
    artifact_sets = {}
    for field in ("inputs", "reruns"):
        artifacts = payload.get(field, [])
        indices = [item.get("shard_index") for item in artifacts
                   if isinstance(item, dict)]
        hashes = [item.get("sha256") for item in artifacts
                  if isinstance(item, dict)]
        if (len(artifacts) != CAPTURE_SHARDS
                or len(indices) != CAPTURE_SHARDS
                or not all(isinstance(index, int) for index in indices)
                or sorted(indices) != list(range(CAPTURE_SHARDS))):
            bad.append(f"Stage-A gate {field} shard population")
        if (len(hashes) != CAPTURE_SHARDS
                or len(set(hashes)) != CAPTURE_SHARDS
                or any(not is_sha256(value) for value in hashes)):
            bad.append(f"Stage-A gate {field} artifact hashes")
        artifact_sets[field] = set(hashes)
    if artifact_sets.get("inputs", set()) & artifact_sets.get("reruns", set()):
        bad.append("Stage-A gate primary/rerun artifact identity overlap")
    primary_run = payload.get("primary_producer_run_id")
    rerun_run = payload.get("rerun_producer_run_id")
    if not is_run_id(primary_run) or not is_run_id(rerun_run):
        bad.append("Stage-A gate producer run identities")
    elif primary_run == rerun_run:
        bad.append("Stage-A gate primary/rerun producer identity reused")
    primary_receipt = payload.get("primary_producer_receipt", {})
    rerun_receipt = payload.get("rerun_producer_receipt", {})
    if (not isinstance(primary_receipt, dict)
            or primary_receipt.get("role") != "stage-a-primary"
            or primary_receipt.get("run_id") != primary_run
            or not is_sha256(primary_receipt.get("sha256"))
            or not is_sha256(primary_receipt.get("nonce"))):
        bad.append("Stage-A gate primary producer receipt")
    if (not isinstance(rerun_receipt, dict)
            or rerun_receipt.get("role") != "stage-a-rerun"
            or rerun_receipt.get("run_id") != rerun_run
            or not is_sha256(rerun_receipt.get("sha256"))
            or not is_sha256(rerun_receipt.get("nonce"))):
        bad.append("Stage-A gate rerun producer receipt")
    if (primary_receipt.get("sha256") == rerun_receipt.get("sha256")
            or primary_receipt.get("nonce") == rerun_receipt.get("nonce")):
        bad.append("Stage-A gate primary/rerun producer receipt reused")
    if payload.get("packet_id") != CAPTURE_PACKET_ID:
        bad.append("Stage-A gate capture packet id")
    if payload.get("capture_packet") != capture_packet():
        bad.append("Stage-A gate capture packet identity/range")
    coverage = payload.get("capture_coverage", {})
    for key, value in capture_coverage().items():
        if coverage.get(key) != value:
            bad.append(f"Stage-A gate capture coverage {key}")
    for key in ("capture_parent_sha256", "diagnostic_records_sha256"):
        values = coverage.get(key, {})
        if (not isinstance(values, dict)
                or set(values) != {str(index) for index in range(CAPTURE_SHARDS)}
                or any(not is_sha256(value) for value in values.values())):
            bad.append(f"Stage-A gate capture coverage {key}")
    if state_set is not None and coverage != state_set.get("capture_coverage"):
        bad.append("Stage-A gate capture coverage differs from excluded state set")

    sources = payload.get("gate_source_digests", {})
    source_names = {
        "compiled_engine", "fast_router", "gate_script", "label_script",
        "producer_receipt_script", "state_script", "teacher_contract",
    }
    if (not isinstance(sources, dict) or set(sources) != source_names
            or any(not is_sha256(value) for value in sources.values())):
        bad.append("Stage-A gate executable source provenance")
    if (payload.get("tree_dirty") or payload.get("promotable") is not True
            or not payload.get("fast_engine")
            or not payload.get("require_voids")
            or not isinstance(payload.get("git"), str)
            or not isinstance(payload.get("python"), str)):
        bad.append("Stage-A gate runtime is not clean/compiled/strict")

    if runtime_identity is not None:
        runtime_keys = ("python", "fast_engine", "require_voids") \
            if source_transition is not None else \
            ("git", "python", "fast_engine", "require_voids")
        for key in runtime_keys:
            if payload.get(key) != runtime_identity.get(key):
                bad.append(f"Stage-A gate/current {key} drift")
        expected_sources = {
            "compiled_engine": runtime_identity.get("fast_binary_sha256"),
            "fast_router": runtime_identity.get("fast_router_sha256"),
            "state_script": runtime_identity.get("state_script_sha256"),
            "gate_script": sha256_file(
                os.path.join(os.path.dirname(__file__), "teacher_v1_gate.py")),
            "label_script": sha256_file(
                os.path.join(os.path.dirname(__file__), "teacher_v1_label.py")),
            "producer_receipt_script": sha256_file(
                os.path.join(os.path.dirname(__file__),
                             "teacher_v1_receipt.py")),
            "teacher_contract": sha256_file(
                os.path.join(os.path.dirname(__file__), "../shengji/teacher_v1.py")),
        }
        if source_transition is not None:
            for name, expected in expected_sources.items():
                if name != "state_script" and sources.get(name) != expected:
                    bad.append(
                        f"Stage-A gate/current {name} source drift")
        elif sources != expected_sources:
            bad.append("Stage-A gate/current executable source drift")

    if verify_artifacts:
        if state_set is None:
            bad.append("Stage-A artifact verification requires the exact state set")
        else:
            try:
                import teacher_v1_gate as gate_validator
            except ImportError as exc:
                bad.append(f"Stage-A gate validator import: {exc}")
            else:
                loaded = {}
                for field in ("inputs", "reruns"):
                    artifacts = payload.get(field, [])
                    paths = [item.get("path") for item in artifacts
                             if isinstance(item, dict)]
                    if (len(paths) != CAPTURE_SHARDS
                            or any(not isinstance(path, str) for path in paths)):
                        bad.append(f"Stage-A gate {field} artifact paths")
                        continue
                    for item in artifacts:
                        path = item["path"]
                        try:
                            actual = sha256_file(path)
                        except OSError as exc:
                            bad.append(
                                f"Stage-A gate {field} artifact unreadable: {exc}")
                            continue
                        if actual != item.get("sha256"):
                            bad.append(
                                f"Stage-A gate {field} artifact byte-hash drift")
                    manifests, records, problems = gate_validator.load_shards(
                        paths, schema=gate_validator.CHEAP_SHARD_SCHEMA,
                        stage="a", mode="cheap",
                        expected_states=state_set.get("states", []),
                        expected_state_sha256=state_set_sha256,
                        verify_receipts=True,
                    )
                    bad += [f"Stage-A gate {field}: {problem}"
                            for problem in problems]
                    if manifests:
                        bad += [f"Stage-A gate {field}: {problem}"
                                for problem in
                                gate_validator.gate_input_runtime_problems(
                                    manifests[0], payload)]
                    for record in records:
                        bad += [f"Stage-A gate {field}: {problem}"
                                for problem in gate_validator.cheap_record_problems(
                                    record, gate_validator.CHEAP_FOLDS)]
                    bad += [f"Stage-A gate {field}: {problem}" for problem in
                            gate_validator.stage_contract_problems(records, "a")]
                    loaded[field] = (manifests, records)
                if "inputs" in loaded and "reruns" in loaded:
                    primary_manifests, primary_records = loaded["inputs"]
                    rerun_manifests, rerun_records = loaded["reruns"]
                    bad += [f"Stage-A gate rerun: {problem}" for problem in
                            gate_validator.deterministic_rerun_problems(
                                primary_records, rerun_records)]
                    actual_primary_run = (primary_manifests[0].get(
                        "producer_run_id") if primary_manifests else None)
                    actual_rerun_run = (rerun_manifests[0].get(
                        "producer_run_id") if rerun_manifests else None)
                    if (primary_run != actual_primary_run
                            or rerun_run != actual_rerun_run):
                        bad.append("Stage-A gate declared/actual producer run drift")
                    if (primary_receipt != (primary_manifests[0].get(
                            "producer_receipt") if primary_manifests else None)
                            or rerun_receipt != (rerun_manifests[0].get(
                                "producer_receipt")
                                if rerun_manifests else None)):
                        bad.append(
                            "Stage-A gate declared/actual producer receipt drift")
    return bad


def freeze(args) -> None:
    if not args.smoke and len(args.input) != CAPTURE_SHARDS:
        raise TeacherProtocolError(
            f"real freeze requires exactly {CAPTURE_SHARDS} diagnostic shards, "
            f"got {len(args.input)}"
        )
    live = runtime(args.smoke)
    transition_id = getattr(args, "source_transition", None)
    use_source_transition = (
        args.stage == "b"
        and transition_id == STAGE_B_SOURCE_TRANSITION_ID
        and not args.smoke
    )
    transition_binding = None
    diagnostics, manifests, problems = [], [], []
    for path in args.input:
        with open(path) as fh:
            payload = json.load(fh)
        manifests.append(payload)
        if payload.get("schema") != DIAGNOSTIC_SCHEMA or not payload.get("complete"):
            problems.append(f"{path}: incomplete/wrong diagnostic schema")
        if not args.smoke and (payload.get("tree_dirty")
                               or not payload.get("promotable")):
            problems.append(f"{path}: dirty/non-promotable diagnostics")
        if payload.get("records_digest") != stable_digest(payload.get("records", [])):
            problems.append(f"{path}: diagnostic record digest")
        diagnostics.extend(payload.get("records", []))
    first = manifests[0] if manifests else {}
    packet_coverage = {}
    if not manifests:
        problems.append("no diagnostic inputs")
    else:
        for index, payload in enumerate(manifests[1:], 1):
            for key in ("git", "actor", "exam_exclusion", "selector_worlds",
                        "selector_policy", "v11_checkpoint_sha256", "python",
                        "fast_binary_sha256", "fast_router_sha256",
                        "state_script_sha256"):
                if payload.get(key) != first.get(key):
                    problems.append(f"diagnostic {index}: {key} drift")
        if not args.smoke:
            packet_problems, packet_coverage = diagnostic_population_problems(
                manifests
            )
            problems += packet_problems
            scanned_deals = [
                seed for manifest in manifests
                for seed in manifest.get("capture_scanned_seeds", [])
            ]
            if (len(scanned_deals) != CAPTURE_MAX_DEALS
                    or len(set(scanned_deals)) != CAPTURE_MAX_DEALS
                    or sorted(scanned_deals)
                    != list(range(SEED_START, CAPTURE_SEED_END + 1))):
                problems.append(
                    "freeze requires the exact 1,024-deal v2 diagnostic "
                    "population"
                )
        live_keys = ("python", "fast_binary_sha256", "fast_router_sha256") \
            if use_source_transition else \
            ("git", "python", "fast_binary_sha256",
             "fast_router_sha256", "state_script_sha256")
        for key in live_keys:
            if first.get(key) != live.get(key):
                problems.append(f"diagnostic/freeze {key} drift")
        if first.get("actor") != actor_identity():
            problems.append("diagnostic/freeze actor identity drift")
    ids = [diag.get("state_id") for diag in diagnostics]
    deals = [diag.get("state", {}).get("seed") for diag in diagnostics]
    if len(ids) != len(set(ids)) or len(deals) != len(set(deals)):
        problems.append("diagnostic inputs duplicate a state/deal")
    excluded_deals: set[int] = set()
    stage_a_gate_binding = None
    if args.stage == "b":
        if transition_id and transition_id != STAGE_B_SOURCE_TRANSITION_ID:
            problems.append("Stage-B source transition id missing or unknown")
        if not args.exclude_state_set and not args.smoke:
            problems.append("Stage B requires --exclude-state-set Stage-A.json")
        elif args.exclude_state_set:
            with open(args.exclude_state_set) as fh:
                previous = json.load(fh)
            input_sha256s = {sha256_file(path) for path in args.input}
            problems += stage_a_exclusion_problems(
                previous, first, input_sha256s)
            previous_states = previous.get("states", [])
            excluded_deals = {
                state.get("seed") for state in previous_states
                if isinstance(state.get("seed"), int)
            }
            for state in previous_states:
                try:
                    replay_state(state)
                except Exception as exc:
                    problems.append(
                        f"excluded Stage-A {state.get('state_id')}: replay {exc}")
            state_set_sha256 = sha256_file(args.exclude_state_set)
            if not args.stage_a_gate and not args.smoke:
                problems.append("Stage B requires --stage-a-gate PASS.json")
            elif args.stage_a_gate:
                with open(args.stage_a_gate) as fh:
                    stage_a_gate = json.load(fh)
                gate_sha256 = sha256_file(args.stage_a_gate)
                if use_source_transition:
                    transition_bad, transition_binding = \
                        stage_b_source_transition_problems(
                            first, previous, state_set_sha256,
                            stage_a_gate, gate_sha256, live, transition_id,
                        )
                    problems += transition_bad
                problems += stage_a_gate_problems(
                    stage_a_gate, state_set_sha256, previous,
                    runtime_identity=(None if args.smoke else live),
                    verify_artifacts=not args.smoke,
                    source_transition=transition_binding)
                stage_a_gate_binding = {
                    "path": args.stage_a_gate,
                    "sha256": gate_sha256,
                    "state_set_sha256": state_set_sha256,
                    "verdict": stage_a_gate.get("verdict"),
                }
    if problems:
        raise TeacherProtocolError("freeze preflight: " + "; ".join(problems))
    states, selection_problems = select_gate_states(
        diagnostics, args.stage, excluded_deals
    )
    problems += selection_problems
    required = STAGE_A_STATES if args.stage == "a" else STAGE_B_STATES
    if len(states) != required:
        problems.append(f"selected {len(states)}, required {required}")
    if len({state["seed"] for state in states}) != len(states):
        problems.append("selected more than one state per deal")
    if args.stage == "b":
        selected_deals = {
            state.get("seed") for state in states
            if isinstance(state, dict) and isinstance(state.get("seed"), int)
        }
        overlap = sorted(selected_deals & excluded_deals)
        if overlap:
            problems.append(
                f"Stage B selected deals overlap Stage A exclusions: "
                f"{overlap[:8]}"
            )
    for state in states:
        try:
            replay_state(state)
        except Exception as exc:
            problems.append(f"{state.get('state_id')}: replay {exc}")
    if problems:
        raise TeacherProtocolError("freeze refused: " + "; ".join(problems))
    first = manifests[0]
    payload = {
        "schema": STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
        "packet_id": first.get("packet_id"),
        "capture_packet": first.get("capture_packet"),
        "capture_coverage": packet_coverage,
        "stage": args.stage, **live, "seed_start": SEED_START,
        "actor": first["actor"], "exam_exclusion": first["exam_exclusion"],
        "one_state_per_deal": True,
        "split_rule": "sha256(experiment_id|split|deal_seed) mod 20 = 70/15/15",
        "selector_contract": {
            "representative_per_cell": (
                STAGE_A_REPRESENTATIVE_PER_CELL if args.stage == "a"
                else STAGE_B_REPRESENTATIVE_PER_CELL
            ),
            "boundary": STAGE_A_OTHER_STATES // 2 if args.stage == "a"
                        else STAGE_B_BOUNDARY_STATES,
            "uncertainty": STAGE_A_OTHER_STATES // 2 if args.stage == "a"
                           else STAGE_B_UNCERTAINTY_STATES,
            "boundary_target_margin": 5.0,
            "uncertainty_order": "disagreement first, then paired SE",
            "challenge_deployment_weightable": False,
            "diagnostics_inspected": (
                "N30 gap-to-5, paired SE, Smart/N30/v11 disagreement only"
            ),
        },
        "diagnostic_inputs": [
            {"path": path, "sha256": sha256_file(path),
             "capture_shard_index": manifest.get("capture_shard_index"),
             "capture_parent_sha256": manifest.get("capture_input_sha256"),
             "diagnostic_records_sha256": manifest.get("records_digest")}
            for path, manifest in zip(args.input, manifests)
        ],
        "excluded_stage_a": (
            None if not args.exclude_state_set else {
                "path": args.exclude_state_set,
                "sha256": sha256_file(args.exclude_state_set),
                "deals": len(excluded_deals),
            }
        ),
        "stage_a_gate": stage_a_gate_binding,
        "source_transition": transition_binding,
        "complete": True, "requested": required, "selected": len(states),
        "states": states, "states_digest": stable_digest(states),
    }
    if not args.smoke:
        violations = state_set_packet_problems(payload)
        if violations:
            raise TeacherProtocolError(
                "state-set packet contract: " + "; ".join(violations)
            )
    write_exclusive(args.out, payload)
    print(f"wrote frozen Stage {args.stage.upper()} set {args.out}: {len(states)} states")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--packet-id", default=CAPTURE_PACKET_ID)
    cap.add_argument("--seed0", type=int, default=SEED_START)
    cap.add_argument("--max-deals", type=int, default=CAPTURE_MAX_DEALS)
    cap.add_argument("--shard-index", type=int, default=0)
    cap.add_argument("--shard-count", type=int, default=CAPTURE_SHARDS)
    cap.add_argument("--exam-split", action="append",
                     default=list(DEFAULT_EXAM_SPLITS))
    cap.add_argument("--out", required=True)
    cap.add_argument("--smoke", action="store_true")
    diag = sub.add_parser("diagnose")
    diag.add_argument("--input", required=True)
    diag.add_argument("--expected-input-sha256", required=True)
    diag.add_argument("--out", required=True)
    diag.add_argument("--smoke", action="store_true")
    freeze_ = sub.add_parser("freeze")
    freeze_.add_argument("--stage", choices=("a", "b"), required=True)
    freeze_.add_argument("--input", action="append", required=True)
    freeze_.add_argument("--exclude-state-set")
    freeze_.add_argument("--stage-a-gate")
    freeze_.add_argument(
        "--source-transition",
        choices=(STAGE_B_SOURCE_TRANSITION_ID,),
        help="packet-specific clean source bridge for an authorized Stage B",
    )
    freeze_.add_argument("--out", required=True)
    freeze_.add_argument("--smoke", action="store_true")
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        if args.mode == "capture":
            capture(args)
        elif args.mode == "diagnose":
            diagnose(args)
        else:
            freeze(args)
    except (OSError, ValueError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
