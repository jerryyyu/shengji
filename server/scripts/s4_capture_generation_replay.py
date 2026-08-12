#!/usr/bin/env python3
"""Independently regenerate the score-free S4 v2 capture population.

The S4 producer's structural verifier replays each serialized state, but that
alone cannot prove that the file contains the first qualifying states from the
declared ascending seed stream.  This separate review witness rescans the raw
deal population, independently applies the per-role quota/stop rule, rebuilds
every accepted state and compares the complete score-free capture body.

No treatment/null outcome or exact endgame score is computed.  A successful
witness grants review evidence only; it cannot launch the S4 screen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
ROOT = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s4_point_banking_screen as S4  # noqa: E402
from shengji.engine import combos, fast, legal  # noqa: E402


SCHEMA = "s4-point-banking-capture-generation-replay-v1"
RUN_ID = "s4-point-banking-capture-generation-replay-161m-v2"
TARGET_GIT = "1b35fb7c6234fb6022181b54ce8210c796cc35c3"
TARGET_STATES_SHA256 = (
    "4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f"
)
TARGET_MATERIAL_SHA256 = (
    "5eeb1b507efc6645c7121fb9214b3e269f48fd251d815b7b029eabffa385c6a8"
)
TARGET_FILE_SHA256S = {
    "server/shengji/ai/point_banking.py": (
        "49d10d1323757756d057fb76afe9aa1142ca33320c9679dd1f172f5bba224cd1"),
    "server/scripts/s4_point_banking_screen.py": (
        "5c6c0bbcf350ecf7e9e340c56542bbecf707638fdf9a399e7db820013aec40b6"),
    "server/tests/test_point_banking.py": (
        "d5c022cada3b4b6857d27fa68c9d01c7df3f5053591597f9c1b988e85ad4f2d3"),
    "server/tests/test_s4_point_banking_screen.py": (
        "46b6ee8fd5375360c0642a79b4e795a1fb9503a6de498b83b13032fc57e7d674"),
}


class GenerationReplayError(RuntimeError):
    """The frozen capture cannot be regenerated under its declared contract."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def runtime() -> dict:
    dirty = bool(_git("status", "--porcelain"))
    if dirty:
        raise GenerationReplayError("real generation replay refuses a dirty tree")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise GenerationReplayError("set SHENGJI_FAST=1")
    routed = (fast.HAVE_FAST and combos.decompose is fast.decompose
              and legal.beats is fast.beats and fast._fast is not None)
    if not routed:
        raise GenerationReplayError("compiled engine is not on the live route")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": False,
        "host": platform.node(),
        "python": sys.version.split()[0],
        "fast_engine": True,
        "fast_routed": True,
        "fast_binary_sha256": sha256_file(fast._fast.__file__),
        "verifier_script_sha256": sha256_file(SCRIPT),
    }


def verify_target_material() -> None:
    observed = {
        path: sha256_file(ROOT / path) for path in TARGET_FILE_SHA256S
    }
    if observed != TARGET_FILE_SHA256S:
        raise GenerationReplayError("S4 target file population drift")
    material = S4.material_identity()
    if (material.get("sha256") != TARGET_MATERIAL_SHA256
            or {item["path"]: item["sha256"]
                for item in material.get("files", [])} != TARGET_FILE_SHA256S):
        raise GenerationReplayError("S4 executable material recipe drift")
    if (S4.RUN_ID != "s4-point-banking-state-screen-161m-v2"
            or S4.SEED0 != 161_000_000
            or S4.MAX_DEALS != 200_000
            or S4.ROLE_QUOTA != {"attacker": 32, "defender": 32}):
        raise GenerationReplayError("S4 capture constants drift")


def regenerate_population(*, seed0: int, max_deals: int,
                          role_quota: dict[str, int],
                          progress: bool = True) -> dict:
    """Reimplement allocation/stop logic without calling capture_states()."""
    accepted: Counter[str] = Counter()
    observed: Counter[str] = Counter()
    rows: list[dict] = []
    scanned = 0
    for offset in range(max_deals):
        seed = seed0 + offset
        scanned += 1
        found = S4._drive_to_trigger(seed)
        if found is not None:
            rnd, seat, null_action, treatment_action, telemetry = found
            role = "attacker" if rnd.is_attacker(seat) else "defender"
            if role not in role_quota:
                raise GenerationReplayError("regenerated an unknown role")
            observed[role] += 1
            if accepted[role] < role_quota[role]:
                rows.append(S4.state_record(
                    rnd, seat, seed, null_action, treatment_action, telemetry))
                accepted[role] += 1
        if progress and scanned % 5_000 == 0:
            print(f"GENERATION_REPLAY_PROGRESS deals={scanned}/{max_deals} "
                  f"accepted={sum(accepted.values())}/{sum(role_quota.values())}",
                  flush=True)
        if all(accepted[role] == role_quota[role] for role in role_quota):
            break
    if dict(accepted) != role_quota:
        raise GenerationReplayError(
            f"regeneration underfilled: accepted={dict(accepted)}")
    return {
        "deals_scanned": scanned,
        "accepted_by_role": dict(accepted),
        "observed_triggers_by_role": dict(observed),
        "states": rows,
    }


def verify_generation(states_path: Path, expected_sha256: str,
                      *, progress: bool = True) -> dict:
    if expected_sha256 != TARGET_STATES_SHA256:
        raise GenerationReplayError("review input is not the frozen S4 v2 asset")
    if sha256_file(states_path) != expected_sha256:
        raise GenerationReplayError("S4 state asset SHA-256 drift")
    try:
        payload = json.loads(states_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise GenerationReplayError(f"cannot read S4 asset: {exc}") from exc
    if not isinstance(payload, dict):
        raise GenerationReplayError("S4 asset root is not an object")
    S4.verify_capture(payload)
    if (payload.get("runtime", {}).get("git") != TARGET_GIT
            or payload.get("runtime", {}).get("material_sha256")
            != TARGET_MATERIAL_SHA256):
        raise GenerationReplayError("S4 capture runtime identity drift")

    # Make the score-free boundary executable: any accidental outcome call
    # during regeneration raises before a witness can publish.
    def outcome_forbidden(*_args, **_kwargs):
        raise GenerationReplayError("generation replay attempted outcome work")

    original_score = S4.score_state
    original_solver = S4.solve_exact_endgame
    S4.score_state = outcome_forbidden
    S4.solve_exact_endgame = outcome_forbidden
    try:
        regenerated = regenerate_population(
            seed0=S4.SEED0, max_deals=S4.MAX_DEALS,
            role_quota=dict(S4.ROLE_QUOTA), progress=progress)
    finally:
        S4.score_state = original_score
        S4.solve_exact_endgame = original_solver

    for key, value in regenerated.items():
        if payload.get(key) != value:
            raise GenerationReplayError(
                f"S4 ascending generation replay drift: {key}")
    if payload.get("contract") != S4.capture_contract():
        raise GenerationReplayError("S4 capture contract drift")
    return regenerated


def publish_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise GenerationReplayError("refusing existing witness or partial")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise GenerationReplayError("witness is not regular/unlinked")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--states", required=True)
    parser.add_argument("--expected-states-sha256", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-git", required=True)
    args = parser.parse_args()

    rt = runtime()
    if rt["git"] != args.expected_git:
        raise GenerationReplayError("verifier Git differs from expected Git")
    out = Path(args.out).resolve()
    if out.name != "generation_replay.json" or out.parent.name != RUN_ID:
        raise GenerationReplayError("witness output namespace drift")
    verify_target_material()
    regenerated = verify_generation(
        Path(args.states), args.expected_states_sha256, progress=True)
    witness = {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "complete": True,
        "runtime": rt,
        "target": {
            "git": TARGET_GIT,
            "states_sha256": TARGET_STATES_SHA256,
            "material_sha256": TARGET_MATERIAL_SHA256,
        },
        "generation_replay": {
            "seed_order": "ascending",
            "allocation": "first trigger per role until exact quotas",
            "deals_scanned": regenerated["deals_scanned"],
            "accepted_by_role": regenerated["accepted_by_role"],
            "observed_triggers_by_role": regenerated[
                "observed_triggers_by_role"],
            "states_rebuilt_and_exactly_equal": len(regenerated["states"]),
        },
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "generation_replay_complete": True,
            "screen_launch_authorized": False,
            "full_game_launch_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
        },
    }
    publish_exclusive(out, witness)
    print(json.dumps({
        "status": "GENERATION_REPLAY_COMPLETE_FOR_REVIEW",
        "path": str(out),
        "sha256": sha256_file(out),
        "deals_scanned": regenerated["deals_scanned"],
        "states": len(regenerated["states"]),
        "outcomes_computed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
